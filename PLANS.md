# Implementation plan

Phases 0–5 are complete within their documented scope.
Phases 6–7 are planned and unimplemented.
ADR 008 records the explicit 2026-09-21 roadmap change after Phase 4.
Each phase must meet its definition of done before the next begins. Tests that
require an external service must be explicit and separate from offline unit CI.

## Phase 0 — repository/tooling foundation

- **Purpose:** Establish a verifiable package and honest engineering contracts.
- **Deliverables:** src-layout package, local Python environment, development
  tools, offline tests/CI, project brief, roadmap, ADRs, and setup documentation.
- **Tests:** Ruff lint/format, strict mypy, isolated installed-package import,
  pytest, and building/installing a wheel; CI on Python 3.12.
- **Definition of done:** Compatibility rationale recorded, local checks pass,
  complete diff reviewed, no secrets/artifacts tracked, and the foundation PR
  merged after passing CI.
- **Deferred:** Source calls, cloud resources, business logic, dbt models, and
  orchestration.

## Phase 1 — CAISO source adapters and normalization

Status: Complete within the [source contract](docs/sources/caiso.md). Both live
products were fetched for 2026-08-01 and normalized; offline fixtures, explicit
grain/time/identity contracts, and source limits are documented. Load fall-back
dates are intentionally rejected because the pinned parser guesses an offset.

- **Purpose:** Turn explicitly selected CAISO products into documented observations.
- **Deliverables:** A narrow source/product scope, source-access terms and
  provenance notes, Python adapter boundaries, normalized schemas with explicit
  grain/units/intervals, deterministic identities, and small offline fixtures.
- **Tests:** Parsing, timezones/DST, interval conventions, malformed responses,
  missing values, stable keys/hashes, and source-aware validation.
- **Definition of done:** Selected products can be fetched in an opt-in smoke
  run and normalized reproducibly from saved fixtures; failures are visible,
  schemas and retrieval limits documented, and unit CI needs no network.
- **Deferred:** Durable warehouse persistence, broad ISO coverage, orchestration,
  and analytical marts.

## Phase 2 — revision-aware BigQuery persistence

Status: Complete within the [warehouse contract](docs/contracts/warehouse.md).
[Live verification](docs/verification/phase2.md) demonstrates real CAISO persistence,
unchanged reruns, disposable revision/recovery tests and cleanup.
See [ADR 005](docs/adr/005-bigquery-persistence.md) for concurrency and clock limits.

- **Purpose:** Persist observations without losing changes or inventing history.
- **Deliverables:** Raw/version schemas, ingestion manifests and provenance,
  idempotent writes, knowledge timestamps, and a documented correction policy.
- **Tests:** Exact rerun no-ops; changed content preserved; A→B→A reappearance;
  late arrivals; concurrent/retried writes; failed batches and committed visibility.
  Use offline contract tests plus opt-in tests in a disposable BigQuery dataset.
- **Definition of done:** Repeating a load adds no duplicate observation versions;
  corrections remain queryable and first-known times are stable; integration
  checks demonstrate the write contract and document costs/cleanup.
- **Deferred:** Full analytical marts, scheduling, and capture-price analysis.

## Phase 3 — dbt analytical warehouse

Status: Complete within documented scope, verified on 2026-09-21. The controlled
native suite passed revision/reappearance, late-arrival, unsuccessful-run exclusion,
incremental/full-refresh equality, deliberate failed-contract detection and repair.
Two real builds, independent reconciliation and live catalog generation passed
without changing cost safeguards. The earlier quota failure is preserved in the
[verification record](docs/verification/phase3.md).

- **Purpose:** Express warehouse transformations and their contracts in SQL.
- **Deliverables:** dbt sources, staging/intermediate models, initial facts with
  documented grain, revision selection rules, lineage, and generated documentation.
- **Tests:** Uniqueness, not-null, relationships, accepted values, interval
  completeness, and revision selection using controlled examples.
- **Definition of done:** A documented dbt build succeeds against a controlled
  dataset; model outputs reconcile to the preserved raw observations and
  failed data contracts are surfaced.
- **Deferred:** Flyte schedules, broad mart coverage, and analytical conclusions.

## Phase 4 — Flyte orchestration and backfills

