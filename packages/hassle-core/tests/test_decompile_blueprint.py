"""Blueprint automations decompile to `blueprint_automation(...)` (DESIGN §5.8),
never to `raw_automation`. Stored `use_blueprint.input` (singular) maps back to
the DSL's ergonomic `inputs=` keyword (docs/ha-api-notes.md §10.5).
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import analyze_coverage, decompile_bundle
from hassle.ir import parse, sha256_hash

FIXTURE = (
    Path(__file__).resolve().parents[3] / "fixtures" / "configs" / "automation_blueprint_based.json"
)


def _load() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_blueprint_decompiles_to_blueprint_automation_call() -> None:
    config = _load()
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})

    assert "blueprint_automation(" in source
    assert "@raw_automation(" not in source
    assert 'use_blueprint="community/motion_activated_light.yaml"' in source
    assert "inputs=" in source
    # Stored input values ride through the `inputs=` mapping.
    assert "binary_sensor.hallway_motion" in source


def test_blueprint_roundtrips_and_counts_toward_coverage(tmp_path: Path) -> None:
    config = _load()
    obj = parse(config, kind="automation")
    objects = {obj.object_key(): obj}
    source = decompile_bundle(objects)

    report = analyze_coverage(objects)
    assert not any(e.object_key == obj.object_key() for e in report.exceptions), (
        "a blueprint automation must decompile with zero raw_* nodes"
    )

    (tmp_path / "bp.py").write_text(source, encoding="utf-8")
    result = compile_bundle(str(tmp_path))
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(config)
