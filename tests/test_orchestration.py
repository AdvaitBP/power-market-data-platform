"""Offline orchestration boundaries: planning, state-aware retry and subprocess failure."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from google.api_core.exceptions import BadRequest, Forbidden, ServiceUnavailable
from orchestration.ingestion import execute_unit, retryable
from orchestration.operations import build_dbt, configuration
from orchestration.plan import Backfill, expand

from power_market_data.time import PACIFIC
from power_market_data.warehouse.model import (
    CommitUnconfirmed,
    Row,
    WarehouseConfig,
    WarehouseError,
)

SPEC = Backfill("00000000000000000000000000000001", "2026-08-02", "2026-08-04")
CONFIG = WarehouseConfig("offline-project")


def test_expansion_is_inclusive_ordered_and_bounded() -> None:
    spec = replace(SPEC, locations=["TH_SP15_GEN-APND", "TH_NP15_GEN-APND"])
    units = expand(spec)
    assert len(units) == 9
    assert [u.product for u in units[:3]] == ["lmp", "lmp", "load"]
    assert [u.day for u in units[::3]] == ["2026-08-02", "2026-08-03", "2026-08-04"]
    assert len({u.run_id for u in units}) == 9
    assert expand(replace(spec, locations=list(reversed(spec.locations)))) == units


def test_resume_identity_and_new_attempt() -> None:
    units = expand(SPEC)
    assert expand(SPEC) == units
    assert expand(replace(SPEC, end_date=SPEC.start_date)) == units[:2]
    fresh = expand(replace(SPEC, backfill_id=uuid4().hex))
    assert {u.run_id for u in units}.isdisjoint(u.run_id for u in fresh)
    assert [u.request() for u in units] == [u.request() for u in fresh]


@pytest.mark.parametrize(
    "changes",
    [
        {"start_date": "2026-08-05"},
        {"end_date": "2026-08-09"},
        {"end_date": str(datetime.now(PACIFIC).date())},
        {"start_date": "20260802"},
        {"end_date": "bad"},
        {"ingest_lmp": False, "ingest_load": False},
        {"locations": []},
        {"locations": ["UNKNOWN"]},
        {"locations": ["TH_NP15_GEN-APND"] * 2},
        {"concurrency": 2},
        {"concurrency": 0},
        {"backfill_id": "not-a-uuid"},
        {"start_date": "2025-11-02", "end_date": "2025-11-02"},
    ],
)
def test_invalid_plan_has_no_external_effect(changes: dict[str, object]) -> None:
    with pytest.raises(WarehouseError):
        expand(replace(SPEC, **changes))  # type: ignore[arg-type]


def test_seven_days_allowed_and_load_only() -> None:
    assert len(expand(replace(SPEC, end_date="2026-08-08"))) == 14
    units = expand(replace(SPEC, ingest_lmp=False, locations=[]))
    assert len(units) == 3 and all(u.product == "load" for u in units)


@pytest.mark.parametrize(
    "status,expected",
    [
        (None, True),
        ("STARTED", True),
        ("FAILED", False),
        ("COMMITTED", False),
        ("SUCCEEDED", False),
        ("UNKNOWN", False),
    ],
)
def test_transient_retry_requires_safe_manifest(status: str | None, expected: bool) -> None:
    manifest: Row | None = {"status": status} if status else None
    assert retryable(ServiceUnavailable("controlled"), manifest) is expected  # type: ignore[no-untyped-call]


@pytest.mark.parametrize(
    "error",
    [
        CommitUnconfirmed("uncertain"),
        WarehouseError("terminal"),
        ValueError("bad schema"),
        Forbidden("quotaExceeded"),  # type: ignore[no-untyped-call]
        BadRequest("schema mismatch"),  # type: ignore[no-untyped-call]
    ],
)
def test_no_retry_for_unsafe_or_deterministic_failures(error: Exception) -> None:
    assert not retryable(error, {"status": "STARTED"})


@pytest.mark.parametrize("prior", [None, "STARTED", "COMMITTED", "SUCCEEDED"])
def test_core_ingest_always_receives_stable_run_id(prior: str | None) -> None:
    unit = expand(SPEC)[0]
    store = Mock()
    store.get_run.return_value = {"status": prior} if prior else None
    manifest: Row = {
        "status": "SUCCEEDED",
        "rows_accepted": 24,
        "new_contents": 24,
        "new_transitions": 24,
    }
    with (
        patch("orchestration.ingestion.BigQueryWarehouse", return_value=store),
        patch("orchestration.ingestion.ingest", return_value=manifest) as ingest,
    ):
        result = execute_unit(unit, CONFIG)
    ingest.assert_called_once_with(store, unit.request(), unit.run_id)
    assert result.reused_success is (prior == "SUCCEEDED")
    assert result.new_contents == (0 if prior == "SUCCEEDED" else 24)


def test_source_failure_marked_terminal_is_not_retried() -> None:
    unit = expand(SPEC)[0]
    store = Mock()
    store.get_run.side_effect = [None, {"status": "FAILED"}]
    error = WarehouseError("source failed")
    error.__cause__ = ServiceUnavailable("transient source error, now terminal")  # type: ignore[no-untyped-call]
    with (
        patch("orchestration.ingestion.BigQueryWarehouse", return_value=store),
        patch("orchestration.ingestion.ingest", side_effect=error),
        pytest.raises(WarehouseError, match="status=FAILED"),
    ):
        execute_unit(unit, CONFIG)


def test_analytics_cannot_target_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "offline-project")
    monkeypatch.setenv("BQ_ANALYTICS_DATASET", "power_market_raw")
    with pytest.raises(WarehouseError, match="differ"):
        configuration()


@pytest.mark.parametrize("cap_exit,build_exit,calls", [(1, 0, 1), (0, 1, 2)])
def test_dbt_failure_is_visible_and_cap_failure_prevents_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, cap_exit: int, build_exit: int, calls: int
) -> None:
    root = tmp_path
    (root / "dbt").mkdir()
    (root / "dbt/profiles.example.yml").write_text("maximum_bytes_billed: 104857600")
    monkeypatch.setenv("GCP_PROJECT_ID", "offline-project")
    monkeypatch.setattr("orchestration.operations.ROOT", root)
    with (
        patch(
            "orchestration.operations.subprocess.run",
            side_effect=[
                Mock(returncode=cap_exit, stdout="", stderr=""),
                Mock(returncode=build_exit, stdout="", stderr=""),
            ],
        ) as run,
        pytest.raises(WarehouseError),
    ):
        build_dbt(SPEC.backfill_id)
    assert run.call_count == calls


@pytest.mark.parametrize(
    "count,keys,ineligible,accepted,passes",
    [
        (24, 24, 0, 24, True),
        (25, 24, 0, 24, False),
        (24, 24, 1, 24, False),
        (23, 23, 0, 24, False),
        (0, 0, 0, 0, True),
    ],
)
def test_bounded_post_build_verification(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
    keys: int,
    ineligible: int,
    accepted: int,
    passes: bool,
) -> None:
    from orchestration.operations import verify
    from orchestration.plan import IngestionResult

    monkeypatch.setenv("GCP_PROJECT_ID", "offline-project")
    unit = expand(SPEC)[0]
    result = IngestionResult(unit, "SUCCEEDED", accepted, accepted, accepted)
    store = Mock()
    store.job_metrics = {"bounded-query": (100, 10485760)}
    store.wait.return_value = [
        {
            "market_date": unit.request().day,
            "hub": unit.location,
            "n": count,
            "keys": keys,
            "ineligible": ineligible,
        }
    ]
    with patch("orchestration.operations.BigQueryWarehouse", return_value=store):
        if passes:
            report = verify([unit], [result])
            assert report.request_counts[unit.label] == count
            assert report.bytes_billed == 10485760
        else:
            with pytest.raises(WarehouseError):
                verify([unit], [result])
    query, parameters = store.query.call_args.args
    assert "BETWEEN @start AND @end" in query
    assert [p.name for p in parameters] == ["start", "end", "hubs"]


def test_quota_cause_chain_cannot_enable_retry() -> None:
    error = Forbidden("quotaExceeded")  # type: ignore[no-untyped-call]
    error.__cause__ = ServiceUnavailable("earlier network error")  # type: ignore[no-untyped-call]
    assert not retryable(error, {"status": "STARTED"})


def test_uncertain_cause_chain_cannot_enable_retry() -> None:
    uncertain = CommitUnconfirmed("unknown job outcome")
    uncertain.__cause__ = ServiceUnavailable("transport")  # type: ignore[no-untyped-call]
    wrapper = WarehouseError("wrapped uncertainty")
    wrapper.__cause__ = uncertain
    assert not retryable(wrapper, {"status": "STARTED"})
