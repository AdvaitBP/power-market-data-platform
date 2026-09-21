# Phase 3 verification — 2026-09-20 and 2026-09-21

**Current status: Phase 3 complete within its documented scope.** The 2026-09-21
controlled suite, real builds, reconciliation, no-op rebuild and live catalog all
passed. The prior unsuccessful attempt is preserved below. No safeguard was
raised or removed.

Status on 2026-09-20: **Incomplete; do not merge.** The controlled BigQuery build was blocked
by the existing custom daily query quota. The formal Phase 3 definition of done
has not been met. No quota or budget setting was increased or removed.

## Toolchain and offline checks on 2026-09-20

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

## Live preflight and controlled attempt on 2026-09-20

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

## Additional non-executing validation on 2026-09-20

BigQuery dry runs validated 18 rendered SELECT queries: all 11 models, all
5 singular tests and both incremental candidate branches. Estimated bytes ranged
from 280 to 193,713 per query over the existing raw data. They confirmed BigQuery
syntax and inferred types without executing queries or creating models.
They do not validate dbt's generated MERGE/DDL, run data tests or establish counts.

## Follow-up required after the 2026-09-20 attempt

No new human authentication is currently needed. Keep safeguards unchanged.

1. Run the current opt-in integration test with dbt Core. It must pass its initial
   build, A→A/A→B/A→B→A and late-arrival updates, full-refresh comparison, native
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

## Completion verification on 2026-09-21

The existing phase/03-dbt-warehouse branch and draft PR #4 were resumed from
bd387bb687ded91763b6dfa388c2b6c70f8d2ced, without rewriting history. The initial
working tree was clean and synchronized. Phase 1/2 observation identities,
serialization, schemas and timestamp contracts are unchanged. The only runtime
edit changes the raw dataset description to neutral technical wording; the
existing dataset description was updated without modifying its tables or records.

The selected toolchain remains Python 3.12.14, dbt-core 1.12.5 and dbt-bigquery
1.12.1. Before submitting live work, the adapter cost-cap regression passed.
ADC worked; both real datasets existed in US; metadata counts still matched the
six raw-table values above. An uncached, one-column raw LMP probe succeeded with
maximumBytesBilled=104857600, 1,584 bytes processed and 10,485,760 bytes billed.
The daily quota was still 5120 MiB and the monthly budget alert still USD 1.

### Controlled native verification

Command: `.\.venv\Scripts\python.exe -m pytest dbt_integration_tests --run-dbt-bigquery -x -s`.
Result: **1 integration test passed in 536.49 seconds**, covering both products.
The initial and full-refresh builds each passed **11 models, 38 data tests and
7 native unit tests**. Four intervening incremental runs each built both facts.
All five independent singular/reconciliation tests passed in the builds.

Owned disposable datasets:

- pmd_dbt_it_raw_20260921_d3a9872fbb36
- pmd_dbt_it_analytics_20260921_d3a9872fbb36

Both were deleted in fixture cleanup; a fresh dataset listing confirmed only
power_market_raw and power_market_analytics remained. The real raw dataset never
received these synthetic rows.

For each product, accepted content/transition counts after the five stages were:

| Stage | Unique accepted contents | Accepted transitions | Current logical rows |
| --- | ---: | ---: | ---: |
| Initial A | 1 | 1 | 1 |
| Unchanged A | 1 | 1 | 1 |
| B | 2 | 2 | 1 |
| A reappears | 2 | 3 | 1 |
| Late historical interval | 3 | 4 | 2 |

The harness now records actual history rows, current facts, clocks, native node
results and the complete incremental/full-refresh snapshots under ignored
artifacts/. Direct inspection of the LMP history for one logical key showed:

| Ordinal | Content/value | Commit sequence | Content first seen (UTC) | Transition known (UTC) |
| --- | --- | ---: | --- | --- |
| 1 | A / 10 USD/MWh | 1 | 2026-09-01 00:01 | 2026-09-01 00:01 |
| 2 | B / 20 USD/MWh | 21 | 2026-09-01 00:21 | 2026-09-01 00:21 |
| 3 | A / 10 USD/MWh | 31 | 2026-09-01 00:01 | 2026-09-01 00:31 |

