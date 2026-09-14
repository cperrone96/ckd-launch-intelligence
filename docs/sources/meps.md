# MEPS HC-243 2022 ingestion and landscape contract

- Release: [HC-243 2022 Full-Year Consolidated](https://meps.ahrq.gov/mepsweb/data_files/pufs/h243/h243dat.zip)
- Population: U.S. civilian, noninstitutionalized population represented by MEPS
- Native grain: one consolidated person-year record (`DUPERSID`)
- Evidence: public observed
- Coverage: 2022 (`DATAYEAR`)

The adapter parses the official fixed-width `H243.DAT` release (or a native
transport layout in tests) and retains documented fields: `DCSELIG`, `DSDIA53`,
`DSKIDN53`, `TOTEXP22`, utilization fields (`OBTOTV22`, `OPTOTV22`, `ERTOT22`,
`IPDIS22`, `RXTOT22`), `PERWT22F`, `DIABW22F`, `VARSTR`, and `VARPSU`. Zero
person weights remain in the exact record denominator but are excluded from
survey-weighted estimates. Survey missing codes remain missing rather than zero.

HC-243 does not provide a confirmed CKD diagnosis for this analysis. The public
landscape uses `DSKIDN53` as a precise, documented proxy for a diabetes-related
kidney problem among `DCSELIG=1` and `DSDIA53=1` respondents, with `DIABW22F`
and Taylor linearization over `VARSTR`/`VARPSU`. The resulting estimates are
descriptive DCS-domain person-year utilization and expenditure estimates; they
are not provider prescribing, claims, causal, or confirmed-CKD estimates.

The reproducible aggregate is
`data/processed/meps_hc243_2022_landscape.json`; its dated manifest and checksum
are under `data/manifests/` and `data/processed/`. No person identifiers are
committed in the aggregate.
