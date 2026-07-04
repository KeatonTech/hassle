"""M2 — Jinja template strings decompile to `template("...")` verbatim.

The expression-sugar builder (`state(x).value > 25`, DESIGN §5.4) is one-way by
design (docs the M1.1 note); the decompiler always emits the raw-Jinja spelling,
never attempts to reverse-engineer the sugar from a rendered template string.
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import analyze_coverage, decompile_bundle
from hassle.ir import parse, sha256_hash

CONFIGS_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "configs"


def test_template_condition_decompiles_verbatim(tmp_path: Path) -> None:
    config = json.loads(
        (CONFIGS_DIR / "automation_condition_template.json").read_text(encoding="utf-8")
    )
    obj = parse(config, kind="automation", key_hint="tmpl_cond")
    objects = {obj.object_key(): obj}
    source = decompile_bundle(objects)

    raw_jinja = "{{ (state_attr('light.hallway', 'brightness') or 0) > 100 }}"
    assert f"template({raw_jinja!r})" in source
    assert "raw_condition" not in source

    report = analyze_coverage(objects)
    assert not any(e.object_key == obj.object_key() for e in report.exceptions)

    (tmp_path / "obj.py").write_text(source, encoding="utf-8")
    result = compile_bundle(str(tmp_path))
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(config)


def test_template_trigger_decompiles_verbatim(tmp_path: Path) -> None:
    config = json.loads(
        (CONFIGS_DIR / "automation_template_trigger.json").read_text(encoding="utf-8")
    )
    obj = parse(config, kind="automation", key_hint="tmpl_trigger")
    source = decompile_bundle({obj.object_key(): obj})
    assert "template(" in source
    assert "raw_trigger" not in source

    (tmp_path / "obj.py").write_text(source, encoding="utf-8")
    result = compile_bundle(str(tmp_path))
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(config)
