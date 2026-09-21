"""Flyte 2 local graph. Source, persistence and SQL contracts stay in their own layers."""

from datetime import timedelta

import flyte
from flyte.errors import NonRecoverableError

from orchestration import operations
from orchestration.ingestion import RetryableIngestionError, execute_unit
from orchestration.plan import (
    Backfill,
    BackfillReport,
    DbtResult,
    IngestionResult,
    Unit,
    VerificationResult,
    expand,
)
from power_market_data.warehouse.model import WarehouseConfig

env = flyte.TaskEnvironment(name="caiso_backfill")
RETRIES = flyte.RetryStrategy(count=1, backoff=flyte.Backoff(base=timedelta(seconds=2)))


@env.task(cache="disable", retries=RETRIES)
async def ingest_day(unit: Unit) -> IngestionResult:
    """One product/date/hub; no observations cross the task boundary."""
    try:
        return execute_unit(unit, WarehouseConfig.from_environment())
    except RetryableIngestionError:
        raise
    except Exception as exc:
        raise NonRecoverableError(str(exc)) from exc


@env.task(cache="disable", retries=0)
async def build_analytics(backfill_id: str) -> DbtResult:
    return operations.build_dbt(backfill_id)


@env.task(cache="disable", retries=0)
async def verify_analytics(units: list[Unit], results: list[IngestionResult]) -> VerificationResult:
    return operations.verify(units, results)


@env.task(cache="disable", retries=0)
async def backfill(spec: Backfill) -> BackfillReport:
    """Fail fast; serial ingestion, then dbt, then bounded verification."""
    units = expand(spec)
    operations.validate_runtime(spec.run_dbt)
    results = []
    for unit in units:
        result = await ingest_day(unit)
        if result.status != "SUCCEEDED":
            raise NonRecoverableError(f"{unit.label}: required ingestion failed")
        results.append(result)
        print(f"SUCCEEDED {unit.label} run={unit.run_id} reused={result.reused_success}")
    dbt = DbtResult("skipped", 0, 0, "")
    verified = VerificationResult("skipped", {})
    if spec.run_dbt:
        dbt = await build_analytics(spec.backfill_id)
        verified = await verify_analytics(units, results)
    report = BackfillReport(
        spec.backfill_id, spec.start_date, spec.end_date, results, dbt, verified
    )
    print(report.text())
    return report
