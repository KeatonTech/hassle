"""`normalize_duration` (a `for_=` value that is neither a timedelta, an
`HH:MM:SS` string, nor a units dict) previously raised a bare
`ValueError`/`TypeError` with no file:line and no "Fix:" text -- reachable
from ordinary bundle authoring (e.g. `state(x).to("on", for_="5 minutes")`,
a natural but wrong format). Fixed by `InvalidDurationError` (what/where/fix,
snapshot-tested), raised by every trigger/condition/purpose builder that
calls `normalize_duration` with a real call-site span.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle import numeric_state, on, state
from hassle.compiler.durations import InvalidDurationError
from hassle.compiler.recording import recording
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    check_snapshot(SNAP_DIR, name, actual)


def _normalize(msg: str) -> str:
    return normalize_error(msg, mask_lines_for=Path(__file__).name)


def test_bad_for_string_on_state_trigger_raises_with_location_and_fix() -> None:
    with recording(alias="x", id="x"), pytest.raises(InvalidDurationError) as excinfo:
        state("light.hallway").to("on", for_="5 minutes")
    msg = str(excinfo.value)
    assert "5 minutes" in msg  # what
    assert "test_duration_error.py" in msg  # where
    assert "Fix:" in msg
    _check_snapshot("invalid_duration_string", _normalize(msg))


def test_bad_for_type_on_numeric_state_raises_with_location_and_fix() -> None:
    with recording(alias="x", id="x"), pytest.raises(InvalidDurationError) as excinfo:
        numeric_state("sensor.x", above=1, for_=object())
    msg = str(excinfo.value)
    assert "test_duration_error.py" in msg
    assert "Fix:" in msg


def test_bad_for_on_purpose_trigger_raises_with_location_and_fix() -> None:
    with recording(alias="x", id="x"), pytest.raises(InvalidDurationError) as excinfo:
        on("motion.detected", target="binary_sensor.x", for_="bogus")
    msg = str(excinfo.value)
    assert "test_duration_error.py" in msg
    assert "Fix:" in msg
