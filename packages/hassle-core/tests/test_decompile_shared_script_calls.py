"""Scripts decompile as `@shared_script` (not `@script`) whenever the
script's own shape allows it, and
a caller's `{"action": "script.<id>", ...}` action decompiles to a real
function call `<fn_name>(<data as kwargs>, metadata={...})` when `<id>` is a
MANAGED script in the same decompile batch and every condition holds --
otherwise it falls back to today's `service()` form (never raw).

Covers:

1. `@shared_script` parity: a `ScriptConfig` whose `fields` are all
   signature-expressible (each field dict has no keys beyond `default`)
   decompiles to `@shared_script` with a typed function signature that
   recompiles to the identical script IR -- the terse form, no explicit
   `fields=` kwarg (DESIGN §5.6/§5.7 parity). A richer `fields` shape (e.g.
   `name`/`description`/`example`/`selector`) ALSO decompiles to
   `@shared_script` (widened), just with `fields=` emitted verbatim and every
   parameter
   `None`-defaulted -- see `test_decompile_shared_script_rich_fields.py` for
   that widened coverage. The `@script` fallback is now rare: only a field
   name that isn't a valid Python identifier, or a malformed `fields` value.
2. Caller rewrite conditions: every data key is a declared field, the action
   is the direct `script.<id>` form, and no extra keys beyond what the call
   reproduces (`target`/`data_template`/`response_variable`) -- otherwise
   `service()`.
3. Cross-file imports: `from scripts.<module> import <fn>` emitted when the
   callee lives in a different destination file (via the pull-supplied
   cross-reference table); same-file calls need no import.
4. Import-cycle detection: a script-to-script call cycle across files breaks
   the back-edge to `service()` with a one-line explanatory comment.
"""

from __future__ import annotations

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.decompiler.codegen import ScriptRef
from hassle.ir import parse, sha256_hash

# ---------------------------------------------------------------------------
# 1. @shared_script parity
# ---------------------------------------------------------------------------


def test_script_with_only_default_fields_decompiles_as_shared_script() -> None:
    config = {
        "alias": "Flash Lights",
        "icon": "mdi:alarm-light",
        "fields": {"times": {"default": 3}, "brightness": {"default": 255}},
        "sequence": [
            {
                "action": "light.turn_on",
                "data": {"entity_id": "light.all", "brightness": "{{ brightness }}"},
            },
        ],
    }
    obj = parse(config, kind="script", key_hint="flash_lights")
    source = decompile_bundle({obj.object_key(): obj})

    assert "@shared_script(" in source
    assert "@script(" not in source
    assert "def flash_lights(times=3, brightness=255):" in source or (
        "def flash_lights(" in source and "times" in source and "brightness" in source
    )


def test_shared_script_decompile_recompiles_to_identical_ir() -> None:
    config = {
        "alias": "Flash Lights",
        "fields": {"times": {"default": 3}},
        "sequence": [{"action": "light.turn_on", "data": {"brightness": "{{ times }}"}}],
    }
    obj = parse(config, kind="script", key_hint="flash_lights")
    source = decompile_bundle({obj.object_key(): obj})

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "scripts.py").write_text(source, encoding="utf-8")
        result = compile_bundle(tmp)

    assert len(result.objects) == 1
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(obj.to_ha())


def test_script_with_rich_field_metadata_decompiles_as_shared_script() -> None:
    # Widened: a field carrying name/description/example (not just default)
    # now ALSO decompiles to @shared_script -- fields= is emitted verbatim
    # (byte-stability by construction) and the parameter is
    # `TemplateExpr`-annotated, required (no default: every field-named
    # parameter is a runtime template marker in the body, never its Python
    # default's type, and the compiler always binds it regardless of whether
    # the signature declares a default at all).
    config = {
        "alias": "Script With Fields",
        "fields": {
            "light_entity": {
                "name": "Light Entity",
                "description": "The light to control",
                "example": "light.bedroom",
            },
        },
        "sequence": [],
    }
    obj = parse(config, kind="script", key_hint="script_with_fields")
    source = decompile_bundle({obj.object_key(): obj})

    assert "@shared_script(" in source
    assert "@script(" not in source
    assert "fields={" in source
    assert '"light_entity"' in source
    assert '"example": "light.bedroom"' in source
    assert "def script_with_fields(*, light_entity: TemplateExpr):" in source


