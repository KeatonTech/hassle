"""The `Finding` model (severity, file:line, message, fix) — DESIGN §9.

Findings are the validator's product surface: every Finding states what/where/fix in
one paragraph, same rubric as compile errors (`tests/snapshots/errors/`),
snapshot-tested under `tests/snapshots/findings/`.
"""

from __future__ import annotations

from hassle.registry.finding import Finding


def test_finding_str_is_one_paragraph_what_where_fix() -> None:
    f = Finding(
        code="unknown-entity",
        severity="error",
        file="automation.py",
        line=12,
        message="`light.halway` is not a known entity.",
        fix="Did you mean `light.hallway`?",
    )
    text = str(f)
    assert "light.halway" in text
    assert "automation.py:12" in text
    assert "Did you mean" in text
    # one paragraph: no embedded newlines
    assert "\n" not in text


def test_finding_without_span_omits_location_gracefully() -> None:
    f = Finding(
        code="unknown-entity",
        severity="error",
        file=None,
        line=None,
        message="`light.halway` is not a known entity.",
        fix="Did you mean `light.hallway`?",
    )
    text = str(f)
    assert "light.halway" in text
    # no dangling "at :None" or similar
    assert ":None" not in text


def test_finding_is_frozen_and_hashable() -> None:
    f1 = Finding(code="x", severity="error", file="a.py", line=1, message="m", fix="f")
    f2 = Finding(code="x", severity="error", file="a.py", line=1, message="m", fix="f")
    assert f1 == f2
    assert hash(f1) == hash(f2)
