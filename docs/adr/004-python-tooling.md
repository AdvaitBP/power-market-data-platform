# ADR 004: Python 3.12 and a small Phase 0 toolchain

- Status: Accepted
- Date: 2026-09-20

## Compatibility evidence

The latest non-yanked stable releases returned by PyPI on this date were checked
together using CPython 3.12.14 on Windows x64:

| Planned dependency | Stable release checked | Published Requires-Python |
| --- | --- | --- |
| [gridstatus](https://pypi.org/project/gridstatus/0.36.0/) | 0.36.0 | >=3.10,<3.15 |
| [google-cloud-bigquery](https://pypi.org/project/google-cloud-bigquery/3.45.2/) | 3.45.2 | >=3.10 |
| [dbt-core](https://pypi.org/project/dbt-core/1.12.5/) | 1.12.5 | >=3.10 |
| [dbt-bigquery](https://pypi.org/project/dbt-bigquery/1.12.1/) | 1.12.1 | >=3.10.0 |
| [flyte](https://pypi.org/project/flyte/2.8.1/) | 2.8.1 | >=3.10 |

The current stable Flyte SDK is the Flyte 2 `flyte` package. Its
[maintainer description](https://pypi.org/project/flyte/) identifies Flyte 2 as
generally available. No preview was selected to obtain Python support.
gridstatus's description recommends Python 3.11+, also satisfied by 3.12.

This joint resolver check succeeded, without installing the future stack:

```powershell
.\.venv\Scripts\python.exe -m pip install --dry-run --ignore-installed --disable-pip-version-check --report artifacts/compatibility/python312-windows.json gridstatus==0.36.0 google-cloud-bigquery==3.45.2 dbt-core==1.12.5 dbt-bigquery==1.12.1 flyte==2.8.1
```

Create the report directory before reproducing this optional check. The report
and download logs are local artifacts, not committed inputs or a dependency lock.
The command may download distribution metadata and archives, but does not
install those packages. No prerelease flag was used.

## Decision

Use Python 3.12, with `requires-python = ">=3.12,<3.13"`, a `.python-version`
file, and CI on 3.12 for Windows and Linux. This narrow declaration reflects the
minor version actually validated, not a claim that later Python versions fail.
There was no dependency-resolution reason to downgrade to 3.11.

Use standard `venv` and `pip` to keep setup explicit. Invoke the virtual
environment interpreter directly; activation and global PATH/policy changes are
unnecessary. Hatchling builds the src-layout package. Phase 0 has no runtime
dependencies. The development extra pins pytest, Ruff, mypy and build; strict
mypy checks only project code/tests, with no suppressions or plugin layer.
The build backend is pinned too.

## Limits and follow-up

A successful resolver run establishes compatible declared constraints for this
Windows interpreter. It does not establish source API correctness, runtime
integration, Flyte server compatibility, or deployment support on every OS.
The future stack was not installed or executed. Its Linux integration must be
verified before deployment; Phase 0 CI validates only the foundation there.

The checked future versions are evidence, not requirements for later phases.
Re-evaluate them when introducing each layer, especially the dbt distribution
choice: [dbt-core's current maintainer notice](https://pypi.org/project/dbt-core/)
describes a transition toward v2 distributions. This project does not migrate or
implement dbt in Phase 0.

Transitive development dependencies are not locked yet. Record a full resolution
when executable data pipelines require reproducible dependency environments;
do not claim bit-for-bit environment reproducibility from direct pins alone.
