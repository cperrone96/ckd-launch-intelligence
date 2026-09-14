# Task 6 implementation report

## Scope

Implemented the CKD plan's synthetic claims journey and time-to-event demonstration
on branch `feature/ckd-task6`, based on approved Task 4 commit `8d68c0e`.

## Delivered

- `src/ckd_intelligence/journeys/synpuf.py`
  - deterministic index/target/follow-up event construction;
  - stable date/through-date/claim-ID ordering;
  - explicit 2008–2010 observation window, 365-day follow-up, 90-day inclusive
    persistence gap, target/no-target censoring, and exclusion rules;
  - fail-closed `public_synthetic` evidence boundary and no cross-source join.
- `src/ckd_intelligence/statistics/time_to_event.py`
  - validated Kaplan–Meier risk sets, events, censor counts, Greenwood variance,
    clipped normal confidence limits, and median survival.
- `sql/marts/mart_synpuf_journeys.sql`
  - DuckDB/PostgreSQL-oriented synthetic-only mart under `analytics_synthetic`.
- `notebooks/04_synthetic_journeys.ipynb`
  - offline fixture execution with repeated CMS synthetic/non-representative labels.
- `docs/methods/synthetic-journeys.md`
  - explicit method contract and limitations.
- `data/fixtures/synpuf_journeys.csv` and its manifest
  - deterministic offline fixture; SHA-256
    `b5113203989dc8c78e5669cdce7fcc6505acbae4317b0e5542267028f8011fe4`.
- `tests/journeys/test_synpuf.py`
  - chronology, tie-break, synthetic-only namespace, boundary persistence, censoring,
    and hand-calculated Kaplan–Meier tests.

## Fix round 1 corrections

- Follow-up is bounded before target/persistence detection; post-censor claims are
  excluded from journey facts and service-through dates are validated against both
  the release and the follow-up boundary.
- Evidence and source release are fail-closed: missing, null, observed, or mixed
  labels are rejected rather than invented, dropped, or relabeled. Schema-valid
  empty input returns typed empty event, summary, and survival outputs.
- SQL now persists event-grain journeys, beneficiary summaries, Kaplan–Meier
  survival/risk tables, and median-survival metadata under `analytics_synthetic`,
  with Python/SQL reconciliation contracts.
- Python and SQL use the same first-target tie-break and event chronology.
- The handcrafted fixture is explicitly `fixture_only` and schema-compatible; it is
  not represented as an official CMS row extract. CMS documentation is listed as
  provenance for the release contract only.
- Notebook cells have stable IDs and repeat the synthetic/non-representative boundary.

## Verification

- Targeted tests: **23 passed** using the available Anaconda environment.
- Full tests excluding the pre-existing DuckDB-dependent SQL test: **142 passed**;
  the complete suite is blocked only by missing `duckdb` in the available runtime.
- Notebook code executed twice manually with deterministic outputs. `nbconvert`
  kernel execution was blocked by the sandbox's local socket restriction.
- Python 3.12 bytecode compilation passed for `src` and `tests`.
- Notebook JSON validation passed.
- `git diff --check` passed.
- Ruff, strict mypy, and live DuckDB/PostgreSQL execution require the project's
  dependency-complete Python 3.12 environment, which was not available in this
  isolated shell; no source or primary worktree changes were made.

## Commit

The implementation is committed on `feature/ckd-task6` after the local static checks.
