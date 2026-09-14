# Medicare Part D ingestion contract

- Release: 2024 Medicare Part D Prescribers by Provider and Drug
- Population: prescriptions represented by the CMS aggregate public-use dataset
- Grain: one provider, drug, and year aggregate
- Evidence: public observed
- Coverage field: `year` (restricted to the registered 2024 release)

Supported layouts are the repository's normalized CSV and the CMS downloadable CSV
or single-CSV ZIP using `Prscrbr_NPI`, `Prscrbr_State_Abrvtn`, `Brnd_Name`,
`Gnrc_Name`, `Tot_Clms`, `Tot_30day_Fills`, and `Tot_Drug_Cst`. Because the native
annual table does not repeat year on every row, its requested/final locator must name
2024. Compressed input is capped at 256 MiB and its sole CSV member at 1 GiB.

The adapter preserves NPI as a ten-character code, a documented U.S./DC/territory
postal code, brand and generic names, claim count, standardized 30-day fills, and drug
cost in U.S. dollars. It checks the provider/drug/year aggregate key and rejects
negative count or cost values. `ZZ` and other placeholder states are not accepted.

Patient/person/beneficiary fields are forbidden at this boundary. These aggregates
cannot support beneficiary-level utilization, journeys, or cross-source linkage.
