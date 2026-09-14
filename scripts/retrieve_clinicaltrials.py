"""Retrieve a reproducible ClinicalTrials.gov API-v2 CKD snapshot.

The API is mutable, so every page request, page token, response checksum, and
retrieval timestamp is retained in an ignored raw manifest. The committed
landscape contains only safe aggregates. Retrieval is fail-closed: a snapshot
is written only after pagination, total-count, and NCT-ID invariants reconcile.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import ssl
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ckd_intelligence.ingestion.trials import CKD_QUERY

ENDPOINT = "https://clinicaltrials.gov/api/v2/studies"
PAGE_SIZE = 1000
NCT_PATTERN = re.compile(r"NCT\d{8}\Z")
FetchPage = Callable[[str], bytes]


def _nct_id(study: object) -> str:
    """Extract and validate the registry identity before it enters the snapshot."""

    if not isinstance(study, dict):
        raise ValueError("ClinicalTrials.gov row is not an object")
    protocol = study.get("protocolSection")
    if not isinstance(protocol, dict):
        raise ValueError("ClinicalTrials.gov row is missing protocolSection")
    identification = protocol.get("identificationModule")
    if not isinstance(identification, dict):
        raise ValueError("ClinicalTrials.gov row is missing identificationModule")
    value = identification.get("nctId")
    if not isinstance(value, str) or NCT_PATTERN.fullmatch(value) is None:
        raise ValueError("ClinicalTrials.gov row has a missing or invalid NCT ID")
    return value


def retrieve_snapshot(
    fetch_page: FetchPage, *, retrieved_at: str | None = None
) -> tuple[dict[str, object], list[bytes]]:
    """Fetch and validate all pages, returning metadata/studies and page bytes.

    ``fetch_page`` is injected so pagination invariants can be tested without
    network access. No output is written until every invariant succeeds.
    """

    snapshot_time = retrieved_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    studies: list[object] = []
    page_payloads: list[bytes] = []
    pages: list[dict[str, object]] = []
    page_token: str | None = None
    seen_page_tokens: set[str] = set()
    seen_nct_ids: set[str] = set()
    total_count: int | None = None
    total_counts_observed: list[int] = []
    total_count_missing_pages = 0

    while True:
        if page_token is not None:
            if page_token in seen_page_tokens:
                raise ValueError("ClinicalTrials.gov pagination repeated a page token")
            seen_page_tokens.add(page_token)
        params: dict[str, str | int] = {
            "query.term": CKD_QUERY,
            "pageSize": PAGE_SIZE,
            "countTotal": "true",
            "format": "json",
        }
        if page_token:
            params["pageToken"] = page_token
        request_url = f"{ENDPOINT}?{urlencode(params)}"
        payload = fetch_page(request_url)
        try:
            document: Any = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("ClinicalTrials.gov API returned invalid JSON") from exc
        if not isinstance(document, dict) or not isinstance(document.get("studies"), list):
            raise ValueError("ClinicalTrials.gov API returned an invalid page")

        page_total = document.get("totalCount")
        if page_total is None:
            if total_count is None:
                raise ValueError("ClinicalTrials.gov first page omitted totalCount")
            total_count_missing_pages += 1
        elif isinstance(page_total, bool) or not isinstance(page_total, int) or page_total < 0:
            raise ValueError("ClinicalTrials.gov totalCount must be a non-negative integer")
        else:
            total_counts_observed.append(page_total)
            if total_count is None:
                total_count = page_total
            elif page_total != total_count:
                raise ValueError("ClinicalTrials.gov totalCount changed during pagination")
        if total_count is None:
            raise ValueError("ClinicalTrials.gov totalCount was not established")

        page_studies = document["studies"]
        for study in page_studies:
            identifier = _nct_id(study)
            if identifier in seen_nct_ids:
                raise ValueError(f"ClinicalTrials.gov duplicate NCT ID: {identifier}")
            seen_nct_ids.add(identifier)
        page_number = len(pages)
        next_token = document.get("nextPageToken")
        if next_token is not None and not isinstance(next_token, str):
            raise ValueError("ClinicalTrials.gov nextPageToken must be text")
        if next_token and next_token in seen_page_tokens:
            raise ValueError("ClinicalTrials.gov pagination repeated a page token")
        pages.append(
            {
                "page_number": page_number,
                "request_url": request_url,
                "params": params,
                "page_token": page_token,
                "next_page_token": next_token,
                "rows": len(page_studies),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "path": f"page-{page_number:04d}.json",
            }
        )
        page_payloads.append(payload)
        studies.extend(page_studies)
        if not next_token:
            break
        page_token = next_token

    if total_count != len(studies) or total_count != len(seen_nct_ids):
        raise ValueError(
            "ClinicalTrials.gov pagination ended before row and unique NCT-ID totals reconciled"
        )
    if not total_counts_observed or len(set(total_counts_observed)) != 1:
        raise ValueError("ClinicalTrials.gov totalCount was not stable")

    metadata: dict[str, object] = {
        "api_version": "v2",
        "endpoint": ENDPOINT,
        "query": CKD_QUERY,
        "page_size": PAGE_SIZE,
        "page_count": len(pages),
        "pagination_complete": True,
        "total_count": total_count,
        "total_counts_observed": total_counts_observed,
        "total_count_stable": True,
        "total_count_missing_pages": total_count_missing_pages,
        "retrieved_row_count": len(studies),
        "unique_valid_nct_id_count": len(seen_nct_ids),
        "retrieved_at": snapshot_time,
        "pages": pages,
    }
    return {"snapshot_metadata": metadata, "studies": studies}, page_payloads


def _fetch_url(request_url: str) -> bytes:
    request = Request(
        request_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ckd-launch-intelligence/1.0",
        },
    )
    try:
        certifi = cast(Any, importlib.import_module("certifi"))
    except ModuleNotFoundError:
        context = ssl.create_default_context()
    else:
        context = ssl.create_default_context(cafile=str(certifi.where()))
    with urlopen(  # noqa: S310 - fixed official host
        request, timeout=120, context=context
    ) as response:
        return cast(bytes, response.read())


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/clinicaltrials/ckd-retrieved/")
    envelope, page_payloads = retrieve_snapshot(_fetch_url)
    output.mkdir(parents=True, exist_ok=True)
    metadata = envelope["snapshot_metadata"]
    assert isinstance(metadata, dict)
    for page, payload in zip(metadata["pages"], page_payloads, strict=True):
        assert isinstance(page, dict)
        (output / str(page["path"])).write_bytes(payload)
    (output / "clinicaltrials-ckd-full.json").write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    (output / "retrieval-manifest.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
