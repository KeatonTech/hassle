"""Regression for a real bug found while fixing M10 round 4 (docs/
ha-api-notes.md §26.10): `run_goldens`'s drift check used plain `!=` on
parsed JSON structures, which is blind to an `int`-vs-`float` difference
(`{"min": 0} == {"min": 0.0}` is `True` in Python) -- so a compiler change
that turned `0` into `0.0` was reported as "up to date" by both the
check-only path and `--update` (neither wrote anything, since neither
believed anything had drifted). Golden files exist to catch exactly this
kind of byte-level drift (R3), so the comparison must be type-strict.
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle_dev.goldens import run_goldens

_BUNDLE_SOURCE = """
from hassle import input_number

thing = input_number(id="thing", name="Thing", min=0, max=8, step=1)
"""


def _make_case(dsl_dir: Path, *, expected_min: object) -> Path:
    case_dir = dsl_dir / "float_drift_case"
    bundle_dir = case_dir / "bundle"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "helpers.py").write_text(_BUNDLE_SOURCE, encoding="utf-8")
    expected_ir = {
        "input_number:thing": {
            "name": "Thing",
            "id": "thing",
            "min": expected_min,
            "max": 8,
            "step": 1,
        }
    }
    expected_path = case_dir / "expected_ir.json"
    expected_path.write_text(json.dumps(expected_ir, indent=2) + "\n", encoding="utf-8")
    return case_dir


def test_int_vs_float_drift_is_detected_not_silently_accepted(tmp_path: Path) -> None:
    # The compiled IR has `min: 0` (an int, from the DSL literal); the golden
    # claims `min: 0.0` (a float) -- these must NOT be treated as matching,
    # even though `0 == 0.0`.
    dsl_dir = tmp_path / "fixtures" / "dsl"
    _make_case(dsl_dir, expected_min=0.0)

    report = run_goldens(dsl_dir, update=False)
    assert report.checked == 1
    assert report.drifted == ["float_drift_case"]
    assert report.updated == []


def test_matching_types_are_not_flagged_as_drift(tmp_path: Path) -> None:
    dsl_dir = tmp_path / "fixtures" / "dsl"
    _make_case(dsl_dir, expected_min=0)

    report = run_goldens(dsl_dir, update=False)
    assert report.checked == 1
    assert report.drifted == []


def test_update_rewrites_a_float_drifted_golden(tmp_path: Path) -> None:
    dsl_dir = tmp_path / "fixtures" / "dsl"
    case_dir = _make_case(dsl_dir, expected_min=0.0)

    report = run_goldens(dsl_dir, update=True)
    assert report.updated == ["float_drift_case"]

    rewritten = json.loads((case_dir / "expected_ir.json").read_text(encoding="utf-8"))
    assert rewritten["input_number:thing"]["min"] == 0
    assert isinstance(rewritten["input_number:thing"]["min"], int)
