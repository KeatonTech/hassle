"""The granular raw escape hatch: raw_trigger/raw_condition/raw_action (DESIGN §5.8).

Verbatim dicts pass through into the recorded stream of the active
automation/script; the containing object's whole-body `normalize_ha` pass
(already applied by the core compiler) normalizes a legacy `service:` action
to `action:`, while an inner trigger `platform:` discriminator is preserved
verbatim -- exactly as HA's own storage normalization behaves
(docs/internals/ha-api-notes.md §10.1).
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler import compile_bundle

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def test_raw_trigger_condition_action_passthrough() -> None:
    result = compile_bundle(FIXTURES / "raw_passthrough" / "bundle")
    obj = result.objects["automation:weird_device_trigger"].to_ha()

    assert obj["triggers"] == [{"platform": "device", "device_id": "abc123", "type": "turned_on"}]
    assert obj["conditions"] == [{"condition": "device", "device_id": "abc123", "type": "is_on"}]
    # service: -> action: via the containing object's normalize_ha pass.
    assert obj["actions"] == [{"action": "light.turn_on", "entity_id": "light.hallway"}]
    assert "service" not in obj["actions"][0]
