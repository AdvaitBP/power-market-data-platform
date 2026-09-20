"""Native-client call contracts and failure handling; the mocks do not execute SQL."""

from datetime import UTC, date, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from google.api_core.exceptions import BadRequest, Conflict, NotFound

from power_market_data.cli import main
from power_market_data.ingestion import ingest
from power_market_data.warehouse import sql
from power_market_data.warehouse.bigquery import BigQueryWarehouse, array
from power_market_data.warehouse.model import (
    CommitUnconfirmed,
    Request,
    WarehouseConfig,
    WarehouseError,
)
from power_market_data.warehouse.schema import TABLES

CONFIG = WarehouseConfig("valid-project")


def store() -> tuple[BigQueryWarehouse, Mock]:
    client = Mock()
    return BigQueryWarehouse(CONFIG, client), client


def test_query_caps_and_stable_conflict_reattachment() -> None:
    warehouse, client = store()
    client.query.side_effect = Conflict("already exists")  # type: ignore[no-untyped-call]
    job = warehouse.query("SELECT 1", job_id="stable")
    assert job is client.get_job.return_value
    args = client.query.call_args.kwargs
    assert args["job_config"].maximum_bytes_billed == 104857600
    assert args["job_retry"] is None
    assert args["job_id"] == "stable"
    assert args["location"] == "US"


def test_empty_array_keeps_typed_schema() -> None:
    encoded = array("contents", TABLES["load_contents"], []).to_api_repr()
    assert encoded["parameterType"]["type"] == "ARRAY"
    assert encoded["parameterValue"]["arrayValues"] == []
    fields = encoded["parameterType"]["arrayType"]["structTypes"]
    assert any(x["name"] == "load" and x["type"]["type"] == "NUMERIC" for x in fields)


@pytest.mark.parametrize("product", ["lmp", "load"])
def test_sql_atomicity_and_concurrency_guards(product: str) -> None:
    query = sql.commit_query(CONFIG, product)
    assert query.index("BEGIN TRANSACTION") < query.index("UPDATE") < query.index("MERGE")
    assert (
        query.index("MERGE")
        < query.index("status = 'COMMITTED'")
        < query.index("COMMIT TRANSACTION")
    )
    assert "= @expected_sequence" in query
    assert "active_run_id IS NULL" in query
    assert "IFNULL(ARRAY_LENGTH(@contents), 0)" in query
    assert "IFNULL(ARRAY_LENGTH(@transitions), 0)" in query
    assert "CURRENT_TIMESTAMP" not in query
    assert "status = 'SUCCEEDED'" not in query
    finalization = sql.finalize_query(CONFIG, product)
    assert "first_seen_at = @knowledge_at" in finalization
    assert "first_seen_at IS NULL" in finalization
    assert "status = 'SUCCEEDED'" in finalization
    assert "active_run_id = NULL" in finalization
    assert "@day" in sql.snapshot_query(CONFIG, product)


def test_failure_cannot_overwrite_committed_success() -> None:
    assert "status = 'STARTED' AND NOT commit_completed" in sql.failure_query(CONFIG)


def test_resume_success_never_resubmits(monkeypatch: pytest.MonkeyPatch) -> None:
    warehouse, client = store()
    manifest = {"status": "SUCCEEDED"}
    monkeypatch.setattr(warehouse, "get_run", lambda _: manifest)
    assert warehouse.reconcile(uuid4().hex) == manifest
    client.query.assert_not_called()


def test_unknown_submission_is_not_marked_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    warehouse, _ = store()
    monkeypatch.setattr(warehouse, "get_run", lambda _: {"status": "STARTED"})
    job = Mock()
    job.result.side_effect = TimeoutError()
    job.state = "RUNNING"
    job.error_result = None
    monkeypatch.setattr(warehouse, "_commit_job", lambda _: job)
    failure = Mock()
    monkeypatch.setattr(warehouse, "fail", failure)
    with pytest.raises(CommitUnconfirmed, match="unknown"):
        warehouse.reconcile(uuid4().hex)
    failure.assert_not_called()


