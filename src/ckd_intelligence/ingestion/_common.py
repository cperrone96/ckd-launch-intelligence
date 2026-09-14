"""Shared bounded I/O and strict parsing utilities for ingestion adapters."""

from __future__ import annotations

import csv
import hashlib
import io
import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ckd_intelligence.quality.contracts import (
    ImmutableBatch,
    IngestionResult,
    QuarantineRecord,
    Scalar,
    SourceManifest,
)
from ckd_intelligence.sources import SourceRecord, get_source_registry

DEFAULT_MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
MISSING_SENTINELS = frozenset({"", ".", "NA", "N/A", "NULL", "NONE"})

RowValidator = Callable[[Mapping[str, str]], tuple[dict[str, Scalar], list[str]]]


@dataclass(frozen=True, slots=True)
class RawSnapshot:
    """Exact retrieved bytes and their content-addressed provenance."""

    payload: bytes
    source_uri: str
    suffix: str
    checksum: str
    cache_path: str | None


def source_record(name: str) -> SourceRecord:
    """Return one registry record, failing if the configured family is absent."""

    return next(record for record in get_source_registry() if record.name == name)


def read_bounded_source(
    source_path_or_url: str | Path,
    *,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
) -> tuple[bytes, str, str]:
    """Read a local file or bounded HTTPS response and return bytes, URI, suffix."""

    raw_source = str(source_path_or_url)
    parsed = urlparse(raw_source)
    if parsed.scheme:
        if parsed.scheme != "https":
            raise ValueError("Only HTTPS source URLs are accepted")
        request = Request(raw_source, headers={"User-Agent": "ckd-launch-intelligence/0.1"})
        with urlopen(request, timeout=30) as response:  # noqa: S310 - HTTPS enforced above
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > max_bytes:
                raise ValueError(f"Source exceeds {max_bytes} byte download limit")
            payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise ValueError(f"Source exceeds {max_bytes} byte download limit")
        suffix = Path(parsed.path).suffix.lower() or ".bin"
        return payload, raw_source, suffix

    path = Path(source_path_or_url).expanduser().resolve(strict=True)
    if path.stat().st_size > max_bytes:
        raise ValueError(f"Source exceeds {max_bytes} byte read limit")
    return path.read_bytes(), str(path), path.suffix.lower() or ".bin"


def cache_snapshot(
    payload: bytes,
    *,
    source: str,
    version: str,
    suffix: str,
    cache_dir: Path | None,
) -> tuple[str, str | None]:
    """Cache exact raw bytes at a content-addressed, immutable path."""

    checksum = hashlib.sha256(payload).hexdigest()
    if cache_dir is None:
        return checksum, None
    safe_suffix = suffix if suffix in {".csv", ".json", ".xpt", ".zip"} else ".bin"
    target = cache_dir / source / version / f"{checksum}{safe_suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
            raise RuntimeError(f"Immutable cache collision at {target}") from None
    return checksum, str(target.resolve())


def load_source(
    source_path_or_url: str | Path,
    *,
    registry: SourceRecord,
    cache_dir: Path | None,
) -> RawSnapshot:
    """Retrieve and immediately cache exact bytes before record validation."""

    payload, source_uri, suffix = read_bounded_source(source_path_or_url)
    checksum, cache_path = cache_snapshot(
        payload,
        source=registry.name,
        version=registry.version,
        suffix=suffix,
        cache_dir=cache_dir,
    )
    return RawSnapshot(payload, source_uri, suffix, checksum, cache_path)


