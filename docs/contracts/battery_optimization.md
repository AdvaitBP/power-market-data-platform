# Battery optimization and daily benchmark

Status: Phase 5 verified locally, natively and in Windows/Linux CI, within the
documented model/sample scope. ADR 008 records the roadmap change.

## Mathematical contract

One horizon contains 1–25 sorted, continuous, hourly UTC price intervals. The
core accepts `PriceInterval` values with Decimal USD/MWh prices, then converts
prices to floating point at the solver boundary. It does no I/O. Negative prices
are valid. Nonfinite prices, naive/non-UTC timestamps, gaps and duplicates fail.

For interval index $t=0,\ldots,n-1$, duration $\Delta t=1$ hour:

- $c_t$: grid-side charging power, MW, nonnegative.
- $d_t$: grid-side discharging power, MW, nonnegative.
- $s_t$: stored energy at interval boundary $t$, MWh ($n+1$ boundaries).
- $z_t\in\{0,1\}$: charging mode. Idle can have either mode value.

With price $p_t$ in USD/MWh and optional cost $k$ in USD/MWh of **grid-side
throughput, counting both charging and discharging**, maximize:

$$\sum_t \left[p_t(d_t-c_t)-k(c_t+d_t)\right]\Delta t.$$

Constraints:

$$s_{t+1}=s_t+\eta_c c_t\Delta t-d_t\Delta t/\eta_d$$
$$0\le s_t\le E,\quad 0\le c_t\le P_c z_t,\quad
0\le d_t\le P_d(1-z_t)$$
$$s_0=S_{initial},\qquad s_n=S_{terminal}.$$

$E$ is positive MWh capacity; power limits are nonnegative MW; efficiencies are
in $(0,1]$; both boundary SOC values lie in $[0,E]$; $k$ is nonnegative. All
inputs must be finite. No configuration is silently repaired. The core can
model different boundary SOC values, but the daily backtester requires equality.
There is no energy carried across daily horizons.

Charge efficiency multiplies grid energy entering the cell. Discharge efficiency
divides grid output to obtain energy withdrawn from the cell. With efficiencies
0.9 each, 1 MWh charged can later supply only 0.81 MWh to the grid. Cash flow uses
grid energy, not cell energy. The binary prevents within-interval simultaneous
operation even when negative prices would reward dissipation through losses.
This is a mixed-integer linear program (MILP), not an unconstrained price-spread
heuristic. Terminal SOC prevents free liquidation of initial energy at the end.

## Solver and numerical acceptance

CVXPY 1.9.3 calls HiGHS/highspy 1.15.1 explicitly. The optional `optimization`
extra contains the solver stack; base package imports do not load it. The default
solve limit is 30 seconds (caller may choose up to 60), with one solver thread,
MIP relative gap 1e-8, absolute gap 1e-6 and feasibility tolerance 1e-7. Only
`optimal` is accepted; infeasible, unbounded, time-limited/inaccurate and failed
solves return a visible error, never zero-valued synthetic dispatch.

An independent Python calculation checks vector lengths, finite values, every
SOC balance, bounds, binary exclusivity and initial/terminal values using absolute
physical tolerance 1e-6 MW/MWh. It checks the monetary objective with absolute
1e-5 USD / relative 1e-8 tolerance. These are numerical tolerances, not permissible
operational violations. Raw returned floats are retained; no rounding/clipping
conceals residuals. Alternative equally optimal schedules can exist, so dispatch
is not claimed unique. Solver status, objective, time, MIP gap and node count are
retained where available. Tiny daily problems establish no scalability claim.

## Metrics and interpretation

- Gross arbitrage value: $\sum_t p_t(d_t-c_t)\Delta t$, USD.
- Modeled throughput cost: $k\sum_t(c_t+d_t)\Delta t$, USD.
- Objective: gross value minus modeled throughput cost.
- Charged/discharged energy: $\sum c_t\Delta t$ / $\sum d_t\Delta t$, grid MWh.
- Grid throughput: sum of those two quantities, MWh.
- Cell throughput: $\sum(\eta_c c_t+d_t/\eta_d)\Delta t$, MWh.
- Equivalent full cycles: cell throughput divided by $2E$; one complete
  charge/discharge through the cell's capacity counts as one cycle.
- Charging/discharging interval counts use power >1e-6 MW; other intervals idle.

The illustrative reference battery is 4 MWh / 1 MW in both directions, 0.95
charge and discharge efficiencies, initial=terminal 2 MWh, and zero throughput
cost. It describes no specific asset. The cost parameter is an illustrative
linear penalty, not a sourced degradation model.

Perfect foresight gives the solver realized prices for the entire horizon. This
is an oracle benchmark for a hypothetical price-taking, energy-only battery.
Current prices may include later revisions; this is not point-in-time research.
There is no forecast, stochastic/robust optimization, market impact, bidding,
ancillary service, capacity payment, fee, capital cost, production P&L or physical
power-flow model. Three dates can verify integration, not establish general
battery economics. Do not annualize them. Phase 6 will address historical
information availability and forecast-driven decisions separately.

