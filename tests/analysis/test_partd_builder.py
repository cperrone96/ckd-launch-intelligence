from __future__ import annotations

import pytest

from scripts.build_public_landscape import _required_nonnegative


def test_partd_required_numeric_fields_distinguish_suppression() -> None:
    with pytest.raises(ValueError, match="missing_or_suppressed"):
        _required_nonnegative({"Tot_Clms": ""}, "Tot_Clms", integer=True)


def test_partd_required_numeric_fields_reject_malformed_or_negative_values() -> None:
    with pytest.raises(ValueError, match="malformed_number"):
        _required_nonnegative({"Tot_Clms": "not-a-number"}, "Tot_Clms", integer=True)
    with pytest.raises(ValueError, match="out_of_range"):
        _required_nonnegative({"Tot_Clms": "-1"}, "Tot_Clms", integer=True)
