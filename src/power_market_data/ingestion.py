"""Coordinate existing CAISO adapters and persistence without mixing their boundaries."""

from collections.abc import Callable, Sequence

from power_market_data.domain import Observation
from power_market_data.sources.caiso import fetch_lmp, fetch_load
from power_market_data.warehouse.bigquery import BigQueryWarehouse, new_run_id
from power_market_data.warehouse.model import Request, Row, WarehouseError


def ingest(
    warehouse: BigQueryWarehouse,
    request: Request,
    run_id: str | None = None,
    fetch: Callable[[], Sequence[Observation]] | None = None,
) -> Row:
    run_id = run_id or new_run_id()
    warehouse.begin(request, run_id)
    prior = warehouse.reconcile(run_id)
    if prior is not None:
        return prior
    try:
        if fetch is not None:
            records = fetch()
        elif request.product == "lmp":
            records = fetch_lmp(request.day, request.location or "")
        else:
            records = fetch_load(request.day)
    except Exception as exc:
        try:
            warehouse.fail(run_id, exc)
        except Exception as failure:
            raise WarehouseError(
                f"run {run_id}: source failed and failure recording failed"
            ) from failure
        raise WarehouseError(f"run {run_id}: {type(exc).__name__}: {exc}") from exc
    return warehouse.persist(request, records, run_id)
