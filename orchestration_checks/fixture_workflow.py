"""Run via flyte run --local; patches only external boundaries in the real graph."""

import socket
from dataclasses import replace
from unittest.mock import patch

import flyte
from flyte.errors import RuntimeUserError
from orchestration.flyte_pipeline import backfill
from orchestration.plan import (
    Backfill,
    DbtResult,
    IngestionResult,
    Unit,
    VerificationResult,
    expand,
)

from orchestration_checks.fixtures import PlannerState
from power_market_data.warehouse.model import Request

checks = flyte.TaskEnvironment(name="offline_orchestration_checks")


@checks.task(cache="disable")
async def verify_workflow(product: str = "lmp") -> str:
    assert product in ("lmp", "load")
    spec = Backfill(
        "00000000000000000000000000000004",
        "2026-08-02",
        "2026-08-04",
        ingest_lmp=product == "lmp",
        ingest_load=product == "load",
    )
    assert all(unit.product == product for unit in expand(spec))
    state = PlannerState()
    events: list[str] = []

    def dbt(backfill_id: str) -> DbtResult:
        assert all(state.runs[u.run_id]["status"] == "SUCCEEDED" for u in expand(active))
        events.append("dbt")
        return DbtResult("passed", 0, 56, "fixture-no-subprocess")

    def verify(units: list[Unit], results: list[IngestionResult]) -> VerificationResult:
        assert events[-1] == "dbt"
        events.append("verify")
        return VerificationResult("passed", {u.label: 1 for u in units})

    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("offline graph")),
        patch.object(socket, "getaddrinfo", side_effect=AssertionError("offline graph")),
        patch("orchestration.ingestion.BigQueryWarehouse", side_effect=lambda config: state),
        patch("orchestration.flyte_pipeline.operations.validate_runtime"),
        patch("orchestration.flyte_pipeline.operations.build_dbt", side_effect=dbt),
        patch("orchestration.flyte_pipeline.operations.verify", side_effect=verify),
        patch(
            "power_market_data.ingestion.fetch_lmp",
            side_effect=lambda day, hub: state.fetch(Request("lmp", day, hub)),
        ),
        patch(
            "power_market_data.ingestion.fetch_load",
            side_effect=lambda day: state.fetch(Request("load", day)),
        ),
        patch.dict("os.environ", {"GCP_PROJECT_ID": "offline-project"}),
    ):
        active = spec
        state.transient_once = True
        state.interrupt_day = "2026-08-03"
        try:
            await backfill(spec)
        except RuntimeUserError:
            pass
        else:
            raise AssertionError("interruption was swallowed")
        assert not events
        assert state.runs[expand(spec)[0].run_id]["status"] == "SUCCEEDED"
        assert state.runs[expand(spec)[1].run_id]["status"] == "COMMITTED"
        assert expand(spec)[2].run_id not in state.runs
        assert state.read_ids[:2] == [expand(spec)[0].run_id] * 2
        report = await backfill(spec)
        assert events == ["dbt", "verify"]
        assert report.ingestions[0].reused_success
        assert state.fetched == ["2026-08-02", "2026-08-03", "2026-08-04"]
        resumed = (set(state.contents), list(state.transitions))
        repeat = await backfill(spec)
        assert all(r.reused_success for r in repeat.ingestions)
        assert sum(r.new_transitions for r in repeat.ingestions) == 0
        assert (state.contents, state.transitions) == resumed
        # A fresh retrieval attempt still delegates exact-repeat deduplication.
        active = replace(spec, backfill_id="00000000000000000000000000000005")
        report = await backfill(active)
        assert not any(r.reused_success for r in report.ingestions)
        assert sum(r.new_contents + r.new_transitions for r in report.ingestions) == 0

        # Independent one-day executions over the same normalized inputs.
        state = PlannerState()
        for day in ("2026-08-02", "2026-08-03", "2026-08-04"):
            active = replace(spec, start_date=day, end_date=day, run_dbt=False)
            await backfill(active)
        assert (state.contents, state.transitions) == resumed

        # A terminal failure cannot be silently revived under the same run ID.
        state = PlannerState()
        state.fail_day = "2026-08-03"
        active = spec
        events.clear()
        for _ in range(2):
            try:
                await backfill(active)
            except RuntimeUserError:
                pass
            else:
                raise AssertionError("terminal failure was swallowed")
        assert state.fetched == ["2026-08-02", "2026-08-03"]
        assert not events
        assert expand(spec)[2].run_id not in state.runs
        state.fail_day = ""
        active = replace(spec, backfill_id="00000000000000000000000000000006")
        await backfill(active)
        assert (state.contents, state.transitions) == resumed
        assert len(state.contents) == len(state.transitions) == 3
        assert events == ["dbt", "verify"]
    return (
        "PASS: native retry, fail-fast, same-ID resume, terminal/new-attempt recovery, equivalence"
    )
