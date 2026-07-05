"""`ux/shared-script-rich-fields` (owner feedback): `@shared_script` gains a
``fields=`` kwarg carrying full stored HA field metadata (name/description/
selector/...), F3-additive. When present it wins VERBATIM over the
signature-derived fields dict -- byte-stability by construction, since the
decompiler must be able to re-emit the exact same ``fields=`` literal it
decompiled from.

The signature stays the ergonomic layer: every declared field becomes a
Python parameter, defaulted from the field's own ``"default"`` key when
present, else ``None`` -- never a required positional parameter (the
compiler always invokes a shared-script body with zero arguments to build
its sequence, DESIGN §5.6). ``param()`` and the caller's call-site kwargs
are validated against ``fields=``'s keys when supplied (the superset source
of truth), not just the Python signature.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler import UnknownFieldError, compile_bundle

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def test_shared_script_fields_kwarg_wins_verbatim_over_signature() -> None:
    result = compile_bundle(FIXTURES / "shared_script_rich_fields" / "bundle")
    script_obj = result.objects["script:notify_all"].to_ha()

    # The stored fields dict is EXACTLY the fields= literal, not a
    # signature-derived {"default": None} shape.
    assert script_obj["fields"]["title"]["name"] == "Title"
    assert script_obj["fields"]["title"]["selector"] == {"text": {}}
    assert script_obj["fields"]["message"]["description"] == "Notification message"
    assert "default" not in script_obj["fields"]["title"]


def test_shared_script_fields_kwarg_caller_rewrite_data() -> None:
    result = compile_bundle(FIXTURES / "shared_script_rich_fields" / "bundle")
    automation_obj = result.objects["automation:garage_door_opened"].to_ha()
    call = automation_obj["actions"][0]
    assert call["action"] == "script.notify_all"
    assert call["data"] == {
        "title": "Garage",
        "message": "Door opened",
        "action_button": "view",
        "action_button_icon": "mdi:garage-open",
        "tag": "garage_door",
    }
    assert call["metadata"] == {}


def test_param_inside_fields_kwarg_script_reads_runtime_field() -> None:
    result = compile_bundle(FIXTURES / "shared_script_rich_fields" / "bundle")
    script_obj = result.objects["script:notify_all"].to_ha()
    assert script_obj["sequence"][0]["data"]["title"] == "{{ title }}"
    assert script_obj["sequence"][0]["data"]["message"] == "{{ message }}"


def test_fields_kwarg_entry_with_no_default_key_still_compiles() -> None:
    # A fields= entry with no "default" key at all is no longer a fallback
    # cause: its Python parameter is None-defaulted (HA-side requiredness
    # lives in the metadata dict, not in whether the compiler can invoke the
    # function with zero args) -- the shared_script body must still be
    # callable with zero arguments to build its sequence.
    result = compile_bundle(FIXTURES / "shared_script_rich_fields" / "bundle")
    script_obj = result.objects["script:notify_all"].to_ha()
    assert "default" not in script_obj["fields"]["action_button_icon"]


def test_call_site_kwarg_validated_against_fields_keys_not_just_signature() -> None:
    # fields= is the superset source of truth for call-site validation: a
    # call-site kwarg name that isn't one of fields='s keys is rejected even
    # if it happens to bind against the underlying Python signature.
    case = FIXTURES / "shared_script_rich_fields_unknown_call_kwarg" / "bundle"
    with pytest.raises(UnknownFieldError) as excinfo:
        compile_bundle(case)
    message = str(excinfo.value)
    assert "untracked" in message
    assert "notify_all" in message
    assert "title" in message  # names the known fields
