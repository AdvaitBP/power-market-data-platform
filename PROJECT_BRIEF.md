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
dbt transformations and Flyte orchestration remain planned.

## Not in scope

Trading strategy, automated bidding, dispatch optimization, production P&L,
proprietary forecasting, and battery optimization are outside this project.
