"""Native BigQuery I/O with atomic batches, an optimistic sequence and job reconciliation."""

import os
from collections.abc import Sequence
from importlib.metadata import version
from typing import cast
from uuid import uuid4

from google.api_core.exceptions import Conflict, GoogleAPICallError, NotFound
from google.auth.exceptions import GoogleAuthError
from google.cloud import bigquery

from power_market_data import __version__
from power_market_data.domain import Observation
from power_market_data.identity import digest
from power_market_data.time import as_utc
from power_market_data.warehouse import sql
from power_market_data.warehouse.model import (
    CONTENT_SCHEMA,
    KEY_SCHEMA,
    WAREHOUSE_SCHEMA,
    CommitUnconfirmed,
    Latest,
    Request,
    Row,
    Snapshot,
    Value,
    WarehouseConfig,
    WarehouseError,
    batch_rows,
    plan_write,
    validate_run_id,
)
from power_market_data.warehouse.schema import TABLES, Fields, table_definition


def scalar(name: str, kind: str, value: Value) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter(name, kind, value)


def struct(name: str | None, fields: Fields, row: Row) -> bigquery.StructQueryParameter:
    return bigquery.StructQueryParameter(
        name, *(scalar(field, kind, row.get(field)) for field, kind, _ in fields)
    )


def array(name: str, fields: Fields, rows: Sequence[Row]) -> bigquery.ArrayQueryParameter:
    # The client annotates parameters but not these two type-descriptor constructors.
    types = [
        bigquery.ScalarQueryParameterType(kind, name=field)  # type: ignore[no-untyped-call]
        for field, kind, _ in fields
    ]
    element_type = bigquery.StructQueryParameterType(*types)  # type: ignore[no-untyped-call]
    return bigquery.ArrayQueryParameter(
        name, element_type, [struct(None, fields, row) for row in rows]
    )