Occurrences 1 and 3 reference the same content ID
0cf68bb04435dfa4e25cd2f9fd45c91cc9ae3c3a98873778e60c6ef882806f21.
The final fact has exactly one row for this logical key and references occurrence
3. The unchanged retrieval created no occurrence. Load produced the same
10/20/10 sequence in MW, with commit sequences 2/22/32 and knowledge times
00:02/00:22/00:32 UTC; its original A first_seen_at remained 00:02 UTC.

The late interval starts at 2025-08-01 07:00 UTC. It entered the incremental
LMP fact at sequence 41 with knowledge time 2026-09-01 00:41 UTC, and load at
sequence 42 / 00:42 UTC. No event-time watermark excluded the old interval.

Adversarial STARTED, FAILED and COMMITTED manifests/content/transition rows were
present only in disposable fixtures. Histories and facts admitted SUCCEEDED
rows exclusively. Native eligibility unit tests also proved these exclusions.
The integration test compared every field of both final facts before and after
full refresh: **equal**, not merely equal row counts. Native DST checks returned
23 and 25 hours for the Pacific spring-forward and fall-back dates.

The deliberate duplicate LMP fact produced `FAIL 1` in
unique_fct_hourly_lmp_logical_key. Rebuilding both facts with full refresh repaired
it, and the same native test then passed. This was an intentional data-contract
failure, not a BigQuery job failure. Controlled docs/catalog generation succeeded.

### Real warehouse inspection

Using the existing ADC profile, `dbt parse --no-partial-parse`, `dbt debug` and
`dbt build` succeeded against power_market_raw into power_market_analytics.
The build passed all 56 nodes: 11 models, 38 data tests and 7 native unit tests.
SQL inspection plus complete small-table API reads independently checked every
model's grain, current-state eligibility, content relationship and revision set.

| Model | Actual rows | Unique grain |
| --- | ---: | --- |
| stg_ingestion_runs | 4 | run_id |
| stg_lmp_contents | 24 | content_id |
| stg_load_contents | 288 | content_id |
| stg_lmp_state_transitions | 24 | transition_id |
| stg_load_state_transitions | 288 | transition_id |
| int_lmp_revision_history | 24 | transition_id |
| int_load_revision_history | 288 | transition_id |
| fct_hourly_lmp | 24 | logical_key |
| fct_system_load_5min | 288 | logical_key |
| mart_daily_lmp_summary | 1 | source, market, location, market_date |
| mart_ingestion_health | 2 | source, product, requested_date, requested_location |

Each row count equaled its distinct-grain count. LMP has 24 distinct logical
keys; load has 288. Current keys equal the latest eligible raw transition keys;
all current content IDs resolve to preserved raw contents; histories contain all
and only successful transitions. Every selected raw content field matched its
fact field. Both originating runs are SUCCEEDED. No failed or unfinalized state
was present.

LMP source/market/location/unit were CAISO, DAY_AHEAD_HOURLY,
TH_NP15_GEN-APND and USD/MWh. Its intervals are aligned, half-open UTC hours.
Load is CAISO system demand in MW, with aligned five-minute UTC intervals.
Both preserve the Pacific market date and timezone-aware UTC boundaries.
All six raw tables were compared field-for-field with the pre-build snapshot;
records were unchanged. The canonical snapshot SHA-256 was
4413f7234f83ec22117ea992079fa9347842e3495bbf60a5949aadb4dc045e16.

Actual daily mart output (no causal interpretation):

| Field | Value |
| --- | --- |
| source | CAISO |
| market | DAY_AHEAD_HOURLY |
| location | TH_NP15_GEN-APND |
| market_date | 2026-08-01 |
| observation_count | 24 |
| average_lmp_usd_per_mwh | 40.610213333 |
| minimum_lmp_usd_per_mwh | 27.19765 |
| maximum_lmp_usd_per_mwh | 65.15886 |
| negative_price_interval_count | 0 |
| expected_hour_count | 24 |

Actual ingestion health: both groups are CAISO, requested date 2026-08-01.
LMP location is TH_NP15_GEN-APND; load location is NULL.

| Product | Runs | Succeeded | Failed | Started | Unfinalized | Accepted rows | New contents | New transitions | Latest successful knowledge (UTC) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| lmp | 3 | 2 | 1 | 0 | 0 | 48 | 24 | 24 | 2026-09-20 18:40:33.065000+00:00 |
| load | 1 | 1 | 0 | 0 | 0 | 288 | 288 | 288 | 2026-09-20 18:41:13.501000+00:00 |

