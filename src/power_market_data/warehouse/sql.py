"""Small, reviewable BigQuery scripts; values are always query parameters."""

from power_market_data.warehouse.model import WAREHOUSE_SCHEMA, WarehouseConfig
from power_market_data.warehouse.schema import TABLES


def guard(config: WarehouseConfig) -> str:
    table = config.table("warehouse_control")
    return f"""
UPDATE `{table}` SET sequence = sequence WHERE singleton = 1;
ASSERT @@row_count = 1 AS 'warehouse control must have exactly one row';
ASSERT (SELECT warehouse_schema FROM `{table}` WHERE singleton = 1)
    = '{WAREHOUSE_SCHEMA}' AS 'incompatible warehouse schema';
"""


def begin_run(config: WarehouseConfig) -> str:
    table = config.table("ingestion_runs")
    names = ", ".join(field for field, _, _ in TABLES["ingestion_runs"])
    values = ", ".join(
        "CURRENT_TIMESTAMP()" if field == "started_at" else f"@run.{field}"
        for field, _, _ in TABLES["ingestion_runs"]
    )
    return f"""
BEGIN TRANSACTION;
{guard(config)}
ASSERT NOT EXISTS (SELECT 1 FROM `{table}`
    WHERE run_id = @run.run_id AND request_id != @run.request_id)
    AS 'run ID already belongs to another request';
INSERT INTO `{table}` ({names})
SELECT {values} FROM UNNEST([1]) AS seed
WHERE NOT EXISTS (SELECT 1 FROM `{table}` WHERE run_id = @run.run_id);
COMMIT TRANSACTION;
"""


def snapshot_query(config: WarehouseConfig, product: str) -> str:
    return f"""
SELECT sequence, active_run_id, warehouse_schema,
ARRAY(SELECT AS STRUCT content_id, logical_key_schema, content_hash_schema
      FROM `{config.table(product + "_contents")}`
      WHERE market_date = @day) AS contents,
ARRAY(SELECT AS STRUCT logical_key, content_hash, ordinal
      FROM `{config.table(product + "_state_transitions")}`
      WHERE market_date = @day
      QUALIFY ROW_NUMBER() OVER (PARTITION BY logical_key ORDER BY ordinal DESC) = 1) AS latest
FROM `{config.table("warehouse_control")}` WHERE singleton = 1
"""


def merge_rows(config: WarehouseConfig, name: str, parameter: str, key: str) -> str:
    columns = ", ".join(field for field, _, _ in TABLES[name])
    values = ", ".join("S." + field for field, _, _ in TABLES[name])
    return f"""
MERGE `{config.table(name)}` T USING UNNEST(@{parameter}) S
ON T.{key} = S.{key}
WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({values});
"""


def commit_query(config: WarehouseConfig, product: str) -> str:
    runs, control = config.table("ingestion_runs"), config.table("warehouse_control")
    return f"""
BEGIN TRANSACTION;
{guard(config)}
ASSERT (SELECT COUNT(*) FROM `{runs}` WHERE run_id = @run_id AND status = 'STARTED') = 1
    AS 'run is not started';
ASSERT (SELECT sequence FROM `{control}` WHERE singleton = 1) = @expected_sequence
    AS 'stale snapshot: another batch committed; start a new attempt';
ASSERT (SELECT active_run_id IS NULL FROM `{control}` WHERE singleton = 1)
    AS 'an earlier commit requires finalization';
UPDATE `{control}` SET sequence = sequence + 1, active_run_id = @run_id WHERE singleton = 1;
{merge_rows(config, product + "_contents", "contents", "content_id")}
{merge_rows(config, product + "_state_transitions", "transitions", "transition_id")}
UPDATE `{runs}` SET
    status = 'COMMITTED', commit_completed = TRUE, batch_hash = @batch_hash,
    commit_job_id = @commit_job_id, commit_sequence = @expected_sequence + 1,
    rows_fetched = @accepted, rows_normalized = @accepted,
    rows_accepted = @accepted, rows_rejected = 0,
    new_contents = IFNULL(ARRAY_LENGTH(@contents), 0),
    new_transitions = IFNULL(ARRAY_LENGTH(@transitions), 0)
WHERE run_id = @run_id;
COMMIT TRANSACTION;
"""


def finalize_query(config: WarehouseConfig, product: str) -> str:
    runs, control = config.table("ingestion_runs"), config.table("warehouse_control")
    return f"""
BEGIN TRANSACTION;
{guard(config)}
IF (SELECT status FROM `{runs}` WHERE run_id = @run_id) != 'SUCCEEDED' THEN
    ASSERT (SELECT active_run_id FROM `{control}` WHERE singleton = 1) = @run_id
        AS 'run does not own the finalization gate';
    ASSERT (SELECT status FROM `{runs}` WHERE run_id = @run_id) = 'COMMITTED'
        AS 'run has not durably committed';
    UPDATE `{config.table(product + "_contents")}`
        SET first_seen_at = @knowledge_at WHERE first_run_id = @run_id AND first_seen_at IS NULL;
    UPDATE `{config.table(product + "_state_transitions")}`
        SET known_at = @knowledge_at WHERE run_id = @run_id AND known_at IS NULL;
    UPDATE `{runs}` SET status = 'SUCCEEDED', completed_at = CURRENT_TIMESTAMP(),
        knowledge_at = @knowledge_at, query_bytes_processed = @processed,
        query_bytes_billed = @billed WHERE run_id = @run_id;
    UPDATE `{control}` SET active_run_id = NULL WHERE singleton = 1;
END IF;
COMMIT TRANSACTION;
"""


def failure_query(config: WarehouseConfig) -> str:
    return f"""
BEGIN TRANSACTION;
{guard(config)}
UPDATE `{config.table("ingestion_runs")}`
SET status = 'FAILED', completed_at = CURRENT_TIMESTAMP(),
    error_class = @error_class, error_message = @error_message, rows_accepted = 0,
    commit_job_id = COALESCE(@commit_job_id, commit_job_id)
WHERE run_id = @run_id AND status = 'STARTED' AND NOT commit_completed;
COMMIT TRANSACTION;
"""