class BigQueryWarehouse:
    def __init__(self, config: WarehouseConfig, client: bigquery.Client | None = None) -> None:
        self.config = config
        self.job_metrics: dict[str, tuple[int, int]] = {}
        try:
            self.client = client or bigquery.Client(
                project=config.project, location=config.location
            )
        except GoogleAuthError as exc:
            raise WarehouseError(
                "ADC unavailable; run gcloud auth application-default login"
            ) from exc

    def job_id(self, run_id: str, operation: str) -> str:
        namespace = digest(
            "warehouse-job/v1",
            {
                "project": self.config.project,
                "dataset": self.config.dataset,
                "location": self.config.location,
            },
        )[:16]
        return f"pmd_{namespace}_{run_id}_{operation}"

    def query(
        self,
        query: str,
        parameters: Sequence[
            bigquery.ScalarQueryParameter
            | bigquery.StructQueryParameter
            | bigquery.ArrayQueryParameter
        ] = (),
        job_id: str | None = None,
    ) -> bigquery.QueryJob:
        config = bigquery.QueryJobConfig(
            query_parameters=list(parameters),
            use_legacy_sql=False,
            maximum_bytes_billed=self.config.maximum_bytes_billed,
            labels={"application": "power-market-data-platform", "phase": "02"},
        )
        try:
            return self.client.query(
                query,
                job_config=config,
                job_id=job_id,
                location=self.config.location,
                job_retry=None,
                timeout=60,
            )
        except Conflict:
            if job_id is None:
                raise
            return cast(
                bigquery.QueryJob, self.client.get_job(job_id, location=self.config.location)
            )

    def wait(self, job: bigquery.QueryJob) -> list[Row]:
        rows = [cast(Row, dict(row.items())) for row in job.result(timeout=180, job_retry=None)]
        self.job_metrics[job.job_id] = (job.total_bytes_processed or 0, job.total_bytes_billed or 0)
        return rows

    def bootstrap(self) -> None:
        dataset = bigquery.Dataset(f"{self.config.project}.{self.config.dataset}")
        dataset.location = self.config.location
        dataset.labels = {"managed_by": "power-market-data-platform", "schema": "v1"}
        dataset.description = (
            "Portfolio raw observations, contents, transitions and ingestion runs."
        )
        try:
            actual = self.client.create_dataset(dataset, exists_ok=True, timeout=60)
            if actual.location.lower() != self.config.location.lower():
                raise WarehouseError("existing dataset location differs from BQ_LOCATION")
            if actual.labels.get("managed_by") != "power-market-data-platform":
                raise WarehouseError("refusing to bootstrap an unrelated dataset")
            if actual.default_table_expiration_ms or actual.default_partition_expiration_ms:
                raise WarehouseError("raw retention contract forbids dataset default expirations")
            for name in TABLES:
                expected = table_definition(self.config, name)
                actual_table = self.client.create_table(expected, exists_ok=True, timeout=60)
                fields = tuple((f.name, f.field_type, f.mode) for f in actual_table.schema)
                # BigQuery returns INTEGER rather than the INT64 alias.
                normalized = tuple(
                    (n, {"INTEGER": "INT64", "BOOLEAN": "BOOL"}.get(t, t), m) for n, t, m in fields
                )
                if normalized != TABLES[name]:
                    raise WarehouseError(
                        f"incompatible schema for {name}; no destructive migration"
                    )
                if (
                    actual_table.expires
                    or actual_table.time_partitioning
                    or actual_table.range_partitioning
                    or actual_table.clustering_fields
                ):
                    raise WarehouseError(f"unexpected retention/physical layout for {name}")
            control = self.config.table("warehouse_control")
            self.wait(
                self.query(
                    f"""
MERGE `{control}` T USING (SELECT 1 AS singleton) S ON T.singleton = S.singleton
WHEN NOT MATCHED THEN INSERT (singleton, sequence, warehouse_schema, active_run_id)
VALUES (1, 0, '{WAREHOUSE_SCHEMA}', NULL);
ASSERT (SELECT COUNT(*) FROM `{control}`) = 1 AS 'invalid warehouse control';
""",
                    job_id=self.job_id("bootstrap", "v1"),
                )
            )
        except GoogleAPICallError as exc:
            raise WarehouseError(f"BigQuery bootstrap failed: {type(exc).__name__}") from exc

    def get_run(self, run_id: str) -> Row | None:
        validate_run_id(run_id)
        rows = self.wait(
            self.query(
                f"SELECT * FROM `{self.config.table('ingestion_runs')}` WHERE run_id = @run_id",
                [scalar("run_id", "STRING", run_id)],
            )
        )
        if len(rows) > 1:
            raise WarehouseError("duplicate manifest IDs; warehouse requires investigation")
        return rows[0] if rows else None

    def begin(self, request: Request, run_id: str) -> Row:
        validate_run_id(run_id)
        row: Row = {
            "run_id": run_id,
            "request_id": request.request_id,
            "source": "CAISO",
            "product": request.product,
            "requested_date": request.day,
            "requested_location": request.location,
            "status": "STARTED",
            "commit_completed": False,
            "package_version": __version__,
            "library_version": version("gridstatus"),
            "warehouse_schema": WAREHOUSE_SCHEMA,
            "logical_key_schema": KEY_SCHEMA,
            "content_hash_schema": CONTENT_SCHEMA,
            "code_revision": os.environ.get("PMD_CODE_REVISION"),
        }
        self.wait(
            self.query(
                sql.begin_run(self.config),
                [struct("run", TABLES["ingestion_runs"], row)],
                self.job_id(run_id, "begin"),
            )
        )
        manifest = self.get_run(run_id)
        if manifest is None or manifest["request_id"] != request.request_id:
            raise WarehouseError("run ID is bound to a different request or manifest is absent")
        return manifest

    def snapshot(self, request: Request) -> Snapshot:
        rows = self.wait(
            self.query(
                sql.snapshot_query(self.config, request.product),
                [scalar("day", "DATE", request.day)],
            )
        )
        if len(rows) != 1:
            raise WarehouseError("missing/duplicate warehouse control row; bootstrap first")
        row = rows[0]
        if row["warehouse_schema"] != WAREHOUSE_SCHEMA:
            raise WarehouseError("incompatible warehouse schema")
        if row["active_run_id"] is not None:
            raise WarehouseError(f"run {row['active_run_id']} requires warehouse resume")
        contents = cast(list[Row], row["contents"])
        if any(
            c["logical_key_schema"] != KEY_SCHEMA or c["content_hash_schema"] != CONTENT_SCHEMA
            for c in contents
        ):
            raise WarehouseError("incompatible identity schemas; explicit migration required")
        ids = frozenset(str(c["content_id"]) for c in contents)
        if len(ids) != len(contents):
            raise WarehouseError("duplicate content IDs; warehouse requires investigation")
        latest = {
            str(item["logical_key"]): Latest(str(item["content_hash"]), cast(int, item["ordinal"]))
            for item in cast(list[Row], row["latest"])
        }
        return Snapshot(cast(int, row["sequence"]), ids, latest)

    def fail(self, run_id: str, error: Exception, commit_job_id: str | None = None) -> None:
        # Detailed exceptions stay local; manifests never ingest arbitrary client/credential text.
        message = (
            "Source/normalization/warehouse validation failed; inspect the invoking CLI error."
            if not isinstance(error, GoogleAPICallError)
            else "BigQuery job failed; inspect its job ID and authenticated job diagnostics."
        )
        self.wait(
            self.query(
                sql.failure_query(self.config),
                [
                    scalar("run_id", "STRING", run_id),
                    scalar("error_class", "STRING", type(error).__name__),
                    scalar("error_message", "STRING", message),
                    scalar("commit_job_id", "STRING", commit_job_id),
                ],
                # This guarded update can be resubmitted after a failed recording job.
                # A failed deterministic job ID would permanently pin the failure.
            )
        )

    def _commit_job(self, run_id: str) -> bigquery.QueryJob | None:
        try:
            return cast(
                bigquery.QueryJob,
                self.client.get_job(
                    self.job_id(run_id, "commit"), location=self.config.location, timeout=60
                ),
            )
        except NotFound:
            return None

    def reconcile(self, run_id: str) -> Row | None:
        manifest = self.get_run(run_id)
        if manifest is None:
            raise WarehouseError("unknown run ID")
        if manifest["status"] == "SUCCEEDED":
            return manifest
        if manifest["status"] == "FAILED":
            raise WarehouseError(f"run {run_id} failed; use a new run ID for a new attempt")
        job = self._commit_job(run_id)
        if job is None:
            if manifest["status"] == "COMMITTED":
                raise CommitUnconfirmed(
                    "commit job metadata unavailable; manual reconciliation required"
                )
            return None
        try:
            self.wait(job)
        except Exception as exc:
            # Only a confirmed terminal failure permits a FAILED manifest.
            try:
                job.reload(timeout=60)
            except Exception:
                raise CommitUnconfirmed(f"job outcome unknown; resume run {run_id}") from exc
            if job.state == "DONE" and job.error_result is not None:
                try:
                    self.fail(run_id, exc, job.job_id)
                except Exception as recording_error:
                    raise WarehouseError(
                        f"commit failed; failure status pending; resume run {run_id}"
                    ) from recording_error
                raise WarehouseError(f"commit job failed for run {run_id}: {job.job_id}") from exc
            raise CommitUnconfirmed(f"job outcome unknown; resume run {run_id}") from exc
        if job.ended is None:
            raise CommitUnconfirmed(f"job completion timestamp unavailable; resume run {run_id}")
        try:
            self.wait(
                self.query(
                    sql.finalize_query(self.config, str(manifest["product"])),
                    [
                        scalar("run_id", "STRING", run_id),
                        scalar("knowledge_at", "TIMESTAMP", as_utc(job.ended)),
                        scalar("processed", "INT64", job.total_bytes_processed),
                        scalar("billed", "INT64", job.total_bytes_billed),
                    ],
                )
            )
        except Exception as exc:
            raise CommitUnconfirmed(
                f"data committed; finalization pending for run {run_id}"
            ) from exc
        result = self.get_run(run_id)
        if result is None or result["status"] != "SUCCEEDED":
            raise CommitUnconfirmed(f"success confirmation unavailable; resume run {run_id}")
        return result

    def persist(self, request: Request, records: Sequence[Observation], run_id: str) -> Row:
        manifest = self.get_run(run_id)
        if manifest is None or manifest["request_id"] != request.request_id:
            raise WarehouseError("run ID is not bound to this request; begin the correct run first")
        prior = self.reconcile(run_id)
        if prior is not None:
            return prior
        try:
            rows = batch_rows(request, records)
            plan = plan_write(run_id, rows, self.snapshot(request))
        except Exception as exc:
            self.fail(run_id, exc)
            raise
        parameters: list[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter] = [
            scalar("run_id", "STRING", run_id),
            scalar("expected_sequence", "INT64", plan.expected_sequence),
            scalar("batch_hash", "STRING", plan.batch_hash),
            scalar("accepted", "INT64", plan.accepted),
            scalar("commit_job_id", "STRING", self.job_id(run_id, "commit")),
            array("contents", TABLES[request.product + "_contents"], plan.contents),
            array("transitions", TABLES[request.product + "_state_transitions"], plan.transitions),
        ]
        try:
            self.query(
                sql.commit_query(self.config, request.product),
                parameters,
                self.job_id(run_id, "commit"),
            )
        except Exception as exc:
            raise CommitUnconfirmed(f"submission outcome unknown; resume run {run_id}") from exc
        result = self.reconcile(run_id)
        if result is None:
            raise CommitUnconfirmed(f"commit job not yet visible; resume run {run_id}")
        return result

    def inspect(self, request: Request, limit: int = 5) -> dict[str, object]:
        """Operational inspection of one request, not an as-of analytical consumer."""
        runs = self.config.table("ingestion_runs")
        contents = self.config.table(request.product + "_contents")
        transitions = self.config.table(request.product + "_state_transitions")
        location = "AND C.location = @location" if request.product == "lmp" else ""
        parameters = [
            scalar("day", "DATE", request.day),
            scalar("request_id", "STRING", request.request_id),
            scalar("limit", "INT64", min(max(limit, 1), 100)),
        ]
        if request.product == "lmp":
            parameters.append(scalar("location", "STRING", request.location))
        counts = self.wait(
            self.query(
                f"""
SELECT
 (SELECT COUNT(*) FROM `{contents}` C JOIN `{runs}` R ON C.first_run_id = R.run_id
  WHERE C.market_date = @day AND R.status = 'SUCCEEDED' {location}) AS contents,
 (SELECT COUNT(*) FROM `{transitions}` T
  JOIN `{contents}` C ON T.content_id = C.content_id
  JOIN `{runs}` R ON T.run_id = R.run_id
  WHERE T.market_date = @day AND C.market_date = @day
  AND R.status = 'SUCCEEDED' {location}) AS transitions
""",
                parameters,
            )
        )
        manifests = self.wait(
            self.query(
                f"SELECT * FROM `{runs}` WHERE requested_date = @day "
                "AND request_id = @request_id ORDER BY started_at DESC LIMIT @limit",
                parameters,
            )
        )
        return {"counts": counts[0], "runs": manifests}


def new_run_id() -> str:
    return uuid4().hex
