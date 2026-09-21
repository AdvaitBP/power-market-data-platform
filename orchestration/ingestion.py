"""Delegate state recovery to Phase 2; classify only narrowly safe task retries."""

from google.api_core.exceptions import (
    BadGateway,
    BadRequest,
    Forbidden,
    GatewayTimeout,
    InternalServerError,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
)
from google.auth.exceptions import GoogleAuthError
from requests.exceptions import ConnectionError as RequestConnectionError
from requests.exceptions import Timeout as RequestTimeout

from orchestration.plan import IngestionResult, Unit
from power_market_data.errors import SchemaError, UnsupportedRequestError, ValidationError
from power_market_data.ingestion import ingest
from power_market_data.warehouse.bigquery import BigQueryWarehouse
from power_market_data.warehouse.model import (
    CommitUnconfirmed,
    Row,
    WarehouseConfig,
    WarehouseError,
    validate_run_id,
)


class RetryableIngestionError(WarehouseError):
    """A transient failure for which re-entering the same run is safe."""


def transient(error: BaseException) -> bool:
    """Use exception types, never message substring guesses about quotas."""
    causes: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in causes:
        causes.append(current)
        current = current.__cause__
    if any(
        isinstance(
            e,
            (
                BadRequest,
                Forbidden,
                TooManyRequests,
                Unauthorized,
                GoogleAuthError,
                SchemaError,
                ValidationError,
                UnsupportedRequestError,
                CommitUnconfirmed,
            ),
        )
        for e in causes
    ):
        return False
    return any(
        isinstance(
            e,
            (
                ServiceUnavailable,
                InternalServerError,
                BadGateway,
                GatewayTimeout,
                RequestConnectionError,
                RequestTimeout,
            ),
        )
        for e in causes
    )


def retryable(error: Exception, manifest: Row | None) -> bool:
    # COMMITTED/uncertain outcomes require explicit same-ID reconciliation.
    # A terminal FAILED source attempt can never be revived by a task retry.
    return (
        not isinstance(error, CommitUnconfirmed)
        and (manifest is None or manifest["status"] == "STARTED")
        and transient(error)
    )


def execute_unit(unit: Unit, config: WarehouseConfig) -> IngestionResult:
    request = unit.request()
    validate_run_id(unit.run_id)
    warehouse = BigQueryWarehouse(config)
    try:
        prior = warehouse.get_run(unit.run_id)
    except Exception as exc:
        # No ingestion call or new submission happened in this invocation.
        if transient(exc):
            raise RetryableIngestionError(f"{unit.label}: transient manifest read") from exc
        raise WarehouseError(f"{unit.label}: manifest read failed; run={unit.run_id}") from exc
    try:
        manifest = ingest(warehouse, request, unit.run_id)
    except Exception as exc:
        try:
            state = warehouse.get_run(unit.run_id)
        except Exception:
            state = {"status": "UNKNOWN"}
        if retryable(exc, state):
            raise RetryableIngestionError(f"{unit.label}: retry same run={unit.run_id}") from exc
        raise WarehouseError(
            f"{unit.label}: stopped; run={unit.run_id}; "
            f"status={state['status'] if state else 'ABSENT'}; {type(exc).__name__}. "
            "Resume uncertain/STARTED runs with the same backfill ID; "
            "a terminal FAILED run requires a new backfill ID."
        ) from exc
    if manifest["status"] != "SUCCEEDED":
        raise WarehouseError(f"{unit.label}: ingestion did not finalize SUCCEEDED")
    reused = prior is not None and prior["status"] == "SUCCEEDED"
    return IngestionResult(
        unit=unit,
        status="SUCCEEDED",
        accepted_rows=int(str(manifest["rows_accepted"])),
        new_contents=0 if reused else int(str(manifest["new_contents"])),
        new_transitions=0 if reused else int(str(manifest["new_transitions"])),
        reused_success=reused,
    )
