# CKD Launch Intelligence

Public-data portfolio project for reproducible CKD patient-need and launch-planning
analysis. The fictional scenario is educational and does not provide diagnosis,
treatment recommendations, or patient targeting.

## Runtime

- DuckDB is the credential-free default for local analysis and automated tests.
- PostgreSQL is the primary deployment target. Its Compose service binds only to
  `127.0.0.1` and reads its password from the uncommitted
  `CKD_POSTGRES_PASSWORD` environment variable through a Docker secret.
- Raw data families use separate schemas. Observed outputs belong in
  `analytics_observed`; CMS DE-SynPUF demonstrations belong in
  `analytics_synthetic`.

Install the development environment with `make install`, then run the full local
quality gate with `make check`. Before starting PostgreSQL, provide a local secret:

```bash
export CKD_POSTGRES_PASSWORD='choose-a-local-password'
docker compose up -d postgres
```

## Fixture provenance

Task 1 includes only small committed registry-metadata fixtures, not downloaded
source rows. Each `SourceRecord.checksum` is the SHA-256 digest of the corresponding
fixture bytes. Later ingestion will create separate manifests that authenticate
downloaded public-data snapshots.
