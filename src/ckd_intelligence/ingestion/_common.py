"""Shared bounded I/O and strict parsing utilities for ingestion adapters."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from numbers import Real
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

READ_CHUNK_BYTES = 1024 * 1024
MISSING_SENTINELS = frozenset({"", ".", "NA", "N/A", "NULL", "NONE"})

RowValidator = Callable[[Mapping[str, str]], tuple[dict[str, Scalar], list[str]]]


@dataclass(frozen=True, slots=True)
class RawSnapshot:
    """Exact retrieved bytes and their content-addressed provenance."""

    payload: bytes
    requested_source_uri: str
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
    max_bytes: int,
) -> tuple[bytes, str, str, str]:
    """Stream a bounded local/HTTPS source and return bytes and canonical locators."""

    raw_source = str(source_path_or_url)
    parsed = urlparse(raw_source)
    if parsed.scheme:
        if parsed.scheme != "https":
            raise ValueError("Only HTTPS source URLs are accepted")
        request = Request(raw_source, headers={"User-Agent": "ckd-launch-intelligence/0.1"})
        with urlopen(request, timeout=30) as response:  # noqa: S310 - HTTPS enforced above
            final_url = response.geturl()
            if urlparse(final_url).scheme != "https":
                raise ValueError("HTTPS source redirected to a non-HTTPS location")
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > max_bytes:
                raise ValueError(f"Source exceeds {max_bytes} byte download limit")
            chunks: list[bytes] = []
            byte_count = 0
            while True:
                chunk = response.read(min(READ_CHUNK_BYTES, max_bytes - byte_count + 1))
                if not chunk:
                    break
                byte_count += len(chunk)
                if byte_count > max_bytes:
                    raise ValueError(f"Source exceeds {max_bytes} byte download limit")
                chunks.append(chunk)
            payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise ValueError(f"Source exceeds {max_bytes} byte download limit")
        suffix = Path(urlparse(final_url).path).suffix.lower() or ".bin"
        return payload, raw_source, final_url, suffix

    path = Path(source_path_or_url).expanduser().resolve(strict=True)
    if path.stat().st_size > max_bytes:
        raise ValueError(f"Source exceeds {max_bytes} byte read limit")
    with path.open("rb") as handle:
        local_chunks = iter(lambda: handle.read(READ_CHUNK_BYTES), b"")
        payload = b"".join(local_chunks)
    return payload, str(path), str(path), path.suffix.lower() or ".bin"


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
    max_bytes: int,
) -> RawSnapshot:
    """Retrieve and immediately cache exact bytes before record validation."""

    payload, requested_uri, source_uri, suffix = read_bounded_source(
        source_path_or_url, max_bytes=max_bytes
    )
    suffix = infer_suffix(payload, suffix)
    checksum, cache_path = cache_snapshot(
        payload,
        source=registry.name,
        version=registry.version,
        suffix=suffix,
        cache_dir=cache_dir,
    )
    return RawSnapshot(payload, requested_uri, source_uri, suffix, checksum, cache_path)


def infer_suffix(payload: bytes, hinted_suffix: str) -> str:
    """Identify common public-data formats when a download endpoint has no extension."""

    if payload.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return ".zip"
    stripped = payload.lstrip()
    if stripped.startswith((b"{", b"[")):
        return ".json"
    if payload.startswith(b"HEADER RECORD*******LIBRARY HEADER RECORD"):
        return ".xpt"
    if hinted_suffix in {".csv", ".json", ".xpt", ".zip"}:
        return hinted_suffix
    try:
        first_line = payload.decode("utf-8-sig").splitlines()[0]
    except (UnicodeDecodeError, IndexError):
        return hinted_suffix
    return ".csv" if "," in first_line else hinted_suffix


def csv_payload_from_snapshot(
    snapshot: RawSnapshot,
    *,
    max_uncompressed_bytes: int,
) -> bytes:
    """Return CSV bytes directly or from a single-member bounded ZIP archive."""

    if snapshot.suffix != ".zip":
        return snapshot.payload
    try:
        with zipfile.ZipFile(io.BytesIO(snapshot.payload)) as archive:
            members = [
                info
                for info in archive.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".csv")
            ]
            if len(members) != 1:
                raise ValueError("ZIP source must contain exactly one CSV member")
            member = members[0]
            if member.file_size > max_uncompressed_bytes:
                raise ValueError("ZIP CSV exceeds the source-specific uncompressed limit")
            with archive.open(member) as handle:
                payload = handle.read(max_uncompressed_bytes + 1)
    except zipfile.BadZipFile as exc:
        raise ValueError("Source must be a valid ZIP archive") from exc
    if len(payload) > max_uncompressed_bytes:
        raise ValueError("ZIP CSV exceeds the source-specific uncompressed limit")
    return payload


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
    if len(columns) != len(reader.fieldnames or ()):
        raise ValueError("CSV header contains duplicate columns")
    for row in reader:
        parsed_row = {
            key: value if value is not None else ""
            for key, value in row.items()
            if key is not None
        }
        if None in row:
            parsed_row["_ingestion_error"] = "csv:extra_values"
        elif any(value is None for value in row.values()):
            parsed_row["_ingestion_error"] = "csv:missing_values"
        rows.append(parsed_row)
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


def require_release_identity(
    rows: Sequence[Mapping[str, str]], field: str, expected: str
) -> None:
    """Fail before manifest creation when bytes identify a different release."""

    identified = {row[field].strip() for row in rows if row.get(field, "").strip()}
    if not identified:
        raise ValueError(f"Source does not identify registered version {expected}")
    contradictory = sorted(identified - {expected})
    if contradictory:
        raise ValueError(
            f"Source release {contradictory} does not match registered version {expected}"
        )


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
        if row.get("_ingestion_error"):
            reasons.append(row["_ingestion_error"])
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
        requested_source_uri=snapshot.requested_source_uri,
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


def optional_text_value(row: Mapping[str, str], field: str) -> str | None:
    """Return null for a documented missing marker without treating optionality as error."""

    value = row[field].strip()
    return None if value.upper() in MISSING_SENTINELS else value


def native_scalar_text(value: object) -> str:
    """Represent a decoded SAS scalar without raising on malformed row values."""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    if isinstance(value, Real) and not isinstance(value, bool):
        numeric = float(value)
        if not math.isfinite(numeric):
            return ""
        if numeric.is_integer():
            return str(int(numeric))
    return str(value).strip()


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
