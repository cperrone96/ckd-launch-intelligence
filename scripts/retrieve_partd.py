"""Retrieve a bounded, complete CMS Part D 2024 generic dictionary slice.

The API response is retained only under the gitignored raw-data directory.  The
committed artifact is built from aggregates and never contains provider NPIs.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINT = "https://data.cms.gov/data-api/v1/dataset/9552739e-3d05-4c1b-8eff-ecabf391e2e5/data"
PAGE_SIZE = 5000
GENERICS = (
    "Empagliflozin",
    "Dapagliflozin Propanediol",
    "Finerenone",
)


def fetch(generic: str, output: Path) -> dict[str, object]:
    pages: list[dict[str, object]] = []
    offset = 0
    while True:
        query = urlencode({"size": PAGE_SIZE, "offset": offset, "filter[Gnrc_Name]": generic})
        url = f"{ENDPOINT}?{query}"
        request = Request(
            url, headers={"Accept": "application/json", "User-Agent": "ckd-launch-intelligence/1.0"}
        )
        with urlopen(request, timeout=120) as response:  # noqa: S310 - fixed CMS host
            payload = response.read()
        rows = json.loads(payload)
        if not isinstance(rows, list):
            raise ValueError(f"CMS API returned a non-list page for {generic}")
        page_path = output / f"{generic.lower().replace(' ', '-')}-{offset}.json"
        page_path.write_bytes(payload)
        pages.append(
            {
                "offset": offset,
                "limit": PAGE_SIZE,
                "rows": len(rows),
                "url": url,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        )
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return {
        "generic": generic,
        "pages": pages,
        "rows_retrieved": sum(int(p["rows"]) for p in pages),
    }


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw/partd/2024-ckd-dictionary-v1")
    output.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    generics = [fetch(generic, output) for generic in GENERICS]
    manifest = {
        "source": "CMS Medicare Part D Prescribers by Provider and Drug",
        "release": "2024",
        "endpoint": ENDPOINT,
        "dataset_uuid": "9552739e-3d05-4c1b-8eff-ecabf391e2e5",
        "page_size": PAGE_SIZE,
        "retrieved_at": retrieved_at,
        "pagination_complete": True,
        "generics": generics,
    }
    (output / "retrieval-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
