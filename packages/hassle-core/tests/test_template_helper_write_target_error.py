"""Reviewer follow-up (M10 merge): `template_number`/`template_select` missing
their required write-target kwarg (`set_value=`/`select_option=`) used to only
fail at APPLY time with a bare backend `ValueError` (`_check_required_fields`
in `hassle.backend.direct`/`hassle.backend.fake`) -- `hassle validate` would
pass a bundle guaranteed to fail on push. `MissingTemplateHelperWriteTargetError`
(`hassle.compiler.errors`) makes this a compile-time error, raised from the DSL
builder itself (`hassle.compiler.template_helpers._declare_template_helper`),
so it is caught the moment the bundle is compiled -- by `hassle validate`,
`hassle plan`, and `hassle push` alike, all of which compile before anything
else. Snapshot-tested per R6 (what/where/fix, one paragraph).

The backend-side `_check_required_fields` checks are UNCHANGED and remain a
second line of defense (they guard any non-DSL path that builds a
`TemplateHelperConfig` directly, e.g. a hand-rolled `raw`/adopt path).

Template-helper declarations are prebuilt objects (like the nine storage-
collection helpers) -- no `recording()`/`@automation` context is needed to
call `template_number`/`template_select` directly, matching how they are
written in a real bundle (module scope, see
`fixtures/dsl/template_helper_declarations/bundle/helpers.py`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hassle import template_binary_sensor, template_number, template_select, template_sensor
from hassle.compiler import MissingTemplateHelperWriteTargetError
from hassle.compiler.template_helpers import reset_declared_template_helpers

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


def _check_snapshot(name: str, actual: str) -> None:
    import os

    path = SNAP_DIR / f"{name}.txt"
    if os.environ.get("HASSLE_UPDATE_SNAPSHOTS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual + "\n", encoding="utf-8")
    assert path.is_file(), f"missing snapshot {path}; set HASSLE_UPDATE_SNAPSHOTS=1 to write it"
    assert actual == path.read_text(encoding="utf-8").rstrip("\n")


def _normalize(msg: str) -> str:
    return re.sub(r"(/[^\s:]+/)([^/\s:]+\.py)", r"\2", msg)


@pytest.fixture(autouse=True)
def _reset():
    reset_declared_template_helpers()
    yield
    reset_declared_template_helpers()


def test_template_number_missing_set_value_message() -> None:
    with pytest.raises(MissingTemplateHelperWriteTargetError) as excinfo:
        template_number(name="Active HVAC Zones", state="{{ 1 }}")
    _check_snapshot("template_number_missing_set_value", _normalize(str(excinfo.value)))


def test_template_number_missing_set_value_has_location_and_fix() -> None:
    with pytest.raises(MissingTemplateHelperWriteTargetError) as excinfo:
        template_number(name="Active HVAC Zones", state="{{ 1 }}")
    msg = str(excinfo.value)
    assert "test_template_helper_write_target_error.py" in msg  # where (file)
    assert "set_value=" in msg  # names the missing kwarg
    assert "template_number(name=" in msg  # one-line fix example


def test_template_select_missing_select_option_message() -> None:
    with pytest.raises(MissingTemplateHelperWriteTargetError) as excinfo:
        template_select(name="House Scene", state="{{ 'home' }}", options="{{ ['home'] }}")
    _check_snapshot("template_select_missing_select_option", _normalize(str(excinfo.value)))


def test_template_select_missing_select_option_has_location_and_fix() -> None:
    with pytest.raises(MissingTemplateHelperWriteTargetError) as excinfo:
        template_select(name="House Scene", state="{{ 'home' }}", options="{{ ['home'] }}")
    msg = str(excinfo.value)
    assert "test_template_helper_write_target_error.py" in msg
    assert "select_option=" in msg
    assert "template_select(name=" in msg


def test_template_number_with_set_value_does_not_raise() -> None:
    template_number(
        name="Active HVAC Zones",
        state="{{ 1 }}",
        set_value={"action": "input_number.set_value", "data": {"value": "{{ value }}"}},
    )


def test_template_select_with_select_option_does_not_raise() -> None:
    template_select(
        name="House Scene",
        state="{{ 'home' }}",
        options="{{ ['home'] }}",
        select_option={"action": "input_select.select_option", "data": {"option": "{{ o }}"}},
    )


def test_template_sensor_and_binary_sensor_have_no_write_target_requirement() -> None:
    # Read-only domains: `state` alone is HA's required schema (module
    # docstring) -- must NOT raise `MissingTemplateHelperWriteTargetError`.
    template_sensor(name="Average Temp", state="{{ 1 }}")
    template_binary_sensor(name="Any Door Open", state="{{ true }}")
