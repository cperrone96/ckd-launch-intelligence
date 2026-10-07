# CKD Launch Intelligence

CKD Launch Intelligence is a reproducible, public-data portfolio project for
turning heterogeneous kidney-health evidence into a reviewable analytics product.
It demonstrates survey estimation, leakage-safe model comparison, public-market
and trial-landscape aggregation, synthetic claims-journey engineering, a
scenario-only opportunity framework, a verified offline API, and an evidence-led
dashboard.

The product is educational. It is not a diagnostic system, a clinical decision
tool, a patient-targeting system, a market forecast, or a claim of commercial
experience. No customer, employer, client, or proprietary business data is used.

## Two-minute reviewer path

1. Open the [dashboard review screenshot](.impeccable/review/desktop.png) or run
   the dashboard locally.
2. Read the [metric dictionary](docs/metric-dictionary.md#patient-need) to see
   how denominators, survey weights, and uncertainty stay visible.
3. Review the [patient-finding model card](docs/models/patient-finding-model-card.md)
   for leakage controls and held-out performance.
4. Open the [opportunity framework](docs/methods/opportunity-framework.md) to see
   why incompatible national, provider-state, and study-country data remain
   separate rather than becoming a misleading leaderboard.
5. Inspect [release notes](docs/release-notes.md) and [UAT](docs/uat.md) for the
   engineering evidence behind the result.

The decision story is simple: quantify a documented cross-sectional need signal,
test whether a restricted pre-laboratory feature set carries useful ranking
signal, describe care/therapy/trial context without cross-source joins, and make
uncertainty and evidence strength part of the interface.

## Defensible findings in the committed release

Every finding below is traceable to a committed artifact, source population,
denominator, method, uncertainty statement, and evidence classification.

| Finding | Source, population, period, denominator | Method and uncertainty | Evidence and artifact | Decision implication |
|---|---|---|---|---|
| The primary cross-sectional indicator is 13.9% (95% CI 12.5–15.3%) in the complete-case NHANES domain. | CDC/NCHS NHANES 2017–2018; MEC-examined U.S. civilian, noninstitutionalized adults excluding known pregnancy; denominator 5,016 complete eGFR/UACR records. | 2-year MEC weights; stratified-PSU Taylor linearization; 15 design degrees of freedom. Missing labs are excluded/unknown, never zero. | `public_observed`; `data/processed/patient_need_summary.json`. | Establishes a national/domain-level sizing signal, not a persistent CKD prevalence estimate or patient list. |
| The pre-specified logistic model exceeded the prevalence reference on the held-out analytic sample, with ROC-AUC 0.755 (0.708–0.781) and PR-AUC 0.462 (0.390–0.513). | NHANES 2017–2018; 5,016-person complete-case model cohort; untouched holdout n=993, indicator prevalence 18.63%. | Grouped survey-cluster split; age, sex, and race/ethnicity only; 1,000 cluster bootstrap replicates. Metrics are unweighted and not population performance. | `public_observed`; `data/processed/patient_finding_model_comparison.json`; see model card. | Supports an auditable educational ranking experiment, not diagnosis, care decisions, or targeting. |
| MEPS shows 11.2% proxy-positive prevalence in the documented diabetes-care domain, with 12.25 office visits and USD 16,746 average total expenditure per person-year. | MEPS/AHRQ HC-243 2022; survey-eligible respondents with self-reported diabetes and the DSKIDN53 kidney-problem proxy; denominator 1,063. | Taylor linearization over MEPS strata/PSUs; 95% CIs are retained in the artifact. DSKIDN53 is not confirmed CKD. | `public_observed`; `data/processed/meps_hc243_2022_landscape.json`. | Provides care-context and resource-use context at its own person-year grain, not a provider or patient-journey estimate. |
| The public trial snapshot contains 3,706 registered CKD studies; 419 are marked `RECRUITING` and 214 `NOT_YET_RECRUITING`. | ClinicalTrials.gov API v2 exact CKD condition query; registered-study snapshot; status denominator 3,706. | Fully paginated retrieval and reconciliation; status is registry metadata, not treatment effectiveness or patient demand. | `public_observed`; `data/processed/clinicaltrials_ckd_landscape.json`. | Helps frame evidence activity and study-status review while preserving registry limitations. |
| The opportunity view withholds a composite/state leaderboard. | NHANES/MEPS national survey domains, CMS provider-state aggregates, and ClinicalTrials.gov study-country mentions have incompatible geography and time windows. | Scenario scoring accepts only explicitly compatible scenario inputs; missingness is not zero and sensitivity is reported. | `scenario-only` framework; [opportunity notebook](notebooks/05_opportunity_scenarios.ipynb) uses `fixture_only` illustrative inputs. | Makes the safe business decision explicit: compare source panels first; do not imply patient demand or cross-source geography. |

## Evidence boundary

The release uses four distinct evidence labels:

- `public_observed`: aggregate outputs derived from the documented CDC/NCHS,
  AHRQ/MEPS, CMS Part D, and ClinicalTrials.gov public sources.
- `public_synthetic`: the CMS DE-SynPUF-compatible journey demonstration label.
- `fixture_only`: handcrafted or representative data used to exercise deterministic
  code paths when raw public snapshots are unavailable. It is not official source
  data and cannot overwrite observed artifacts.
- `scenario-only`: caller-supplied illustrative aggregates accepted by the
  opportunity framework only after explicit compatibility, time, geography, and
  coverage checks. It is not observed market evidence.

No patient-level cross-source join is performed. NHANES and MEPS remain national
or survey-domain panels; Part D retains provider-reported state; trials retain
study-country mentions. Synthetic journeys are never presented as representative
of Medicare beneficiaries.

## Reproduce locally

Use Python 3.12 exactly:

```bash
make install
make check
```

The default test path is offline and credential-free. It uses committed fixtures
and verified processed artifacts; CI does not download source rows. To run the
full release gate independently:

```bash
make lint
make typecheck
make test
```

`make check` also validates the local Docker Compose configuration; Docker is not
needed for the offline test, lint, type, or notebook paths used by CI.

The optional PostgreSQL contract remains explicit. Set a local
`CKD_POSTGRES_PASSWORD` and run the Compose service only when exercising that
integration path; the standard release gate does not require it.

### API

```bash
PYTHONPATH=.:src .venv/bin/uvicorn api.main:app --reload
```

The versioned contract is served at `http://127.0.0.1:8000/api/v1`; OpenAPI is
at `/openapi.json`. The API loads only allowlisted, checksum- and manifest-verified
artifacts and fails closed on stale bytes or metadata.

### Dashboard

```bash
PYTHONPATH=.:src .venv/bin/python -m dashboard.app
```

Open `http://127.0.0.1:8050`. The dashboard consumes versioned API response
models and repeats evidence metadata, source population, denominator, uncertainty,
and limitations on each page. Committed review captures are in
`.impeccable/review/`; the [mobile capture](.impeccable/review/mobile.png) shows
the responsive path and [synthetic capture](.impeccable/review/synthetic-desktop.png)
shows the explicit CMS synthetic boundary. The current dashboard review also
discloses partial API windows, renders real empty/error/loading states, and loads
only the data required by each route.

### Notebook smoke run

The notebooks are deterministic demonstrations backed by committed inputs and
are safe to execute without credentials. A CI smoke run executes them into a
temporary output directory so committed notebooks and artifacts are not rewritten:

```bash
mkdir -p /tmp/ckd-notebooks
for notebook in notebooks/*.ipynb; do
  PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" .venv/bin/python -m jupyter nbconvert --to notebook --execute "$notebook" \
    --output-dir /tmp/ckd-notebooks --ExecutePreprocessor.timeout=120
done
```

## Technical deep dive

- [Data lineage](docs/lineage.md) traces source → validation → artifact → API/dashboard.
- [Data dictionary](docs/data-dictionary.md) defines grains, fields, and identifier rules.
- [Metric dictionary](docs/metric-dictionary.md) defines denominators, estimates,
  uncertainty, and interpretation boundaries.
- [UAT and release gate](docs/uat.md) records contract, accessibility, and failure-state checks.
- [Risk register](docs/risk-register.md) records scientific, privacy, and product risks.
- [Source contracts](docs/sources/) document release URLs and ingestion rules.
- [Methods](docs/methods/) document scenario ranking and synthetic journeys.

## Repository map

```text
api/                 FastAPI contract and verified artifact service
dashboard/           Dash evidence workbench
data/manifests/      Dated source/artifact/fixture metadata
data/processed/      Committed aggregate artifacts and SHA-256 sidecars
notebooks/           Reproducible analysis and scenario walkthroughs
src/ckd_intelligence/ analysis, ingestion, modeling, SQL, journeys
tests/               Unit, contract, provenance, adversarial, and SQL tests
docs/                Lineage, dictionaries, UAT, risks, and release notes
```
