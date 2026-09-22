# Phase 5 verification: battery benchmark

Status on 2026-09-22 UTC: **Phase 5 verification complete within its stated scope**.
Local checks, native/live verification and Windows/Linux CI pass. The initial quota-blocked
attempt is preserved below; ordinary quota reset later permitted completion
without changing the 5 GiB allowance. Real three-day results appear in the later
completion section; synthetic results remain explicitly separate.

## Roadmap and environment

Started from clean synchronized main at `e797eba9e48d91d7142bbfb8caf84d189d7096f3`
in `C:\Users\advai\dev\power-market-data-platform`, then created
`phase/05-battery-optimization`. ADR 008 explicitly changes the old Phase 5 and
brief exclusion: battery optimization comes now; quality/as-of/forecasting moves
to Phase 6; reproducibility audit becomes Phase 7. No prior ADR history or
Phase 1/2 identity, timestamp, source or raw storage contract was rewritten.

Python 3.12.14, CVXPY 1.9.3 and highspy 1.15.1 were verified from stable PyPI
metadata and installed in the application's optional `optimization` extra.
Both solvers' selected packages have Python 3.12 Windows wheels. A native Windows
probe reported HIGHS in `cvxpy.installed_solvers()` and solved a binary-constrained
example to objective 11.200000000000003, status `optimal`, gap 0. pip check passed.
The first solver-stack import was slow; a separately time-limited diagnostic
exited while importing OSQP, but the original probe completed successfully and
subsequent full tests passed. No dependency downgrade or vendor patch was needed.

The existing Plotly 6.9.0 installation supplies the optional one-day HTML figure;
it is now also declared directly in the extra. No solver dependency was installed
in dbt or Flyte environments. dbt remains Core 1.12.5 / bigquery 1.12.1; Flyte
remains 2.8.1. No remote service, new infrastructure or source retrieval was added.

## Hand-computed model evidence

All powers below are grid-side MW, SOC is MWh, prices USD/MWh, intervals one hour.
Unless stated otherwise, capacity and both power limits are 1, efficiencies are
1, initial=terminal SOC is 0 and modeled throughput cost is 0.

| Case | Input / expected result | Observed result |
| --- | --- | --- |
| Flat price | [50,50,50], cost 1 per grid-throughput MWh: idle | All charge/discharge zero; objective 0 |
| Low/high | [10,30]: charge 1 then discharge 1; SOC [0,1,0] | Schedule/SOC match; objective 20 |
| Efficiency | [5,20], both efficiencies .9: 1 charged, .81 discharged | SOC [0,.9,0]; objective 11.2 |
| Terminal SOC | [100], initial=terminal 1: preserve energy | Idle; SOC [1,1]; objective 0. Test-only unconstrained terminal liquidation gives 100 |
| Power limit | [10,30], capacity 2, limits .5: transfer .5 | Charge/discharge .5; objective 10 |
| Energy limit | [10,30], capacity .4: transfer .4 | Maximum SOC .4; objective 8 |
| Negative price | [-100], both efficiencies .9, initial=terminal 0 | MILP idle. Test-only loose LP charges 1/discharges .81 simultaneously for value 19 |
| Insufficient spread | [10,11] with .9 efficiencies | Idle; objective 0 |
| Throughput cost | [10,12] with cost 2 on both grid-side legs | Idle; objective 0 |
| Infeasible | No charging power, initial 0, required terminal 1 | Explicit infeasible error; no dispatch |

Ten deterministic generated 12-hour price series include negative and positive
prices. Tests independently verify bounds, every SOC equation, boundary SOC,
exclusivity and recomputed objective, rather than checking solver status alone.
Corrupted returned vectors/objective are rejected. Solver failure, time-limited,
unbounded and inaccurate statuses are visible errors. Invalid configuration,
nonfinite/unrepresentable numerical values and mismatched horizons fail before
solving. A final review improved missing/null field diagnostics and overflow
handling; their regression checks are included.

## Offline daily integration

