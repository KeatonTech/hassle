"""`hassle_cli.plan_render` must not let an HA-supplied string (an
`object_key`'s identity half, a conflict's raw `local`/`remote` config, the
decompiled 3-way diff text) carry a raw ANSI escape sequence into the
terminal -- see `test_terminal_sanitization.py` and
`hassle_cli.render`'s module docstring for why `markup=False` alone does not
already guarantee this.

Regression companion to `test_conflict_ux.py::
test_dsl_diff_list_literal_is_not_mangled_by_rich_markup` (same `_FakeEntry`/
`_FakePlan` pattern, direct against `render_plan` so a future change to the
surrounding CLI/snapshot machinery can't mask a regression here).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from unittest.mock import patch

from rich.console import Console

from hassle.sync import PlanAction
from hassle_cli import plan_render

CLEAR_SCREEN = "\x1b[2J"
SET_TITLE = "\x1b]0;title\x07"


@dataclass
class _FakeConflict:
    local: dict[str, object]
    remote: dict[str, object]


@dataclass
class _FakeEntry:
    object_key: str
    kind: str
    action: PlanAction
    local: dict[str, object] | None
    remote: dict[str, object] | None
    conflict: _FakeConflict | None = None


@dataclass
class _FakePlan:
    entries: list[_FakeEntry]


def _render(entry: _FakeEntry) -> str:
    buf = io.StringIO()
    console = Console(file=buf, no_color=True, force_terminal=False, width=100)
    with patch.object(plan_render, "is_modernization_only_diff", return_value=False):
        plan_render.render_plan(console, _FakePlan(entries=[entry]))
    return buf.getvalue()


def test_object_key_ansi_escape_is_stripped() -> None:
    # Previously rendered with markup ON and no sanitization at all (the
    # audit's "line ~47" finding) -- the identity half of `object_key` can be
    # HA-supplied.
    entry = _FakeEntry(
        object_key=f"automation:hall_light{CLEAR_SCREEN}",
        kind="automation",
        action=PlanAction.UPDATE,
        local=None,
        remote=None,
    )
    output = _render(entry)
    assert "\x1b" not in output
    assert "hall_light" in output


def test_conflict_diff_text_ansi_escape_is_stripped() -> None:
    local = {
        "id": "a",
        "alias": f"A{CLEAR_SCREEN}",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [],
        "actions": [],
    }
    remote = {**local, "alias": f"A (remote edit){SET_TITLE}"}
    entry = _FakeEntry(
        object_key="automation:a",
        kind="automation",
        action=PlanAction.CONFLICT,
        local=local,
        remote=remote,
        conflict=_FakeConflict(local=local, remote=remote),
    )
    output = _render(entry)
    assert "\x1b" not in output
    assert "\x07" not in output
    # The diff itself must still be legible -- sanitizing must not eat the
    # non-control content around the escape sequence.
    assert "remote edit" in output


def test_conflict_no_diff_fallback_ansi_escape_is_stripped() -> None:
    # Forces the "(local)"/"(remote)" raw fallback (`dsl_diff` returns "" when
    # both sides decompile identically) rather than the unified-diff path
    # above. Uses a plain string (not a dict) for `local`/`remote` -- a raw
    # Python `dict` repr already backslash-escapes control characters in its
    # string values (`repr`), which would mask the very bug being tested for;
    # a bare string interpolated via `str()` carries the raw bytes straight
    # through, which is what this fallback's `f"  {local}"` actually does.
    local = f"same{CLEAR_SCREEN}"
    remote = f"same{CLEAR_SCREEN}"
    entry = _FakeEntry(
        object_key="automation:a",
        kind="automation",
        action=PlanAction.CONFLICT,
        local=local,  # type: ignore[arg-type]
        remote=remote,  # type: ignore[arg-type]
        conflict=_FakeConflict(local=local, remote=remote),
    )
    with patch.object(plan_render, "dsl_diff", return_value=""):
        buf = io.StringIO()
        console = Console(file=buf, no_color=True, force_terminal=False, width=100)
        with patch.object(plan_render, "is_modernization_only_diff", return_value=False):
            plan_render.render_plan(console, _FakePlan(entries=[entry]))
        output = buf.getvalue()
    assert "\x1b" not in output
    assert "same" in output
