"""One capped, bounded SELECT from the analytical input mart; no raw writes."""

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from google.cloud import bigquery

from power_market_data.backtesting.inputs import COLUMNS, MarketPrice, from_row, requests
from power_market_data.errors import ValidationError
from power_market_data.warehouse.model import WarehouseConfig


@dataclass(frozen=True)
class QueryUsage:
    job_id: str
    bytes_processed: int | None
    bytes_billed: int | None
    input_relation: str


def read_prices(
    start: date, end: date, location: str, *, client: Any = None
) -> tuple[tuple[MarketPrice, ...], QueryUsage]:
    requests(start, end, location)  # Validate before credentials/client/query creation.
    config = WarehouseConfig.from_environment()
    dataset = os.environ.get("BQ_ANALYTICS_DATASET", "power_market_analytics")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", dataset):
        raise ValidationError("BQ_ANALYTICS_DATASET must be a simple dataset identifier")
    if dataset == config.dataset:
        raise ValidationError("analytics and raw datasets must differ")
    relation = f"{config.project}.{dataset}.mart_battery_optimization_inputs"
    connection = (
        client
        if client is not None
        else bigquery.Client(project=config.project, location=config.location)
    )
    sql = (
        f"SELECT {', '.join(COLUMNS)} FROM `{relation}` "
        "WHERE market_date BETWEEN @start AND @end AND location = @hub "
        "ORDER BY interval_start_utc"
    )
    job = connection.query(
        sql,
        location=config.location,
        job_retry=None,
        job_config=bigquery.QueryJobConfig(
            maximum_bytes_billed=config.maximum_bytes_billed,
            labels={"phase": "phase05", "operation": "battery-input"},
            query_parameters=[
                bigquery.ScalarQueryParameter("start", "DATE", start),
                bigquery.ScalarQueryParameter("end", "DATE", end),
                bigquery.ScalarQueryParameter("hub", "STRING", location),
            ],
        ),
    )
    rows = tuple(from_row(dict(row)) for row in job.result(timeout=120))
    return rows, QueryUsage(
        str(job.job_id), job.total_bytes_processed, job.total_bytes_billed, relation
    )
