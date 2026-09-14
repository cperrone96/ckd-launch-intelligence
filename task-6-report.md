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

## Fix round 2 corrections

- Replaced text-only SQL assertions with executable DuckDB reconciliation tests for
  standard, all-censored, empty, adversarial-tie, spanning-claim, and spanning-only
  scenarios.
  Each scenario is rerun in the same session and a fresh DuckDB session. PostgreSQL
  coverage uses the same scenarios when `CKD_TEST_POSTGRES_URL` and `psycopg` are
  available, with an explicit unavailable-service skip.
- SQL and Python now share category event order `index=0`, `pre_target=1`,
  `target=2`, `follow_up=3`. Only the first qualifying CKD claim at the inclusive
  persistence boundary receives `is_persistence_event=true`, including same-day ties.
- Eligibility and service-through filtering occur before final index/follow-up
  calculation. A spanning early claim is removed and the index is recomputed from
  the remaining valid claim; spanning-only beneficiaries produce typed empty output.
- SQL drops all temporary and final output tables, including metadata, so same- and
  fresh-session reruns are safe.
- Strict typing was made explicit around pandas' dynamically typed row operations.
  The existing notebook import-format issue was also corrected so the repository
  lint gate is clean.

## Verification

- Primary Python 3.12 environment: `/Users/christinaperrone/Documents/Claude/Projects/Data Design Dynamics/portfolio-projects/ckd-launch-intelligence/.venv/bin/python`.
- Full test command (`PYTHONPATH=/private/tmp/ckd-task6-worktree/src python -m pytest -q`):
  **145 passed, 1 skipped**. The only skip is PostgreSQL because `psycopg` is not
  installed/configured in this environment.
- Executable SQL command for DuckDB: **1 passed**. It reconciled all six scenarios,
  including same-session and fresh-session reruns. PostgreSQL test is intentionally
  skipped only because its optional driver/database is unavailable.
- `python -m ruff check .`: **All checks passed**.
- `python -m mypy`: **Success: no issues found in 40 source files**.
- Notebook code executed twice manually with deterministic outputs. Standard
  `nbconvert --execute` was also attempted but the sandbox disallows Jupyter's local
  kernel socket bind; the notebook's code cells themselves passed both runs.
- Python 3.12 bytecode compilation passed for `src` and `tests`.
- Notebook JSON validation passed.
- `git diff --check` passed.
- The primary dependency-complete Python 3.12 environment was used for pytest,
  DuckDB, Ruff, mypy, and manual notebook execution. PostgreSQL remained skipped
  only because `psycopg` and a configured PostgreSQL service were unavailable.
  Standard `nbconvert --execute` was blocked by the sandbox's local kernel socket
  policy; the notebook code cells passed two deterministic manual runs.

## Commit

The implementation is committed on `feature/ckd-task6` after the local static checks.
