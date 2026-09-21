"""Existing dbt subprocess and a bounded post-build check; no transformation SQL."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from google.cloud import bigquery

from orchestration.plan import DbtResult, IngestionResult, Unit, VerificationResult
from power_market_data.warehouse.bigquery import BigQueryWarehouse, scalar
from power_market_data.warehouse.model import WarehouseConfig, WarehouseError, validate_run_id

ROOT = Path(__file__).resolve().parents[1]
DBT_BIN = ROOT / "artifacts/dbt-core-venv" / ("Scripts" if os.name == "nt" else "bin")


def configuration() -> tuple[WarehouseConfig, str]:
    raw = WarehouseConfig.from_environment()
    analytics = os.environ.get("BQ_ANALYTICS_DATASET", "power_market_analytics")
    WarehouseConfig(raw.project, analytics, raw.location)  # Validate the identifier.
    if analytics in (raw.dataset, "power_market_raw"):
        raise WarehouseError("analytics target must differ from raw")
    return raw, analytics


def validate_runtime(run_dbt: bool) -> None:
    configuration()
    if run_dbt and not (DBT_BIN / ("dbt.exe" if os.name == "nt" else "dbt")).is_file():
        raise WarehouseError("install the isolated dbt/requirements.txt environment first")


def build_dbt(backfill_id: str) -> DbtResult:
    validate_run_id(backfill_id)
    raw, analytics = configuration()
    destination = ROOT / "artifacts/orchestration" / backfill_id / uuid4().hex
    destination.mkdir(parents=True, exist_ok=True)
    # Use the committed capped profile, never an arbitrary user profile.
    shutil.copyfile(ROOT / "dbt/profiles.example.yml", destination / "profiles.yml")
    python = DBT_BIN / ("python.exe" if os.name == "nt" else "python")
    dbt = DBT_BIN / ("dbt.exe" if os.name == "nt" else "dbt")
    environment = {
        **os.environ,
        "GCP_PROJECT_ID": raw.project,
        "BQ_RAW_DATASET": raw.dataset,
        "BQ_ANALYTICS_DATASET": analytics,
        "BQ_LOCATION": raw.location,
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        "PYTHONUTF8": "1",
    }
    # The verified adapter cap must pass before any build submits queries.
    cap = subprocess.run(
        [str(python), str(ROOT / "dbt/tooling/check_cost_cap.py")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    (destination / "cap.log").write_text(cap.stdout + cap.stderr, encoding="utf-8")
    if cap.returncode:
        raise WarehouseError(f"dbt safety-cap regression failed; see {destination / 'cap.log'}")
    log = destination / "dbt.log"
    try:
        result = subprocess.run(
            [
                str(dbt),
                "build",
                "--fail-fast",
                "--project-dir",
                str(ROOT / "dbt"),
                "--profiles-dir",
                str(destination),
                "--target-path",
                str(destination / "target"),
                "--log-path",
                str(destination / "logs"),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WarehouseError(
            "dbt timed out; inspect BigQuery jobs before resuming or starting another writer"
        ) from exc
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise WarehouseError(f"dbt failed (exit {result.returncode}); see {log}")
    results = json.loads((destination / "target/run_results.json").read_text(encoding="utf-8"))
    statuses = [row["status"] for row in results["results"]]
    if not statuses or any(status not in ("success", "pass") for status in statuses):
        raise WarehouseError(f"dbt did not produce an entirely successful build; see {log}")
    return DbtResult("passed", result.returncode, len(statuses), str(log))


def verify(units: list[Unit], results: list[IngestionResult]) -> VerificationResult:
    raw, analytics = configuration()
    warehouse = BigQueryWarehouse(raw)
    counts: dict[str, int] = {}
    for product, table in (("lmp", "fct_hourly_lmp"), ("load", "fct_system_load_5min")):
        selected = [unit for unit in units if unit.product == product]
        if not selected:
            continue
        relation = f"{raw.project}.{analytics}.{table}"
        warehouse.client.get_table(relation)
        location = "location" if product == "lmp" else "''"
        predicate = "and f.location in UNNEST(@hubs)" if product == "lmp" else ""
        parameters = [
            scalar("start", "DATE", selected[0].request().day),
            scalar("end", "DATE", selected[-1].request().day),
        ]
        query_parameters: list[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter] = [
            *parameters
        ]
        if product == "lmp":
            query_parameters.append(
                bigquery.ArrayQueryParameter(
                    "hubs", "STRING", sorted({unit.location for unit in selected})
                )
            )
        job = warehouse.query(
            f"""
            SELECT f.market_date, {location} AS hub, COUNT(*) AS n,
                COUNT(DISTINCT f.logical_key) AS keys,
                COUNTIF(r.status IS DISTINCT FROM 'SUCCEEDED') AS ineligible
            FROM `{relation}` f
            LEFT JOIN `{raw.table("ingestion_runs")}` r ON f.state_run_id = r.run_id
            WHERE f.market_date BETWEEN @start AND @end {predicate}
            GROUP BY f.market_date, hub
            """,
            query_parameters,
        )
        rows = warehouse.wait(job)
        for row in rows:
            if row["n"] != row["keys"] or row["ineligible"] != 0:
                raise WarehouseError(f"bounded analytical uniqueness/eligibility failed: {table}")
            counts[f"{row['market_date']}/{product}/{row['hub'] or 'CAISO'}"] = int(str(row["n"]))
    for result in results:
        if counts.get(result.unit.label, 0) < result.accepted_rows:
            raise WarehouseError(f"accepted observations missing from facts: {result.unit.label}")
        counts.setdefault(result.unit.label, 0)
    return VerificationResult(
        "passed",
        counts,
        sum(metric[0] for metric in warehouse.job_metrics.values()),
        sum(metric[1] for metric in warehouse.job_metrics.values()),
    )