def parse_csv(payload: bytes, required_columns: frozenset[str]) -> list[dict[str, str]]:
    """Parse UTF-8 CSV and fail closed when its schema is incomplete."""

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Source must be valid UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    columns = frozenset(reader.fieldnames or ())
    missing = sorted(required_columns - columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    rows: list[dict[str, str]] = []
    for row in reader:
        if None in row:
            raise ValueError("CSV row contains more values than declared columns")
        rows.append({key: value for key, value in row.items() if key is not None})
    return rows


def reject_forbidden_fields(
    rows: Sequence[Mapping[str, object]], forbidden: frozenset[str]
) -> None:
    """Reject schemas that would invite unsupported patient-level linkage."""

    if not rows:
        return
    present = sorted(forbidden.intersection(rows[0]))
    if present:
        raise ValueError(f"Forbidden patient-level fields: {', '.join(present)}")


def duplicate_keys(
    rows: Sequence[Mapping[str, str]], key: Callable[[Mapping[str, str]], tuple[str, ...]]
) -> set[tuple[str, ...]]:
    """Return every non-empty business key occurring more than once."""

    counts = Counter(key(row) for row in rows)
    return {value for value, count in counts.items() if count > 1 and all(value)}


def validate_rows(
    rows: Sequence[Mapping[str, str]],
    validator: RowValidator,
) -> tuple[ImmutableBatch, tuple[QuarantineRecord, ...]]:
    """Partition rows without silently fixing any invalid source value."""

    valid: list[dict[str, Scalar]] = []
    quarantined: list[QuarantineRecord] = []
    for row_number, row in enumerate(rows, start=2):
        typed, reasons = validator(row)
        if reasons:
            quarantined.append(
                QuarantineRecord(
                    row_number=row_number,
                    reasons=tuple(sorted(set(reasons))),
                    raw_record=MappingProxyType(dict(row)),
                )
            )
        else:
            valid.append(typed)
    return ImmutableBatch.from_records(valid), tuple(quarantined)


def result_with_manifest(
    *,
    registry: SourceRecord,
    snapshot: RawSnapshot,
    valid: ImmutableBatch,
    quarantine: tuple[QuarantineRecord, ...],
    coverage_values: Iterable[str],
    source_updated_at: str | None = None,
) -> IngestionResult:
    """Build the standard deterministic result and manifest."""

    coverage = sorted(coverage_values)
    manifest = SourceManifest(
        source=registry.name,
        version=registry.version,
        evidence_type=registry.evidence_type,
        population=registry.population,
        grain=registry.grain,
        input_checksum=snapshot.checksum,
        byte_count=len(snapshot.payload),
        record_count=len(valid) + len(quarantine),
        valid_count=len(valid),
        quarantine_count=len(quarantine),
        source_uri=snapshot.source_uri,
        cache_path=snapshot.cache_path,
        coverage_start=coverage[0] if coverage else None,
        coverage_end=coverage[-1] if coverage else None,
        source_updated_at=source_updated_at,
    )
    return IngestionResult(valid=valid, quarantine=quarantine, manifest=manifest)


def text_value(
    row: Mapping[str, str],
    field: str,
    reasons: list[str],
    *,
    additional_missing: frozenset[str] = frozenset(),
) -> str:
    value = row[field].strip()
    if value.upper() in MISSING_SENTINELS | additional_missing:
        reasons.append(f"{field}:missing_sentinel")
    return value


def number_value(
    row: Mapping[str, str],
    field: str,
    reasons: list[str],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    additional_missing: frozenset[str] = frozenset(),
) -> float | None:
    value = text_value(row, field, reasons, additional_missing=additional_missing)
    if value.upper() in MISSING_SENTINELS | additional_missing:
        return None
    try:
        parsed = float(value)
    except ValueError:
        reasons.append(f"{field}:invalid_number")
        return None
    if not math.isfinite(parsed):
        reasons.append(f"{field}:invalid_number")
    elif (minimum is not None and parsed < minimum) or (
        maximum is not None and parsed > maximum
    ):
        reasons.append(f"{field}:out_of_range")
    return parsed


def integer_value(
    row: Mapping[str, str],
    field: str,
    reasons: list[str],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    additional_missing: frozenset[str] = frozenset(),
) -> int | None:
    value = text_value(row, field, reasons, additional_missing=additional_missing)
    if value.upper() in MISSING_SENTINELS | additional_missing:
        return None
    try:
        parsed = int(value)
    except ValueError:
        reasons.append(f"{field}:invalid_integer")
        return None
    if (minimum is not None and parsed < minimum) or (
        maximum is not None and parsed > maximum
    ):
        reasons.append(f"{field}:out_of_range")
    return parsed


def date_value(row: Mapping[str, str], field: str, reasons: list[str]) -> str:
    value = text_value(row, field, reasons)
    if value.upper() in MISSING_SENTINELS:
        return value
    try:
        date.fromisoformat(value)
    except ValueError:
        reasons.append(f"{field}:invalid_date")
    return value


def datetime_value(value: object, field: str) -> str:
    """Validate a required ISO 8601 metadata timestamp while preserving text."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty ISO 8601 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO 8601 timestamp") from exc
    return value
