from __future__ import annotations

from types import MappingProxyType

import pytest

from ckd_intelligence.quality.contracts import ImmutableBatch


def test_immutable_batch_supports_rows_and_columns_without_mutation() -> None:
    batch = ImmutableBatch.from_records([{"id": "one", "value": 2}])

    assert batch[0]["id"] == "one"
    assert batch["value"] == (2,)
    assert list(batch) == [MappingProxyType({"id": "one", "value": 2})]
    with pytest.raises(KeyError):
        _ = batch["missing"]