The 48 accepted LMP rows include the unchanged 24-row retrieval; only 24 unique
contents/transitions exist. Failures remain visible in operational health and
do not supply analytical state.

### Unchanged second build and live catalog

A second `dbt build --project-dir dbt --profiles-dir dbt --fail-fast` passed all
56 nodes again. Both incremental models reported MERGE with **0 rows affected**.
A second inspection found all eleven model outputs field-for-field identical
(after sorting by row content), not just unchanged counts. The 24/288 facts
remained unique, current content and transition IDs were unchanged, and the raw
snapshot still matched. This run added no false revision.

`dbt docs generate --project-dir dbt --profiles-dir dbt` succeeded. The generated
catalog has **11 real analytical relations and 5 raw sources**, populated column
metadata and no catalog errors. The two facts are tables and the other nine
models are views. Manifest, catalog, index and logs remain ignored locally under
dbt/target and dbt/logs; generated documentation is not committed.

Two tool warnings were reviewed rather than hidden. dbt reports unspecified
NUMERIC precision/scale in the fact contracts. These fields deliberately retain
the same unparameterized BigQuery NUMERIC type as raw storage (precision 38,
scale 9), which Phase 2 already checks for exact representability. Fact values
matched preserved raw values exactly. See the
[BigQuery decimal type definition](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/data-types#decimal_types).
The catalog's agate conversion warns that table_owner is absent; relation and
column entries were inspected and present. Neither warning was a failed data
contract, job, build or catalog error.

### Completion-run usage and unchanged safeguards

These metadata totals cover jobs created since 2026-09-21 13:06:49.786034 UTC
through the completed live catalog, including the quota probe, disposable suite,
two real builds and inspections. Parent query statistics exclude script children
to avoid double counting. Totals use jobs visible to the authenticated user
within this interval.

| Scope | Query jobs | Bytes processed | Bytes billed | Failed BigQuery query jobs |
| --- | ---: | ---: | ---: | ---: |
| Controlled disposable suite | 188 | 84,075,132 | 2,736,783,360 | 0 |
| Entire completion run | 330 | 171,132,348 | 4,655,677,440 | 0 |

There were 355 total jobs including the 25 tiny fixture batch loads. The expected
dbt uniqueness failure returned a failing test result from successful SQL; it
is not a failed BigQuery job. Reported bytes are usage statistics, not a computed
dollar charge or guarantee of zero cost.

Analytics logical storage reported by table metadata: **190,392 bytes**:
15,864 for fct_hourly_lmp and 174,528 for fct_system_load_5min. Views have no stored
rows of their own. Both facts remain unpartitioned and unclustered; no speedup
claim is made for this small dataset.

Post-verification checks confirmed:

- the daily custom query quota is still **5120 MiB (5 GiB)**;
- the unchanged project-scoped **USD 1 monthly budget alert** retains its
  1%, 50% and 100% current-spend thresholds and includes credits;
- every one of the 330 submitted query jobs carried **104857600** as its
  maximumBytesBilled cap;
- only power_market_raw and power_market_analytics remain; no disposable
  datasets, reservations or continuously running resources were left behind.

No quota, budget, per-job cap, IAM setting or authentication mechanism was changed.

### Final local validation and scope

All application commands in the first command block were rerun successfully:
`pip check`, Ruff lint, Ruff format check (49 files), strict mypy (31 source
files), **191 offline pytest tests**, isolated import (0.1.0), source distribution
and wheel build. Archive inspection confirmed no local profiles, credentials,
virtual environments or generated dbt outputs entered either package.
The dbt environment's `pip check`, version check and single offline adapter
cost-cap unittest passed. The live parse/debug/build/docs commands and opt-in
integration command above passed with the selected toolchain. SQL models needed
no changes after native execution; integration assertions/reporting were expanded
to retain inspectable row evidence and verify cleanup.

The integration report, complete fact snapshots, dbt run results, usage report
and command logs remain under ignored artifacts/. Public evidence is summarized
here without committing downloaded market records or generated catalogs.

There is no Flyte, automated multi-date backfill, final Data Quality Observatory,
as-of consumer query or renewable capture-price analysis. Current-state
incremental correctness depends on the Phase 2 ordered finalization protocol,
append-only successful raw history and one dbt writer per target. A dbt graph is
not one atomic warehouse snapshot; ingestion must be quiescent for a stable
reconciliation run. No Phase 4 work was started.