def test_script_with_non_identifier_field_name_falls_back_to_plain_script() -> None:
    # The one remaining genuine @script fallback trigger: a field name that
    # cannot become a Python parameter at all (HA's UI never produces one,
    # but the DSL must still round-trip it losslessly if it appears).
    config = {
        "alias": "Weird Field Name",
        "fields": {"not-a-valid-identifier": {"name": "Weird"}},
        "sequence": [],
    }
    obj = parse(config, kind="script", key_hint="weird_field_name")
    source = decompile_bundle({obj.object_key(): obj})

    assert "@script(" in source
    assert "@shared_script(" not in source
    assert "fields={" in source


def test_script_with_no_fields_decompiles_as_shared_script() -> None:
    config = {"alias": "Movie Time", "sequence": []}
    obj = parse(config, kind="script", key_hint="movie_time")
    source = decompile_bundle({obj.object_key(): obj})

    assert "@shared_script(" in source
    assert "def movie_time():" in source


# ---------------------------------------------------------------------------
# 2. caller rewrite conditions
# ---------------------------------------------------------------------------


def _script_and_caller(call_action: dict[str, object]) -> dict[str, object]:
    script_obj = parse(
        {
            "alias": "Dismiss Notification",
            "fields": {"notification_id": {"default": ""}},
            "sequence": [
                {
                    "action": "persistent_notification.dismiss",
                    "data": {"notification_id": "{{ notification_id }}"},
                }
            ],
        },
        kind="script",
        key_hint="dismiss_notification",
    )
    automation_obj = parse(
        {
            "id": "1",
            "alias": "Dismiss Reminder",
            "triggers": [],
            "conditions": [],
            "actions": [call_action],
        },
        kind="automation",
    )
    return {script_obj.object_key(): script_obj, automation_obj.object_key(): automation_obj}


def test_direct_script_call_becomes_function_call() -> None:
    objects = _script_and_caller(
        {
            "action": "script.dismiss_notification",
            "data": {"notification_id": "guest_reminder"},
            "metadata": {},
        }
    )
    source = decompile_bundle(objects)

    assert 'dismiss_notification(notification_id="guest_reminder", metadata={})' in source
    assert '"script.dismiss_notification"' not in source
    assert "service(" not in source or "persistent_notification.dismiss" in source


def test_rewritten_call_recompiles_byte_identical() -> None:
    call_action = {
        "action": "script.dismiss_notification",
        "data": {"notification_id": "guest_reminder"},
        "metadata": {},
    }
    objects = _script_and_caller(call_action)
    source = decompile_bundle(objects)

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "objects.py").write_text(source, encoding="utf-8")
        result = compile_bundle(tmp)

    recompiled_automation = result.objects["automation:1"].to_ha()
    original_automation = objects["automation:1"].to_ha()  # type: ignore[union-attr]
    assert sha256_hash(recompiled_automation) == sha256_hash(original_automation)


def test_call_with_undeclared_data_key_falls_back_to_service() -> None:
    # `extra` isn't a declared field of dismiss_notification -- the rewrite
    # can't reproduce it via the function's kwargs, so this stays service().
    objects = _script_and_caller(
        {
            "action": "script.dismiss_notification",
            "data": {"notification_id": "guest_reminder", "extra": "nope"},
        }
    )
    source = decompile_bundle(objects)

    assert '"script.dismiss_notification"' in source or "'script.dismiss_notification'" in source
    assert "dismiss_notification(notification_id=" not in source


def test_call_with_target_falls_back_to_service() -> None:
    # target: isn't reproducible by the shared_script call form at all.
    objects = _script_and_caller(
        {
            "action": "script.dismiss_notification",
            "target": {"entity_id": "script.dismiss_notification"},
            "data": {"notification_id": "guest_reminder"},
        }
    )
    source = decompile_bundle(objects)

    assert "dismiss_notification(notification_id=" not in source


def test_call_to_service_turn_on_form_is_not_rewritten() -> None:
    # script.turn_on with entity_id/variables is a different, generic-caller
    # shape -- never rewritten (task spec: "script.turn_on stays service()").
    objects = _script_and_caller(
        {
            "action": "script.turn_on",
            "target": {"entity_id": "script.dismiss_notification"},
            "data": {"variables": {"notification_id": "guest_reminder"}},
        }
    )
    source = decompile_bundle(objects)

    assert "script.turn_on" in source
    assert "dismiss_notification(notification_id=" not in source


