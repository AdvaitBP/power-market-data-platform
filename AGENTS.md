# Engineering contract

Read README.md, PROJECT_BRIEF.md, PLANS.md, and all existing docs/adr/*.md before
changing architecture. Follow the current phase's completion criteria; do not
silently start a later phase. Record a new or superseding ADR when a decision
changes.

## Public claims and scope

- Describe implemented behavior accurately. Mark planned components as planned.
  Do not inflate reliability, performance, coverage, or deployment claims.
- Keep documentation technically grounded and free of employer-specific or
  recruiting references.
- Prefer explicit code and small interfaces. Add abstractions and dependencies
  only for demonstrated needs; avoid speculative frameworks.
- Never commit secrets, tokens, cloud credentials, .env, virtual environments, or
  generated datasets. Keep examples credential-free and fixtures small.

## Data contracts for future phases

- Use timezone-aware UTC as the canonical analytical timestamp for keys and
  joins. Preserve source/local timestamps and timezone context when useful.
  Reject or explicitly resolve DST ambiguity; never silently guess an offset.
- State the grain, units, interval boundaries, dimensions, and null semantics
  for every important dataset before implementing its schema.
- Derive deterministic logical keys from the documented grain. Separate logical
  observation identity from source-content/version identity.
- Make ingestion idempotent: exact reruns must not duplicate observations or
  rewrite their first-known times.
- Preserve materially changed source observations and provenance. Never blindly
  overwrite previous values. Distinguish event time from ingestion/knowledge time
  and source publication time; do not claim knowledge before this system had it.
- Keep ingestion, orchestration, storage, and transformation separate according
  to the ADRs. Orchestration must call ingestion code rather than own its rules.

## Development and validation

- Verify the repository root, branch, remote, and working tree before changes.
  Preserve unexpected user edits. Work in the actual checkout.
- Use Python 3.12 and a repository-local .venv. Invoke its interpreter directly;
  shell activation, PATH edits, and machine-wide policy changes are unnecessary.
- Add or update tests for changed behavior. Prefer offline unit tests with local
  fixtures; keep any future credentialed integration tests separately opt-in.
- Before claiming completion, run Ruff lint and format checks, mypy, pytest,
  package build, and installed-package import as appropriate to the change.
  Use the commands in README.md. Report failures and unrun checks honestly.
- Review the complete diff and untracked files, check that ignored artifacts are
  untracked, and ensure documentation matches the implementation before commit.
- Do not bypass failing CI. Inspect PR changes and automated checks before merge.
