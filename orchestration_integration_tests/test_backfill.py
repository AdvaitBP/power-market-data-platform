"""Native, disposable contract. Never inject failures into the real CAISO datasets."""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import flyte
import pytest
from flyte.errors import RuntimeUserError
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from orchestration import operations
from orchestration.flyte_pipeline import backfill
from orchestration.plan import Backfill, BackfillReport, expand
from orchestration_checks.fixtures import records

from power_market_data.ingestion import ingest
from power_market_data.warehouse.bigquery import BigQueryWarehouse
from power_market_data.warehouse.model import CommitUnconfirmed, Request, Row, WarehouseConfig

ROOT = Path(__file__).resolve().parents[1]


def execute(spec: Backfill) -> BackfillReport:
    # Flyte's supported local engine executes the actual tasks and dependencies.
    run = flyte.with_runcontext(
        mode="local",
        run_base_dir=str(ROOT / "artifacts/flyte-integration/metadata"),
        raw_data_path=str(ROOT / "artifacts/flyte-integration/raw"),
    ).run(backfill, spec=spec)
    run.wait()
    return cast(BackfillReport, run.outputs()[0])


def test_interrupted_resume_equals_daily_ingestion(monkeypatch: pytest.MonkeyPatch) -> None:
    base = WarehouseConfig.from_environment()
    client = bigquery.Client(project=base.project, location=base.location)
    suffix = datetime.now(UTC).strftime("%Y%m%d_") + uuid4().hex[:12]
    owned: list[str] = []
    started = datetime.now(UTC)
    report: dict[str, Any] = {"cleanup": False, "scenarios": {}}
    spec = Backfill(uuid4().hex, "2026-08-02", "2026-08-04")
    snapshots: list[dict[str, Any]] = []
    try:
        for scenario in ("daily", "resume"):
            raw_name = f"pmd_flyte_it_{scenario}_raw_{suffix}"
            analytics = f"pmd_flyte_it_{scenario}_analytics_{suffix}"
            raw = WarehouseConfig(base.project, raw_name, base.location)
            for name in (raw_name, analytics):
                dataset = bigquery.Dataset(f"{base.project}.{name}")
                dataset.location = base.location
                dataset.labels = {"managed_by": "power-market-data-platform", "owner": suffix}
                if name == analytics:
                    dataset.default_table_expiration_ms = 24 * 60 * 60 * 1000
                client.create_dataset(dataset)  # No exists_ok: never adopt an existing dataset.
                owned.append(name)
            store = BigQueryWarehouse(raw, client)
            store.bootstrap()
            monkeypatch.setenv("BQ_RAW_DATASET", raw_name)
            monkeypatch.setenv("BQ_ANALYTICS_DATASET", analytics)
            if scenario == "daily":
                # Three independently bounded daily runs; source inputs are identical.
                for unit in expand(spec):
                    ingest(
                        store,
                        unit.request(),
                        unit.run_id,
                        fetch=partial(records, unit.request()),
                    )
                operations.build_dbt(spec.backfill_id)
                report["scenarios"][scenario] = "six bounded requests, then dbt build"
            else:
                original_reconcile = BigQueryWarehouse.reconcile
                interrupted = False
                target = expand(spec)[2].run_id

                def lose_ack(
                    self: BigQueryWarehouse,
                    run_id: str,
                    target_run_id: str = target,
                    reconcile: Callable[[BigQueryWarehouse, str], Row | None] = original_reconcile,
                ) -> Row | None:
                    nonlocal interrupted
                    result = reconcile(self, run_id)
                    if run_id == target_run_id and result is not None and not interrupted:
                        interrupted = True
                        raise CommitUnconfirmed("controlled acknowledgement loss after acceptance")
                    return result

                with (
                    patch(
                        "power_market_data.ingestion.fetch_lmp",
                        side_effect=lambda day, hub: records(Request("lmp", day, hub)),
                    ),
                    patch(
                        "power_market_data.ingestion.fetch_load",
                        side_effect=lambda day: records(Request("load", day)),
                    ),
                    patch.object(BigQueryWarehouse, "reconcile", lose_ack),
                ):
                    with pytest.raises(RuntimeUserError, match="stopped"):
                        execute(spec)
                    assert interrupted
                    assert store.get_run(expand(spec)[0].run_id)["status"] == "SUCCEEDED"  # type: ignore[index]
                    assert store.get_run(expand(spec)[3].run_id) is None
                    with pytest.raises(NotFound):
                        client.get_table(f"{base.project}.{analytics}.fct_hourly_lmp")
                    resumed = execute(spec)
                    assert len(resumed.ingestions) == 6
                    assert resumed.dbt.status == resumed.verification.status == "passed"
                    before_repeat = snapshot(client, raw, analytics)
                    # Same IDs resume, new IDs exercise a genuinely repeated retrieval.
                    replay = execute(replace(spec, run_dbt=False))
                    assert all(r.reused_success for r in replay.ingestions)
                    repeated = execute(replace(spec, backfill_id=uuid4().hex))
                    assert sum(r.new_contents + r.new_transitions for r in repeated.ingestions) == 0
                    assert snapshot(client, raw, analytics) == before_repeat
                report["scenarios"][scenario] = {
                    "interrupted": interrupted,
                    "requests": len(resumed.ingestions),
                    "reused_on_resume": sum(r.reused_success for r in resumed.ingestions),
                    "rerun_new_contents": 0,
                    "rerun_new_transitions": 0,
                }
            snapshots.append(snapshot(client, raw, analytics))
        assert snapshots[0] == snapshots[1]
        report["logical_equivalence"] = True
    finally:
        report["owned_datasets"] = owned
        for name in owned:
            identifier = f"{base.project}.{name}"
            if client.get_dataset(identifier).labels.get("owner") != suffix:
                raise RuntimeError(f"refusing cleanup: owner changed for {identifier}")
            client.delete_dataset(identifier, delete_contents=True, not_found_ok=True)
        remaining = [d.dataset_id for d in client.list_datasets()]
        assert not set(owned).intersection(remaining)
        report.update(cleanup=True, remaining_datasets=remaining)
        jobs = [
            j
            for j in client.list_jobs(min_creation_time=started)
            if isinstance(j, bigquery.QueryJob) and not j.parent_job_id
        ]
        report.update(
            query_jobs=len(jobs),
            failed_query_jobs=sum(bool(j.error_result) for j in jobs),
            bytes_processed=sum(j.total_bytes_processed or 0 for j in jobs),
            bytes_billed=sum(j.total_bytes_billed or 0 for j in jobs),
        )
        path = ROOT / "artifacts/phase4-integration-report.json"
        path.write_text(json.dumps(report, default=str, indent=2), encoding="utf-8")


