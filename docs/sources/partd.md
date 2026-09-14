# Medicare Part D ingestion contract

- Release: 2024 Medicare Part D Prescribers by Provider and Drug
- Population: prescriptions represented by the CMS aggregate public-use dataset
- Grain: one provider, drug, and year aggregate
- Evidence: public observed
- Coverage field: `year` (restricted to the registered 2024 release)

The adapter preserves NPI as a ten-character code, state, brand and generic names,
claim count, standardized 30-day fills, and drug cost in U.S. dollars. It checks the
provider/drug/year aggregate key and rejects negative count or cost values.

Patient/person/beneficiary fields are forbidden at this boundary. These aggregates
cannot support beneficiary-level utilization, journeys, or cross-source linkage.
