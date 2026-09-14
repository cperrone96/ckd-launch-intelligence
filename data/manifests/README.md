# Ingestion manifests

Each ingestion run returns an immutable `SourceManifest`. The manifest records the
registered source/version, evidence type, population, grain, exact input SHA-256,
byte and record counts, coverage, source URI, and the content-addressed cache path.

Raw snapshots are cached only after bytes are actually read. Their path is:

`data/raw/<source>/<version>/<sha256>.<extension>`

The filename checksum is calculated from the exact bytes; it is never predicted or
copied from registry metadata. Re-ingesting the same bytes reuses the same verified
path. This directory intentionally contains no fabricated run manifest or source
snapshot. Tests use temporary cache roots and committed, small fixtures.

Manifests describe one source at a time. They do not authorize patient-level joins
between NHANES, MEPS, Part D, ClinicalTrials.gov, or DE-SynPUF.
