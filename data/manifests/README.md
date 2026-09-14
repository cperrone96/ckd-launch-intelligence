# Ingestion manifests

Each ingestion run returns an immutable `SourceManifest`. The manifest records the
registered source/version, evidence type, population, grain, exact input SHA-256,
byte and record counts, coverage, requested locator, final canonical locator after any
HTTPS redirect, and the content-addressed cache path.

Raw snapshots are cached only after bytes are actually read. Their path is:

`data/raw/<source>/<version>/<sha256>.<extension>`

The filename checksum is calculated from the exact bytes; it is never predicted or
copied from registry metadata. Re-ingesting the same bytes reuses the same verified
path. This directory intentionally contains no fabricated run manifest or source
snapshot. Tests use temporary cache roots and committed, small fixtures.

Manifests describe one source at a time. They do not authorize patient-level joins
between NHANES, MEPS, Part D, ClinicalTrials.gov, or DE-SynPUF.

The committed `*_landscape.json` manifests document safe public-observed
aggregates for MEPS HC-243 2022, the bounded CMS Part D therapy dictionary, and
the fully paginated ClinicalTrials.gov CKD query. Raw source pages remain under
the ignored `data/raw/` directory; aggregate outputs retain source, population,
time, grain, retrieval, and checksum metadata and do not contain person,
beneficiary, NPI, or trial identifiers.

Dataset-level release identity is checked before a manifest is returned. Bytes that
identify a contradictory release remain safely cached for audit, but cannot receive a
manifest carrying the configured registry version.
