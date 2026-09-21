# ADR 006 — dbt transformations over accepted transition history

- Date: 2026-09-20
- Status: Accepted; native BigQuery execution verified on 2026-09-21.
- Scope: Phase 3. ADRs 001–005 and raw schemas remain unchanged.

## Context

Python owns external access, normalization and source-aware validation. BigQuery
already preserves contents, transitions and run manifests. These tables require
relational joins, eligibility rules, current-state selection and tests before
they are useful as facts. Python could execute that SQL, but dbt supplies its
dependency graph, source references, materializations, data tests and lineage
without extending the ingestion service into a transformation runner.

## Tooling decision

Use stable **dbt-core==1.12.5** with **dbt-bigquery==1.12.1**, installed with pip
in the separate ignored artifacts/dbt-core-venv environment on Python 3.12.14.
These versions support native Windows and Python 3.12 without Docker, WSL or
a paid dbt account. The adapter is separate; its transitive dependencies stay
outside the application runtime environment.

Official documentation was checked on 2026-09-20 after dbt v2 reached GA.
The recommended free standard distribution, dbt==2.0.6, was installed and
evaluated first. Its bundled native BigQuery integration parsed this project and
authenticated successfully. However, the submitted BigQuery test job did **not**
contain maximumBytesBilled even though debug displayed the configured 104857600.
That observed cost-control incompatibility is the concrete reason to choose
the traditional stable Python toolchain here. We do not infer that every v2
installation behaves identically or dismiss GA based on old preview documentation.

The evaluated job was adbc-71926d60-e58a-482c-8703-b61085608905 in US.
Its BigQuery configuration omitted the cap and its execution was rejected by
the unchanged daily custom quota. No further v2 queries were submitted after
inspection. The selected Python adapter passed both its offline submission check
and native verification on 2026-09-21: all 330 completion-run query jobs carried
maximumBytesBilled=104857600. See the [verification record](../verification/phase3.md)
for the controlled suite, real builds and unchanged safeguards.

Sources:
[official installation](https://docs.getdbt.com/docs/local/install-dbt),
[GA announcement](https://www.getdbt.com/blog/dbt-summit-2026-product-announcements),
[dbt-core package](https://pypi.org/project/dbt-core/1.12.5/),
[dbt-bigquery package](https://pypi.org/project/dbt-bigquery/1.12.1/).

## Model decision

Five raw sources feed thin staging views. Content eligibility checks first_run_id;
transition eligibility checks run_id. Both must originate in SUCCEEDED manifests.
The manifests staging/health models deliberately retain other statuses.

Two intermediate views preserve every accepted transition and its content.
Two incremental facts resolve current state directly from those views, avoiding
a redundant second pair of current-state views. Their grain is one logical key,
selected by descending per-key ordinal, commit_sequence and transition_id.
Ordering is deterministic and relies on the raw writer's documented per-key
and global ordering. Tie-breakers do not repair malformed ordering introduced
by manual edits outside that protocol.

| Transition | Referenced content | Content first known | Current state |
| --- | --- | --- | --- |
| 1 | A | t1 | A |
| 2 | B | t2 | B |
| 3 | A | still t1 | A, known again at t3 |

Selecting max(contents.first_seen_at) would incorrectly select B at t3.
Appending each retrieval as a fact would duplicate A on an unchanged rerun.
Neither is acceptable.

## Incremental decision and assumptions

Both facts use native BigQuery merge, unique_key=logical_key. Candidate history
has commit_sequence greater than the maximum stored in the corresponding fact.
The newest candidate per logical key updates that fact row; new keys insert.
No event-time cutoff is used. An old event first accepted at a new sequence is
eligible. A→A adds no transition and needs no fact update.

This watermark depends on ADR 005's singleton sequencing/finalization guard:
a higher data commit cannot finish before an earlier unfinished commit finalizes.
Successful history is append-only through the approved writer. Product-specific
gaps and unchanged runs are harmless because only actual transitions advance a
fact's watermark. There are no tombstones to delete current rows.

Full refresh resolves all eligible history without the incremental predicate.
It should equal the incrementally maintained result over the same stable input;
the opt-in test compares every fact field. Schema changes fail explicitly.
Changing grain, eligibility or transformation semantics requires a reviewed
full refresh/migration, not merely rerunning incrementally.

Run one dbt writer per target dataset. dbt does not make the whole model graph a
single atomic snapshot. A source commit during a build may make downstream
reconciliation fail; quiesce ingestion and rerun. Manual edits/deletions of accepted
raw history or fact watermarks invalidate these assumptions. No generic migration,
locking service, scheduler or as-of consumer is introduced.

## Physical design and tests

Staging, histories and two small summaries are views. Facts are unpartitioned,
unclustered tables: current data is tiny, and filtering only event partitions
would miss old-event revisions. No performance improvement has been measured.
Future volume should motivate a measured physical-design change.

Native dbt data tests validate key/grain, lineage, eligibility, source values and
UTC/Pacific interval contracts. GA native unit tests use dictionary fixtures;
they run in BigQuery. The experimental local unit-test engine is not used.
Offline CI executes the portable SELECT subset with SQLite plus Jinja and parses
the full dbt project with credentials unavailable. SQLite is not a substitute
for BigQuery types, actual MERGE or the formal cloud definition of done.

[Unit-test reference](https://docs.getdbt.com/docs/build/unit-tests).
