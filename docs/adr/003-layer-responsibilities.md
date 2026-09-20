# ADR 003: Separate ingestion, storage, transformation and orchestration

- Status: Accepted for planned architecture
- Date: 2026-09-20

## Decision

| Layer | Intended responsibility | Boundary |
| --- | --- | --- |
| Python | External I/O, source normalization, provenance and source-aware validation | Produces explicit observation contracts; does not hide scheduling or marts in adapters. |
| BigQuery | Durable analytical storage for observations, revisions and run metadata | Persistence must honor idempotency and committed visibility; it is not the source parser. |
| dbt | Warehouse-native SQL transformations, tests, lineage and marts | Reads documented persisted contracts; does not fetch CAISO data. |
| Flyte | Task dependencies, retries and historical backfills | Calls existing ingestion/storage/transformation interfaces; does not redefine their rules. |

A Python storage adapter will handle BigQuery I/O separately from CAISO parsing.
Offline tests should exercise normalization without a cloud client or
orchestrator. Cloud integration and orchestration tests will be opt-in.

## Rationale

One script mixing requests, parsing, writes, SQL and retries makes it difficult to
replay a response without rewriting data, or retry a write without refetching a
changed source. These boundaries let the source contract be tested independently,
keep SQL lineage visible, and make backfills reuse the same ingestion behavior.

The separation does not require a plugin system, generic adapter framework, or
separate services. Start with small explicit modules when the relevant phase
needs them. Dependency/runtime environments may be separated if measured
compatibility or deployment constraints require it.

## Consequences

Interfaces and failure behavior must be documented as each layer is introduced.
A task reporting success must mean its outputs are durably available. A retry
does not make a write idempotent; the persistence contract must do that.

Only packaging and development tooling exist in Phase 0. The four layers above
are planned responsibilities, not deployed components.
