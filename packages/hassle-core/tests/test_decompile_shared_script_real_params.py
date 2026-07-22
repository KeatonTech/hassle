"""Decompiling a shared-script's own body reads its fields bare.

Inside a `@shared_script`'s own sequence, a `"{{ <field> }}"` data value whose
name is exactly one of the script's own fields decompiles to the bare
parameter name (a real-world `dismiss_notification` shape); a larger
invertible expression containing a field read decompiles through the
bounded Jinja inverter with fields bound as bare parameters too; anything the
inverter can't invert keeps the raw string (the raw escape hatch fallback).
The shared-script field context must never leak into automation
decompilation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hassle.compiler import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import parse, sha256_hash


def _recompile_sha(obj_config: dict[str, object], *, kind: str, key_hint: str) -> tuple[str, str]:
    """Decompile ``obj_config`` (one IR object) then recompile the decompiled
    source, returning (decompiled_source, sha_of_recompiled_ir)."""
    obj = parse(obj_config, kind=kind, key_hint=key_hint)
    source = decompile_bundle({obj.object_key(): obj})
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "scripts.py").write_text(source, encoding="utf-8")
        result = compile_bundle(tmp)
    assert len(result.objects) == 1
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(obj.to_ha())
    return source, sha256_hash(recompiled.to_ha())


def test_bare_field_read_decompiles_to_bare_parameter_shape() -> None:
    """A real-world `dismiss_notification` shape: stored data
    `{"notification_id": "{{ tag }}"}` with field `tag` decompiles to
    `tag=tag` and recompiles byte-identically."""
    config = {
        "alias": "Dismiss notification",
        "fields": {"tag": {"default": ""}},
        "sequence": [
            {
                "action": "persistent_notification.dismiss",
                "data": {"notification_id": "{{ tag }}"},
            }
        ],
    }
    source, _ = _recompile_sha(config, kind="script", key_hint="dismiss_notification")
    # TemplateExpr-annotated, field_default(...)-defaulted (body-true typing,
    # see `_shared_script_signature`'s docstring) -- not `tag: str = ""`.
    assert 'def dismiss_notification(*, tag: TemplateExpr = field_default("")):' in source
    assert "notification_id=tag" in source
    assert "{{ tag }}" not in source  # not the raw-string fallback


def test_composed_field_expression_decompiles_through_inverter() -> None:
    """A larger invertible expression over a field (`concat`'s `~`-join)
    decompiles through the bounded Jinja inverter with the field bound as a
    bare parameter, not just a single bare read."""
    config = {
        "alias": "Dismiss tagged",
        "fields": {"tag": {"default": ""}},
        "sequence": [
            {
                "action": "persistent_notification.dismiss",
                "data": {"notification_id": "{{ tag ~ '_x' }}"},
            }
        ],
    }
    source, _ = _recompile_sha(config, kind="script", key_hint="dismiss_tagged")
    assert 'concat(tag, "_x")' in source


def test_non_invertible_template_keeps_raw_string_fallback() -> None:
    """A template the bounded inverter can't parse at all keeps the raw
    string (the raw escape hatch fallback) -- never partial/incorrect output."""
    config = {
        "alias": "Weird template",
        "fields": {"tag": {"default": ""}},
        "sequence": [
            {
                "action": "persistent_notification.dismiss",
                # `now()` isn't in the inverter's bounded grammar at all.
                "data": {"notification_id": "{{ now() }}"},
            }
        ],
    }
    source, _ = _recompile_sha(config, kind="script", key_hint="weird_template")
    assert '"{{ now() }}"' in source


def test_field_context_never_leaks_into_automation_decompile() -> None:
    """An automation's OWN template data (never inside a shared-script body)
    must decompile exactly as before -- no bare-parameter rewrite, since
    there is no enclosing shared-script field context at all. This is the
    same-batch version of the leak concern: a script with field `tag` is
    decompiled ALONGSIDE an automation whose own (unrelated) `variables:`
    read is also named `tag` -- the automation's `{{ tag }}` must stay
    `var("tag")`, never rewritten to a bare `tag` just because some OTHER
    object in the same batch happens to declare a field of that name.
    """
    script_config = {
        "alias": "Dismiss notification",
        "fields": {"tag": {"default": ""}},
        "sequence": [
            {
                "action": "persistent_notification.dismiss",
                "data": {"notification_id": "{{ tag }}"},
            }
        ],
    }
    automation_config = {
        "id": "notify_from_variable",
        "alias": "Notify from variable",
        "triggers": [{"trigger": "state", "entity_id": "input_boolean.guest_mode", "to": "off"}],
        "conditions": [],
        "actions": [
            {
                "action": "notify.mobile_app",
                "data": {"message": "{{ tag }}"},
            }
        ],
        "variables": {"tag": "hello"},
    }
    script_obj = parse(script_config, kind="script", key_hint="dismiss_notification")
    automation_obj = parse(automation_config, kind="automation", key_hint="notify_from_variable")
    source = decompile_bundle(
        {script_obj.object_key(): script_obj, automation_obj.object_key(): automation_obj}
    )
    # The script's OWN field read is bare (as proven above)...
    assert "notification_id=tag" in source
    # ...but the automation's unrelated data value of the SAME literal Jinja
    # text is decompiled exactly as it always was (a plain service-call
    # data value never goes through the field-aware inverter outside a
    # shared-script body) -- NOT rewritten to a bare (meaningless, undefined
    # outside a shared-script body) name just because some OTHER object in
    # the same batch happens to declare a field called `tag`.
    assert 'message="{{ tag }}"' in source
    assert "message=tag" not in source
