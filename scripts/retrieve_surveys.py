"""Download the NHANES 2017-2018 and MEPS HC-243 public-use files and verify checksums.

Files land under the gitignored ``data/raw`` directory. Each file is checked against
the SHA-256 recorded in the committed manifest; a mismatch aborts without
overwriting a verified file. Files already present and verified are skipped.

Usage::

    python scripts/retrieve_surveys.py
"""

from __future__ import annotations

import hashlib
import json
import ssl
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
NHANES_MANIFEST = ROOT / "data/manifests/nhanes-2017-2018-patient-need.json"
NHANES_DIR = ROOT / "data/raw/nhanes/2017-2018"
MEPS_MANIFEST = ROOT / "data/manifests/meps_hc243_2022_landscape.json"
MEPS_PATH = ROOT / "data/raw/meps/HC-243-2022/h243dat.zip"


def _tls_context() -> ssl.SSLContext:
    """Prefer certifi's CA bundle (python.org macOS builds ship without system CAs)."""

    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_verified(url: str, destination: Path, expected_sha256: str) -> str:
    """Download ``url`` to ``destination`` unless a verified copy already exists."""

    if destination.is_file() and _sha256(destination) == expected_sha256:
        return "verified (cached)"
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-HTTPS source: {url}")
    request = Request(url, headers={"User-Agent": "ckd-launch-intelligence/1.0"})
    with urlopen(request, timeout=300, context=_tls_context()) as response:  # noqa: S310 - HTTPS enforced above
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256:
        raise ValueError(
            f"checksum mismatch for {url}: expected {expected_sha256}, received {digest}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(payload)
    temporary.replace(destination)
    return "downloaded and verified"


def main() -> int:
    nhanes = json.loads(NHANES_MANIFEST.read_text(encoding="utf-8"))
    for item in nhanes["files"]:
        status = fetch_verified(item["url"], NHANES_DIR / item["name"], item["sha256"])
        print(f"NHANES {item['name']}: {status}")
    meps = json.loads(MEPS_MANIFEST.read_text(encoding="utf-8"))
    status = fetch_verified(meps["source_url"], MEPS_PATH, meps["source_sha256"])
    print(f"MEPS {MEPS_PATH.name}: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
