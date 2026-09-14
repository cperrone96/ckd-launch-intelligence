# Transparent opportunity scenarios

## Purpose and boundary

This method produces a reproducible, multi-criteria **scenario ranking** for a
fictional launch-planning exercise. It is not a market-size estimate, an
objective geographic truth, a clinical recommendation, or patient-level
targeting.

The source families in this project do not share a defensible geography:

| Source | Population and grain | Geographic interpretation |
| --- | --- | --- |
| NHANES | Survey participants; weighted national/domain estimates | National or documented survey domain |
| MEPS | HC-243 consolidated person-year records; weighted national estimates | National or documented survey domain |
| CMS Part D | Provider/drug/geography aggregate | Provider-reported geography, not beneficiary residence |
| ClinicalTrials.gov | Registered study and study-country mention | Study-country activity, not patient demand |

These panels remain separate in the dashboard. They must not be joined at the
person level or silently crosswalked into a state leaderboard.

## Composite contract

`rank_opportunities(inputs, weights)` accepts only rows with
`scenario_only=True`, a shared `compatibility_key`, a shared `time_period`, and
`geography_scope="scenario"`. Every component (`need`, `screening_gap`,
`prescribing`, and `trial_activity`) carries:

- source population and grain;
- `evidence_type` (`public_observed`, `public_synthetic`, or `fixture_only`);
- provenance (file, query, or caller-supplied scenario source);
- coverage in `[0, 1]`;
- limitations and a time period.

The scenario flag is a deliberate gate. It makes the compatibility assumption
visible and prevents a national survey estimate, provider-state prescribing
count, and study-country mention from being presented as the same geographic
quantity. Scalar values are accepted only for an explicit scenario and are
marked as caller-supplied illustrative aggregates.

Weights must declare all four components, be non-negative, and sum to exactly 1
within a small floating-point tolerance. The implementation does not silently
renormalize weights.

## Normalization and score

Eligibility is determined before normalization. For each component, only rows
with complete values and coverage at or above the explicit threshold contribute
to the observed min/max; eligible values are then min-max normalized:

`normalized = (value - component_min) / (component_max - component_min)`

If all available values are equal, the normalized value is `0.5` for every
available row. A missing value stays `null`; it is never converted to zero.
The weighted score is:

`score = Σ(weight_component × normalized_component)`

A row is `scorable=false` when any component is missing or any component's
coverage is below the explicit `minimum_coverage` threshold (default 80%). It
receives null normalized values, no rank, and no score. Its extreme or missing
values cannot change an eligible candidate's normalization. Coverage is not a statistical confidence level;
it is a completeness gate for the scenario input.

Ranks are deterministic: score descending, then candidate key ascending. This
is an ordinal tie policy, so equal scores are still reproducibly ordered and are
not falsely described as materially different.

## Sensitivity

Pass alternative, plausible weight sets with `sensitivity_weights`. The result
reports the low/high score and rank across the base plus alternative sets. A
narrow rank interval supports a stable scenario; a wide interval should be
described as weight-sensitive. The ranking is not validated by this analysis and
should not be interpreted as causal or predictive.

## Example input shape

```python
inputs = [{
    "key": "Illustrative scenario A",
    "geography": "Illustrative scenario A",
    "time_period": "2024",
    "scenario_only": True,
    "compatibility_key": "demo",
    "components": {
        "need": {
            "value": 0.80,
            "source_population": "illustrative survey aggregate",
            "grain": "scenario aggregate",
            "evidence_type": "fixture_only",
            "provenance": "notebook cell",
            "geography_scope": "scenario",
            "time_period": "2024",
            "compatibility_key": "demo",
            "coverage": 1.0,
            "limitations": ["Illustrative; not an observed geographic estimate."],
        },
        # screening_gap, prescribing, and trial_activity use the same contract.
    },
}]
```

The notebook uses deterministic illustrative inputs so the method can be
executed without exposing proprietary customer, clinical, or commercial data.
