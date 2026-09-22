# ADR 008: Battery dispatch benchmark and revised analytical roadmap

- Date: 2026-09-21
- Status: Accepted; native Windows toolchain, local model and three real daily
  solves verified. The initial native-test quota blockage was resolved after
  ordinary reset, without changing safeguards. Final CI/merge remains a gate.
- Scope: Explicitly changes the original Phase 5/brief scope; extends ADR 003
  with an independent optimization consumer. ADRs 001–007 remain historical
  decisions and their data/time/identity/persistence contracts are unchanged.

## Why the roadmap changed

Phases 0–4 established traceable market data and repeatable bounded ingestion,
recovery and SQL transformations. The next question is how those trusted prices
support a constrained energy decision. The original plan deferred battery
optimization and prioritized quality/as-of/capture-price work. This decision
changes that priority openly after the platform became usable.

Phase 5 becomes deterministic battery dispatch and perfect-foresight historical
backtesting. Phase 6 retains the original point-in-time quality/as-of work and
adds price forecasting, forecast-driven dispatch and economic regret. Historical
feature availability is particularly important there to avoid leakage. Phase 7
becomes the reproducibility audit. Capture-price analysis is optional later work.
No forecasting, stochastic optimization, bidding or Phase 6 implementation is
part of this change.

## Tooling and dependency boundary

Select stable CVXPY 1.9.3 and highspy 1.15.1, checked against PyPI on this date.
[CVXPY metadata](https://pypi.org/project/cvxpy/1.9.3/) requires Python >=3.11;
[highspy metadata](https://pypi.org/project/highspy/1.15.1/) requires >=3.9.
Both publish CPython 3.12 Windows x64 wheels. Installed execution, not metadata
alone, must verify the selected combination before claiming compatibility.
A Python 3.12.14 Windows probe found HIGHS in installed_solvers(), solved a
two-variable binary-constrained example to optimal status with objective 11.2,
and exposed solve time, mip_gap and mip_node_count. pip check passed.

Use the optional application extra `.[optimization]`. Ingestion users need not
install solvers. The optimization core imports CVXPY only when solving. Do not
put these dependencies into the dbt or Flyte tooling environments. Direct pins
record the tested combination; this is not a complete transitive lock. The
optional figure reuses Plotly already present through gridstatus and declares
that dependency directly; no new plotting engine or service is added.

[CVXPY's solver interface](https://www.cvxpy.org/tutorial/solvers/) supports
explicit `solver="HIGHS"` and HiGHS options. The
[HiGHS options reference](https://ergo-code.github.io/HiGHS/dev/options/definitions/)
documents MIP tolerances and time limits. CVXPY keeps the mathematical expressions
close to the written model; HiGHS provides an open-source MILP solver without a
commercial license. No solver-speed comparison or scalability claim is intended.

## Formulation and boundaries

Use grid-side charge/discharge MW, SOC in MWh and one binary charging-mode
variable per hourly interval. The SOC equation includes separate charging and
discharging efficiencies. Fix both initial and terminal SOC. Maximize the known
price cash flow minus a configurable grid-side throughput cost; the cost defaults
to zero and is not an industry degradation estimate.

The binary forbids simultaneous charging/discharging. An unrestricted continuous
LP can exploit negative prices by dissipating purchased energy through losses
within one interval while returning to the same SOC. A MILP makes the physical
contract explicit. Daily horizons have only 23–25 binaries, including DST; tiny
solve times do not establish large-horizon performance.

The optimizer accepts typed UTC price intervals, without CAISO or warehouse I/O.
A separate backtesting adapter reads a narrow dbt view over current LMP facts,
retains input lineage, requires continuous Pacific days and solves each day
independently with equal starting/terminal SOC. Results independently reconcile
physical constraints and the monetary objective. No stored energy crosses daily
boundaries in this benchmark.

Known realized prices make this a perfect-foresight oracle. Current accepted
prices may contain revisions learned much later. They are not an as-of dataset
or information a historical operator had. Gross arbitrage value omits asset
capital costs, fees, ancillary services and market impact; it is not P&L.

## Alternatives

- A continuous LP is simpler and can be adequate under additional price/cost
  assumptions. Those assumptions do not guarantee exclusivity with negative
  electricity prices, so the baseline retains binaries.
- Direct highspy or scipy.optimize.milp would avoid CVXPY canonicalization but
  require more manual matrix/index construction. Both are reasonable choices;
  no performance comparison was needed for these small models.
- Pyomo is viable but adds no needed capability for this formulation.
- Commercial solvers can solve this problem; no measured need justifies one.
- A warehouse-only implementation would mix decision optimization with SQL
  transformations. A remote service or new Flyte task adds no required boundary.

## Verification and limits

First prove hand-computed cases and invariant checks offline, then the mart and
existing August 1–3 NP15 sample natively when normal quota permits. Never create
new source history to enlarge the sample. Preserve the 5 GiB/day, $1 alert and
100 MiB query limits. Live quota blockage leaves Phase 5 incomplete and unmerged.
Three observed days establish integration, not general battery economics.
