# Phase 2 verification — 2026-09-20

This records observed results, not a service-level or zero-cost guarantee.
Python 3.12.14, gridstatus 0.36.0 and google-cloud-bigquery 3.45.2 were used.
Phase 1 source, grain, hash and time contracts were not changed.

## Resources and authentication

The dedicated project is `advait-power-market-20260920`. User Application
Default Credentials were used; credentials remain outside the repository.
Billing was linked by the account owner because the billing-free sandbox
cannot run the required DML. The official Windows Google Cloud CLI 585.0.0
was installed locally under ignored artifacts; no global PATH or PowerShell
execution-policy change was needed. BigQuery was enabled; the Billing Budgets
API was enabled for the requested alert. No compute resources were created.

Only `power_market_raw` remains, in US. Final table metadata:

| Table | Rows | Logical storage bytes |
| --- | ---: | ---: |
| ingestion_runs | 4 | 2,030 |
| warehouse_control | 1 | 30 |
| lmp_contents | 24 | 12,696 |
| lmp_state_transitions | 24 | 9,360 |
| load_contents | 288 | 136,512 |
| load_state_transitions | 288 | 112,320 |

All six tables have no partitioning, clustering or expiration. Total reported
logical storage was 272,948 bytes. There is no analytics dataset.

## Real CAISO workflow

Bootstrap succeeded and repeated bootstrap was tested without replacing data.
These commands used the existing Phase 1 adapters:

```powershell
$env:GCP_PROJECT_ID = "advait-power-market-20260920"
.\.venv\Scripts\power-market-data.exe warehouse bootstrap
.\.venv\Scripts\power-market-data.exe ingest caiso lmp --date 2026-08-01 --location TH_NP15_GEN-APND
.\.venv\Scripts\power-market-data.exe warehouse inspect lmp --date 2026-08-01 --location TH_NP15_GEN-APND
# Repeat the same ingest and inspect commands with a new attempt ID.
.\.venv\Scripts\power-market-data.exe ingest caiso load --date 2026-08-01
.\.venv\Scripts\power-market-data.exe warehouse inspect load --date 2026-08-01
```

| Attempt | Accepted rows | New contents | New transitions | Result |
| --- | ---: | ---: | ---: | --- |
| First NP15 day | 24 | 24 | 24 | SUCCEEDED |
| NP15 rerun during quota exhaustion | 0 | 0 | 0 | FAILED, transaction rolled back |
| NP15 rerun after recovery | 24 | 0 | 0 | SUCCEEDED |
| First load day | 288 | 288 | 288 | SUCCEEDED |

The failed attempt's inserted counts are NULL in its manifest; zeros above
describe the verified absence of committed additions. Its commit_completed is
false and the failed job ID remains available for authenticated diagnostics.
The four manifests contain three successes and one failure.

All 24 original LMP contents retained first_seen_at
2026-09-20T18:31:21.334Z after the rerun. Load first_seen_at was
2026-09-20T18:41:13.501Z. Both products covered interval start
2026-08-01T07:00:00Z through final interval end 2026-08-02T07:00:00Z.
Persisted units were USD/MWh and MW. Logical keys and content hashes were
64-character SHA-256 hex strings. No real CAISO values were modified to
simulate revisions.

## Disposable integration tests

```powershell
.\.venv\Scripts\python.exe -m pytest integration_tests --run-bigquery -v
```

**7 passed in 569.62 seconds.** These verified idempotent bootstrap, A→A,
A→B→A for both products, historical event time with current knowledge time,
forced transaction rollback, post-commit finalization recovery, stale competing
plans, and successful-empty versus failed runs.

After fixing recovery of a failure-recording job interrupted by quota exhaustion:

```powershell
.\.venv\Scripts\python.exe -m pytest integration_tests --run-bigquery -v -k transaction_rolls_back_every_observation
```

**1 passed, 6 deselected in 89.39 seconds.** This revalidated rollback,
retention of the failed commit job ID, and a subsequent successful attempt.
There are seven distinct integration tests, not eight. The actual quota-blocked
NP15 manifest was also successfully reconciled before the new live attempt.

Both successful test datasets were deleted:
`pmd_it_20260920_0360460a2777` and `pmd_it_20260920_c7d9f49ba662`.
Earlier disposable development datasets were deleted too. A final API inventory
confirmed that only power_market_raw remained.

## Cost controls and observed usage

- Python query jobs use maximum_bytes_billed=104857600 (100 MiB).
- The project daily query quota is **5,120 MiB (5 GiB)**, verified after testing.
  It was temporarily raised to 8,192 MiB to finish the bounded verification and
  then restored. The lower quota can block further queries until usage resets.
- A project-scoped **USD 1 monthly budget alert** has current-spend thresholds
  of 1%, 50% and 100%, using default billing-admin/user notifications.
  It includes credits and is an alert, not a hard spending cap.
- No reservations, streaming writes, unattended jobs or public-dataset scans
  were created.

The initial 5 GiB quota blocked a rerun after development and integration jobs.
BigQuery applies minimum billed sizes per statement, so tiny tables do not imply
zero billed query units. That interruption exposed and led to a tested recovery
fix: guarded failure-status updates can be resubmitted with fresh job IDs.

| Scope | Jobs counted | Bytes processed | Billed query bytes |
| --- | ---: | ---: | ---: |
| Seven-test suite, successfully awaited jobs | 156 | 318,274 | 4,257,218,560 |
| Focused regression, successfully awaited jobs | 22 | 6,832 | 450,887,680 |
| All project parent query jobs observed that day, including development/failures | 253 | 797,417 | 6,595,543,040 |

The last line excludes child jobs to avoid double-counting scripts and includes
seven failed parent jobs, some intentionally induced. These are server-reported
job statistics, **not an invoice or proof of a dollar charge**. The approximately
6.14 GiB query total and small storage footprint are expected to fit normal free
allowances if other account usage has not consumed them. No dollar charge was
verified. Quotas are approximate and budget alerts do not guarantee zero cost.

## Offline validation

From the actual checkout, with its local environment:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -I -c "import power_market_data; import power_market_data.warehouse.bigquery; print(power_market_data.__version__)"
.\.venv\Scripts\python.exe -m build
```

The offline suite has **172 tests**, including existing Phase 1 tests, production
transition-planner tests, native-client call/failure contracts and CLI tests.
Ordinary tests make no source/cloud requests. Without --run-bigquery, all seven
integration tests skip. CI also installs the built wheel and reruns offline tests.

## Limits

Concurrency verification covers stale competing snapshots and replay contracts;
it is not a multi-writer stress benchmark. Cooperating writers share the native
control-row protocol. Administrators can bypass it; BigQuery does not enforce
the logical unique keys. Knowledge time is the documented conservative successful
job-completion bound, not an exact internal commit clock.

No dbt, Flyte, analytical marts, as-of consumer query, capture-price analysis,
additional source products, source-deletion support or raw-file archive was added.