## Analytical input and daily backtest

`mart_battery_optimization_inputs` is a view with one current accepted CAISO
DAY_AHEAD_HOURLY price per location and UTC hourly interval, also identified by
`logical_key`. It projects `fct_hourly_lmp`, whose state is selected from eligible
SUCCEEDED transitions. It never selects the newest unique content row directly.
A→B→A therefore selects the later return to A while preserving A's original
content first-seen time and the later transition/knowledge time. No load enters
this price-only benchmark.

All 19 columns are required: source, market, unit, market_date, location,
interval_start_utc, interval_end_utc, lmp, logical_key, content_id, content_hash,
logical_key_schema, content_hash_schema, transition_id, state_run_id,
state_ordinal, commit_sequence, first_seen_at and state_known_at. Native dbt
contracts retain NUMERIC price, DATE market date and TIMESTAMP clocks. Tests
check key uniqueness/nullness and reconcile every projected field in both
directions against the fact, plus location/interval grain and time/unit rules.
There is no partition/cluster on this small view and no measured speedup claim.

The read adapter accepts 1–7 **inclusive**, completed Pacific dates and one
supported hub. It performs one parameterized SELECT with a 100 MiB ceiling and
records job ID/processed/billed bytes. It does not fetch CAISO or write raw data.
Input lineage and exact decimal prices are retained in the local result; schema
versions are explicit. A result is reproducible from those inputs even if the
current warehouse state changes later. It is not a historical knowledge-cutoff
query. Use a quiescent analytical target as required by ADR 006.

Before any solve, all days must contain exactly the continuous UTC intervals
between consecutive Pacific midnights: 24 normally, 23 on spring-forward and 25
on fall-back. The repeated fall-back local hour has distinct UTC identities.
Missing/duplicate intervals, missing days, unexpected locations, null values,
wrong units, naive times and incompatible identity schemas fail visibly. This
checks benchmark eligibility; it does not prove CAISO source completeness.

Per-day results include solver diagnostics, dispatch, boundary SOC, gross value,
modeled cost, min/max price, physical metrics and lineage. Aggregates sum value,
throughput and cycles; mean/median and best/worst days describe this sample only.
Activity percentages weight intervals, not days, so DST days are handled correctly.
Equal best/worst values use the earliest selected date. No energy is carried
between independent days. Zero throughput cost may permit several optimal
schedules; numerical diagnostics do not establish operational feasibility.

## Reproducible local commands

From the repository root, PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,optimization]"
.\.venv\Scripts\power-market-data.exe battery-backtest --start-date 2026-08-01 --end-date 2026-08-01 --location TH_NP15_GEN-APND --config examples/battery_reference.json --input-json tests/fixtures/battery_prices.json --output artifacts/battery-synthetic.json
```

The fixture is entirely invented, including its lineage IDs. No credentials or
network are needed after installation. The CLI prints a JSON report and writes
only paths explicitly requested; create the destination directory first if absent.
To generate one local figure, add `--figure artifacts/battery-dispatch.html`.
It contains hourly LMP, grid charge/discharge and boundary SOC, with UTC axes
and Pacific-offset price hover labels. It reuses Plotly already present through
gridstatus (also declared directly in the optimization extra). It is one static
local report with interactive inspection, not an application or hosted service.
Only the first selected day's figure is produced; multi-day metrics stay in JSON.
Generated reports/HTML remain ignored under `artifacts/`.

For live integration, **only when ordinary quota permits**, with existing ADC
and the selected isolated dbt Core environment:

```powershell
$env:GCP_PROJECT_ID = "your-dedicated-project-id"
$env:BQ_ANALYTICS_DATASET = "power_market_analytics"
$env:DBT_SEND_ANONYMOUS_USAGE_STATS = "false"
.\artifacts\dbt-core-venv\Scripts\python.exe dbt/tooling/check_cost_cap.py
.\artifacts\dbt-core-venv\Scripts\dbt.exe build --select mart_battery_optimization_inputs --project-dir dbt --profiles-dir dbt
.\.venv\Scripts\power-market-data.exe battery-backtest --start-date 2026-08-01 --end-date 2026-08-03 --location TH_NP15_GEN-APND --config examples/battery_reference.json --warehouse --output artifacts/battery-np15.json --figure artifacts/battery-dispatch.html
```

Use your existing profile rather than replacing it. The input command does not
build the mart implicitly. Upstream current facts must already exist and their
Phase 3 eligibility/reconciliation tests must remain healthy. This bounded
integration adds no backfill or new infrastructure. Preserve 5 GiB/day, the $1
monthly alert and 100 MiB Python/dbt caps; an alert is not a spending cap. Normal
CI installs the optimization extra and runs solver/fixture tests without cloud
access; isolated dbt/Flyte dependencies remain separate. Live failure leaves the
Phase 5 completion gate open. See the verification record for observed results.
