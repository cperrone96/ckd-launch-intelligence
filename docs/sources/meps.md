# MEPS ingestion contract

- Release: HC-243 (2021) public-use release
- Population: U.S. civilian, noninstitutionalized population represented by MEPS
- Grain: one normalized condition, event, prescription, or expenditure record
- Evidence: public observed
- Coverage field: `year`

The adapter requires an explicit event key, person identifier, year, condition code,
event type, expenditure in U.S. dollars, person weight, variance stratum, and variance
PSU. Prescription name is retained when applicable and remains null for non-RX rows.
It is never manufactured from another event type.

National inference requires the MEPS weights and variance-design fields. Public-use
condition detail is limited, and MEPS people are never linked to another source.
