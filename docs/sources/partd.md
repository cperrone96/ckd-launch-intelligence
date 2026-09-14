# Medicare Part D 2024 ingestion and landscape contract

- Release: [2024 Medicare Part D Prescribers by Provider and Drug](https://data.cms.gov/provider-summary-by-type-of-service/medicare-part-d-prescribers/medicare-part-d-prescribers-by-provider-and-drug)
- API dataset UUID: `9552739e-3d05-4c1b-8eff-ecabf391e2e5` <!-- gitleaks:allow; public CMS dataset identifier -->
- Population: prescriptions represented by CMS aggregate public-use data
- Native grain: provider, drug, and geography aggregate
- Evidence: public observed

The public landscape retrieves complete paginated rows for the versioned,
non-exhaustive dictionary `ckd-therapy-dictionary-v1`: Empagliflozin and
Dapagliflozin Propanediol (SGLT2 inhibitors), and Finerenone (a nonsteroidal
mineralocorticoid receptor antagonist). The class rationale is a descriptive
selection rule, not an indication or treatment-outcome claim. Generic names are
matched exactly to CMS values and brands remain separate rows.

Each API page, offset, row count, URL, and SHA-256 is recorded in the ignored raw
retrieval manifest. The committed artifact aggregates by generic, brand, and
state, removes NPIs, and proves that the selected generic pages ended with a
short page. It does not claim national all-activity coverage beyond those
selected generics.

CMS detailed provider-drug rows exclude providers with fewer than 11 total
claims. An absent provider-drug row is therefore not zero, and beneficiary
fields are not used. The artifact cannot establish CKD indication, adherence,
outcomes, or patient journeys. See
`data/processed/partd_2024_ckd_therapy_landscape.json` and its dated manifest.
