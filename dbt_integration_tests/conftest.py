"""Explicit opt-in and owned disposable raw/analytics datasets."""

import json
import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from dbt_checks.fixtures import RAW_TABLES, scenario
from google.cloud import bigquery

from power_market_data.warehouse.model import MAX_BYTES_BILLED, WarehouseConfig
from power_market_data.warehouse.schema import table_definition

ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-dbt-bigquery", action="store_true", default=False)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not config.getoption("--run-dbt-bigquery") or os.environ.get("CI"):
        for item in items:
            item.add_marker(pytest.mark.skip(reason="requires --run-dbt-bigquery; disabled in CI"))


@dataclass
class DbtWarehouse:
    client: bigquery.Client
    raw: WarehouseConfig
    analytics: str
    report: dict[str, Any] = field(default_factory=dict)

    def publish(self, step: str) -> None:
        # Batch loads replace ONLY this test's owned tables. They do not exercise
        # Phase 2 writes (tested separately) or mutate verified CAISO observations.
        for table, rows in scenario(step).items():
            schema = table_definition(self.raw, table).schema
            job = self.client.load_table_from_json(
                json.loads(json.dumps(rows, default=str)),
                self.raw.table(table),
                job_config=bigquery.LoadJobConfig(
                    schema=schema,
                    write_disposition="WRITE_TRUNCATE",
                ),
                location=self.raw.location,
            )
            job.result(timeout=120)

    def dbt(self, *arguments: str, expected_failure: bool = False) -> None:
        binary = (
            ROOT
            / "artifacts"
            / "dbt-core-venv"
            / ("Scripts/dbt.exe" if os.name == "nt" else "bin/dbt")
        )
        environment = {
            **os.environ,
            "GCP_PROJECT_ID": self.raw.project,
            "BQ_RAW_DATASET": self.raw.dataset,
            "BQ_ANALYTICS_DATASET": self.analytics,
            "BQ_LOCATION": self.raw.location,
            "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        }
        command = [
            str(binary),
            *arguments,
            "--project-dir",
            str(ROOT / "dbt"),
            "--profiles-dir",
            str(ROOT / "dbt"),
        ]
        if not expected_failure:
            command.append("--fail-fast")
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        self.report.setdefault("commands", []).append(
            {
                "arguments": arguments,
                "exit_code": result.returncode,
            }
        )
        log = ROOT / "artifacts" / f"dbt-integration-{len(self.report['commands'])}.log"
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        print(result.stdout, result.stderr)
        if expected_failure:
            assert result.returncode != 0, "deliberately broken data contract was not surfaced"
            results = json.loads((ROOT / "dbt/target/run_results.json").read_text("utf-8"))
            assert any(
                row["status"] == "fail" and row["unique_id"].startswith("test.")
                for row in results["results"]
            ), "must fail a data test, not authentication/SQL/quota"
        else:
            assert result.returncode == 0, f"dbt failed; see {log}"

    def query(self, sql: str) -> list[dict[str, Any]]:
        job = self.client.query(
            sql,
            location=self.raw.location,
            job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED),
        )
        return [dict(row) for row in job.result(timeout=120)]

    def rows(self, model: str) -> list[dict[str, Any]]:
        # Read API avoids an additional billable scan for tiny result assertions.
        return [
            dict(row)
            for row in self.client.list_rows(
                f"{self.raw.project}.{self.analytics}.{model}",
                max_results=100,
            )
        ]


@pytest.fixture(scope="session")
def warehouse() -> Iterator[DbtWarehouse]:
    base = WarehouseConfig.from_environment()
    suffix = datetime.now(UTC).strftime("%Y%m%d_") + uuid4().hex[:12]
    raw = WarehouseConfig(base.project, "pmd_dbt_it_raw_" + suffix, base.location)
    analytics = "pmd_dbt_it_analytics_" + suffix
    client = bigquery.Client(project=base.project, location=base.location)
    store = DbtWarehouse(client, raw, analytics)
    owned: list[str] = []
    started = datetime.now(UTC)
    store.report.update(raw=raw.dataset, analytics=analytics, cleanup=False)
    try:
        for name in (raw.dataset, analytics):
            dataset = bigquery.Dataset(f"{base.project}.{name}")
            dataset.location = base.location
            dataset.labels = {"managed_by": "pmd-dbt-integration", "owner": suffix}
            dataset.default_table_expiration_ms = 24 * 60 * 60 * 1000
            client.create_dataset(dataset)  # Collision must fail, never adopt an existing dataset.
            owned.append(name)
        for name in RAW_TABLES:
            client.create_table(table_definition(raw, name))
        yield store
    finally:
        for name in owned:
            identifier = f"{base.project}.{name}"
            actual = client.get_dataset(identifier)
            if actual.labels.get("owner") != suffix:
                raise RuntimeError("refusing cleanup: disposable dataset ownership changed")
            client.delete_dataset(identifier, delete_contents=True, not_found_ok=True)
        store.report["cleanup"] = True
        jobs = list(client.list_jobs(min_creation_time=started))
        # Parent query statistics already include script children; do not double count.
        queries = [
            job for job in jobs if isinstance(job, bigquery.QueryJob) and not job.parent_job_id
        ]
        store.report.update(
            query_jobs=len(queries),
            bytes_processed=sum(job.total_bytes_processed or 0 for job in queries),
            bytes_billed=sum(job.total_bytes_billed or 0 for job in queries),
        )
        path = ROOT / "artifacts" / "phase3-integration-report.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(store.report, default=str, indent=2), encoding="utf-8")
        print(json.dumps(store.report, default=str))
