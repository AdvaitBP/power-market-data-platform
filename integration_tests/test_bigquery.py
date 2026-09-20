"""Actual BigQuery transactions using tiny synthetic observations, never altered CAISO data."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from power_market_data.domain import LmpObservation, LoadObservation, Observation, Provenance
from power_market_data.warehouse import sql
from power_market_data.warehouse.bigquery import BigQueryWarehouse, array, scalar
from power_market_data.warehouse.model import (
    CommitUnconfirmed,
    Request,
    WarehouseError,
    batch_rows,
    plan_write,
)
from power_market_data.warehouse.schema import TABLES


def sample(request: Request) -> Observation:
    start, _ = request.bounds
    from datetime import timedelta

    provenance = Provenance(
        retrieved_at_utc=datetime.now(UTC),
        source_url="https://example.invalid/synthetic",
        source_method="integration fixture",
        library_version="synthetic-v1",
    )
    if request.product == "lmp":
        return LmpObservation(
            location=request.location or "",
            interval_start_utc=start,
            interval_end_utc=start + timedelta(hours=1),
            lmp=Decimal("-7"),
            energy=Decimal("-6"),
            congestion=Decimal("-0.5"),
            loss=Decimal("-0.5"),
            provenance=provenance,
        )
    return LoadObservation(
        interval_start_utc=start,
        interval_end_utc=start + timedelta(minutes=5),
        load=Decimal("21000.000000001"),
        provenance=provenance,
    )


def accept(warehouse: BigQueryWarehouse, request: Request, record: Observation) -> str:
    run_id = uuid4().hex
    warehouse.begin(request, run_id)
    result = warehouse.persist(request, [record], run_id)
    assert result["status"] == "SUCCEEDED" and result["commit_completed"] is True
    return run_id


def test_bootstrap_twice_preserves_data(warehouse: BigQueryWarehouse) -> None:
    warehouse.bootstrap()
    warehouse.bootstrap()
    assert (
        len(
            list(
                warehouse.client.list_tables(
                    f"{warehouse.config.project}.{warehouse.config.dataset}"
                )
            )
        )
        == 6
    )


@pytest.mark.parametrize("product", ["lmp", "load"])
def test_repeat_revision_reappearance_and_late_arrival(
    warehouse: BigQueryWarehouse,
    product: str,
) -> None:
    request = Request(product, date(2025, 1, 15), "TH_NP15_GEN-APND" if product == "lmp" else None)
    original = sample(request)
    revised = (
        replace(original, lmp=Decimal("20"))
        if isinstance(original, LmpObservation)
        else replace(original, load=Decimal("22000"))
    )
    first = accept(warehouse, request, original)
    initial = warehouse.get_run(first)
    assert initial is not None
    first_known = initial["knowledge_at"]
    assert isinstance(first_known, datetime) and first_known > original.interval_end_utc
    repeat = accept(warehouse, request, original)
    repeated = warehouse.get_run(repeat)
    assert repeated is not None
    assert repeated["new_contents"] == repeated["new_transitions"] == 0
    assert warehouse.inspect(request)["counts"] == {"contents": 1, "transitions": 1}
    accept(warehouse, request, revised)
    assert warehouse.inspect(request)["counts"] == {"contents": 2, "transitions": 2}
    reappeared = accept(warehouse, request, original)
    assert warehouse.inspect(request)["counts"] == {"contents": 2, "transitions": 3}
    # Replaying the first run after other states never creates another transition.
    assert warehouse.persist(request, [original], first)["knowledge_at"] == first_known
    assert warehouse.inspect(request)["counts"] == {"contents": 2, "transitions": 3}
    transitions = warehouse.wait(
        warehouse.query(
            f"SELECT content_id, ordinal, known_at FROM "
            f"`{warehouse.config.table(product + '_state_transitions')}` "
            "WHERE market_date = @day ORDER BY ordinal",
            [scalar("day", "DATE", request.day)],
        )
    )
    assert [row["ordinal"] for row in transitions] == [1, 2, 3]
    assert transitions[0]["content_id"] == transitions[2]["content_id"]
    assert str(transitions[0]["known_at"]) < str(transitions[2]["known_at"])
    values = warehouse.wait(
        warehouse.query(
            f"SELECT first_seen_at, {product} AS value FROM "
            f"`{warehouse.config.table(product + '_contents')}` WHERE first_run_id = @first",
            [scalar("first", "STRING", first)],
        )
    )
    assert values[0]["first_seen_at"] == first_known
    assert values[0]["value"] == (
        original.lmp if isinstance(original, LmpObservation) else original.load
    )
    assert warehouse.get_run(reappeared) is not None


def test_transaction_rolls_back_every_observation(
    warehouse: BigQueryWarehouse,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = Request("load", date(2025, 1, 16))
    run_id = uuid4().hex
    warehouse.begin(request, run_id)
    real = sql.commit_query
    monkeypatch.setattr(
        sql,
        "commit_query",
        lambda config, product: real(config, product).replace(
            "COMMIT TRANSACTION;",
            "ASSERT FALSE AS 'intentional rollback test'; COMMIT TRANSACTION;",
        ),
    )
    with pytest.raises(WarehouseError, match="commit job failed"):
        warehouse.persist(request, [sample(request)], run_id)
    manifest = warehouse.get_run(run_id)
    assert manifest is not None
    assert manifest["status"] == "FAILED" and manifest["commit_completed"] is False
    assert manifest["commit_job_id"] == warehouse.job_id(run_id, "commit")
    assert warehouse.inspect(request)["counts"] == {"contents": 0, "transitions": 0}
    monkeypatch.setattr(sql, "commit_query", real)
    accept(warehouse, request, sample(request))
    assert warehouse.inspect(request)["counts"] == {"contents": 1, "transitions": 1}


def test_interrupted_after_commit_reconciles_without_duplicate(
    warehouse: BigQueryWarehouse,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = Request("load", date(2025, 1, 17))
    run_id = uuid4().hex
    warehouse.begin(request, run_id)
    real = sql.finalize_query
    monkeypatch.setattr(sql, "finalize_query", lambda config, product: "SELECT 1/0")
    with pytest.raises(CommitUnconfirmed, match="finalization pending"):
        warehouse.persist(request, [sample(request)], run_id)
    manifest = warehouse.get_run(run_id)
    assert manifest is not None and manifest["status"] == "COMMITTED"
    assert manifest["commit_completed"] is True and manifest["knowledge_at"] is None
    assert warehouse.inspect(request)["counts"] == {"contents": 0, "transitions": 0}
    monkeypatch.setattr(sql, "finalize_query", real)
    result = warehouse.reconcile(run_id)
    assert result is not None and result["status"] == "SUCCEEDED"
    assert warehouse.reconcile(run_id) == result
    assert warehouse.inspect(request)["counts"] == {"contents": 1, "transitions": 1}


def test_stale_competing_snapshot_is_rejected(warehouse: BigQueryWarehouse) -> None:
    request = Request("load", date(2025, 1, 18))
    record = sample(request)
    run_id = uuid4().hex
    warehouse.begin(request, run_id)
    plan = plan_write(run_id, batch_rows(request, [record]), warehouse.snapshot(request))
    # Another process commits between this process's snapshot and submission.
    accept(warehouse, request, record)
    job_id = warehouse.job_id(run_id, "commit")
    warehouse.query(
        sql.commit_query(warehouse.config, "load"),
        [
            scalar("run_id", "STRING", run_id),
            scalar("expected_sequence", "INT64", plan.expected_sequence),
            scalar("batch_hash", "STRING", plan.batch_hash),
            scalar("accepted", "INT64", plan.accepted),
            scalar("commit_job_id", "STRING", job_id),
            array("contents", TABLES["load_contents"], plan.contents),
            array("transitions", TABLES["load_state_transitions"], plan.transitions),
        ],
        job_id,
    )
    with pytest.raises(WarehouseError, match="commit job failed"):
        warehouse.reconcile(run_id)
    assert warehouse.inspect(request)["counts"] == {"contents": 1, "transitions": 1}


def test_empty_success_and_source_failure_are_distinct(warehouse: BigQueryWarehouse) -> None:
    request = Request("load", date(2025, 1, 19))
    empty, failed = uuid4().hex, uuid4().hex
    warehouse.begin(request, empty)
    result = warehouse.persist(request, [], empty)
    assert result["status"] == "SUCCEEDED" and result["rows_accepted"] == 0
    warehouse.begin(request, failed)
    warehouse.fail(failed, ValueError("synthetic failure"))
    manifest = warehouse.get_run(failed)
    assert manifest is not None and manifest["status"] == "FAILED"
    assert manifest["rows_fetched"] is None
    assert manifest["error_class"] == "ValueError"
    assert warehouse.inspect(request)["counts"] == {"contents": 0, "transitions": 0}
