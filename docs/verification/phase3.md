# Phase 3 verification â€” 2026-09-20

Status: **Incomplete; do not merge.** The controlled BigQuery build was blocked
by the existing custom daily query quota. The formal Phase 3 definition of done
has not been met. No quota or budget setting was increased or removed.

## Toolchain and offline checks

Final toolchain: Python 3.12.14, dbt-core 1.12.5, dbt-bigquery 1.12.1 in
artifacts/dbt-core-venv. The application retains gridstatus 0.36.0 and
google-cloud-bigquery 3.45.2. Jinja2 3.1.6 is a development-only dependency for
executing the portable SQL subset in offline tests.

Commands run from the actual repository (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -I -c "import power_market_data; print(power_market_data.__version__)"
.\.venv\Scripts\python.exe -m build
.\artifacts\dbt-core-venv\Scripts\python.exe -m pip check
.\artifacts\dbt-core-venv\Scripts\python.exe dbt/tooling/check_cost_cap.py
.\artifacts\dbt-core-venv\Scripts\dbt.exe --version
```

Results: dependency checks passed; Ruff lint/format passed; strict mypy passed;
**191 offline pytest tests passed**, including 19 new SQL/guard tests; isolated
import printed 0.1.0; source distribution and wheel built. The separate adapter
cap regression check passed (one unittest); it intercepts the native client's
submission and confirms maximumBytesBilled=104857600 without networking.

With GCP_PROJECT_ID=offline-project, GOOGLE_APPLICATION_CREDENTIALS set to a
nonexistent path and DBT_SEND_ANONYMOUS_USAGE_STATS=false:

```powershell
.\artifacts\dbt-core-venv\Scripts\dbt.exe parse --project-dir dbt --profiles-dir dbt --no-partial-parse
.\artifacts\dbt-core-venv\Scripts\dbt.exe docs generate --no-compile --empty-catalog --static --project-dir dbt --profiles-dir dbt
```

Both passed. The project defines **11 models, 38 data tests and 7 native unit
tests**, over 5 sources. Generated manifest/lineage, index.html and static_index.html
are ignored in dbt/target. The catalog is intentionally empty: these docs do not
demonstrate materialized warehouse models or live column statistics.

Offline SQL tests exercise both products through unchanged A, B, returned A and
late historical events; unsuccessful run rows remain excluded. They compare
candidate-plus-prior rows with full-query results. Native MERGE and native
full-refresh equivalence remain unverified; SQLite is not BigQuery.

## Live preflight and controlled attempt

The dedicated project is advait-power-market-20260920. ADC authenticated using
the existing personal-user credentials outside the repository. Dataset metadata
confirmed unchanged raw counts:

| Raw table | Rows |
| --- | ---: |
| ingestion_runs | 4 |
| lmp_contents | 24 |
| lmp_state_transitions | 24 |
| load_contents | 288 |
| load_state_transitions | 288 |
| warehouse_control | 1 |

A simple raw LMP/run join dry run estimated 993 bytes. Metadata inspection found
272,948 raw bytes before this work. The separate power_market_analytics dataset
was created in US and remains **empty**. The verified raw dataset was not modified.

The initially evaluated free GA dbt 2.0.6 passed debug with ADC. The command

`python -m pytest dbt_integration_tests --run-dbt-bigquery -x -s`

then attempted one controlled integration test using that distribution. It created:

- pmd_dbt_it_raw_20260920_670abb9aea22
- pmd_dbt_it_analytics_20260920_670abb9aea22

The build's then-current graph contained 11 models, 37 data tests and 6 unit
tests. Result: **1 source data test passed, 9 query errors, 44 skipped nodes**.
The pytest integration result was **1 failed, 0 passed**. No analytical model
was materialized. Both disposable datasets were deleted, and a subsequent
dataset listing showed only power_market_raw and power_market_analytics.

Exact cause reported by BigQuery (excerpt):

```text
403: Custom quota exceeded: Your usage exceeded the custom quota for
QueryUsagePerDay, which is set by your administrator.
reason: quotaExceeded
```

Example failed job: adbc-71926d60-e58a-482c-8703-b61085608905, US.
The controlled attempt submitted 10 query jobs; reported totals were
**264 bytes processed and 10,485,760 bytes billed**. These are bytes, not an
invoice or a guarantee of zero cost. Daily quota remained 5120 MiB (5 GiB);
the existing $1 budget alert and Python 100 MiB query ceiling were unchanged.

Inspecting the evaluated v2 job also showed that its configured maximum_bytes_billed
was absent from the submitted job. This caused the documented switch to the stable
Python toolchain, whose cap propagation passes an offline adapter-path check.
The current integration harness uses the selected Python toolchain and stops on
the first failed build. It was not resubmitted after the quota block.
This evaluation must not be reported as a successful dbt Core build.

## Additional non-executing validation

BigQuery dry runs validated 18 rendered SELECT queries: all 11 models, all
5 singular tests and both incremental candidate branches. Estimated bytes ranged
from 280 to 193,713 per query over the existing raw data. They confirmed BigQuery
syntax and inferred types without executing queries or creating models.
They do not validate dbt's generated MERGE/DDL, run data tests or establish counts.

## Required after quota becomes available

No new human authentication is currently needed. Keep safeguards unchanged.

1. Run the current opt-in integration test with dbt Core. It must pass its initial
   build, Aâ†’A/Aâ†’B/Aâ†’Bâ†’A and late-arrival updates, full-refresh comparison, native
   unit/data tests, deliberate failed-contract assertion, repair and cleanup.
2. Build against the unchanged real raw dataset into power_market_analytics.
3. Verify actual facts/history counts, daily NP15 summary and ingestion health,
   and run the independent reconciliation tests. Expected source counts are not
   proof of resulting model counts.
4. Generate the live catalog/docs, record query/job metadata, review the PR and
   CI again, then mark Phase 3 complete and merge only if its definition is met.

Quota availability is the observed blocker to proceeding with cloud verification;
unexecuted checks may still reveal implementation issues. There is no claim that
simply waiting proves they will pass.
