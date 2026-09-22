# Battery optimization and daily benchmark

Status: Phase 5 implementation in progress; native warehouse integration is a
separate completion gate. ADR 008 records the roadmap change.

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

$$\sum_t p_t(d_t-c_t)\Delta t-k(c_t+d_t)\Delta t.$$

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
