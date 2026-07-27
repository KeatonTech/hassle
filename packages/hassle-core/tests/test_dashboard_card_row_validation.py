"""SF-4 (review round): entity-row parameters reject garbage instead of
silently compiling it.

Test contract: `hassle.compiler.dashboards.builders.normalize_rows` (the ONE
row-normalizer shared by every `entities`-shaped-row builder across
`cards/layout.py`, `cards/display.py`, `cards/visual.py` and `cards/media.py`)
raises `EntityRowTypeError` in two real bug shapes that used to compile clean
into garbage:

- a bare `str`/`EntityRef` passed where a LIST of rows was expected --
  `c.entity_filter(entities="light.hall")` used to silently become ten
  one-character rows (Python iterates a string character by character);
- a row that is neither `str`/`EntityRef` nor `dict` -- `c.entities(["a",
  "b"])` (a `list` passed as ONE row because the caller forgot to unpack)
  used to `str()`-stringify into a single nonsense row.

Covers every affected builder named in the review: `entities`, `glance`,
`heading` (its `badges=`), `entity_filter`, `history_graph`,
`statistics_graph`, `calendar`, `logbook`, `map`, `picture_glance`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hassle.cards import (
    entities,
    entity_filter,
    glance,
    heading,
)
from hassle.compiler.dashboards.cards.media import map as c_map
from hassle.compiler.dashboards.cards.media import picture_glance
from hassle.compiler.dashboards.cards.visual import (
    calendar,
    history_graph,
    logbook,
    statistics_graph,
)
from hassle.compiler.dashboards.errors import EntityRowTypeError
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import section, view
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"

# ---------------------------------------------------------------------------
# A bare string where a LIST of rows was expected -- only the two builders
# whose row parameter is an ordinary keyword (not varargs) can even receive
# a bare string in the position a list was expected.
# ---------------------------------------------------------------------------


def _entity_filter_bare_string() -> None:
    with entity_filter(entities="light.hall"):
        pass


def _heading_bare_string() -> None:
    heading(badges="sensor.x")


@pytest.mark.parametrize(
    "call",
    [_entity_filter_bare_string, _heading_bare_string],
    ids=["entity_filter", "heading"],
)
def test_bare_string_where_a_row_list_was_expected_raises(call: Any) -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(EntityRowTypeError) as excinfo:
            call()
    assert excinfo.value.reason == "bare_string"


def test_bare_string_error_message_names_the_fix() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(EntityRowTypeError) as excinfo:
            with entity_filter(entities="light.hall"):
                pass
    message = str(excinfo.value)
    assert "light.hall" in message
    assert "list" in message.lower()


# ---------------------------------------------------------------------------
# A row that is neither `str`/`EntityRef` nor `dict` -- every row-taking
# builder in the affected list, varargs or plain-keyword-list alike.
# ---------------------------------------------------------------------------
_BAD_ROW: list[str] = ["a", "b"]  # a `list` -- never a valid row


def _entities_bad_row() -> None:
    entities(_BAD_ROW)


def _glance_bad_row() -> None:
    glance(_BAD_ROW)


def _heading_bad_row() -> None:
    heading(badges=[_BAD_ROW])


def _entity_filter_bad_row() -> None:
    with entity_filter(entities=[_BAD_ROW]):
        pass


def _history_graph_bad_row() -> None:
    history_graph(_BAD_ROW)


def _statistics_graph_bad_row() -> None:
    statistics_graph(_BAD_ROW)


def _calendar_bad_row() -> None:
    calendar(_BAD_ROW)


def _logbook_bad_row() -> None:
    logbook(_BAD_ROW)


def _map_bad_row() -> None:
    c_map(_BAD_ROW)


def _picture_glance_bad_row() -> None:
    picture_glance(_BAD_ROW)


@pytest.mark.parametrize(
    "call",
    [
        _entities_bad_row,
        _glance_bad_row,
        _heading_bad_row,
        _entity_filter_bad_row,
        _history_graph_bad_row,
        _statistics_graph_bad_row,
        _calendar_bad_row,
        _logbook_bad_row,
        _map_bad_row,
        _picture_glance_bad_row,
    ],
    ids=[
        "entities",
        "glance",
        "heading",
        "entity_filter",
        "history_graph",
        "statistics_graph",
        "calendar",
        "logbook",
        "map",
        "picture_glance",
    ],
)
def test_a_non_str_non_dict_row_raises(call: Any) -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(EntityRowTypeError) as excinfo:
            call()
    assert excinfo.value.reason == "bad_row"
    assert excinfo.value.value == _BAD_ROW


def test_bad_row_error_message_names_the_type() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(EntityRowTypeError) as excinfo:
            entities(_BAD_ROW)
    message = str(excinfo.value)
    assert "list" in message.lower()


# ---------------------------------------------------------------------------
# Message snapshots (R6: error messages are product surface).
# ---------------------------------------------------------------------------
def test_bare_string_message_snapshot() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(EntityRowTypeError) as excinfo:
            with entity_filter(entities="light.hall"):
                pass
    check_snapshot(
        SNAP_DIR,
        "dashboard_entity_row_bare_string",
        normalize_error(str(excinfo.value), mask_lines_for=Path(__file__).name),
    )


def test_bad_row_message_snapshot() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(EntityRowTypeError) as excinfo:
            entities(_BAD_ROW)
    check_snapshot(
        SNAP_DIR,
        "dashboard_entity_row_bad_row_type",
        normalize_error(str(excinfo.value), mask_lines_for=Path(__file__).name),
    )
