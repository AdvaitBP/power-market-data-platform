# Phase 4 verification — recovery, live backfill and fresh retrieval

Status on 2026-09-21: **Phase 4 verified within the orchestration contract**.
The controlled cloud suite, saved real backfill, fresh real retrieval, dbt builds
and independent analytical reconciliation passed. The normal 5 GiB daily quota
was restored and independently verified before final Git review and merge.
No implementation changes were needed during live verification.

The record below preserves the earlier deferral and quota failure. The final
completion section records the later authorized 30 GiB allowance and its removal.

## Initial attempt, before temporary quota authorization

The following initial evidence records the earlier insufficient-headroom
deferral. The later completion attempt and its actual cloud usage are recorded
below; the initial zero-query result is not the total for this phase.

## Repository and toolchain

Work began from clean, synchronized main at
`7d3c6688bb67c411faf91c1839dd064a900f7f15`, in the actual checkout
`C:\Users\advai\dev\power-market-data-platform`, then created
`phase/04-flyte-orchestration`. No task-sandbox implementation was created.

Python is **3.12.14**. Stable **flyte 2.8.1**, published 2026-09-16, was installed
in `artifacts/flyte-venv`. Native Windows task execution, typed dataclass
boundaries and one task retry were observed with `TaskEnvironment`,
`@env.task`, `RetryStrategy` and `Backoff`. The first probe completed its
tasks but the CLI failed while printing Unicode through Windows cp1252.
Process-local `PYTHONUTF8=1` fixed the CLI exit; no machine-wide setting changed.

No Docker, WSL, Devbox, Kubernetes, remote backend, scheduler or continuously
running service was installed or required. dbt remains isolated at
dbt-core **1.12.5** and dbt-bigquery **1.12.1**. Application runtime dependencies,
source adapters, persistence implementation, identities, prior ADRs and dbt
SQL remain unchanged.

## Native local evidence

The actual backfill graph was executed with controlled external boundaries.
The fixture uses the existing `ingest()`, `batch_rows()` and `plan_write()`.
It is not a BigQuery emulator and does not establish native transaction or SQL
materialization correctness. Network sockets are blocked inside this graph.

Four native tests passed:

- CLI fixture graph for LMP, including a real two-second Flyte retry.
- Local SDK fixture graph for load, with the same dependency/recovery assertions.
- Invalid typed JSON plan rejected through the actual Flyte CLI.
- Invalid typed plan rejected through the local SDK, before credentials/I/O.

For each product the controlled scenario used 2026-08-02 through 2026-08-04,
with one synthetic normalized observation per date:

| Step | Observed result |
| --- | --- |
| Initial transient manifest-read failure | One Flyte retry; same derived run ID. |
| First date accepted | One content and one transition remain valid. |
| Second date interrupted after planned acceptance | COMMITTED fixture state, visible task failure; third date not started; dbt not called. |
| Resume with same backfill ID | First success reused, second reconciled, third ingested; dbt then verification. |
| Repeat same ID | All three successes reused; no source retrieval or new states. |
| New ID, unchanged input | New manifests; zero new contents/transitions. |
| Three separate one-day executions | Same three content identities and three logical transition tuples as resumed backfill. |
| Terminal failure on second date | No retry of FAILED, no third date, no dbt; same-ID rerun remains terminal. |
| Corrected new-ID attempt | Earlier content deduplicated; three final contents/transitions, same logical result. |

An opt-in integration test is implemented to check actual BigQuery writes,
acknowledgement loss, same-ID resume, new-ID repeat, native dbt builds and logical
fact equivalence using four owned disposable datasets. It had **not executed in
the initial attempt**. The ordinary collection correctly skips it; the later
opt-in result appears below.

## Cloud preflight and reason for deferral

At **2026-09-21 13:57:50 UTC**, existing ADC metadata access succeeded for
`advait-power-market-20260920`. The only datasets were
`power_market_raw` and `power_market_analytics`.

Raw metadata counts remained:

