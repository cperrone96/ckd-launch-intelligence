# NHANES ingestion contract

- Release: 2017–2018 public-use cycle
- Population: U.S. civilian, noninstitutionalized population represented by NHANES
- Grain: one normalized survey-participant record
- Evidence: public observed
- Coverage field: `survey_cycle`

The adapter accepts a bounded UTF-8 CSV prepared from the demographic, examination,
questionnaire, and kidney-relevant laboratory files. It preserves the participant
identifier, survey cycle, sample weight, strata, PSU, demographics, and laboratory
units in their column names. Required fields, clinical-value ranges, survey-design
values, and participant-key uniqueness are validated before use.

Missing sentinels are quarantined, never changed to zero. Downstream population
estimates must use the documented survey design and weights. Cross-sectional CKD
indicators are not confirmed clinical diagnoses.
