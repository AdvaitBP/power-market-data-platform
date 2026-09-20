# ADR 005: Unique contents, ordered transitions and committed runs in BigQuery

- Status: Accepted
- Date: 2026-09-20
- Extends: ADR 002; Phase 1 grain, time and hash contracts are unchanged.

## Decision

Use six native BigQuery tables in a raw dataset: ingestion_runs, warehouse_control,
lmp_contents, load_contents, lmp_state_transitions and load_state_transitions.
Contents store each distinct logical-key/content-hash pair once. Transitions
record a change from the latest accepted state, including a return to an older
content. Manifests record each bounded attempt, including unchanged retrievals
and failures. The one-row control table supplies a dataset-wide sequence and a
pending-finalization guard; it is not an external locking service.

| Run | Observed value | Unique contents after acceptance | Transitions |
| --- | --- | --- | --- |
| 1 | A: LMP = -7 | A | 1 → A |
| 2 | A: LMP = -7 | A | unchanged |
| 3 | B: LMP = 20 | A, B | 2 → B |
| 4 | A: LMP = -7 | A, B | 3 → A |

The fourth run references the original A content. Its transition is new, but A's
first_seen_at is not rewritten. These rows record what this system observed;
they do not establish the source's complete publication/revision sequence.

## Alternatives

1. **Overwrite one row per logical observation:** simple current-state lookup,
   but destroys the previous value and cannot reproduce observed revisions.
2. **Append every retrieval:** preserves downloads, but confuses unchanged
   retrievals with revisions and repeats source contents unnecessarily.
3. **Unique contents alone:** deduplicates repeats but loses A→B→A ordering.
4. **Chosen model:** distinct contents, transitions and manifests give each
   concept its own grain. Two typed product families avoid a generic EAV table.
5. **PostgreSQL:** enforced unique constraints and transactional row locks would
   simplify a high-concurrency operational write path. BigQuery instead fits the
   planned warehouse-native SQL analysis without operating a database server.
   Its DML latency, unconstrained keys and snapshot-isolation conflicts require
   the explicit small-volume write protocol below. No performance advantage is
   claimed or measured.

## Atomicity and knowledge time

BigQuery supports atomic multi-table DML transactions and snapshot isolation.
However, CURRENT_TIMESTAMP inside a transaction is the transaction's **start**,
not its commit time. See [transaction behavior](https://docs.cloud.google.com/bigquery/docs/transactions)
and [job statistics](https://docs.cloud.google.com/bigquery/docs/reference/rest/v2/Job#JobStatistics).

The implementation uses a data commit followed by metadata finalization:

1. Persist a STARTED manifest before fetching. A source/preparation failure can
   become FAILED without publishing observation rows.
2. Read a bounded snapshot and compute changes using the tested Python planner.
3. One transaction updates the control row, asserts the expected sequence and
   no pending finalization, merges contents/transitions, and marks the run
   COMMITTED with commit_completed=true. Either all these writes commit or none
   do. Every writer must follow this protocol.
4. Wait for the stable commit query job to finish successfully. Its server
   reported end time supplies knowledge_at. This is a **conservative completion
   bound on durable acceptance**, not a claim to the exact internal commit
   instant. It is never event time, retrieval time, or transaction start.
5. A second atomic transaction fills new content first_seen_at and transition
   known_at, marks SUCCEEDED, and releases the guard. Existing first_seen_at
   values remain unchanged. Consumers must filter manifests to SUCCEEDED.

A crash between steps 3 and 5 leaves COMMITTED, not SUCCEEDED or FAILED.
All observation writes are already durable, but they are not eligible consumer
input. No later batch can commit before finalization. Resume retrieves the
original commit job and retains its original completion time, even if recovery
happens much later. A lost response is never treated as proof of failure.
A crash before submission leaves STARTED and can refetch under the same request.

This refines ADR 002's knowledge-time implementation rather than silently
pretending BigQuery exposes a commit clock inside the transaction. A future
as-of consumer must use the documented conservative clock and successful-run
filter, not the provisional raw rows. No as-of consumer is implemented here.

## Retry and concurrency

A caller-generated UUID identifies one bounded attempt. A deterministic request
digest binds its product/date/hub; a batch digest records accepted key/hash pairs.
Stable BigQuery job IDs identify begin and commit submissions. Reusing a run ID
means resume that attempt, not fetch a later revision. SUCCEEDED replay is a
no-op even after other runs changed the same logical observation.

Native concurrent updates to the control row conflict. The expected-sequence
ASSERT also rejects a stale plan submitted after a competing writer committed.
There is no reliance on unenforced primary keys, insert-only MERGE uniqueness,
or an assumed automatic transaction retry. A terminally failed attempt remains
FAILED; a new attempt uses a new run ID and reads a fresh snapshot. Request-level
client transport retries can reattach to the same job; workflow retries are not
implemented.

Failure-status and finalization updates are guarded and idempotent, but use fresh
job IDs when resubmitted. Reattaching forever to a failed metadata job would
prevent recovery after a quota or transient error. If failure recording itself
fails, the manifest stays unresolved and resume must reconcile the original
commit job before publishing a terminal status.

This serializes cooperating data commits at dataset scope and favors correctness
over throughput. It does not provide fair scheduling, automatic deadlock recovery,
or protection from an administrator bypassing the protocol. The finalization
guard has no TTL: silently expiring it could invent order. Resume must resolve
it. If server job metadata has expired before an unresolved commit is recovered,
automatic recovery stops for manual investigation instead of guessing a time.
Bootstrap uses a deterministic seed job; do not concurrently replace/delete the
dataset or bootstrap it outside this implementation.

## Numeric representation and schema evolution

Persist prices and demand as NUMERIC(38,9), timestamps as TIMESTAMP, the Pacific
market date as DATE, counts/ordinals as INT64, and status/identities as STRING.
Values not exactly representable as NUMERIC are rejected at the warehouse
boundary; they are never rounded while retaining an incompatible Phase 1 hash.
This adds a storage-capacity constraint, not a redefinition of Phase 1 values.

Persist observation-key/v1 and observation-content/v1 explicitly, plus
warehouse/v1. A grain, serialization or material-field change requires a new
schema decision and explicit migration or separate tables. Bootstrap validates
existing schemas and never recreates them. No speculative migration framework
is added.

## Deletion, retention and physical layout

Absence from a subsequent retrieval is not a deletion signal. Neither current
CAISO adapter exposes a verified tombstone, so deletion/retraction transitions
are unsupported.

Accepted contents, transitions and manifests have no automatic expiration.
The initial volume is small; a larger system would need an explicit retention
and access policy. Disposable test datasets are separately owned and deleted.

All six tables initially have **no partitioning and no clustering**. Operational
reads select a bounded market date/request or a run ID. Expected tables are too
small to justify tiny daily partitions or measured clustering claims. Revisit
monthly event-time partitions and logical-key clustering using actual scan sizes
before growing beyond the current query cap.

## Verification and limits

Offline tests exercise the actual planner, canonical serialization and client
failure decisions. They do not emulate BigQuery SQL. Opt-in disposable-dataset
tests exercise actual commit/rollback, stale plans, finalization recovery,
A→A, A→B→A, late arrival and idempotent bootstrap. See the warehouse contract
and the [recorded live verification](../verification/phase2.md) for observed results.

No dbt, Flyte, marts, as-of consumer, additional source products, or capture-price
analysis is introduced by this decision.
