"""M2.1 — teach the decompiler numeric_state's `attribute=` field (M1.1 addition).

M1.1 added ``attribute=`` to the ``numeric_state()`` builder (both trigger and
condition forms, ``hassle.compiler.triggers.NumericStateExpr`` -- reads an
entity attribute instead of its main state) after M2 branched, so the M2
decompiler never learned to reproduce it: a stored ``numeric_state`` trigger/
condition carrying ``attribute`` currently falls back to ``raw_trigger``/
``raw_condition``, costing ``fixtures/configs/automation_math_shade_sun.json``
its spot in the DSL-coverage clean set even though the compile side has
supported it since M1.1.
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle.decompiler import analyze_coverage, decompile_bundle
from hassle.decompiler.exprs import decompile_condition, decompile_trigger
from hassle.ir import parse

CONFIGS_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "configs"


def test_numeric_state_trigger_with_attribute_decompiles_without_raw() -> None:
    body = {
        "trigger": "numeric_state",
        "entity_id": "sun.sun",
        "attribute": "elevation",
        "above": 0,
    }
    src = decompile_trigger(body)
    assert src is not None, "numeric_state trigger with attribute= fell back to raw"
    assert src == "numeric_state('sun.sun', attribute='elevation', above=0)"


def test_numeric_state_condition_with_attribute_decompiles_without_raw() -> None:
    body = {
        "condition": "numeric_state",
        "entity_id": "sun.sun",
        "attribute": "elevation",
        "above": 0,
    }
    src = decompile_condition(body)
    assert src is not None, "numeric_state condition with attribute= fell back to raw"
    assert src == "numeric_state('sun.sun', attribute='elevation', above=0)"


def test_automation_math_shade_sun_decompiles_with_zero_raw_nodes() -> None:
    # The full hash-level round-trip for this exact fixture (incl. id
    # synthesis and the time_pattern platform:->trigger: modernization) is
    # already asserted by test_roundtrip_corpus.py over the whole corpus;
    # this test checks the qualitative decompile shape only (attribute=
    # reproduced, zero raw_* fallback) to avoid duplicating that logic.
    config = json.loads(
        (CONFIGS_DIR / "automation_math_shade_sun.json").read_text(encoding="utf-8")
    )
    key_hint = "automation_math_shade_sun"
    obj = parse(config, kind="automation", key_hint=key_hint)
    objects = {obj.object_key(): obj}
    source = decompile_bundle(objects)

    assert "attribute='elevation'" in source, source

    report = analyze_coverage(objects)
    assert not any(e.object_key == obj.object_key() for e in report.exceptions), (
        f"automation_math_shade_sun should decompile with zero raw_* nodes, "
        f"got exceptions: {report.exceptions}"
    )