| Table | Rows |
| --- | ---: |
| ingestion_runs | 4 |
| warehouse_control | 1 |
| lmp_contents | 24 |
| lmp_state_transitions | 24 |
| load_contents | 288 |
| load_state_transitions | 288 |

Service Usage reported the unchanged daily **5,120 MiB / 5 GiB** custom quota.
The budget API response matched the prior **$1 monthly alert** configuration.
The selected dbt adapter passed its **104857600-byte / 100 MiB** cap regression.

The day's already observed parent query jobs, excluding script children:

| Metric | Value |
| --- | ---: |
| Query jobs | 330 |
| Bytes processed | 171,132,348 |
| Bytes billed | 4,655,677,440 |
| Nominal headroom below 5 GiB | 713,031,680 bytes / 680 MiB |

These jobs came from Phase 3 completion. They are not Phase 4 usage.
Job statistics provide a conservative planning estimate, not an exact remaining
quota meter or a dollar bill.

The intended real backfill is two completed dates (2026-08-02 and 2026-08-03),
NP15 LMP plus system load: four bounded requests, then dbt and verification,
followed by an unchanged retrieval/rerun. A normal 24-hour day would suggest
24 LMP and 288 load intervals, but no Phase 4 source rows were fetched or counted.

The previous Phase 3 controlled suite alone used 2,736,783,360 billed query bytes;
the two real builds and other checks added roughly another 1.9 billion bytes.
Two more full builds plus raw DML and a disposable recovery suite cannot
reasonably be budgeted inside the measured 680 MiB headroom. Therefore no
Phase 4 billable query was submitted to discover a predictable quota failure.
This is an **insufficient-headroom deferral**, not an observed new quota error.

Initial-attempt cloud query bytes processed/billed: **0 / 0**. No datasets, tables,
manifests, CAISO observations or analytical facts were created or modified by
this phase's verification. No billing safeguard was raised or removed.
No claim of a guaranteed zero-dollar bill is made. A second metadata check at
14:23:51 UTC confirmed the same counts, 330 jobs, unchanged quota/budget and
100 MiB caps on all observed query jobs.

## Initial validation commands and outcomes

