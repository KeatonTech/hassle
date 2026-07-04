"""M1 integration smoke: one bundle exercising >=15 constructs must compile
cleanly and yield the expected object set + construct shapes.

The golden pair (fixtures/dsl/kitchen_sink_full) is checked by the parametrized
golden-pair suite; this test additionally asserts the constructs are actually
present (a golden that silently lost the choose/parallel/macro would still be
"a valid golden", so we pin the shapes explicitly here).
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle_core.compiler import compile_bundle

_BUNDLE = Path(__file__).resolve().parents[3] / "fixtures" / "dsl" / "kitchen_sink_full" / "bundle"


def test_kitchen_sink_object_set() -> None:
    result = compile_bundle(_BUNDLE)
    keys = set(result.objects)
    assert keys == {
        "input_boolean:guest_mode",
        "input_number:target_brightness",
        "script:flash_lights",
        "automation:kitchen_sink",
    }


def test_kitchen_sink_constructs_present() -> None:
    result = compile_bundle(_BUNDLE)
    auto = result.objects["automation:kitchen_sink"].to_ha()
    blob = json.dumps(auto)

    # purpose trigger with area target + behavior + options.for
    assert '"trigger": "motion.detected"' in blob
    assert '"area_id": "living_room"' in blob
    assert '"behavior": "first"' in blob
    # classic + state-with-options triggers
    assert '"trigger": "numeric_state"' in blob
    assert '"id": "guest_on"' in blob
    # combinators + template condition
    assert '"condition": "and"' in blob and '"condition": "not"' in blob
    assert '"condition": "template"' in blob
    # nested control flow
    assert '"if":' in blob and '"then":' in blob and '"else":' in blob
    assert '"choose":' in blob and '"default":' in blob
    assert '"repeat":' in blob and '"count": 2' in blob
    assert '"parallel":' in blob
    assert '"wait_template":' in blob
    # macro inlined (announce -> notify + fire_event both present)
    assert '"action": "notify.mobile_app"' in blob
    assert '"event": "hassle_announced"' in blob
    # shared-script call
    assert '"action": "script.flash_lights"' in blob
    # service response_variable folded in
    assert '"response_variable": "forecast"' in blob
    # raw_action passthrough (the raw delay dict)
    assert '"delay": {"seconds": 5}' in blob
    # template expression value
    assert "states('input_number.target_brightness') | float" in blob
    # action primitives
    assert '"stop": "done"' in blob


def test_kitchen_sink_script_has_fields_from_signature() -> None:
    result = compile_bundle(_BUNDLE)
    script = result.objects["script:flash_lights"].to_ha()
    # @shared_script derives fields from the signature (count default 3)
    assert "fields" in script
    assert script["fields"]["count"]["default"] == 3
