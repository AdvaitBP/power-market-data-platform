# Implementation plan

Phases 0 and 1 are complete within their documented scope. Phases 2–6 are
planned and unimplemented; Phase 2 has not started.
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

- **Purpose:** Coordinate bounded, repeatable runs without embedding domain rules.
- **Deliverables:** Tasks calling existing adapters/storage and dbt interfaces,
  explicit date-range inputs, retries/timeouts, manifests, and resumable backfills.
- **Tests:** Dependency order, parameter validation, retry idempotency, partial
  failures, bounded concurrency, and backfill equivalence to incremental runs.
- **Definition of done:** A small historical backfill can be interrupted and
  resumed without duplicates or silent gaps; execution environment, credentials,
  and operational limits are documented and an opt-in run verifies them.
- **Deferred:** Additional orchestration systems and large unattended deployments.

## Phase 5 — data-quality/as-of/capture-price analytics

- **Purpose:** Show what data quality and revision timing mean for an analysis.
- **Deliverables:** Freshness/completeness/revision reports, as-of queries using
  knowledge cutoffs, and renewable capture-price/supply-timing examples with
  explicit price locations, generation units, interval weighting, and exclusions.
- **Tests:** No observations learned after the cutoff enter an as-of result;
  corrections change only eligible results; hand-calculated weighted-price
  examples cover missing intervals, zero generation, and negative prices.
- **Definition of done:** Results reproduce from a recorded cutoff and versioned
  transformations; quality gaps are visible alongside conclusions, and examples
  state their geographic, temporal, and data limitations.
- **Deferred:** Trading, bidding, dispatch/battery optimization, forecasts, and P&L.

## Phase 6 — public portfolio/reproducibility audit

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
