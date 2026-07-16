"""HA version-range check (DESIGN §4, §15).

`DirectBackend` reads `GET /api/config` (WS `get_config`) and warns when the
instance's HA version falls outside the range Hassle has been tested against.
The pure comparison logic lives in `hassle.backend.version` so it is testable
without a live instance; the live half (that a real `get_config` populates
`DirectBackend.ha_version`) is exercised by the integration suite.
"""

from __future__ import annotations

import pytest

from hassle.backend.version import (
    TESTED_HA_MAX,
    TESTED_HA_MIN,
    parse_ha_version,
    version_warning,
)


def test_parse_calendar_version() -> None:
    assert parse_ha_version("2026.7.1") == (2026, 7, 1)
    assert parse_ha_version("2026.2") == (2026, 2, 0)
    assert parse_ha_version("2026.7.0b3") == (2026, 7, 0)


def test_in_range_no_warning() -> None:
    assert version_warning(TESTED_HA_MIN) is None
    assert version_warning(TESTED_HA_MAX) is None


def test_below_range_warns_with_version_and_range() -> None:
    warning = version_warning("2023.1.0")
    assert warning is not None
    assert "2023.1.0" in warning
    assert TESTED_HA_MIN in warning and TESTED_HA_MAX in warning


def test_above_range_warns() -> None:
    warning = version_warning("2099.12.0")
    assert warning is not None
    assert "2099.12.0" in warning


@pytest.mark.parametrize("bad", ["", "not-a-version", "abc.def"])
def test_unparseable_version_warns_rather_than_crashing(bad: str) -> None:
    # An unparseable version must never crash the CLI; it degrades to a warning.
    assert version_warning(bad) is not None
