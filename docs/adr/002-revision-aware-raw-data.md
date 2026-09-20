# ADR 002: Preserve changed source observations

- Status: Accepted for future raw-storage design
- Date: 2026-09-20

## Context

The value retrieved for a market interval can change after its first publication.
Blind replacement loses the evidence needed to explain why a rerun changed an
analysis. Repeated requests also return identical rows; storing every retrieval
as a new observation confuses retries with source corrections.

## Decision

Future raw storage must distinguish these concepts:

- **Logical observation identity:** A deterministic key derived from documented
  grain: source/product, market, location, UTC interval and other dimensions that
  identify the fact. A measured value and retrieval time are not part of this key.
- **Content identity:** A hash of a canonical representation of material source
  fields, including relevant values, units and quality/status flags. Define
  field order, nulls, numeric precision, timezone representation and schema/hash
  version. Exclude run IDs, retrieval clocks and other incidental metadata.
- **Row/version identity:** A deterministic identifier linking the logical key
  and a distinct source-content state. Source revision IDs, when reliable, are
  preserved separately. A content hash is not an ordering or publication time.
- **Event time:** The interval or instant being measured, independent of when
  the pipeline encounters the observation.
- **Ingestion/knowledge time:** The first successful durable acceptance of a
  source observation by this system. Preserve retrieval/response and optional
  source-publication timestamps separately. Do not backdate knowledge time to
  event time or assume publication time proves this system had the data.

Exact reruns must not duplicate a logical/content version or rewrite its
first-known time. Material changes must be preserved alongside earlier values,
with retrieval provenance and a link to the ingestion manifest. Invalid rows
must remain diagnosable without silently becoming valid analytical facts.

Distinct content alone does not describe all history: if the source changes
A→B→A, the last A is a new observed transition even though its content is already
known. Preserve ordered sightings/transitions, referencing content versions,
with stable ingestion/batch identities so replaying the same batch is a no-op.
Unchanged retrievals may be recorded in manifests without duplicating fact rows.

A future as-of query must use only observations accepted by its knowledge cutoff.
Historical backfills do not establish what this pipeline would have known before
it existed. Reproducing an analysis also requires versioned transformation logic,
not merely preserved inputs.

## Consequences and verification

Storage and queries are more involved than an overwrite table, but revisions can
be explained and reruns can be distinguished from corrections. Phase 2 must
settle atomic commit visibility, concurrent writers, deterministic tie-breaking,
deletion/retraction semantics, hash evolution, and retention before claiming
as-of support. Tests must include repeats, material changes, late arrivals,
A→B→A, and interrupted/retried loads.

No raw warehouse, hashing implementation, or as-of query exists in Phase 0.
