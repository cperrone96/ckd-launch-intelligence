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

## Verification

- Python 3.12 bytecode compilation passed for `src` and `tests`.
- Notebook JSON validation passed.
- `git diff --check` passed.
- Full pytest/Ruff/mypy/notebook execution could not run in this isolated worktree
  because the environment has no cached dependencies and sandbox DNS blocked package
  installation. No source or primary worktree changes were made.

## Commit

The implementation is committed on `feature/ckd-task6` after the local static checks.
