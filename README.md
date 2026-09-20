# power-market-data-platform

Revision-aware data platform for ingesting, validating, modeling, and analyzing
U.S. wholesale power-market data.

Public market data is not necessarily final when first retrieved. An interval
can arrive late, be corrected, or appear differently in a later download.
Timestamps can also hide local-time ambiguity or incompatible interval labels.

The engineering thesis is that an analytical result should be traceable to its
source observations and to what the system knew at the time. That requires
explicit event and knowledge times, source provenance, preserved material
revisions, idempotent reruns, and visible data-quality failures.

## Current status

**Phase 3 implementation: awaiting quota-limited BigQuery verification.** The existing CAISO adapter
fetches hourly day-ahead LMP at NP15/SP15/ZP26 and five-minute system load.
Normalized observations can now be persisted with ingestion manifests, distinct
source contents, ordered state transitions and explicit knowledge times.

A repeated A→A creates another run, not another revision. A→B→A preserves two
unique contents and three transitions, including the later return to A.
BigQuery transactions and a native sequencing guard prevent partial successful
batches and reject stale cooperating writers. See the
[warehouse contract](docs/contracts/warehouse.md) and [ADR 005](docs/adr/005-bigquery-persistence.md)
for the exact commit, recovery, clock and concurrency limitations.

The adapter uses gridstatus 0.36.0. Its fall-back load parser cannot reliably
distinguish repeated local hours, so those load dates remain unsupported.
Phase 1 [source](docs/sources/caiso.md) and [domain/time](docs/contracts/observations.md)
contracts are unchanged. BigQuery uses native google-cloud-bigquery 3.45.2.

Offline tests cover source normalization, identities, DST, warehouse planning,
client failure behavior and CLI commands. Separate opt-in tests use disposable
BigQuery datasets. [Recorded verification](docs/verification/phase2.md) includes
real-day counts, an unchanged rerun, recovery and cost metadata. Windows/Linux CI
remains offline after dependency installation.
The standalone dbt project now contains accepted revision histories, incremental
current LMP/load facts and daily-price/ingestion summaries. Offline SQL tests and
a credential-free project parse pass. The controlled live build was blocked by
the existing daily BigQuery quota, so Phase 3 is **not complete or merged** and
no live analytical model counts are claimed. See the
[analytics contract](docs/contracts/analytics.md),
[toolchain decision](docs/adr/006-dbt-analytical-state.md) and
[Phase 3 verification](docs/verification/phase3.md).
There is no Flyte, automated multi-date backfill, full Data Quality Observatory,
as-of consumer analysis or capture-price analysis.

## Architecture and planned layers

```mermaid
flowchart LR
    C["CAISO public data"] --> P["Python: implemented retrieval, normalization, validation"]
    P --> B["BigQuery: implemented contents, transitions, runs"]
    B --> D["dbt: implemented models; live verification pending"]
    D --> A["Planned quality, as-of and capture-price analysis"]
    F["Planned Flyte: dependencies, retries, backfills"] -. orchestrates .-> P
    F -. orchestrates .-> D
```

A corrected price for the same interval and location represents a changed
observation, not a new market interval. Overwriting it prevents an earlier result
from being explained; appending every unchanged download creates duplicates.
The persistence contract separates logical identity from content
versions and their observed history, including a value that changes and later
returns to its original state.

Canonical analytical time is UTC; the CLI also renders Pacific offsets for
interpretation. Raw source files are not retained. Historical backfills
will not be presented as evidence of what this system knew before it collected the data.

See the [project brief](PROJECT_BRIEF.md), [phase completion criteria](PLANS.md),
and [architecture decisions](docs/adr/).

## Planned phases

| Phase | Focus |
| --- | --- |
| 0 | Repository/tooling foundation — complete |
| 1 | CAISO source adapters and normalization — complete within documented limits |
| 2 | Revision-aware BigQuery persistence — complete within documented limits |
| 3 | dbt analytical warehouse — implemented, live verification blocked; incomplete |
| 4 | Flyte orchestration and backfills |
| 5 | Data-quality/as-of/capture-price analytics |
| 6 | Public portfolio/reproducibility audit |

## Repository structure

```text
.github/workflows/ci.yml     Offline validation after dependency installation
docs/adr/                   Architecture and Python compatibility decisions
src/power_market_data/      CAISO adapter, domain records, warehouse boundary, CLI
docs/sources/               Verified access methods and provenance limitations
docs/contracts/            Observation and warehouse grains, clocks, identities, recovery
tests/fixtures/             Small synthetic source-shape fixtures
tests/                     Offline source, warehouse and package tests
integration_tests/         Explicitly opted-in raw-persistence BigQuery tests
dbt/                       SQL models, sources, contracts, unit/data tests, profile example
dbt_checks/                Shared synthetic dbt contract fixtures
dbt_integration_tests/     Opt-in native dbt builds in disposable datasets
AGENTS.md                   Engineering contract
PROJECT_BRIEF.md            Motivation and scope
PLANS.md                    Deliverables and completion criteria
pyproject.toml              Packaging, development dependencies and checks
.env.example                Non-secret warehouse configuration names
```