def test_call_to_unmanaged_script_stays_service() -> None:
    # The callee isn't in this decompile batch at all -- unknown, stays service().
    automation_obj = parse(
        {
            "id": "1",
            "alias": "Calls Someone Elses Script",
            "triggers": [],
            "conditions": [],
            "actions": [{"action": "script.not_in_this_batch", "data": {"x": 1}}],
        },
        kind="automation",
    )
    source = decompile_bundle({automation_obj.object_key(): automation_obj})

    assert "script.not_in_this_batch" in source
    assert "not_in_this_batch(" not in source


# ---------------------------------------------------------------------------
# 3. cross-file imports
# ---------------------------------------------------------------------------


def test_cross_file_call_emits_import_from_script_module() -> None:
    # The callee script itself isn't in THIS decompile_bundle() call -- only
    # the automation is; the cross-reference table (below) stands in for it,
    # exactly as a real pull batch would supply it for a script decompiled
    # into a different destination file.
    automation_obj = parse(
        {
            "id": "1",
            "alias": "Dismiss Reminder",
            "triggers": [],
            "conditions": [],
            "actions": [
                {
                    "action": "script.dismiss_notification",
                    "data": {"notification_id": "x"},
                }
            ],
        },
        kind="automation",
    )
    # The script lives in a DIFFERENT destination file than the caller: only
    # the automation is in this decompile_bundle() call; the cross-reference
    # table supplies where the script function actually lives.
    refs = {
        "dismiss_notification": ScriptRef(
            module="scripts.notify", function_name="dismiss_notification"
        )
    }
    source = decompile_bundle({automation_obj.object_key(): automation_obj}, script_refs=refs)

    assert "from scripts.notify import dismiss_notification" in source
    assert 'dismiss_notification(notification_id="x")' in source


def test_same_file_call_needs_no_import() -> None:
    objects = _script_and_caller(
        {"action": "script.dismiss_notification", "data": {"notification_id": "x"}}
    )
    refs = {
        "dismiss_notification": ScriptRef(
            module="scripts.notify", function_name="dismiss_notification"
        )
    }
    source = decompile_bundle(objects, script_refs=refs)

    assert "from scripts.notify import" not in source
    assert 'dismiss_notification(notification_id="x")' in source


def test_unknown_script_ref_stays_service_even_with_refs_table() -> None:
    automation_obj = parse(
        {
            "id": "1",
            "alias": "Calls Someone Elses Script",
            "triggers": [],
            "conditions": [],
            "actions": [{"action": "script.ghost", "data": {"x": 1}}],
        },
        kind="automation",
    )
    refs = {
        "dismiss_notification": ScriptRef(
            module="scripts.notify", function_name="dismiss_notification"
        )
    }
    source = decompile_bundle({automation_obj.object_key(): automation_obj}, script_refs=refs)

    assert "script.ghost" in source
    assert "from scripts" not in source


# ---------------------------------------------------------------------------
# 4. import-cycle detection
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# round-trip integrity: the new corpus fixture pair, decompiled TOGETHER
# ---------------------------------------------------------------------------


def test_corpus_fixture_pair_rewrite_round_trips_byte_identical() -> None:
    """`fixtures/configs/automation_calls_script_with_metadata.json` +
    `fixtures/configs/script_dismiss_notification.json` (mirrors a
    real-world dismiss_notification shape), decompiled TOGETHER so the caller
    rewrite actually fires -- compile(decompile(x)) stays byte-identical."""
    import json
    import tempfile
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    automation_config = json.loads(
        (repo_root / "fixtures/configs/automation_calls_script_with_metadata.json").read_text()
    )
    script_config = json.loads(
        (repo_root / "fixtures/configs/script_dismiss_notification.json").read_text()
    )
    automation_obj = parse(automation_config, kind="automation")
    script_obj = parse(script_config, kind="script", key_hint="dismiss_notification")
    objects = {automation_obj.object_key(): automation_obj, script_obj.object_key(): script_obj}

    source = decompile_bundle(objects)
    # The rewrite must actually have fired (else this test would be vacuous).
    assert "dismiss_notification(notification_id=" in source

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "objects.py").write_text(source, encoding="utf-8")
        result = compile_bundle(tmp)

    from hassle.ir import normalize_ha

    # Compared against normalize_ha(x), exactly like test_roundtrip_corpus
    # (compile(decompile(x)) == normalize_ha(x); these two corpus
    # fixtures use the legacy `service:` key, which normalizes to `action:`
    # regardless of this feature).
    assert sha256_hash(result.objects["automation:dismiss_reminder_automation"].to_ha()) == (
        sha256_hash(normalize_ha(automation_obj.to_ha(), kind="automation"))
    )
    assert sha256_hash(result.objects["script:dismiss_notification"].to_ha()) == sha256_hash(
        normalize_ha(script_obj.to_ha(), kind="script")
    )


