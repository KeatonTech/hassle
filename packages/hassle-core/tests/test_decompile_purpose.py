"""M2 — 2026.7 purpose-specific triggers/conditions decompile to `on()`/`met()`
with the right target helper (area/floor/label/device_id/entity) -- never
`raw_*` (per MILESTONES M2 hard requirements; these count toward the 90% gate).

The full hash-level round-trip for every one of these fixtures (incl. `id`
synthesis and legacy `platform:` modernization) is already asserted by
test_roundtrip_corpus.py over the whole corpus; these tests check the
qualitative decompile shape only, to avoid duplicating that logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hassle.decompiler import analyze_coverage, decompile_bundle
from hassle.ir import parse

CONFIGS_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "configs"

CASES = [
    ("automation_purpose_trigger_area_behavior_first.json", 'area("office")'),
    ("automation_purpose_trigger_label_behavior_all.json", 'label("security")'),
    ("automation_purpose_trigger_entity_target.json", '"binary_sensor.hall_motion"'),
    ("automation_purpose_trigger_renamed_legacy_key.json", '"sensor.wireless_device_battery"'),
    ("automation_purpose_condition.json", 'met("climate.is_target_temperature"'),
]


@pytest.mark.parametrize("filename,expected_snippet", CASES, ids=[c[0] for c in CASES])
def test_purpose_trigger_decompiles_without_raw(filename: str, expected_snippet: str) -> None:
    config = json.loads((CONFIGS_DIR / filename).read_text(encoding="utf-8"))
    obj = parse(config, kind="automation", key_hint=Path(filename).stem)
    objects = {obj.object_key(): obj}
    source = decompile_bundle(objects)

    assert expected_snippet in source, source

    report = analyze_coverage(objects)
    assert not any(e.object_key == obj.object_key() for e in report.exceptions), (
        f"{filename} must decompile with zero raw_* nodes"
    )


def test_purpose_trigger_floor_and_device_targets(tmp_path: Path) -> None:
    config = json.loads(
        (CONFIGS_DIR / "automation_purpose_trigger_floor_device.json").read_text(encoding="utf-8")
    )
    obj = parse(config, kind="automation", key_hint="floor_device")
    source = decompile_bundle({obj.object_key(): obj})

    assert 'floor("upstairs")' in source
    assert 'device_id("aaaabbbbccccdddd1111222233334444")' in source
    assert 'behavior="each"' in source
    objects = {obj.object_key(): obj}
    report = analyze_coverage(objects)
    assert not any(e.object_key == obj.object_key() for e in report.exceptions)
