"""Explicitly opt-in credentialed tests; ordinary CI never opens a cloud client."""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from power_market_data.warehouse.bigquery import BigQueryWarehouse
from power_market_data.warehouse.model import WarehouseConfig


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-bigquery",
        action="store_true",
        default=False,
        help="Run tiny credentialed tests and delete their owned disposable dataset",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not config.getoption("--run-bigquery") or os.environ.get("CI"):
        reason = "BigQuery tests require --run-bigquery and are disabled in CI"
        for item in items:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def warehouse() -> Iterator[BigQueryWarehouse]:
    base = WarehouseConfig.from_environment()
    dataset = "pmd_it_" + datetime.now(UTC).strftime("%Y%m%d_") + uuid4().hex[:12]
    store = BigQueryWarehouse(WarehouseConfig(base.project, dataset, base.location))
    owned_id = f"{base.project}.{dataset}"
    report: dict[str, object] = {"dataset": owned_id, "cleanup": False}
    try:
        store.bootstrap()
        yield store
    finally:
        # Only the exact randomly allocated dataset can be deleted.
        actual = store.client.get_dataset(owned_id)
        if (
            actual.dataset_id != dataset
            or actual.labels.get("managed_by") != "power-market-data-platform"
        ):
            raise RuntimeError("refusing cleanup of an unowned dataset")
        store.client.delete_dataset(owned_id, delete_contents=True, not_found_ok=True)
        report.update(
            cleanup=True,
            query_jobs=len(store.job_metrics),
            bytes_processed=sum(x[0] for x in store.job_metrics.values()),
            bytes_billed=sum(x[1] for x in store.job_metrics.values()),
        )
        path = Path(__file__).resolve().parents[1] / "artifacts" / "phase2-integration-report.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
