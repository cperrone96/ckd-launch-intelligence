# MEPS ingestion contract

- Release: HC-243 (2021) public-use release
- Population: U.S. civilian, noninstitutionalized population represented by MEPS
- Grain: one normalized condition, event, prescription, or expenditure record
- Evidence: public observed
- Coverage field: `year`

Supported layouts are (1) the repository's normalized event exchange CSV, with an
explicit `HC-243-2021` release field, and (2) the native HC-243 full-year person-level
XPT (`h243` in the locator) using `DUPERSID`, `TOTEXP21`, `PERWT21F`, `VARSTR`, and
`VARPSU`. The native XPT path intentionally returns person-year expenditure records;
it does not pretend HC-243 contains condition, event, or prescription-detail rows.
Those other MEPS file families require their own future registered releases.

Input is capped at 750 MiB. The normalized event layout requires a valid ICD-10 code,
event type, expenditure in U.S. dollars, person weight, variance stratum, and variance
PSU. Prescription name is retained when applicable; documented missing markers in
this optional field remain null and are never manufactured from another event type.

National inference requires the MEPS weights and variance-design fields. Public-use
condition detail is limited, and MEPS people are never linked to another source.
