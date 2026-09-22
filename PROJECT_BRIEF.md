# Project brief

I study Mathematics and Computer Science at Duke and am interested in electricity
markets and clean energy. Working with messy renewable-energy and
environmental-market datasets made me interested in the infrastructure behind an
analysis: which observations can be trusted, what changed, and whether a result
can be reproduced later.

This project applies that question to public wholesale power-market data. CAISO
is the first intended source because California power markets connect to my
previous energy work and offer rich public market data. The aim is to understand
how reliable data supports decisions about actual power systems and markets.

The engineering focus is explicit interval semantics, source provenance,
idempotent reruns, preserved revisions, and analysis bounded by what the system
knew at a given time. Phase 1 implements a narrow Python CAISO adapter and
normalization boundary. Phase 2 adds BigQuery contents, transitions and run
manifests with explicit durable acceptance and recovery semantics.
Phase 3 adds dbt analytical models and tests. Phase 4 coordinates bounded
requests, recovery and downstream dbt builds through local Flyte execution.

## Revised analytical objective (2026-09-21)

Battery optimization was excluded from the original brief. After the data and
recovery contracts were established, the project objective changed explicitly:
Phase 5 studies how trusted prices support constrained energy decisions through
a hypothetical battery's perfect-foresight historical dispatch. This is an oracle
benchmark, not an operating policy. [ADR 008](docs/adr/008-battery-benchmark.md)
records the change and its boundaries.

Point-in-time data quality and as-of work moves to Phase 6 alongside price
forecasting and forecast-driven dispatch comparisons. Capture-price analysis is
an optional later extension. None of those Phase 6 features exists yet.

## Not in scope

Real trading strategy, automated bidding, operational battery scheduling,
production P&L, proprietary forecasting, ancillary services and market impact
remain outside this project. Phase 5 adds only deterministic, energy-only,
price-taking dispatch against known prices. It does not add forecasting,
stochastic optimization or a deployed optimizer.