## Local setup

Use Python 3.12. The [compatibility decision](docs/adr/004-python-tooling.md)
records the initial future-stack check and its limitations. Runtime dependencies
are gridstatus==0.36.0, google-cloud-bigquery==3.45.2 and Windows timezone data.
The development extra pins direct validation tools. No ORM, orchestration
framework or transitive lockfile is added.

From the repository root, on Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

If the Python launcher is absent in a Codex desktop environment, this is the
bundled-interpreter fallback used during initial setup:

```powershell
$python312 = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $python312 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The bundle path is specific to that environment; other machines can use their
installed Python 3.12 executable. No environment activation or PowerShell
execution-policy change is required.

On Linux/macOS:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Installation downloads packages. Validation thereafter requires no CAISO access,
cloud credentials, Docker, or WSL. Package builds may download their isolated
build dependencies. Configuration reads process environment variables; no dotenv
loader is used.
.env.example lists non-secret names, and local .env files are ignored.

## Live source inspection

After installation, from Windows PowerShell:

```powershell
.\.venv\Scripts\power-market-data.exe caiso lmp --date 2026-08-01 --location TH_NP15_GEN-APND --limit 2
.\.venv\Scripts\power-market-data.exe caiso load --date 2026-08-01 --limit 2
```

On Linux/macOS, use .venv/bin/power-market-data. Alternatively run the same
arguments with the environment interpreter and -m power_market_data.cli.
--limit bounds printed rows; each request fetches one historical Pacific day.
Output includes UTC intervals, explicit Pacific offsets, decimal strings, source
metadata and SHA-256 identities. No cloud write or local data file is produced.
Errors return nonzero exit status. The installed CLI succeeded for both examples
on 2026-09-20 (24 LMP rows and 288 load rows); this does not guarantee other dates.

## Persist a bounded source request

Authenticate using user Application Default Credentials and configure a dedicated
billing-enabled Google Cloud project. BigQuery's no-billing sandbox does not
support this DML contract. Credentials must stay outside Git and .env.

```powershell
$env:GCP_PROJECT_ID = "your-dedicated-project-id"
$env:BQ_LOCATION = "US"
$env:BQ_RAW_DATASET = "power_market_raw"
.\.venv\Scripts\power-market-data.exe warehouse bootstrap
.\.venv\Scripts\power-market-data.exe ingest caiso lmp --date 2026-08-01 --location TH_NP15_GEN-APND
.\.venv\Scripts\power-market-data.exe warehouse inspect lmp --date 2026-08-01 --location TH_NP15_GEN-APND
```

The CLI prints the run ID before source access. A repeated command with a new ID
is a new attempt; an unchanged source state adds no content or transition.
warehouse resume --run-id ID reconciles a submitted commit without fetching again.
A terminal failure requires a new attempt. Bootstrap never recreates existing data.

Python queries have a 100 MiB maximum-bytes-billed ceiling. This is a bounded
portfolio workload, not a promise of zero cost; budget alerts are not spending
caps. See [costs, setup, integration tests and cleanup](docs/contracts/warehouse.md).

## dbt transformations

The selected stable toolchain is dbt-core 1.12.5 plus dbt-bigquery 1.12.1 in a
separate repository-local environment. The recommended free v2 distribution was
evaluated first; observed job metadata did not carry its configured query cap,
so the [ADR](docs/adr/006-dbt-analytical-state.md) records this compatibility exception.
Follow the [PowerShell setup/build/docs commands](docs/contracts/analytics.md#local-tooling-and-execution).
The target is a separate, configurable power_market_analytics dataset in US.
Never point it at raw storage. Ordinary CI does not execute warehouse queries.

## Validation

Windows PowerShell, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -I -c "import power_market_data; print(power_market_data.__version__)"
.\.venv\Scripts\python.exe -m build
```

On Linux/macOS, use .venv/bin/python in place of .\.venv\Scripts\python.exe.
CI also replaces the editable installation with the built wheel and reruns the
import and test. This checks that installation works independently of the
repository's working directory. Ordinary tests do not call external services.

## Limitations

Validation applies to rows returned by gridstatus, which may already have dropped
missing rows or pivoted duplicate components. Full-day completeness is not
asserted. Fall-back load dates are rejected; the source notes describe other
schema, transport and usage limitations. Fixtures are synthetic and ordinary
tests make no source or cloud calls. Durable contents and observed transitions
exist, but no raw response archive or verified source-deletion signal exists.
Writers must follow the documented transaction protocol; finalization can require
explicit recovery. dbt SQL exists, but live materialization, revision/full-refresh
verification and real-data analytics remain pending quota availability. No Flyte,
automated backfills, final Data Quality Observatory, as-of consumer query or
capture-price analysis is implemented.
Direct development tools are pinned; transitive dependencies are not fully locked.

Trading strategy, automated bidding, dispatch optimization, production P&L,
proprietary forecasting, and battery optimization are outside scope.