The synthetic 24-hour fixture is 17,753 bytes with invented prices and lineage
IDs, not copied CAISO data. The installed CLI executed the complete input,
validation, solve, metric, JSON and optional figure path with no credentials.
The reference configuration is 4 MWh, 1 MW in each direction, .95 efficiencies,
initial=terminal 2 MWh, one-hour intervals and zero throughput cost.

Observed synthetic results (not real market results):

| Metric | Value |
| --- | ---: |
| Price minimum / maximum | -10 / 70 USD/MWh |
| Gross arbitrage value / objective | 257.32105263157894 USD |
| Charged / discharged | 6.105263157894736 / 5.509999999999999 grid MWh |
| Grid throughput | 11.615263157894734 MWh |
| Cell throughput | 11.599999999999998 MWh |
| Equivalent full cycles | 1.4499999999999997 |
| Initial / final SOC | 2 / 2 MWh |
| Minimum / maximum SOC | 0 / 4 MWh within numerical tolerance |
| Charging / discharging / idle intervals | 7 / 6 / 11 |
| Status / gap / nodes | optimal / 0 / 1 |
| Observed solve time | 0.23888860001170542 seconds |

One daily figure was generated locally at `artifacts/battery-dispatch.html`.
JSON at `artifacts/battery-synthetic.json` retains every price, lineage identifier,
configuration value and dispatch vector. Both remain ignored. The numerical
precision above records solver output, not economic precision. Zero cost and
repeated prices may admit several equally optimal schedules.

Tests also cover 23-hour spring-forward, 25-hour fall-back, ordinary winter and
summer days; interval-weighted aggregate percentages; missing/duplicate days or
hours; schema/unit/lineage validation; query caps; CLI failures; and base import
without loading CVXPY. Offline SQL SELECT tests show that the new mart projects
current eligible state through A→A, A→B, A→B→A and late arrival, excluding the
fixture's FAILED/unfinalized observations through the existing fact. They are
not evidence of native BigQuery execution.

## Initial native attempt and quota chronology

No quota increase was requested or performed for Phase 5.

1. At 03:52:54 UTC on September 22, metadata showed 1,005 existing same-Pacific-day
   parent query jobs, 185,333,392 processed bytes and 16,997,416,960 billed bytes.
   Project custom quota was 5,120 MiB (5 GiB); the $1 monthly budget was unchanged.
   Metadata confirmed existing raw contents/transitions (72 LMP, 864 load),
   12 manifests and current facts (72 LMP, 864 load).
2. The first capped preflight used the reserved alias `rows` and failed SQL
   parsing. It was corrected to `row_count`; the corrected bounded August 1 NP15
   read succeeded with count 24, 1,872 processed bytes and 10,485,760 billed bytes.
   Thus the historical same-day total alone was not treated as conclusive proof
   that no query could run.
3. The one-test dbt cap regression passed, then `dbt build --select
   mart_battery_optimization_inputs --project-dir dbt --profiles-dir dbt` ran at
   04:16 UTC. Native contract compilation and view creation succeeded (0 bytes
   processed). The adapter emitted its existing NUMERIC precision/scale warning;
   the projection preserves the source's BigQuery NUMERIC values without casts.
4. All three selected data tests errored with `quotaExceeded`, specifically the
   project custom `QueryUsagePerDay`: not-null key, unique key, and complete
   battery-input reconciliation. Build exit code was 1: **1 model passed,
   3 tests errored**. These are infrastructure errors, not passed assertions or
   demonstrated data-contract failures.
5. Cloud query work stopped. No three-day price read or battery solve was attempted
   after the quota errors. At 04:17:40 UTC, metadata independently confirmed the
   5 GiB quota and $1 budget were unchanged. Every one of the eight new query-job
   configurations retained `maximumBytesBilled=104857600` (100 MiB).

The new relation is
`advait-power-market-20260920.power_market_analytics.mart_battery_optimization_inputs`,
a view over the existing hourly LMP fact. At this point its **actual row count
was not verified yet**. Existing fact/table metadata remains 72 LMP / 864 load, with unchanged raw
counts. There were no writes to raw source records or manifests, no backfill,
no disposable dataset, and no new cloud infrastructure.