def test_rich_field_corpus_fixture_pair_rewrite_round_trips_byte_identical() -> None:
    """A real-world-shape fixture --
    `fixtures/configs/script_call_to_action_notification.json` (every field
    carries selector/name/description, mirroring `call_to_action_
    notification`'s real shape) + `fixtures/configs/
    automation_calls_call_to_action_notification.json` (calls it with
    metadata:{}), decompiled TOGETHER so the caller rewrite actually fires --
    round-trips byte-identically AND the caller rewrites to a function call
    (not just falls back to service())."""
    import json
    import tempfile
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    automation_config = json.loads(
        (
            repo_root / "fixtures/configs/automation_calls_call_to_action_notification.json"
        ).read_text()
    )
    script_config = json.loads(
        (repo_root / "fixtures/configs/script_call_to_action_notification.json").read_text()
    )
    automation_obj = parse(automation_config, kind="automation")
    script_obj = parse(script_config, kind="script", key_hint="script_call_to_action_notification")
    objects = {automation_obj.object_key(): automation_obj, script_obj.object_key(): script_obj}

    source = decompile_bundle(objects)
    # The script decompiles as @shared_script (widened rule), and the
    # rewrite actually fires (else this test would be vacuous).
    assert "@shared_script(" in source
    assert "@script(" not in source
    assert "call_to_action_notification(" in source
    assert 'action="script.call_to_action_notification"' not in source

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "objects.py").write_text(source, encoding="utf-8")
        result = compile_bundle(tmp)

    from hassle.ir import normalize_ha

    assert sha256_hash(result.objects["automation:garage_door_opened_notify"].to_ha()) == (
        sha256_hash(normalize_ha(automation_obj.to_ha(), kind="automation"))
    )
    assert sha256_hash(
        result.objects["script:script_call_to_action_notification"].to_ha()
    ) == sha256_hash(normalize_ha(script_obj.to_ha(), kind="script"))


def test_script_to_script_call_cycle_breaks_back_edge_to_service() -> None:
    # script A (in file "a.py") calls script B (in file "b.py"); B calls A
    # back -- a genuine cross-file import cycle. One edge must break to
    # service(), with a one-line comment, so neither generated file needs a
    # circular import.
    script_a = parse(
        {
            "alias": "Script A",
            "fields": {},
            "sequence": [{"action": "script.script_b", "data": {}}],
        },
        kind="script",
        key_hint="script_a",
    )
    script_b = parse(
        {
            "alias": "Script B",
            "fields": {},
            "sequence": [{"action": "script.script_a", "data": {}}],
        },
        kind="script",
        key_hint="script_b",
    )
    refs = {
        "script_a": ScriptRef(
            module="scripts.a",
            function_name="script_a",
            known_fields=frozenset(),
            calls=frozenset({"script_b"}),
        ),
        "script_b": ScriptRef(
            module="scripts.b",
            function_name="script_b",
            known_fields=frozenset(),
            calls=frozenset({"script_a"}),
        ),
    }
    # Decompiled separately (different destination files) -- exactly the
    # cross-file shape that can cycle.
    source_a = decompile_bundle({script_a.object_key(): script_a}, script_refs=refs)
    source_b = decompile_bundle({script_b.object_key(): script_b}, script_refs=refs)

    # At least one direction must have broken to service() with an explanatory
    # comment (never both raw, never a circular import emitted in either file).
    a_calls_b_as_function = "script_b(" in source_a
    b_calls_a_as_function = "script_a(" in source_b
    assert not (a_calls_b_as_function and b_calls_a_as_function), (
        "both directions of a script-to-script call cycle were rewritten to "
        "function calls -- exactly one back-edge must break to service()"
    )
    broken_source = source_b if a_calls_b_as_function else source_a
    assert "service(" in broken_source
    assert "# hassle:" in broken_source and "cycle" in broken_source.lower()