Status: **complete within documented limits**, verified on 2026-09-21. Native
Flyte execution, controlled interruption/resumption equivalence, the saved real
two-day NP15/load backfill, fresh retrieval, dbt and analytical reconciliation
passed. Exact real retrieval added no content or transitions and changed no fact
rows. Temporary daily quota increases and both restorations to 5 GiB remain in
the [Phase 4 verification record](docs/verification/phase4.md).

- **Purpose:** Coordinate bounded, repeatable runs without embedding domain rules.
- **Deliverables:** Tasks calling existing adapters/storage and dbt interfaces,
  explicit date-range inputs, retries/timeouts, manifests, and resumable backfills.
- **Tests:** Dependency order, parameter validation, retry idempotency, partial
  failures, bounded concurrency, and backfill equivalence to incremental runs.
- **Definition of done:** A small historical backfill can be interrupted and
  resumed without duplicates or silent gaps; execution environment, credentials,
  and operational limits are documented and an opt-in run verifies them.
- **Deferred:** Additional orchestration systems and large unattended deployments.

## Phase 5 — Battery dispatch optimization and historical backtesting

Status: **complete within the documented model and three-day sample scope**. [ADR 008](docs/adr/008-battery-benchmark.md)
replaces the former immediate data-quality/as-of/capture-price objective. This is
an explicit scope change, not a claim that batteries were always in scope.
The local model/offline backtest, native input tests and three real daily solves
pass. The initial quota blockage was resolved by ordinary reset, without an
increase. See
[Phase 5 verification](docs/verification/phase5.md).

- **Purpose:** Study constrained energy decisions using the trusted current-state
  price data through a price-taking, perfect-foresight energy-arbitrage benchmark.
- **Deliverables:** Optional CVXPY/HiGHS application extra, a typed battery MILP,
  physical/monetary reconciliation, a current-price dbt input mart, independent
  daily backtesting, one local dispatch figure and mathematical documentation.
- **Tests:** Hand-computed schedules, terminal SOC, efficiencies, power/energy
  bounds, negative-price exclusivity, invalid inputs, solver failures, objective
  reconciliation, daily continuity/DST and offline end-to-end backtests.
- **Definition of done:** The model and offline tests pass; the native dbt input
  mart and existing three NP15 days flow into the solver, all schedules pass
  physical/economic checks, measured results/limits are recorded, and Windows/Linux
  CI passes. Quota-blocked live verification leaves the PR draft and unmerged.
- **Deferred:** Forecasts, as-of inputs, stochastic/robust optimization, real
  bidding, ancillary services, market impact, rolling SOC across days and P&L.

## Phase 6 — Point-in-time quality, forecasting and forecast-driven dispatch

- **Purpose:** Compare decisions made with information available at the time
  against the Phase 5 oracle benchmark, without look-ahead leakage.
- **Deliverables:** Knowledge-cutoff queries and quality reports; a documented
  forecasting baseline, temporal evaluation and forecast-driven dispatch with
  economic regret. These are planned, not implemented. The original as-of and
  Data Quality Observatory work moves here; it is not discarded.
- **Tests:** No post-cutoff observations/features, revision timing, missing-data
  handling, chronological train/evaluation separation, physical feasibility and
  independently reconciled regret against the same-horizon oracle.
- **Definition of done:** Recorded input cutoffs and model versions reproduce
  predictions and decisions; forecast and economic errors are reported without
  claiming a deployable trading policy.
- **Deferred:** Trading/bidding automation, proprietary forecasts, stochastic
  optimization and real asset P&L. Capture-price analysis is an optional later
  analytical extension, not an immediate mandatory phase.

## Phase 7 — Public reproducibility audit

- **Purpose:** Let another reader verify the engineering and its limitations.
- **Deliverables:** Fresh-checkout walkthrough, bounded sample reproduction,
  provenance/license audit, architecture/status review, and measured results
  linked to reproducible commands and data versions.
- **Tests:** Clean-environment installation, offline CI, sample reproduction,
  link/secret/artifact review, and an explicit audit of every public claim.
- **Definition of done:** A reader can reproduce the documented sample with
  stated inputs and costs; credentialed steps are distinguished from offline
  checks, and unsupported claims or unverifiable results are removed.
- **Deferred:** Claims about operational service levels or capabilities that have
  not been measured and demonstrated.
