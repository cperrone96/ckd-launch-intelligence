# UAT and release gate

Release review date: 2026-09-11. The review covers the API and dashboard commits
through the reviewed current HEAD `df2a964` (`fix(dashboard): restore disclosure
affordances`).

## Automated gate

The offline gate is:

```bash
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest -q
```

The current result is **257 passed, 2 skipped**. The two skips are explicit
PostgreSQL integration contracts because no PostgreSQL URL is configured. Ruff is
clean and strict mypy reports no issues across 72 source files. The test suite uses
committed fixtures and artifacts; it does not call source websites.

## Contract and provenance checks

- Manifest artifact path, SHA-256 sidecar, computed digest, and evidence metadata
  must agree; stale or malformed content fails closed.
- Artifact JSON must be an object with the required source-specific collection and
  member fields. Invalid members, missing trial dimension fields, traversal, and
  wrong manifest namespaces return an integrity error rather than an empty result.
- API responses are strict typed models with `additionalProperties: false` in the
  generated OpenAPI schema.
- Synthetic journeys validate the fixture manifest and checksum before reading the
  CSV. The fixture remains `public_synthetic`/`fixture_only`, and its limitation is
  rendered beside the result.
- API responses do not serialize beneficiary, provider, NCT, claim, or other raw row
  identifiers.

## Dashboard review

Each route was rendered against the versioned API client and checked for:

- evidence type, population, grain, denominator, uncertainty, artifact provenance,
  and limitations;
- explicit loading, empty, and error components;
- trial evidence from ClinicalTrials.gov rather than shared NHANES evidence;
- shown/total counts and a partial-window disclosure for paginated tables;
- visible mobile navigation, 44px touch targets, horizontal-table affordance, and
  text alternatives;
- a non-diagnostic patient-finding label and the CMS synthetic-data boundary.

Committed review captures are `desktop.png`, `mobile.png`,
`patient-finding-mobile.png`, and `synthetic-desktop.png` under
`.impeccable/review/`. The Impeccable detector was run once during design review;
the final bounded visual correction pass refreshed these captures without rerunning
the detector.

## Manual acceptance path

1. Start the API from the repository root and confirm `/api/v1/health` reports the
   committed repository/evidence boundary.
2. Start the dashboard and open `/`, `/patient-need`, `/patient-finding`,
   `/care-and-prescribing`, `/trials`, `/opportunity`, and `/synthetic-journeys`.
3. Confirm that every page identifies its source population and limitations, and
   that synthetic content is not described as Medicare beneficiary evidence.
4. Tamper with a copied artifact or manifest in a temporary test directory and
   confirm the API returns `artifact_integrity_error` with HTTP 503.
5. Run the notebook smoke command from the README into a temporary output folder;
   do not overwrite committed notebooks or observed artifacts.
