"""Immutable source-ingestion result contracts."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import overload

from ckd_intelligence.sources import EvidenceType

Scalar = str | int | float | None
Record = Mapping[str, Scalar]


@dataclass(frozen=True, slots=True)
class ImmutableBatch:
    """Small immutable row batch with both row and column access."""

    records: tuple[Record, ...]

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Scalar]]) -> ImmutableBatch:
        """Defensively copy rows into read-only mappings."""

        return cls(tuple(MappingProxyType(dict(record)) for record in records))

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self) -> Iterator[Record]:
        return iter(self.records)

    @overload
    def __getitem__(self, item: int) -> Record: ...

    @overload
    def __getitem__(self, item: str) -> tuple[Scalar, ...]: ...

    def __getitem__(self, item: int | str) -> Record | tuple[Scalar, ...]:
        if isinstance(item, int):
            return self.records[item]
        if not self.records or item not in self.records[0]:
            raise KeyError(item)
        return tuple(record[item] for record in self.records)


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """One rejected source record and every detected validation reason."""

    row_number: int
    reasons: tuple[str, ...]
    raw_record: Record


@dataclass(frozen=True, slots=True)
class SourceManifest:
    """Content-addressed, deterministic provenance for one ingestion run."""

    source: str
    version: str
    evidence_type: EvidenceType
    population: str
    grain: str
    input_checksum: str
    byte_count: int
    record_count: int
    valid_count: int
    quarantine_count: int
    requested_source_uri: str
    source_uri: str
    cache_path: str | None
    coverage_start: str | None
    coverage_end: str | None
    source_updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Validated and quarantined records with their immutable manifest."""

    valid: ImmutableBatch
    quarantine: tuple[QuarantineRecord, ...]
    manifest: SourceManifest