Run from the actual checkout. Core commands:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -I -c "import power_market_data; print(power_market_data.__version__)"
.\.venv\Scripts\python.exe -m build
```

Passed: dependency consistency, lint, formatting, strict typing, **233 offline
tests** (including **42 orchestration tests**), installed-package import
(`0.1.0`), source distribution and wheel build. Archive inspection found the
optional tooling in the source distribution, a core-only wheel and no local
environments, credentials, profiles or generated artifacts.

Isolated dbt commands:

```powershell
.\artifacts\dbt-core-venv\Scripts\python.exe -m pip check
.\artifacts\dbt-core-venv\Scripts\python.exe dbt/tooling/check_cost_cap.py
$env:GCP_PROJECT_ID = "offline-project"
$env:GOOGLE_APPLICATION_CREDENTIALS = "deliberately-missing-credentials.json"
$env:DBT_SEND_ANONYMOUS_USAGE_STATS = "false"
.\artifacts\dbt-core-venv\Scripts\dbt.exe parse --project-dir dbt --profiles-dir dbt
```

Passed: dependency consistency, **one cap regression test**, credential-free
parse. No Phase 4 live dbt build or native dbt data/unit test run had occurred
at that stage.

Isolated Flyte commands:

```powershell
.\artifacts\flyte-venv\Scripts\python.exe -m pip check
.\artifacts\flyte-venv\Scripts\python.exe -c "import flyte; print(flyte.__version__)"
.\artifacts\flyte-venv\Scripts\python.exe -m mypy orchestration orchestration_checks orchestration_integration_tests
$env:PYTHONUTF8 = "1"
.\artifacts\flyte-venv\Scripts\python.exe -m pytest orchestration_checks orchestration_integration_tests
```

Passed: dependency consistency, version 2.8.1, strict typing of 12 files and
**four native tests**. **One cloud integration test skipped** because opt-in
was absent. Two upstream Flyte/Pydantic deprecation warnings were visible;
neither was suppressed or treated as successful cloud verification.

## Initial completion gates

1. Recheck ADC, quota headroom, budget and raw counts without changing safeguards.
2. Run the disposable native integration suite, inspect its facts/transitions
   and verify ownership-based cleanup.
3. Run the two-day real Flyte backfill through the local engine.
4. Inspect manifests/raw/facts, rerun with a new retrieval ID and establish no
   duplicate contents or fake transitions. Record real row/byte counts.
5. Verify dbt ordering/results and bounded analytical checks against BigQuery.
6. Update this record, README and Phase 4 status only after the mandatory cloud
   evidence exists, then obtain green final-head Windows/Linux CI before merge.

README retained the last completed Phase 3 status until that verification passed. Phase 4's definition of done is not weakened. There is no
remote always-on Flyte deployment, automated scheduler, final Data Quality
Observatory, as-of consumer analytics or capture-price analysis.

## Completion attempt with an explicitly authorized temporary quota

The existing branch and draft PR #5 were resumed at
`5e40df1c989e7b9c7219200a9479b8907ea7506c`, clean and synchronized with origin.
The complete published patch matched the previously reviewed patch. No new
phase branch was created and no earlier history was rewritten.

At **14:40:11 UTC**, metadata-only preflight confirmed the same six raw-table
counts, two real datasets, 330 earlier query jobs, 4,655,677,440 billed bytes,
unchanged budget configuration and 100 MiB Python/dbt query caps. The cap
regression passed before cloud execution.

The user explicitly authorized **only** the project-level `QueryUsagePerDay`
override to increase temporarily from **5,120 MiB to 12,288 MiB** (5 to 12 GiB)
for this verification. The existing Service Usage consumer override was updated
using its [documented PATCH API](https://docs.cloud.google.com/service-usage/docs/reference/rest/v1beta1/services.consumerQuotaMetrics.limits.consumerOverrides/patch).
The verification runner restored the original value in a `finally` block.

| Event on 2026-09-21 | UTC time | Verified project quota |
| --- | --- | ---: |
| Preflight | 14:40:11 | 5 GiB |
| Increase requested | 14:42:04 | — |
| Increase verified | 14:42:10 | 12 GiB |
| Restoration requested after live failure | 15:02:39 | — |
| Restoration verified | 15:02:42 | 5 GiB |
| Independent postflight | 15:03:30 | 5 GiB |

The user-level quota, $1 monthly budget alert, Python/dbt 100 MiB caps and all
other safeguards were unchanged. No reservations, remote Flyte resources,
VMs, Kubernetes or continuously running resources were created. A budget alert
is not a hard spending cap, and job statistics below are not an invoice.

## Controlled native cloud result

This exact opt-in command passed **1 test in 1156.34 seconds**:

```powershell
$env:GCP_PROJECT_ID = "advait-power-market-20260920"
$env:BQ_LOCATION = "US"
$env:PYTHONUTF8 = "1"
.\artifacts\flyte-venv\Scripts\python.exe -m pytest orchestration_integration_tests --run-flyte-bigquery -v
```

The actual Flyte local SDK executed the repository backfill tasks. Controlled source
records used one LMP and one load observation for each date from 2026-08-02
through 2026-08-04; no real CAISO value was altered.

- The reference case accepted six independently bounded requests, then ran dbt.
- The interrupted graph accepted August 2 LMP/load, then lost the acknowledgement
  after August 3 LMP was durably accepted and finalized. The task failed visibly.
  August 3 load had no manifest and no analytical fact table existed: later
  ingestion and dbt had not run.
- Resuming the same backfill ID reused **three** SUCCEEDED manifests and completed
  the remaining three requests. It did not generate replacement run IDs.
- Replaying the same ID reused all six successes without source retrieval.
- A fresh backfill ID over identical controlled input created six new successful
  attempt manifests, **zero contents and zero transitions**. Complete fact rows
  were unchanged. Both dbt fact MERGEs reported **0 rows affected**.
- The reference and resumed cases each ended with **3 LMP contents, 3 LMP
  transitions, 3 LMP facts; 3 load contents, 3 load transitions, 3 load facts**.
  Contents, logical transition tuples and all contracted fact fields agreed;
  only independent attempt IDs and retrieval/knowledge clocks were excluded.
  Commit sequences for corresponding original requests also agreed.

The three actual dbt builds each passed **56 nodes: 11 models, 38 data tests and
7 unit tests**, with `PASS=56 WARN=0 ERROR=0 SKIP=0` in dbt's node summary.
Native local checks were rerun separately: **4 passed**, including the actual Flyte two-second
transient retry with an unchanged run ID, terminal failure handling and typed
input rejection. The cloud interruption was a lost acknowledgement after
SUCCEEDED, while the offline fixture also exercised COMMITTED reconciliation.
These are distinct evidence cases, not claims that a live network fault occurred.

Owned disposable datasets were deleted and absence verified:

```text
pmd_flyte_it_daily_raw_20260921_08d3728cc4e3
pmd_flyte_it_daily_analytics_20260921_08d3728cc4e3
pmd_flyte_it_resume_raw_20260921_08d3728cc4e3
pmd_flyte_it_resume_analytics_20260921_08d3728cc4e3
```

Only `power_market_raw` and `power_market_analytics` remained. An auxiliary
metadata inspection raced with deletion of a dbt temporary test table and
returned NotFound; the integration test itself passed and completed cleanup.
Both native pytest runs reported two upstream Flyte/Pydantic deprecation
warnings; these were not suppressed.

## Real Flyte execution and exact recovery point

The actual native Windows CLI was launched at **15:01:27 UTC**, using Flyte
**2.8.1**, with this input (no Docker, WSL or remote backend):

```powershell
$env:PYTHONUTF8 = "1"
$env:GCP_PROJECT_ID = "advait-power-market-20260920"
$env:BQ_RAW_DATASET = "power_market_raw"
$env:BQ_ANALYTICS_DATASET = "power_market_analytics"
$env:BQ_LOCATION = "US"
$spec = '{"backfill_id":"3fdcca7e53a0440c8ea4fdd0403d452c","start_date":"2026-08-02","end_date":"2026-08-03","ingest_lmp":true,"ingest_load":true,"locations":["TH_NP15_GEN-APND"],"run_dbt":true,"concurrency":1}'
.\artifacts\flyte-venv\Scripts\flyte.exe run --local --raw-data-path artifacts/flyte/raw orchestration/flyte_pipeline.py backfill --spec $spec
```

Execution name: `7e3b4210-92c8-4311-a401-7a519153f168`.
The task graph was `backfill` → serial `ingest_day` → `build_analytics` →
`verify_analytics`; it stopped during the second `ingest_day`.

| Pacific date / product | Stable run ID | Final observed status | Accepted | New contents | New transitions |
| --- | --- | --- | ---: | ---: | ---: |
| 2026-08-02 / NP15 LMP | `13ad8ff858bb5a02aec95f0b0b6a3d7e` | SUCCEEDED | 24 | 24 | 24 |
| 2026-08-02 / load | `fff833cf2b8d51d9803b478cc0a4cc75` | STARTED | null | null | null |
| 2026-08-03 / NP15 LMP | `f14f6e10cd255044b3c4e7c06ccff00c` | No manifest; not started | — | — | — |
| 2026-08-03 / load | `46d71453438751d5ad7022e8d5495ef6` | No manifest; not started | — | — | — |

CAISO NP15 retrieval succeeded. The 24 accepted observations retained hourly UTC
boundaries, Pacific market date 2026-08-02, CAISO/DAY_AHEAD_HOURLY/NP15 dimensions
and USD/MWh units. Logical keys and content IDs were unique. Acceptance knowledge
time was **15:02:05.570 UTC** and the run finalized at **15:02:06.255 UTC**.
No full-day source-completeness claim follows from that row count.

At **15:02:38 UTC**, BigQuery returned `403 quotaExceeded` for `QueryUsagePerDay`
during the load attempt's post-begin manifest read. Its diagnostic read also hit
the quota. Flyte reported UNKNOWN at that moment, raised NonRecoverableError and
skipped its remaining retry. A later non-query table read established the durable
manifest was **STARTED**, not FAILED or COMMITTED. Load source access had not
begun. Its null counters must not be interpreted as a successful empty batch.

The guard has `active_run_id = null`; there is no unresolved COMMITTED writer.
**Resume the exact saved backfill ID when normal quota headroom is available.**
The first success will be reused, and the STARTED load attempt can continue
under the existing Phase 2 protocol. Do not create a replacement UUID for this
interrupted attempt or manually edit its manifest. A later fresh-retrieval
idempotency check should use a new backfill UUID only after this attempt completes.

No live dbt build, analytical verification task or exact live rerun occurred.
Their success and rows affected are **not established** by the controlled suite.
The real daily-summary view was not re-queried after the quota stop.

## Warehouse state and usage after the 12 GiB attempt

Non-query table reads verified every original raw content/transition and every
original fact row remained unchanged. New LMP rows are preserved raw data, not
newly verified analytical facts. The real facts still reflect the previous build;
global latest-transition/fact reconciliation is pending the deferred dbt run.

| Table | Final rows |
| --- | ---: |
| ingestion_runs | 6: 4 SUCCEEDED, 1 prior FAILED, 1 STARTED |
| warehouse_control | 1; no active run |
| lmp_contents / lmp_state_transitions | 48 / 48 |
| load_contents / load_state_transitions | 288 / 288 |
| fct_hourly_lmp | 24, unchanged |
| fct_system_load_5min | 288, unchanged |

Usage was collected from parent QueryJob metadata since **14:41:57 UTC**,
excluding script children to avoid double counting:

| Scope | Query jobs | Failed jobs | Bytes processed | Bytes billed |
| --- | ---: | ---: | ---: | ---: |
| Controlled suite | 431 | 0 | 398,801 | 7,885,291,520 |
| Partial real execution | 15 | 2 quota failures | 69,529 | 346,030,080 |
| Phase 4 completion attempt total | 446 | 2 | 468,330 | 8,231,321,600 |

Every observed query job carried `maximum_bytes_billed = 104857600`.
The full day's 776 parent jobs, including earlier Phase 3 work, reported
12,886,999,040 billed bytes. Job totals are usage statistics, not an exact quota
meter or a posted monetary charge. Minimum billed query/table units explain why
billed bytes greatly exceed processed bytes for these tiny tests. No dollar
charge was inferred or claimed.

Real raw logical storage increased from **272,948 to 295,663 bytes**:
**22,715 bytes added**. Real analytics logical storage remained **190,392 bytes**
(**0 added**). Disposable live datasets were removed; these logical storage
numbers do not measure retained time-travel/fail-safe physical storage or a bill.

Independent postflight matched the original Service Usage quota response and
budget response. The dbt adapter-cap test and Python 104857600-byte assertion
passed again after restoration. No further billable queries were attempted.

## Validation and remaining gates after the 12 GiB attempt

The previously listed core commands were rerun successfully: pip check, Ruff
lint/format, mypy, **233 offline pytest tests** (42 orchestration), isolated import
and package build. Isolated Flyte pip check, version, mypy over 12 files and
**4 native tests** passed. dbt pip check, **1 cap regression** and credential-free
parse passed. The separate cloud suite is now **1 passed**. No failing assertion
was weakened, and no implementation fix was needed.

The remaining mandatory gates at that point were:

1. With sufficient normal daily headroom, resume the saved two-day real workflow
   through ingestion, dbt and analytical verification.
2. Run its unchanged fresh-retrieval check and inspect contents, transitions,
   manifests, full facts, dbt MERGE results and relevant daily summaries.
3. Record that evidence, update completed status only then, and obtain green
   final-head Windows/Linux CI before marking ready and merging PR #5.

The already passed controlled suite need not be repeated merely because the real
run resumes on another day; rerun it if code changes or new evidence warrants it.
No authentication or OS action was needed. The blocker was query quota,
not missing credentials. At that point Phase 4 remained incomplete; the later
completion below closed these gates without starting Phase 5.

## Final completion with the authorized 30 GiB allowance

The clean, synchronized existing branch and draft PR #5 resumed at
`1d58326b0b9d54e7d7815e19ef4089f0266ecb20`. The already passed controlled cloud
suite was **not rerun**: there was no relevant implementation change. Its native
interruption/resumption and equivalence evidence remains valid above.

At 15:23:34 UTC on 2026-09-21, preflight confirmed the project quota was 5 GiB,
the $1 monthly alert and 100 MiB caps were unchanged, the warehouse guard had no
active run, and no manifest was COMMITTED. The saved SUCCEEDED/STARTED/absent
unit states matched the preceding record. Earlier same-day usage was
12,886,999,040 billed bytes across 776 parent query jobs.

Only the project-level daily override changed, under explicit user authorization:

| Event (2026-09-21 UTC) | Time | Effective quota |
| --- | --- | ---: |
| Temporary increase requested | 15:26:37 | — |
| Increase verified | 15:26:43 | 30 GiB / 30,720 MiB |
| Restore requested after both workflows and inspections | 15:36:56 | — |
| Restoration verified | 15:37:00 | 5 GiB / 5,120 MiB |
| Independent quota/budget postflight | 15:38:19 | 5 GiB / 5,120 MiB |

Restoration ran in `finally`. User-level quotas, IAM, billing-account configuration,
pricing model, budget and Python/dbt caps were not changed. After restoration,
the budget API response matched the original $1 monthly alert configuration,
the Python cap assertion and dbt adapter-cap regression passed, and every new
query job reported `maximum_bytes_billed = 104857600`.

Read-only US inventories returned no BigQuery reservations, capacity commitments
or scheduled transfer configurations. Query metadata recorded no reservation
usage. Compute Engine, Kubernetes Engine and Cloud Run APIs remained disabled;
they were not enabled merely to list resources. No VM, cluster, remote Flyte
backend or continuously running resource was created. Only the two real datasets
remain; no disposable dataset was needed for this completion.

### Actual Flyte commands and ordering

Both commands used native Windows local execution with Flyte **2.8.1**, Python
**3.12.14** and the unchanged `TaskEnvironment` graph. No Docker or WSL was used.
The process environment selected the dedicated project, raw/analytics datasets
and US location as in the earlier invocation. `PYTHONUTF8=1` remained local to
those processes; the code revision environment recorded the current head.

The saved plan was reused exactly, then only its UUID changed for fresh retrieval:

```powershell
$spec = '{"backfill_id":"3fdcca7e53a0440c8ea4fdd0403d452c","start_date":"2026-08-02","end_date":"2026-08-03","ingest_lmp":true,"ingest_load":true,"locations":["TH_NP15_GEN-APND"],"run_dbt":true,"concurrency":1}'
.\artifacts\flyte-venv\Scripts\flyte.exe run --local --raw-data-path artifacts/flyte/raw orchestration/flyte_pipeline.py backfill --spec $spec

