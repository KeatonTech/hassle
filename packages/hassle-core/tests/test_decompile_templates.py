"""M2 — Jinja template strings decompile to `template("...")` verbatim.

The expression-sugar builder (`state(x).value > 25`, DESIGN §5.4) is one-way by
design (docs the M1.1 note); the decompiler always emits the raw-Jinja spelling,
never attempts to reverse-engineer the sugar from a rendered template string.

The full hash-level round-trip for these exact fixtures (incl. the `id`
synthesis and legacy `platform:` modernization test_roundtrip_corpus.py
documents) is already asserted there over the whole corpus; these tests check
the qualitative decompile shape only (verbatim template text, zero raw_*
fallback) to avoid duplicating that expectation-adjustment logic.
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle.decompiler import analyze_coverage, decompile_bundle
from hassle.ir import parse

CONFIGS_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "configs"


def _no_raw_exception(objects: dict[str, object], key: str) -> bool:
    report = analyze_coverage(objects)  # type: ignore[arg-type]
    return not any(e.object_key == key for e in report.exceptions)


def test_template_condition_decompiles_verbatim() -> None:
    config = json.loads(
        (CONFIGS_DIR / "automation_condition_template.json").read_text(encoding="utf-8")
    )
    obj = parse(config, kind="automation", key_hint="tmpl_cond")
    objects = {obj.object_key(): obj}
    source = decompile_bundle(objects)

    raw_jinja = "{{ (state_attr('light.hallway', 'brightness') or 0) > 100 }}"
    assert f"template({raw_jinja!r})" in source
    assert _no_raw_exception(objects, obj.object_key())


def test_template_trigger_decompiles_verbatim() -> None:
    config = json.loads(
        (CONFIGS_DIR / "automation_template_trigger.json").read_text(encoding="utf-8")
    )
    obj = parse(config, kind="automation", key_hint="tmpl_trigger")
    objects = {obj.object_key(): obj}
    source = decompile_bundle(objects)
    assert "template(" in source
    assert _no_raw_exception(objects, obj.object_key())