### Initial attempt usage only

| Metric | Observed value |
| --- | ---: |
| Parent query jobs submitted | 8 |
| Failed query jobs | 4 (1 syntax error, 3 quota errors) |
| Bytes processed | 1,872 |
| Bytes billed | 10,485,760 |
| Added raw logical table storage | 0 bytes |
| Added analytical logical table storage | 0 bytes (new view stores no rows) |

The postflight same-Pacific-day totals, including historical Phase 3/4 activity,
were 1,013 parent queries, 185,335,264 processed bytes and 17,007,902,720 billed bytes.
Job metrics with absent processed/billed values contribute zero to these reported
sums. These are BigQuery usage statistics, not an invoice or a claimed dollar cost.
Only metadata reads occurred after the failed build. The 100 MiB limits, 5 GiB
custom quota, $1 alert, billing configuration and existing infrastructure were
left unchanged.

## Validation commands and results

From the actual repository, PowerShell (no activation or PATH edits):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,optimization]"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -I -c "import power_market_data; import power_market_data.optimization.battery; print(power_market_data.__version__)"
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\power-market-data.exe battery-backtest --start-date 2026-08-01 --end-date 2026-08-01 --location TH_NP15_GEN-APND --config examples/battery_reference.json --input-json tests/fixtures/battery_prices.json --output artifacts/battery-synthetic.json --figure artifacts/battery-dispatch.html
.\artifacts\dbt-core-venv\Scripts\python.exe -m pip check
.\artifacts\dbt-core-venv\Scripts\python.exe dbt/tooling/check_cost_cap.py
.\artifacts\dbt-core-venv\Scripts\dbt.exe parse --project-dir dbt --profiles-dir dbt
.\artifacts\flyte-venv\Scripts\python.exe -m pip check
.\artifacts\flyte-venv\Scripts\python.exe -m mypy orchestration orchestration_checks orchestration_integration_tests
.\artifacts\flyte-venv\Scripts\python.exe -m pytest orchestration_checks orchestration_integration_tests -q
```

The credential-free dbt parse used `GCP_PROJECT_ID=offline-project`, a nonexistent
`GOOGLE_APPLICATION_CREDENTIALS` path and disabled anonymous usage telemetry.
These overrides were process-local and absent during the native attempt.

All local checks pass: **314 offline tests**, of which **76** cover optimization
and backtesting (47 mathematical/solver tests, 29 input/backtest/CLI tests), plus
five new portable mart scenarios. mypy checks 43 files. The isolated dbt cap check
passes **1 test**; parse discovers **12 models, 41 data tests, 7 native unit tests**.
The new three data tests initially hit the quota, then passed after reset; no new dbt unit
test is needed for a pure projection. Existing native unit tests were not rerun.
The unchanged Flyte environment passes dependency checks, mypy and **4 local tests**;
one opt-in cloud suite is skipped, with two existing upstream Pydantic warnings.
The built wheel was also installed and its 314 tests passed outside editable
source resolution; the normal editable installation was restored. An initial
`--no-build-isolation` restore lacked Hatchling and failed; restoring with normal
build isolation succeeded. No previously completed expensive controlled cloud
suite was rerun.

Windows/Linux CI evidence is recorded on the PR. Offline green checks alone
do not satisfy cloud/data gates.

## Completion gates recorded after the initial attempt

The following was the recorded continuation checklist. Native/data items were
subsequently completed as described below, without raising any safeguards:

1. Rerun the scoped native build/test command above. Require all three tests to
   pass, preserving the already-implemented current-state and lineage contracts.
2. Read the existing August 1–3 2026 NP15 sample through the new mart using the
   documented `battery-backtest --warehouse` command. Measure the row count and
   per-day coverage; do not force 72 rows merely because the fact metadata says 72.
3. Require each daily solve to return accepted optimal dispatch and pass the
   independent physical/objective checks. Inspect low/high price intervals,
   charging/discharging and SOC trajectories. Investigate surprising schedules.
4. Record actual per-day and aggregate values, throughput, cycles and diagnostics,
   with one optional real daily figure. Do not label the synthetic numbers above
   as CAISO results and do not annualize the three-day sample.
5. Record new usage separately, verify safeguards again, update status only after
   observed success, and require final-head Windows/Linux CI before merge.

No forecasting, as-of consumer query, final Data Quality Observatory, stochastic
or robust optimization, bidding, ancillary services, capture-price analysis,
new ISO, remote optimizer or scheduler is implemented. Phase 6 has not started.


## Completion after ordinary quota reset

The local session paused overnight during an offline dbt parse, then resumed on
September 22. At 13:03:42 UTC the new Pacific day had zero query jobs/bytes in job
metadata. The project quota was still 5,120 MiB, the $1 budget was unchanged, and
all original raw/fact counts were unchanged. No temporary quota override was used.

The cost-cap regression passed again. This scoped command then passed natively:

```powershell
.\artifacts\dbt-core-venv\Scripts\dbt.exe build --select mart_battery_optimization_inputs reconcile_lmp --project-dir dbt --profiles-dir dbt
```

At 13:05:31 UTC: **1 view + 4 data tests passed, zero errors**. The four tests
were the three new input-mart tests plus the existing independent raw-to-current
LMP history/fact reconciliation. The NUMERIC warning remained visible; no cast,
rounding or field change was introduced. Native success required no weakening of
assertions. Review made the reconciliation SQL's explicit projection easier to
read, without changing the compared fields.

The installed live command subsequently passed:

```powershell
.\.venv\Scripts\power-market-data.exe battery-backtest --start-date 2026-08-01 --end-date 2026-08-03 --location TH_NP15_GEN-APND --config examples/battery_reference.json --warehouse --output artifacts/battery-np15.json --figure artifacts/battery-dispatch.html
```

The adapter read **72 actual rows, 24 per Pacific day**, with distinct logical
keys and location/UTC intervals. All were CAISO DAY_AHEAD_HOURLY, NP15, USD/MWh;
UTC intervals, Pacific dates, required lineage/schema fields and continuity
passed validation. Native reconciliation verified complete projection from the
current fact, which itself reconciled with eligible successful raw transitions.
No superseded content rows or failed/unfinalized states entered the input.

Reference settings: 4 MWh capacity, 1 MW charging and discharging limits, 0.95
charge/discharge efficiencies, initial=terminal 2 MWh, hourly intervals, zero
modeled throughput cost. All following monetary values are **simulated gross
arbitrage value under perfect foresight**, not revenue forecasts or asset P&L.

| Pacific day | Intervals | Min / max price (USD/MWh) | Gross value (USD) | Charged / discharged (grid MWh) | Grid throughput (MWh) | Equivalent full cycles |
| --- | ---: | --- | ---: | --- | ---: | ---: |
| 2026-08-01 | 24 | 27.19765 / 65.15886 | 89.263708837 | 5.540166205 / 5.000000000 | 10.540166205 | 1.315789474 |
| 2026-08-02 | 24 | 25.83308 / 85.1957 | 131.051612018 | 6.210526316 / 5.605000000 | 11.815526316 | 1.475000000 |
| 2026-08-03 | 24 | 31.26647 / 110.73877 | 166.417436368 | 6.210526316 / 5.605000000 | 11.815526316 | 1.475000000 |

| Pacific day | Charge / discharge / idle intervals | Initial / final SOC (MWh) | Min / max SOC (MWh) | Status | Solve seconds | MIP gap |
| --- | --- | --- | --- | --- | ---: | ---: |
| 2026-08-01 | 8 / 5 / 11 | 2 / 2 | 0 / 4 within tolerance | optimal | 0.062615100 | 1.59e-16 |
| 2026-08-02 | 7 / 6 / 11 | 2 / 2 | 0 / 4 within tolerance | optimal | 0.023083000 | 0 |
| 2026-08-03 | 7 / 6 / 11 | 2 / 2 | 0 / 4 within tolerance | optimal | 0.038278700 | 0 |

Each solve explored one MIP node. Independently recomputing the saved schedules
reproduced every objective; maximum SOC equation residual across the three days
was 1.1102230246251565e-16 MWh. Bounds, no simultaneous operation and boundary SOC
passed. These are numerical checks on this simplified model, not certification
of a physical asset.

Aggregate: **386.732757223 USD** gross value, average
128.910919074 and median 131.051612018
USD/day; best observed day August 3, worst August 1. Grid throughput was
34.171218837 MWh; cell throughput 34.126315789
MWh; equivalent cycles 4.265789474. Interval activity:
30.555556% charging, 23.611111% discharging,
45.833333% idle. No annualization or general storage-economic
conclusion follows from this three-day, one-hub sample.

### Economic inspection of the actual dispatch

All times here are Pacific with offset -07:00. On August 1, the three cheapest
hours (09:00–11:00, minimum 27.19765) charge at 1 MW; the highest price at 19:00
(65.15886) discharges at 1 MW. SOC reaches 4 MWh before evening discharge. The
small 21:00 charge at 51.82617 before a 22:00 sale at 57.83866 initially deserves
inspection: round-trip-adjusted sale value is about 52.20 per charging MWh,
slightly above 51.83. It is consistent with the specified zero throughput cost,
efficiency and hourly power limits. Charging at 23:00 restores terminal SOC.

On August 2, low-price 08:00–10:00 hours charge at 1 MW (minimum 25.83308); the
three highest 18:00–20:00 hours discharge at 1 MW (peak 85.1957). August 3 similarly
charges the low-price 08:00–11:00 period and discharges at 18:00–20:00, including
the 110.73877 maximum. Both later days discharge some initial stored energy in
the first two hours, recharge during lower-priced hours, and charge in the last
two hours to restore 2 MWh. That terminal replenishment prevents value from being
claimed merely by ending empty. It also illustrates why selecting only globally
cheapest/highest hours is not the full intertemporal optimization problem.

The saved local report retains all 72 exact prices and lineage references plus
dispatch vectors/configuration. The one daily figure path now shows the **real
August 1** schedule (replacing the earlier synthetic figure). No market cause
or deployable trading policy is inferred from this schedule inspection.

### Completion and total usage

| Metric | Completion after reset | All Phase 5, including initial errors |
| --- | ---: | ---: |
| Parent query jobs | 8 | 16 |
| Failed query jobs | 0 | 4 |
| Bytes processed | 76,608 | 78,480 |
| Bytes billed | 41,943,040 | 52,428,800 |
| Added logical table storage | 0 | 0 |

The 72-row read alone processed 33,552 bytes and billed 10,485,760 bytes. The
successful completion window's four tests and view build include metadata/cache
jobs; reported totals use job metadata, without inferring charges. The only new
relation is a view; original table bytes and raw/fact counts remained unchanged.

At 13:07:45 UTC, metadata verified **project quota 5 GiB/day**, the unchanged
**$1 monthly budget alert**, and **100 MiB maximumBytesBilled on all 16 Phase 5
query jobs**, including the actual adapter read and dbt submissions. Billing,
IAM, user quotas, reservations and infrastructure were not modified. No new
CAISO request, backfill, remote service or continuously running resource exists.

Local checks passed on the final implementation. Both Windows and Linux CI
passed on implementation commit `488053659d83826e6815f5312e9372f1db88bafb`
([CI run](https://github.com/AdvaitBP/power-market-data-platform/actions/runs/35731912661)).
The complete published diff was matched to the reviewed checkout. Review checked
units/equations, terminal SOC, negative-price exclusivity, current-transition
lineage, bounded/capped reads, optional dependency isolation, actual versus
synthetic results, and secret/generated-artifact exclusion. No model/data
assertion was weakened to obtain a pass.

The final documentation closure is rechecked by Windows/Linux CI before merge;
[PR #6](https://github.com/AdvaitBP/power-market-data-platform/pull/6) records that
final-head check and merge outcome. The complete earlier blocked attempt is
retained above. Phase 6 has not started.