$spec = '{"backfill_id":"09b48fd791f94b66bcfd32d7269bfbbd","start_date":"2026-08-02","end_date":"2026-08-03","ingest_lmp":true,"ingest_load":true,"locations":["TH_NP15_GEN-APND"],"run_dbt":true,"concurrency":1}'
.\artifacts\flyte-venv\Scripts\flyte.exe run --local --raw-data-path artifacts/flyte/raw orchestration/flyte_pipeline.py backfill --spec $spec
```

The saved execution ran from **15:26:43 to 15:31:01 UTC**. The fresh execution ran
from **15:31:12 to 15:36:44 UTC**. Each graph executed `backfill`, four serial
`ingest_day` tasks, `build_analytics`, then `verify_analytics`.
The wrappers called existing ingestion/persistence, the verified dbt subprocess
and bounded fact checks. No source or warehouse rules were moved into Flyte.
Both dbt execution-start timestamps were after all four required manifest
completion timestamps; no ingestion overlapped its workflow's dbt graph.

### Saved manifests after successful resumption

All four manifests are SUCCEEDED. Counters below describe the durable attempt,
including the original August 2 LMP acceptance, rather than only this process.
LMP location is `TH_NP15_GEN-APND`; load is CAISO system load.

| Date / product | Run ID | Fetched | Accepted | New contents | New transitions | Knowledge time (2026-09-21 UTC) |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 2026-08-02 / lmp | `13ad8ff858bb5a02aec95f0b0b6a3d7e` | 24 | 24 | 24 | 24 | 15:02:05.570000 |
| 2026-08-02 / load | `fff833cf2b8d51d9803b478cc0a4cc75` | 288 | 288 | 288 | 288 | 15:27:13.037000 |
| 2026-08-03 / lmp | `f14f6e10cd255044b3c4e7c06ccff00c` | 24 | 24 | 24 | 24 | 15:27:58.171000 |
| 2026-08-03 / load | `46d71453438751d5ad7022e8d5495ef6` | 288 | 288 | 288 | 288 | 15:28:39.061000 |

The first LMP manifest was preserved field-for-field and its task reported
`reused_success=True`, zero new contents/transitions for this invocation and no
source refetch. The previously STARTED load manifest kept its run ID and original
start time and completed normally. The resume therefore made **three** source
requests, adding **600 contents and 600 transitions**. No terminal failure was
revived and no knowledge time was backdated to the market interval.

### Real fresh-retrieval result

The fresh UUID produced four new successful manifests and **four new CAISO
requests**, not a reuse-only check. Each accepted the actual returned rows:

| Date / product | New run ID | Fetched / accepted | New contents | New transitions |
| --- | --- | ---: | ---: | ---: |
| 2026-08-02 / lmp | `29dfb40badd650bcbc80d4e1ad79a803` | 24 / 24 | 0 | 0 |
| 2026-08-02 / load | `069432216d735f71be659d9fc4480839` | 288 / 288 | 0 | 0 |
| 2026-08-03 / lmp | `d4b832a812025f0a882242802823b413` | 24 / 24 | 0 | 0 |
| 2026-08-03 / load | `d982cce68c6b55598d000c62c4af8630` | 288 / 288 | 0 | 0 |

No normalized CAISO source revision was observed. Full contents and transition
rows, including first-known times, were unchanged from successful resumption.
Complete LMP/load fact rows and daily-price summaries also matched field-for-field.
The extra manifests represent real retrieval attempts, not duplicated observations.

### dbt and independent reconciliation

Both real builds passed **56 nodes: 11 models, 38 data tests and 7 unit tests**.
dbt-core **1.12.5** and dbt-bigquery **1.12.1** were unchanged. The resumed build's
MERGEs affected **48 LMP and 576 load rows**, including the earlier accepted LMP
that had not reached facts. The fresh build's MERGEs affected **0 and 0 rows**.
Both bounded verification tasks passed with 24 LMP and 288 load facts for each
requested date. Their queries reported 103,098 / 103,458 processed bytes and
41,943,040 billed bytes each; these are included in the total below.

Independent checks compared actual raw/fact table rows and bounded SQL history
results. Fact keys equaled latest eligible SUCCEEDED transition keys; every
current content ID was preserved raw content; history contained all and only
eligible transitions. Keys were unique, units remained USD/MWh and MW, intervals
were aware UTC with one-hour/five-minute durations, and Pacific market dates
matched their starts. Every earlier accepted content/transition remained intact.
The guard ended with no active writer; no STARTED or COMMITTED run remained.

| Final relation | Rows / grain |
| --- | --- |
| ingestion_runs | 12 attempts: 11 SUCCEEDED, 1 historical FAILED |
| warehouse_control | 1 dataset sequencing row |
| lmp_contents / lmp_state_transitions | 72 unique contents / 72 occurrences |
| load_contents / load_state_transitions | 864 unique contents / 864 occurrences |
| int_lmp_revision_history / int_load_revision_history | 72 / 864 eligible occurrences |
| fct_hourly_lmp / fct_system_load_5min | 72 / 864 current logical observations |

### Actual daily NP15 summary

All rows below are CAISO, DAY_AHEAD_HOURLY, TH_NP15_GEN-APND. Dates are Pacific;
prices are USD/MWh. These are queried mart results, with no causal interpretation
or claim that returned intervals establish upstream completeness.

| Market date | Observations | Expected hours | Average | Minimum | Maximum | Negative intervals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-08-01 | 24 | 24 | 40.610213333 | 27.19765 | 65.15886 | 0 |
| 2026-08-02 | 24 | 24 | 42.808755 | 25.83308 | 85.1957 | 0 |
| 2026-08-03 | 24 | 24 | 50.723734583 | 31.26647 | 110.73877 | 0 |

### Actual final ingestion health

All rows are CAISO; LMP uses NP15 and load has no requested hub. All started and
unfinalized counts are zero. Accepted-row sums count successful attempts and
therefore deliberately exceed unique source counts on repeated retrievals.

| Date / product | Runs | Succeeded | Failed | Successful rows accepted | New contents / transitions | Latest successful knowledge (UTC) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-08-01 / lmp | 3 | 2 | 1 | 48 | 24 / 24 | 2026-09-20 18:40:33.065000+00:00 |
| 2026-08-01 / load | 1 | 1 | 0 | 288 | 288 / 288 | 2026-09-20 18:41:13.501000+00:00 |
| 2026-08-02 / lmp | 2 | 2 | 0 | 48 | 24 / 24 | 2026-09-21 15:31:46.093000+00:00 |
| 2026-08-02 / load | 2 | 2 | 0 | 576 | 288 / 288 | 2026-09-21 15:32:46.064000+00:00 |
| 2026-08-03 / lmp | 2 | 2 | 0 | 48 | 24 / 24 | 2026-09-21 15:33:31.209000+00:00 |
| 2026-08-03 / load | 2 | 2 | 0 | 576 | 288 / 288 | 2026-09-21 15:34:20.203000+00:00 |

### New completion usage and validation

Only the later 30 GiB completion window is counted here; the earlier controlled
suite and Phase 3 usage are excluded. Parent QueryJobs exclude script children.
No billable queries ran after safeguard restoration.

| Metric | New completion window |
| --- | ---: |
| Query jobs | 229 |
| Failed query jobs | 0 |
| Bytes processed | 13,732,714 |
| Bytes billed | 4,110,417,920 |

Cumulative same-day usage was **1,005 query jobs**,
**185,333,392 processed bytes** and **16,997,416,960 billed bytes**.
These are usage statistics, not an invoice or an inferred dollar charge.

| Logical storage | Before completion | After completion | Added bytes |
| --- | ---: | ---: | ---: |
| power_market_raw | 295,663 | 818,484 | 522,821 |
| power_market_analytics | 190,392 | 571,176 | 380,784 |

Logical table bytes do not describe time-travel/fail-safe physical storage or a
posted charge. No cost guarantee is inferred from these small amounts.

All normal credential-free checks passed again: core pip check, Ruff lint and
format, mypy, **233 offline tests** (including 42 orchestration), isolated import
and source/wheel build; Flyte pip check/version, mypy and **4 native local tests**;
dbt pip check, parse and the **one-test cap regression**. The two upstream
Flyte/Pydantic deprecation warnings remained visible. The **one previously passed
controlled cloud test was retained, not rerun**. No test assertions were weakened.

No implementation fix was required. The complete PR diff was reviewed for retry
classification, stable run IDs, delegation to existing domain/storage code,
ingestion/dbt ordering, secret/artifact exclusion and accurate claims. Normal
configuration retains 5 GiB/day and 100 MiB/query; temporary allowances are
documented as historical verification exceptions, not operational defaults. Final CI/review/merge evidence is
recorded on [PR #5](https://github.com/AdvaitBP/power-market-data-platform/pull/5).

There is no remote Flyte cluster, automated scheduler, final Data Quality
Observatory, as-of consumer analytics, battery optimization, forecasting or
capture-price analysis. Phase 5 was not started.
