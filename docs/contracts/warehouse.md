# Phase 2 warehouse contract

The warehouse accepts only the existing normalized CAISO records. It does not
call gridstatus, parse DataFrames, or change Phase 1 logical keys/content hashes.
The small ingestion coordinator calls the existing source adapter and then the
storage boundary. [ADR 005](../adr/005-bigquery-persistence.md) explains the decisions.

## Tables and grains

Names below are relative to the configured raw dataset, normally power_market_raw.

| Table | Grain |
| --- | --- |
| ingestion_runs | One UUID-identified bounded ingestion attempt |
| warehouse_control | Exactly one row for this warehouse schema's commit sequence and finalization guard |
| lmp_contents | One distinct Phase 1 LMP logical key/content hash under the recorded identity schemas |
| load_contents | One distinct Phase 1 load logical key/content hash under the recorded identity schemas |
| lmp_state_transitions | One material LMP state occurrence for a logical key in an accepted run |
| load_state_transitions | One material load state occurrence for a logical key in an accepted run |

The authoritative field definitions are in
[src/power_market_data/warehouse/schema.py](../../src/power_market_data/warehouse/schema.py).
They use typed columns, not a JSON payload table:

- Contents: content_id, logical_key/hash and their schema versions; source,
  product, source_dataset, market_date (Pacific DATE), UTC interval TIMESTAMPs,
  unit; LMP market/location and four NUMERIC values, or load area and NUMERIC load;
  first retrieval timestamp/endpoint/method/library version; first_run_id and
  nullable first_seen_at until finalization.
- Transitions: deterministic transition_id, run_id, content_id, logical key/hash
  and versions, market date/interval start, per-observation ordinal, dataset
  commit_sequence, retrieval timestamp and nullable known_at until finalization.
- Runs: request ID, product/date/hub, server start/completion timestamps, status,
  commit_completed, row counts, inserted content/transition counts, batch hash,
  commit job ID/sequence, knowledge_at, package/library/warehouse/identity versions,
  optional supplied code revision, error class/message and commit-job byte totals.
- Control: singleton=1, monotonic sequence, warehouse_schema and active_run_id.

TIMESTAMPs represent UTC instants. Values must fit NUMERIC(38,9) exactly, including
negative LMPs; otherwise the entire batch fails. No rounding or arbitrary price
cap is applied. Raw tables have no expiration, partitions or clustering.
These choices reflect small volume, not a measured performance benefit.

## Run counts and errors

A successful run counts rows returned by the Phase 1 adapter, after any parsing
or dropping done inside gridstatus. On success rows_fetched/normalized/accepted
equal that count, including unchanged observations; new_contents/new_transitions
describe actual additions. rows_rejected=0. Phase 1 fails the whole response on
validation errors, so unavailable counts remain NULL on failure instead of
inventing a rejected-row count. Accepted rows are zero for a confirmed failed
batch. Empty normalized batches can succeed through the storage API, but the
CAISO adapter still treats an empty source response as a request error.

Failure messages in manifests are sanitized categories, not arbitrary exception
text that could contain credentials. CLI errors and authenticated BigQuery job
diagnostics supply detail. A failure to contact BigQuery before a manifest is
durable cannot itself be recorded there; the CLI reports the failure. No logging
system can promise durable failed-run visibility during a complete storage outage.

STARTED means no confirmed commit, COMMITTED means all intended observation
writes are durable but finalization is pending, SUCCEEDED means eligible input,
and FAILED means no observation commit succeeded. A lost/late job response stays
unconfirmed; it is not relabeled FAILED without a terminal job error.

## Identity and clocks

Phase 1 logical and content hashes retain their exact contracts. Additional
warehouse digests use the same sorted compact UTF-8 JSON encoding:

- content_id: namespace warehouse-content/v1 plus logical_key, content_hash,
  logical_key_schema and content_hash_schema.
- transition_id: namespace state-transition/v1 plus run_id and key (logical key).
- request_id: namespace bounded-request/v1 plus source=CAISO, short product
  (lmp/load), Pacific date and location (empty for load).
- batch_hash: namespace batch-content/v1 plus sorted logical-key/content-hash pairs.
  It excludes retrieval time and row ordering.

Event time is the original interval. Retrieval time is separate provenance.
knowledge_at is the successful data-commit job's server-reported end time: a
conservative confirmation bound on durable acceptance, not exact transaction
commit time. The finalization transaction copies it into newly accepted content
first_seen_at and transition known_at. completed_at is an operational marker from
the finalization transaction start; it is not an exact commit clock.
Never use CURRENT_TIMESTAMP inside the data transaction as a commit timestamp.

A→A makes two manifests, one content and one transition. A→B makes two contents
and two transitions. A→B→A has two contents and three transitions: the original
A first_seen_at survives and the last A occurrence has a later known_at.
Ordinal orders a logical observation; commit_sequence orders cooperating batches.
Historical intervals ingested now have historical event time and current
knowledge time. Missing rows never create deletion events.

## Commit protocol and recovery

Data merges and COMMITTED status are one multi-statement transaction.
First-known timestamps, SUCCEEDED status and guard release are another atomic
transaction after confirmed data durability. Future consumers **must join the
originating run and filter status=SUCCEEDED**. Operational inspect already does.

