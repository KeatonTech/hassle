"""Regression: the caller function-call rewrite must agree with the SAME
emit decision that picked `@shared_script` vs. the `@script` fallback for
the callee.

A real-world bundle hit this: a script fell back to `@script` -- so it
decompiled to a zero-parameter function -- but its caller still had its
`{"action": "script.<id>", "data": {...}}` action rewritten to a call passing
those kwargs, a call the zero-parameter function cannot accept. `TypeError`
at compile time.

Root cause: `codegen._build_resolver` (same-batch) and
`bundle_ops.build_script_refs` (cross-file) built a `CallTarget`/`ScriptRef`
for EVERY script, keyed only on whether it has any `fields` at all -- never
consulting whether the emitted decorator is actually `@shared_script`
(parameterized call site) or `@script` (no parameters, whatever the caller's
stored `data` was). Fix: the shared_script-vs-fallback decision must be
computed once and gate `CallTarget`/`ScriptRef` creation, not just used to
pick a field allow-list.

**Widened:** the original fix's example fallback shape (a field carrying
`name`/`selector` metadata, no `default`) is now ITSELF
`@shared_script`-expressible (`fields=` emitted verbatim, `None`-defaulted
signature) -- real HA-UI-authored scripts always carry this shape, so the
narrower rule made the whole feature inert on real
bundles. The tests below now use one of the two remaining genuine fallback
triggers (a field spec that isn't a dict at all -- malformed metadata) to
keep exercising the SAME coordination hazard the fix addresses, without
asserting a shape that's no longer a fallback case. (The other trigger, a
field name that isn't a valid Python identifier, is covered in
`test_decompile_shared_script_calls.py`; not reused here because it would
also make the caller's `data` dict key non-identifier-shaped, tripping an
unrelated, pre-existing `service()` codegen limitation on non-identifier
data keys -- out of scope for this fix.)
"""

from __future__ import annotations

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.decompiler.codegen import ScriptRef
from hassle.ir import parse

# A field spec that isn't a dict at all: one of the two remaining genuine
# @script fallback triggers post-widening (HA's UI never produces this
# shape, but the DSL must still round-trip it losslessly if it appears).
_FALLBACK_SCRIPT_CONFIG = {
    "alias": "Adjust TDBU blind",
    "fields": {
        "cover_top": "not-a-dict-spec",
    },
    "sequence": [
        {
            "action": "cover.set_cover_position",
            "target": {"entity_id": "cover.blind"},
            "data": {"position": "{{ cover_top }}"},
        }
    ],
}

_CALLER_AUTOMATION_CONFIG = {
    "id": "ui_cover_control_binding",
    "alias": "UI cover control binding",
    "triggers": [],
    "conditions": [],
    "actions": [
        {
            "action": "script.adjust_tdbu_blind",
            "data": {"cover_top": 42},
        }
    ],
}


def _fallback_script_and_caller() -> dict[str, object]:
    script_obj = parse(_FALLBACK_SCRIPT_CONFIG, kind="script", key_hint="adjust_tdbu_blind")
    automation_obj = parse(_CALLER_AUTOMATION_CONFIG, kind="automation")
    return {script_obj.object_key(): script_obj, automation_obj.object_key(): automation_obj}


def test_call_to_fallback_script_stays_service_same_batch() -> None:
    """The callee falls back to @script (malformed field spec) -- its
    caller, in the SAME decompile batch, must NOT be rewritten to a function
    call."""
    objects = _fallback_script_and_caller()
    source = decompile_bundle(objects)

    assert "@script(" in source
    assert "@shared_script(" not in source
    # The caller must keep the service() form -- never a bare call the
    # zero-parameter fallback function can't accept.
    assert "adjust_tdbu_blind(cover_top=" not in source
    assert "script.adjust_tdbu_blind" in source


def test_decompiled_fallback_pair_actually_compiles() -> None:
    """The missing bundle-level check that would have caught the field
    failure directly: decompile the pair and RECOMPILE it. A coordination bug
    between the emit decision and the caller rewrite raises a TypeError here
    (the exact failure mode seen in a real-world bundle)."""
    objects = _fallback_script_and_caller()
    source = decompile_bundle(objects)

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "objects.py").write_text(source, encoding="utf-8")
        # Must not raise -- this is the assertion the original PR was missing.
        result = compile_bundle(tmp)

    assert "automation:ui_cover_control_binding" in result.objects
    assert "script:adjust_tdbu_blind" in result.objects


def test_call_to_fallback_script_stays_service_cross_file() -> None:
    """Same hazard, cross-file: a ScriptRef built for a script that fell back
    to @script must not resolve the caller rewrite either."""
    automation_obj = parse(_CALLER_AUTOMATION_CONFIG, kind="automation")
    # A hand-built ScriptRef, exactly as the pull layer would supply for a
    # script it knows fell back to @script -- known_fields alone (populated
    # from the raw fields block) is NOT enough; the ref itself must not be
    # usable as a rewrite target for a fallback script.
    refs = {
        "adjust_tdbu_blind": ScriptRef(
            module="scripts.blinds",
            function_name="adjust_tdbu_blind",
            known_fields=frozenset({"cover_top"}),
            is_shared_script=False,
        )
    }
    source = decompile_bundle({automation_obj.object_key(): automation_obj}, script_refs=refs)

    assert "adjust_tdbu_blind(cover_top=" not in source
    assert "script.adjust_tdbu_blind" in source


def test_script_to_script_call_to_fallback_script_stays_service() -> None:
    """Script-to-script calls have the same hazard: a shared_script's own
    sequence calling a script that fell back to @script must also stay
    service(), not just automation-to-script calls."""
    caller_script_config = {
        "alias": "Cover Scene Runner",
        "fields": {},
        "sequence": [{"action": "script.adjust_tdbu_blind", "data": {"cover_top": 10}}],
    }
    caller_obj = parse(caller_script_config, kind="script", key_hint="cover_scene_runner")
    fallback_obj = parse(_FALLBACK_SCRIPT_CONFIG, kind="script", key_hint="adjust_tdbu_blind")
    objects = {caller_obj.object_key(): caller_obj, fallback_obj.object_key(): fallback_obj}

    source = decompile_bundle(objects)

    assert "adjust_tdbu_blind(cover_top=" not in source
    assert "script.adjust_tdbu_blind" in source

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "objects.py").write_text(source, encoding="utf-8")
        result = compile_bundle(tmp)  # must not raise

    assert "script:cover_scene_runner" in result.objects
    assert "script:adjust_tdbu_blind" in result.objects
