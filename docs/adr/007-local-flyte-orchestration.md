# ADR 007: Bounded local Flyte orchestration

Status: accepted for the implementation on the Phase 4 branch. Native local
execution and controlled BigQuery/dbt recovery verification passed. The real
two-day backfill stopped at the daily quota; its completion and rerun remain
pending. This does not mark Phase 4 complete.

## Context

One bounded CAISO request did not need an orchestrator. Multiple dates create
real dependency and recovery requirements: preserve successful days after a
failure, resume uncertain submissions, and run dbt only when ingestion has
stopped. Domain normalization, durable revision decisions and analytical SQL
already have separate owners in ADRs 001–006.

Phase 2 has a dataset-wide sequencing/finalization guard. Concurrent source
tasks ending in writes would compete for that guard. More task parallelism
would not increase its commit throughput.

## Decision

Use stable `flyte==2.8.1` in an isolated repository-local environment. The
[release metadata](https://pypi.org/project/flyte/2.8.1/) declares Python >=3.10;
installation and native Windows local execution were verified on Python 3.12.14.
This is the current Flyte 2 SDK, using `TaskEnvironment`, `@env.task`, typed
dataclass inputs/outputs and tasks awaiting other tasks. It is not the legacy
flytekit workflow DSL.

The [official local execution guide](https://www.union.ai/docs/v2/flyte/user-guide/get-started/run-modes/running-locally/)
documents `flyte run --local file.py task`. The
[retry guide](https://www.union.ai/docs/v2/flyte/user-guide/tasks/task-configuration/retries-and-timeouts/)
documents task-level `RetryStrategy`, `Backoff` and `NonRecoverableError`.
The installed SDK's native local retry path was also executed, rather than
assuming the remote behavior applies locally.

The SDK brings orchestration dependencies including protobuf, Pydantic, HTTP
clients and serializers. They belong in `artifacts/flyte-venv`, not the core
application's runtime dependency list. The project does not use Pydantic for
its own domain or input models. dbt retains its separately verified environment.

The graph has four task boundaries:

1. `backfill` validates the complete input and awaits serial bounded requests.
2. `ingest_day` calls the existing `ingest` and `BigQueryWarehouse`; one task
   handles either of the two existing products. Separate identical LMP/load
   task wrappers would add no behavior.
3. `build_analytics` invokes the existing capped dbt toolchain.
4. `verify_analytics` checks requested fact slices for uniqueness, successful
   originating runs and at least the accepted row count.

Date expansion, UUID derivation, error classification and report formatting
remain ordinary Python. No DataFrames or observation batches cross task
boundaries. All tasks disable Flyte caching: live source contents and external
warehouse state are not pure functions of a date parameter.

## Recovery and ordering

An explicit backfill UUID namespaces UUIDv5 run IDs derived from the existing
bounded-request identity. The same date/product/hub retains its run ID during
task retry and process restart. BigQuery manifests remain the durable truth;
there is no second orchestration database.

A new backfill UUID means new retrieval attempts. Reusing a UUID resumes:
SUCCEEDED requests are reconciled without retrieval; STARTED/uncertain requests
follow Phase 2 recovery. FAILED is terminal, including transient source errors
already recorded as FAILED by Phase 2. A new retrieval after a terminal failure
requires a new backfill UUID. Successful earlier dates can be fetched again
under that new UUID; existing content/transition deduplication still applies.

Only selected transient transport/service errors with an absent or STARTED
manifest are eligible for one Flyte retry, with the same run ID and a two-second
delay. A failed initial manifest read is also safe to retry before any new write
is attempted. Uncertain commits, unknown manifest status, COMMITTED, FAILED,
quota/authentication failures and schema/validation errors stop the task.
Explicit same-ID resumption delegates uncertain submission reconciliation to
Phase 2; it never invents a fresh competing attempt.

The workflow is fail-fast. Accepted days remain durable, later days do not
start, and dbt does not run. dbt and verification have zero automatic retries.
dbt starts only after all required ingestions succeed. Quiescence across
independent processes still requires an operator to run only one cooperating
backfill and one dbt writer per target; no distributed workflow lock is claimed.

## Alternatives

- **Plain Python loop:** the smallest dependency footprint and adequate for one
  command. As dependent backfills grow, task attempts, typed boundaries and
  execution reporting would increasingly be custom orchestration code.
- **Cron:** useful for starting a command on a schedule; does not supply this
  dependency graph or bounded backfill recovery. No scheduler is needed here.
- **Airflow:** a reasonable, established choice for data pipelines. It can
  handle this workload well. Its deployment and operational model would be a
  larger addition than the local path selected for this repository.
- **Prefect or Dagster:** also viable orchestration choices. No comparative
  reliability or performance benchmark was performed.
- **Remote Flyte:** potentially useful later for isolated workers and durable
  control-plane execution history. It is unnecessary for the current manually
  invoked workload and would add infrastructure.

Flyte's typed Python task model fits the established Python ingestion boundary.
This phase explores an orchestration execution model after the core data
contracts exist; it does not move those contracts into a framework.

## Consequences and limits

Seven inclusive completed Pacific days and concurrency one are enforced.
Source courtesy, cost control and recoverability justify these bounds. They
are not a guarantee that a seven-day run fits the daily cloud quota.

Native Windows needs process-local `PYTHONUTF8=1` for Flyte's Unicode CLI
output. No machine-wide setting changes, Docker, WSL, Devbox, cluster or
continuously running resource is required. SDK temporary task metadata is
local; BigQuery manifests, not that temporary directory, drive recovery.

Local task execution is in process. The SDK's remote timeout settings are not
claimed as hard local cancellation guarantees. Existing warehouse calls have
bounded waits; dbt has a 900-second subprocess timeout. Some upstream library
calls may require operator interruption. After interruption or dbt timeout,
inspect in-flight cloud jobs before another writer starts. A local process
exit does not cancel a submitted BigQuery job.

The controlled native persistence/dbt equivalence suite passed on 2026-09-21.
The real CAISO backfill/rerun remains a merge gate. For that verification only,
the user authorized a temporary daily quota increase from 5 to 12 GiB. After
the live quota failure it was restored and verified at 5 GiB; the per-query
caps and budget alert were unchanged. This operational exception does not change
the normal safeguards or the architecture. See the
[contract](../contracts/orchestration.md) and [verification record](../verification/phase4.md).