def test_confirmed_failed_transaction_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    warehouse, _ = store()
    monkeypatch.setattr(warehouse, "get_run", lambda _: {"status": "STARTED"})
    job = Mock()
    job.result.side_effect = BadRequest("transaction failed")  # type: ignore[no-untyped-call]
    job.state = "DONE"
    job.error_result = {"reason": "invalidQuery"}
    monkeypatch.setattr(warehouse, "_commit_job", lambda _: job)
    failure = Mock()
    monkeypatch.setattr(warehouse, "fail", failure)
    with pytest.raises(WarehouseError, match="commit job failed"):
        warehouse.reconcile(uuid4().hex)
    failure.assert_called_once()


def test_job_end_supplies_knowledge_time(monkeypatch: pytest.MonkeyPatch) -> None:
    warehouse, client = store()
    manifests = iter([{"status": "COMMITTED", "product": "load"}, {"status": "SUCCEEDED"}])
    monkeypatch.setattr(warehouse, "get_run", lambda _: next(manifests))
    job = Mock()
    job.result.return_value = []
    job.ended = datetime(2026, 9, 20, tzinfo=UTC)
    job.total_bytes_processed = 123
    job.total_bytes_billed = 10485760
    monkeypatch.setattr(warehouse, "_commit_job", lambda _: job)
    client.query.return_value.result.return_value = []
    warehouse.reconcile(uuid4().hex)
    parameters = client.query.call_args.kwargs["job_config"].query_parameters
    assert next(x for x in parameters if x.name == "knowledge_at").value == job.ended


def test_missing_job_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    warehouse, client = store()
    monkeypatch.setattr(warehouse, "get_run", lambda _: {"status": "STARTED"})
    client.get_job.side_effect = NotFound("job")  # type: ignore[no-untyped-call]
    assert warehouse.reconcile(uuid4().hex) is None
    monkeypatch.setattr(warehouse, "get_run", lambda _: {"status": "COMMITTED"})
    with pytest.raises(CommitUnconfirmed, match="metadata unavailable"):
        warehouse.reconcile(uuid4().hex)


def test_source_failure_has_manifest_without_commit() -> None:
    warehouse = Mock(spec=BigQueryWarehouse)
    warehouse.reconcile.return_value = None
    fetch = Mock(side_effect=RuntimeError("source broke"))
    run_id = uuid4().hex
    with pytest.raises(WarehouseError, match=run_id):
        ingest(warehouse, Request("load", date(2026, 8, 1)), run_id, fetch)
    warehouse.begin.assert_called_once()
    warehouse.fail.assert_called_once()
    warehouse.persist.assert_not_called()


def test_committed_retry_does_not_refetch() -> None:
    warehouse = Mock(spec=BigQueryWarehouse)
    warehouse.reconcile.return_value = {"status": "SUCCEEDED"}
    fetch = Mock()
    assert ingest(warehouse, Request("load", date(2026, 8, 1)), uuid4().hex, fetch) == {
        "status": "SUCCEEDED",
    }
    fetch.assert_not_called()
    warehouse.persist.assert_not_called()


