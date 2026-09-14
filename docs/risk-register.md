# Risk register

| Risk | Impact | Mitigation and release posture |
|---|---|---|
| NHANES is cross-sectional and complete-case | A national signal can be mistaken for persistent disease prevalence | Label as a cross-sectional indicator; retain denominator, missing-lab count, design method, and limitation. |
| MEPS kidney field is a proxy | Users could call it confirmed CKD | Name `DSKIDN53` as a diabetes-related kidney-problem proxy in source docs, API evidence, and dashboard. |
| Part D geography is provider-reported | Provider state could be mistaken for beneficiary residence or demand | Keep provider-state grain and suppress provider identifiers; no patient/geography join. |
| ClinicalTrials.gov status is registry metadata | Recruiting counts could be read as treatment success or demand | Preserve registered-study denominator and state that status is not effectiveness or enrollment outcome. |
| Synthetic journey fixture is not official CMS rows | Demonstration outputs could be generalized to Medicare | Validate and label `public_synthetic` plus `fixture_only`; render “not representative of Medicare beneficiaries.” |
| Source families lack a shared geography/time key | A composite leaderboard could imply unsupported market truth | Keep panels separate; scenario ranking requires explicit compatible inputs and reports sensitivity. |
| Small grouped model holdout | Metrics and subgroup intervals may be unstable | Use cluster split, held-out evaluation, bootstrap caveats, leakage allowlist, and no superiority claim. |
| Artifact or manifest drift | A dashboard could show stale or tampered results | Require exact sidecar/manifest/computed checksum equality and fail closed with HTTP 503. |
| API contract drift | Dashboard could silently drop fields or identifiers | Strict nested Pydantic models, OpenAPI inspection, adversarial tests, and versioned route client. |
| Raw identifiers or proprietary data exposure | Privacy, security, and portfolio-integrity harm | No customer/employer data; no raw source rows in committed outputs; identifier-removal tests and source-specific boundaries. |
| Optional PostgreSQL environment absent | Integration behavior could be untested locally | Keep PostgreSQL tests explicit and skipped only when its URL is unset; DuckDB/fixture path is the release default. |
| Dashboard accessibility or responsive defects | Reviewers may miss evidence or misread clipped tables | Visible navigation, 44px controls, scroll affordance, text alternatives, mobile/synthetic captures, and callback tests. |

The release is suitable as a public portfolio demonstration with these boundaries.
It is not suitable for clinical, patient-targeting, commercial forecasting, or
production decision use without a new validated study, governance review, and
source-specific data agreements.
