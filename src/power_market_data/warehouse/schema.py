"""Explicit, typed BigQuery table contracts. No expirations, partitions or clusters."""

from google.cloud import bigquery

from power_market_data.warehouse.model import WarehouseConfig

type Fields = tuple[tuple[str, str, str], ...]


def required(*fields: tuple[str, str]) -> Fields:
    return tuple((name, kind, "REQUIRED") for name, kind in fields)


COMMON = required(
    ("content_id", "STRING"),
    ("logical_key", "STRING"),
    ("content_hash", "STRING"),
    ("logical_key_schema", "STRING"),
    ("content_hash_schema", "STRING"),
    ("source", "STRING"),
    ("product", "STRING"),
    ("source_dataset", "STRING"),
    ("market_date", "DATE"),
    ("interval_start_utc", "TIMESTAMP"),
    ("interval_end_utc", "TIMESTAMP"),
    ("unit", "STRING"),
    ("retrieved_at_utc", "TIMESTAMP"),
    ("source_url", "STRING"),
    ("source_method", "STRING"),
    ("library_version", "STRING"),
    ("first_run_id", "STRING"),
) + (("first_seen_at", "TIMESTAMP", "NULLABLE"),)
TRANSITIONS = required(
    ("transition_id", "STRING"),
    ("run_id", "STRING"),
    ("logical_key", "STRING"),
    ("content_id", "STRING"),
    ("content_hash", "STRING"),
    ("logical_key_schema", "STRING"),
    ("content_hash_schema", "STRING"),
    ("market_date", "DATE"),
    ("interval_start_utc", "TIMESTAMP"),
    ("ordinal", "INT64"),
    ("commit_sequence", "INT64"),
    ("retrieved_at_utc", "TIMESTAMP"),
) + (("known_at", "TIMESTAMP", "NULLABLE"),)
RUNS = required(
    ("run_id", "STRING"),
    ("request_id", "STRING"),
    ("source", "STRING"),
    ("product", "STRING"),
    ("requested_date", "DATE"),
    ("started_at", "TIMESTAMP"),
    ("status", "STRING"),
    ("commit_completed", "BOOL"),
    ("package_version", "STRING"),
    ("library_version", "STRING"),
    ("warehouse_schema", "STRING"),
    ("logical_key_schema", "STRING"),
    ("content_hash_schema", "STRING"),
) + tuple(
    (name, kind, "NULLABLE")
    for name, kind in (
        ("requested_location", "STRING"),
        ("completed_at", "TIMESTAMP"),
        ("knowledge_at", "TIMESTAMP"),
        ("rows_fetched", "INT64"),
        ("rows_normalized", "INT64"),
        ("rows_accepted", "INT64"),
        ("rows_rejected", "INT64"),
        ("new_contents", "INT64"),
        ("new_transitions", "INT64"),
        ("batch_hash", "STRING"),
        ("error_class", "STRING"),
        ("error_message", "STRING"),
        ("commit_job_id", "STRING"),
        ("commit_sequence", "INT64"),
        ("query_bytes_processed", "INT64"),
        ("query_bytes_billed", "INT64"),
        ("code_revision", "STRING"),
    )
)
TABLES: dict[str, Fields] = {
    "warehouse_control": required(
        ("singleton", "INT64"), ("sequence", "INT64"), ("warehouse_schema", "STRING")
    )
    + (("active_run_id", "STRING", "NULLABLE"),),
    "ingestion_runs": RUNS,
    "lmp_contents": COMMON
    + required(
        ("market", "STRING"),
        ("location", "STRING"),
        ("lmp", "NUMERIC"),
        ("energy", "NUMERIC"),
        ("congestion", "NUMERIC"),
        ("loss", "NUMERIC"),
    ),
    "load_contents": COMMON + required(("area", "STRING"), ("load", "NUMERIC")),
    "lmp_state_transitions": TRANSITIONS,
    "load_state_transitions": TRANSITIONS,
}


def table_definition(config: WarehouseConfig, name: str) -> bigquery.Table:
    table = bigquery.Table(
        config.table(name),
        schema=[bigquery.SchemaField(field, kind, mode=mode) for field, kind, mode in TABLES[name]],
    )
    table.labels = {"managed_by": "power-market-data-platform", "schema": "v1"}
    table.description = "Phase 2 raw persistence; see repository ADR 005 and warehouse contract."
    return table