A control-row UPDATE and expected-sequence ASSERT prevent cooperating stale
writers from both publishing conflicting plans. Append-only MERGE by itself
would not do that. All writers must use this code. Administrators can bypass
the contract; BigQuery does not enforce these logical unique keys.

Use a new run ID for each new source retrieval. To retry an uncertain submission,
reuse the printed run ID. A successful replay returns its manifest without
refetching or changing history, even if other states have since been accepted.
A confirmed failed attempt is terminal; retry it as a new attempt. No workflow
retry scheduler or automatic conflict loop exists.

Failure recording and finalization use fresh query jobs for each resubmission;
their guarded updates are idempotent. If quota/network failure prevents recording
a confirmed failed commit, resume can finish that metadata update later. Until
then, the run stays unresolved and is excluded from successful input. The failed
commit job ID is retained for authenticated diagnostics.

A COMMITTED run blocks subsequent data commits until warehouse resume finalizes
it using its original job completion time. STARTED without a submitted job can
be continued by repeating the original ingest request and run ID. If the job
cannot be located but the manifest says COMMITTED, investigate manually; do not
invent a new timestamp or delete the guard.

## Configuration and commands

No dotenv loader is used. Set process environment variables; .env is ignored
and credentials never belong there. GCP_PROJECT_ID is required and never inferred
from an unrelated ADC project. BQ_RAW_DATASET defaults to power_market_raw,
BQ_LOCATION to US, BQ_MAXIMUM_BYTES_BILLED to 104857600 (100 MiB).
The limit can be lowered but not raised above this Phase 2 safety ceiling.
PMD_CODE_REVISION optionally records the code commit for a run.

Use user Application Default Credentials (gcloud auth application-default login,
or gcloud auth login --update-adc). No service-account key file is needed.
The dataset must be in the requested location and owned/labeled by this project.
Bootstrap creates missing tables, validates existing schemas and refuses
destructive replacement or conflicting retention/layout.

From the repository root in PowerShell:

```powershell
$env:GCP_PROJECT_ID = "your-dedicated-project-id"
$env:BQ_LOCATION = "US"
$env:BQ_RAW_DATASET = "power_market_raw"
.\.venv\Scripts\power-market-data.exe warehouse bootstrap
.\.venv\Scripts\power-market-data.exe ingest caiso lmp --date 2026-08-01 --location TH_NP15_GEN-APND
.\.venv\Scripts\power-market-data.exe ingest caiso load --date 2026-08-01
.\.venv\Scripts\power-market-data.exe warehouse inspect lmp --date 2026-08-01 --location TH_NP15_GEN-APND
.\.venv\Scripts\power-market-data.exe warehouse resume --run-id YOUR_PRINTED_UUID_HEX
```

The original caiso lmp/load commands remain print-only. Each ingest fetches one
historical Pacific day (one hub for LMP), with a maximum of 300 observations.
Existing fall-back load exclusions remain. No backfill-range CLI is introduced.

## Integration tests and cleanup

Ordinary pytest and Windows/Linux CI remain offline. Separately opt in:

```powershell
.\.venv\Scripts\python.exe -m pytest integration_tests --run-bigquery -v
```

This is disabled whenever CI is set. The suite creates a unique
pmd_it_YYYYMMDD_random dataset in the explicit project, loads only synthetic
contract rows, and deletes that exact owned dataset in finally. It never modifies
real CAISO prices to simulate a revision. Tests verify both product families,
bootstrap idempotency, repeats, revision/reappearance, rollback, unfinalized
visibility/recovery, late arrivals, stale plans and empty-versus-failed runs.

The local artifacts/phase2-integration-report.json records cleanup and byte totals
for successfully awaited jobs (not a billing invoice). An abruptly killed Python
process cannot execute finally: list pmd_it_ datasets, verify the exact name and
managed_by label, then delete only that disposable dataset with:

```powershell
bq rm --recursive --dataset "YOUR_PROJECT:EXACT_PMD_IT_DATASET"
```

No TTL is imposed on accepted real observations. Test dataset cleanup is a
different lifecycle. The suite's integration_tests directory is included in
source distributions, not the runtime wheel.

## Costs and operational limits

This is a bounded portfolio workload. Ordinary CI makes no cloud queries.
Every Python query carries maximum_bytes_billed, but multi-statement scripts
can include multiple billable statements and metadata/read requests also have
operational limits. Query-byte totals are not dollar charges: free allowances,
minimum billed sizes, account-wide usage and billing timing matter.

Daily query quotas and budget alerts are additional safeguards, not guarantees
of zero cost. Google's custom quotas are approximate and budgets do not hard-cap
spending. See [cost controls](https://docs.cloud.google.com/bigquery/docs/best-practices-costs),
[custom quotas](https://docs.cloud.google.com/bigquery/docs/custom-quotas), and
[budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets).
No reservations, streaming writes, continuous resources, or public-dataset scans
are needed. Keep future reads date-bounded and inspect processed/billed bytes.
The billing-free sandbox lacks DML and expires tables, so it cannot demonstrate
this transaction/indefinite-retention contract.

No dbt, Flyte, marts, as-of consumer query or capture-price analysis exists here.