def test_cli_requires_explicit_project(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    assert main(["warehouse", "bootstrap"]) == 1
    assert "explicit valid project" in capsys.readouterr().err


def test_persist_refuses_wrong_request_before_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    warehouse, client = store()
    monkeypatch.setattr(warehouse, "get_run", lambda _: {"request_id": "different"})
    with pytest.raises(WarehouseError, match="not bound"):
        warehouse.persist(Request("load", date(2026, 8, 1)), [], uuid4().hex)
    client.query.assert_not_called()


def test_failure_manifest_does_not_store_exception_secrets() -> None:
    warehouse, client = store()
    client.query.return_value.result.return_value = []
    warehouse.fail(uuid4().hex, RuntimeError("secret=do-not-store-this"))
    parameters = client.query.call_args.kwargs["job_config"].query_parameters
    assert "do-not-store-this" not in str([p.to_api_repr() for p in parameters])


@pytest.mark.parametrize("condition", ["unowned", "location", "expiration", "schema"])
def test_bootstrap_refuses_incompatible_existing_resources(condition: str) -> None:
    from google.cloud import bigquery

    from power_market_data.warehouse.schema import table_definition

    warehouse, client = store()
    dataset = bigquery.Dataset("valid-project.power_market_raw")
    dataset.location = "US"
    dataset.labels = {"managed_by": "power-market-data-platform"}
    if condition == "unowned":
        dataset.labels = {}
    elif condition == "location":
        dataset.location = "EU"
    elif condition == "expiration":
        dataset.default_table_expiration_ms = 3600000
    client.create_dataset.return_value = dataset
    wrong = table_definition(CONFIG, "warehouse_control")
    wrong.schema = []
    client.create_table.return_value = wrong
    with pytest.raises(WarehouseError):
        warehouse.bootstrap()
    client.query.assert_not_called()


@pytest.mark.parametrize("status", ["STARTED", "COMMITTED"])
def test_finalization_failure_is_not_success(
    status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warehouse, client = store()
    monkeypatch.setattr(warehouse, "get_run", lambda _: {"status": status, "product": "load"})
    job = Mock()
    job.result.return_value = []
    job.ended = datetime(2026, 9, 20, tzinfo=UTC)
    job.total_bytes_processed = 10
    job.total_bytes_billed = 10485760
    monkeypatch.setattr(warehouse, "_commit_job", lambda _: job)
    client.query.side_effect = TimeoutError("lost response")
    failure = Mock()
    monkeypatch.setattr(warehouse, "fail", failure)
    with pytest.raises(CommitUnconfirmed, match="finalization pending"):
        warehouse.reconcile(uuid4().hex)
    failure.assert_not_called()


def test_cli_fixture_ingestion_and_resume(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    import power_market_data.cli as cli

    monkeypatch.setenv("GCP_PROJECT_ID", "valid-project")
    warehouse = Mock(spec=BigQueryWarehouse)
    warehouse.reconcile.return_value = {"status": "SUCCEEDED"}
    monkeypatch.setattr(cli, "BigQueryWarehouse", lambda _: warehouse)
    run_id = uuid4().hex
    assert main(["ingest", "caiso", "load", "--date", "2026-08-01", "--run-id", run_id]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SUCCEEDED"
    assert main(["warehouse", "resume", "--run-id", run_id]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SUCCEEDED"
    warehouse.persist.assert_not_called()


def test_cli_resume_unknown_outcome_is_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import power_market_data.cli as cli

    monkeypatch.setenv("GCP_PROJECT_ID", "valid-project")
    warehouse = Mock(spec=BigQueryWarehouse)
    warehouse.reconcile.side_effect = CommitUnconfirmed("resume later")
    monkeypatch.setattr(cli, "BigQueryWarehouse", lambda _: warehouse)
    assert main(["warehouse", "resume", "--run-id", uuid4().hex]) == 1
    assert "resume later" in capsys.readouterr().err


def test_failure_recording_can_be_resubmitted_after_quota_error() -> None:
    warehouse, client = store()
    client.query.return_value.result.side_effect = [
        BadRequest("quota exceeded"),  # type: ignore[no-untyped-call]
        [],
    ]
    run_id = uuid4().hex
    with pytest.raises(BadRequest):
        warehouse.fail(run_id, RuntimeError("source failed"), "original-commit")
    warehouse.fail(run_id, RuntimeError("source failed"), "original-commit")
    assert client.query.call_count == 2
    assert all(call.kwargs["job_id"] is None for call in client.query.call_args_list)
    parameters = client.query.call_args.kwargs["job_config"].query_parameters
    assert next(p.value for p in parameters if p.name == "commit_job_id") == "original-commit"


def test_failed_commit_with_pending_manifest_reports_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warehouse, _ = store()
    monkeypatch.setattr(warehouse, "get_run", lambda _: {"status": "STARTED"})
    job = Mock()
    job.result.side_effect = BadRequest("quota exceeded")  # type: ignore[no-untyped-call]
    job.state = "DONE"
    job.error_result = {"reason": "quotaExceeded"}
    monkeypatch.setattr(warehouse, "_commit_job", lambda _: job)
    monkeypatch.setattr(warehouse, "fail", Mock(side_effect=TimeoutError()))
    run_id = uuid4().hex
    with pytest.raises(WarehouseError, match=f"failure status pending; resume run {run_id}"):
        warehouse.reconcile(run_id)