def snapshot(client: bigquery.Client, raw: WarehouseConfig, analytics: str) -> dict[str, Any]:
    """Compare logical outputs, excluding attempt IDs and acceptance/retrieval clocks."""
    answer: dict[str, Any] = {}
    for product, fact in (("lmp", "fct_hourly_lmp"), ("load", "fct_system_load_5min")):
        contents = [dict(r) for r in client.list_rows(raw.table(product + "_contents"))]
        transitions = [dict(r) for r in client.list_rows(raw.table(product + "_state_transitions"))]
        facts = [dict(r) for r in client.list_rows(f"{raw.project}.{analytics}.{fact}")]
        answer[product + "_contents"] = sorted(
            (r["logical_key"], r["content_id"], r["content_hash"], r[product]) for r in contents
        )
        answer[product + "_transitions"] = sorted(
            (r["logical_key"], r["content_id"], r["ordinal"]) for r in transitions
        )
        volatile = {
            "first_run_id",
            "first_seen_at",
            "state_run_id",
            "state_known_at",
            "content_retrieved_at_utc",
            "state_retrieved_at_utc",
            "transition_id",
        }
        answer[product + "_facts"] = sorted(
            [{k: v for k, v in row.items() if k not in volatile} for row in facts],
            key=lambda row: str(row["logical_key"]),
        )
        assert len(contents) == len(transitions) == len(facts) == 3
    return answer
