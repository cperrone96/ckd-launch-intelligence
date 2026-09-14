from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scripts.retrieve_clinicaltrials import retrieve_snapshot


def _study(nct_id: str) -> dict[str, object]:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id},
        }
    }


def _fetcher(pages: dict[str | None, dict[str, object]]) -> Callable[[str], bytes]:
    def fetch(url: str) -> bytes:
        token = parse_qs(urlparse(url).query).get("pageToken", [None])[0]
        document = pages[token]
        return json.dumps(document).encode()

    return fetch


def test_retrieval_requires_rows_and_unique_ids_to_match_total() -> None:
    pages: dict[str | None, dict[str, object]] = {
        None: {"totalCount": 3, "studies": [_study("NCT00000001"), _study("NCT00000002")]}
    }
    with pytest.raises(ValueError, match="totals reconciled"):
        retrieve_snapshot(_fetcher(pages), retrieved_at="2026-09-11T00:00:00Z")


def test_retrieval_rejects_duplicate_nct_id_across_pages() -> None:
    pages: dict[str | None, dict[str, object]] = {
        None: {"totalCount": 2, "studies": [_study("NCT00000001")], "nextPageToken": "next"},
        "next": {"studies": [_study("NCT00000001")]},
    }
    with pytest.raises(ValueError, match="duplicate NCT ID"):
        retrieve_snapshot(_fetcher(pages))


def test_retrieval_rejects_missing_nct_id() -> None:
    pages: dict[str | None, dict[str, object]] = {
        None: {
            "totalCount": 1,
            "studies": [{"protocolSection": {"identificationModule": {}}}],
        }
    }
    with pytest.raises(ValueError, match="missing or invalid NCT ID"):
        retrieve_snapshot(_fetcher(pages))


def test_retrieval_rejects_repeated_page_token() -> None:
    pages: dict[str | None, dict[str, object]] = {
        None: {"totalCount": 2, "studies": [_study("NCT00000001")], "nextPageToken": "next"},
        "next": {"totalCount": 2, "studies": [_study("NCT00000002")], "nextPageToken": "next"},
    }
    with pytest.raises(ValueError, match="repeated a page token"):
        retrieve_snapshot(_fetcher(pages))


def test_retrieval_rejects_total_count_drift() -> None:
    pages: dict[str | None, dict[str, object]] = {
        None: {"totalCount": 2, "studies": [_study("NCT00000001")], "nextPageToken": "next"},
        "next": {"totalCount": 3, "studies": [_study("NCT00000002")]},
    }
    with pytest.raises(ValueError, match="totalCount changed"):
        retrieve_snapshot(_fetcher(pages))


def test_retrieval_accepts_omitted_later_total_when_reconciled() -> None:
    pages: dict[str | None, dict[str, object]] = {
        None: {"totalCount": 2, "studies": [_study("NCT00000001")], "nextPageToken": "next"},
        "next": {"studies": [_study("NCT00000002")]},
    }
    envelope, page_payloads = retrieve_snapshot(
        _fetcher(pages), retrieved_at="2026-09-11T00:00:00Z"
    )
    metadata = envelope["snapshot_metadata"]
    assert isinstance(metadata, dict)
    assert metadata["pagination_complete"] is True
    assert metadata["total_count"] == 2
    assert metadata["retrieved_row_count"] == 2
    assert metadata["unique_valid_nct_id_count"] == 2
    assert metadata["total_count_missing_pages"] == 1
    assert len(page_payloads) == 2


def test_failed_retrieval_does_not_overwrite_existing_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "clinicaltrials-ckd-full.json"
    output.write_text("existing", encoding="utf-8")
    pages: dict[str | None, dict[str, object]] = {
        None: {"totalCount": 3, "studies": [_study("NCT00000001")]}
    }
    monkeypatch.setattr("scripts.retrieve_clinicaltrials._fetch_url", _fetcher(pages))
    monkeypatch.setattr(sys, "argv", ["retrieve_clinicaltrials.py", str(tmp_path)])
    with pytest.raises(ValueError, match="totals reconciled"):
        from scripts.retrieve_clinicaltrials import main

        main()
    assert output.read_text(encoding="utf-8") == "existing"
