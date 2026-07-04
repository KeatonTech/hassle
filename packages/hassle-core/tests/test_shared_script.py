"""M1 test 3 — `@shared_script` compiles to a script object + a call action.

DESIGN §5.6/§5.7: `@shared_script` registers a real HA script (fields derived
from the function signature, defaults -> field defaults); calling the
decorated name from within another automation/script records a
`script.turn_on`-style call action (matching the corpus's stored shape for
invoking a script — a plain `action: script.<object_id>` call), never a
re-run of the function body. `param("name")` inside the body is a runtime
reference to the script's own field; a `param()` for a name absent from the
signature is a snapshot-tested error (M1 test 5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler import UnknownParamError, compile_bundle

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def test_shared_script_compiles_to_script_and_call() -> None:
    result = compile_bundle(FIXTURES / "shared_script_call" / "bundle")

    # The script itself: fields from the signature, defaults preserved,
    # sequence built from the (undecorated) function body.
    script_obj = result.objects["script:flash_lights"].to_ha()
    assert script_obj["alias"] == "Flash lights"
    assert script_obj["icon"] == "mdi:alarm-light"
    assert script_obj["fields"] == {
        "times": {"default": 3},
        "brightness": {"default": 255},
    }
    seq_actions = [a["action"] for a in script_obj["sequence"]]
    assert seq_actions == ["light.turn_on", "light.turn_off"]
    # param("brightness") compiled to a runtime template read, not the
    # compile-time Python default.
    assert script_obj["sequence"][0]["data"]["brightness"] == "{{ brightness }}"

    # The caller: a script.turn_on-style call action, not a re-run of the body.
    automation_obj = result.objects["automation:guest_arrived"].to_ha()
    call = automation_obj["actions"][0]
    assert call["action"] == "script.flash_lights"
    assert call["data"] == {"times": 5, "brightness": 128}


def test_shared_script_field_defaults_from_signature() -> None:
    result = compile_bundle(FIXTURES / "shared_script_call" / "bundle")
    script_obj = result.objects["script:flash_lights"].to_ha()
    assert script_obj["fields"]["times"]["default"] == 3


def test_param_unknown_name_raises() -> None:
    case = FIXTURES / "shared_script_param_unknown" / "bundle"
    with pytest.raises(UnknownParamError) as excinfo:
        compile_bundle(case)
    message = str(excinfo.value)
    assert "param('brightness')" in message
    assert "scripts.py:9" in message
    assert "times" in message  # names the known fields


def test_param_outside_shared_script_raises() -> None:
    from hassle.compiler import NoParamContextError
    from hassle.compiler.scripts import param

    with pytest.raises(NoParamContextError):
        param("anything")
