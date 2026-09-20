# ADR 001: UTC is canonical analytical time

- Status: Accepted for future data contracts
- Date: 2026-09-20

## Context

Market reports may label an interval by its start, end, market date, or local
hour. Local clock labels alone are not unique during the autumn DST transition,
and some labels do not exist during the spring transition. A local operating
day can contain 23 or 25 hours; assuming 24 creates false gaps or duplicates.

## Decision

Use timezone-aware UTC instants for analytical keys and joins. Every dataset
must define whether timestamps mark interval starts or ends and document its
interval duration. Where applicable, normalize intervals as [start, end).

Preserve the original timestamp label, source timezone/offset, and market date
when needed to interpret the source. For California local time, use the IANA
zone America/Los_Angeles, not a fixed UTC offset.

Do not interpret a naive local time as UTC or infer DST from row order. An
ambiguous local label requires source offset, fold, or another documented source
convention. Reject/quarantine unresolved ambiguous or nonexistent local times
with a useful validation error. A join must also agree on interval boundaries,
market, and location; sharing a UTC timestamp alone is insufficient.

## Consequences and verification

UTC gives a stable chronological coordinate; local operating-day reporting still
requires explicit timezone conversion. A later normalization phase must test
both DST transitions, interval-end conventions, and local-date boundaries.

This ADR defines a contract. No timestamp parser or dataset is implemented in
Phase 0.
