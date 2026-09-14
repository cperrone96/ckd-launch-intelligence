"""Retrieve a reproducible ClinicalTrials.gov API-v2 CKD snapshot.

The API is mutable, so every page request, page token, response checksum, and
retrieval timestamp is retained in an ignored raw manifest.  The committed
landscape contains only safe aggregates.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi

from ckd_intelligence.ingestion.trials import CKD_QUERY

ENDPOINT = "https://clinicaltrials.gov/api/v2/studies"
PAGE_SIZE = 1000


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/clinicaltrials/ckd-retrieved/")
    output.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    studies: list[object] = []
    pages: list[dict[str, object]] = []
    page_token: str | None = None
    total_count: int | None = None
    total_counts_observed: list[int] = []
    total_count_missing_pages = 0

    while True:
        params: dict[str, str | int] = {
            "query.term": CKD_QUERY,
            "pageSize": PAGE_SIZE,
            "countTotal": "true",
            "format": "json",
        }
        if page_token:
            params["pageToken"] = page_token
        request_url = f"{ENDPOINT}?{urlencode(params)}"
        request = Request(
            request_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ckd-launch-intelligence/1.0",
            },
        )
        context = ssl.create_default_context(cafile=certifi.where())
        with urlopen(  # noqa: S310 - fixed official host
            request, timeout=120, context=context
        ) as response:
            payload = response.read()
        document = json.loads(payload)
        if not isinstance(document, dict) or not isinstance(document.get("studies"), list):
            raise ValueError("ClinicalTrials.gov API returned an invalid page")
        page_total = document.get("totalCount")
        if page_total is None and total_count is not None:
            total_count_missing_pages += 1
        elif not isinstance(page_total, int):
            raise ValueError("ClinicalTrials.gov API page omitted totalCount")
        else:
            total_counts_observed.append(page_total)
        if total_count is None:
            total_count = page_total
        elif page_total != total_count:
            # The registry can change during a multi-page read. Keep every
            # page and report the instability rather than discarding data.
            pass
        page_number = len(pages)
        page_path = output / f"page-{page_number:04d}.json"
        page_path.write_bytes(payload)
        next_token = document.get("nextPageToken")
        pages.append(
            {
                "page_number": page_number,
                "request_url": request_url,
                "params": params,
                "page_token": page_token,
                "next_page_token": next_token,
                "rows": len(document["studies"]),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "path": page_path.name,
            }
        )
        studies.extend(document["studies"])
        if not next_token:
            break
        if not isinstance(next_token, str):
            raise ValueError("ClinicalTrials.gov nextPageToken must be text")
        page_token = next_token

    if not studies or total_count is None:
        raise ValueError("ClinicalTrials.gov pagination returned no studies")
    envelope = {
        "snapshot_metadata": {
            "api_version": "v2",
            "endpoint": ENDPOINT,
            "query": CKD_QUERY,
            "page_size": PAGE_SIZE,
            "page_count": len(pages),
            "pagination_complete": True,
            "total_count": total_count,
            "total_counts_observed": total_counts_observed,
            "total_count_stable": len(set(total_counts_observed)) == 1,
            "total_count_missing_pages": total_count_missing_pages,
            "retrieved_row_count": len(studies),
            "retrieved_at": retrieved_at,
            "pages": pages,
        },
        "studies": studies,
    }
    (output / "clinicaltrials-ckd-full.json").write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    (output / "retrieval-manifest.json").write_text(
        json.dumps(envelope["snapshot_metadata"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
