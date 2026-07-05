"""`ux/shared-script-calls` (owner feedback): the `@shared_script` caller-side
wrapper must be able to carry `metadata`/`alias`/`enabled` step options on the
recorded call action, so the decompiler's function-call rewrite (a caller
`script.<id>` action becomes `<fn_name>(<data kwargs>, metadata={...})`) can
recompile to a byte-identical `{"action": "script.<id>", "data": {...},
"metadata": {...}}` shape (F3-additive extension of `ScriptCallAction`,
`hassle/compiler/scripts.py`).
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler import compile_bundle

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def test_shared_script_call_carries_metadata() -> None:
    result = compile_bundle(FIXTURES / "shared_script_call_metadata" / "bundle")
    automation_obj = result.objects["automation:dismiss_reminder"].to_ha()
    call = automation_obj["actions"][0]
    assert call["action"] == "script.dismiss_notification"
    assert call["data"] == {"notification_id": "guest_reminder"}
    assert call["metadata"] == {}


def test_shared_script_call_metadata_omitted_when_not_passed() -> None:
    result = compile_bundle(FIXTURES / "shared_script_call" / "bundle")
    automation_obj = result.objects["automation:guest_arrived"].to_ha()
    call = automation_obj["actions"][0]
    assert "metadata" not in call


def test_shared_script_call_carries_alias_and_enabled() -> None:
    result = compile_bundle(FIXTURES / "shared_script_call_metadata" / "bundle")
    automation_obj = result.objects["automation:dismiss_reminder"].to_ha()
    call = automation_obj["actions"][0]
    assert call["alias"] == "Dismiss the guest reminder"
    assert call["enabled"] is False
