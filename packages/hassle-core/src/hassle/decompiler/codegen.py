"""IR object -> DSL Python source (DESIGN §7.3): the top-level assembler.

``decompile_bundle`` takes every IR object in a compiled result (or a manifest
of any subset) and produces one deterministic, ruff-formatted Python module.
``decompile_object`` produces the source for a single object (a `def` or a
bare ``blueprint_automation(...)`` call), used both by ``decompile_bundle`` and
by the splice codemod (which replaces one object's def in an existing file).

Deterministic ordering (R8): objects are emitted sorted by object key, so the
same IR always produces byte-identical source regardless of dict iteration
order.
"""

from __future__ import annotations

import subprocess
from typing import Any, cast

from hassle.decompiler.actions import INDENT, decompile_action
from hassle.decompiler.exprs import decompile_condition, decompile_trigger, render_literal
from hassle.ir.keys import HELPER_DOMAINS
from hassle.ir.models import AutomationConfig, HelperConfig, IRObject, ScriptConfig
from hassle.ir.normalize import normalize_ha

# Every builder name a decompiled bundle might reference. Rather than compute a
# precise per-bundle import list (which would make splice's "leave the rest of
# the file untouched" harder to reason about — a change to one object could
# ripple into the shared import line), a fresh whole-bundle decompile imports
# the full frozen F3 surface it might need; unused names are harmless (ruff's
# default lint selection does flag unused imports, but the decompiler's own
# generated files are not linted in CI, only ruff-*formatted*).
_ALL_BUILDER_NAMES: tuple[str, ...] = (
    "all_of",
    "any_of",
    "area",
    "automation",
    "blueprint_automation",
    "calendar",
    "choose",
    "counter",
    "delay",
    "device_id",
    "else_then",
    "event",
    "fire_event",
    "floor",
    "geo_location",
    "homeassistant_shutdown",
    "homeassistant_start",
    "hours",
    "if_then",
    "input_boolean",
    "input_button",
    "input_datetime",
    "input_number",
    "input_select",
    "input_text",
    "label",
    "met",
    "minutes",
    "mqtt",
    "not_",
    "numeric_state",
    "on",
    "only_if",
    "parallel",
    "persistent_notification",
    "raw_action",
    "raw_automation",
    "raw_condition",
    "raw_trigger",
    "repeat_count",
    "repeat_for_each",
    "repeat_until",
    "repeat_while",
    "schedule",
    "script",
    "seconds",
    "service",
    "state",
    "stop",
    "sun",
    "tag",
    "template",
    "time",
    "time_pattern",
    "timer",
    "trigger_condition",
    "variables",
    "wait_for",
    "wait_template",
    "webhook",
    "when",
    "zone",
)


def _identifier(object_key: str) -> str:
    """Derive a snake_case Python identifier from an object key.

    ``"<kind>:<identity>"`` -> a safe identifier: non-identifier characters
    become underscores; a leading digit gets a leading underscore (Python
    identifiers can't start with a digit).
    """
    _, _, identity = object_key.partition(":")
    raw = identity or object_key
    chars = [c if c.isalnum() else "_" for c in raw]
    ident = "".join(chars)
    if not ident or ident[0].isdigit():
        ident = f"_{ident}"
    return ident


def _blueprint_source(obj: AutomationConfig, ident: str) -> str | None:
    body = obj.to_ha()
    raw_use_blueprint = body.get("use_blueprint")
    if not isinstance(raw_use_blueprint, dict):
        return None
    use_blueprint = cast("dict[str, Any]", raw_use_blueprint)
    if set(body) - {"id", "alias", "description", "use_blueprint"}:
        return None  # extra top-level fields we don't model on a blueprint object
    path = use_blueprint.get("path")
    raw_inputs = use_blueprint.get("input")
    if not isinstance(path, str) or not isinstance(raw_inputs, dict):
        return None
    inputs = cast("dict[str, Any]", raw_inputs)
    if set(use_blueprint) != {"path", "input"}:
        return None
    kwargs = [f"id={obj.identity!r}", f'use_blueprint="{path}"']
    if body.get("alias") is not None:
        kwargs.append(f"alias={body['alias']!r}")
    if body.get("description") is not None:
        kwargs.append(f"description={body['description']!r}")
    kwargs.append(f"inputs={render_literal(inputs)}")
    return f"{ident} = blueprint_automation({', '.join(kwargs)})\n"


def _raw_automation_source(obj: AutomationConfig, ident: str) -> str:
    """Whole-object fallback: ``@raw_automation(id=...)`` over a function
    returning the verbatim (already-normalized) body (DESIGN §5.8)."""
    body = dict(normalize_ha(obj.to_ha(), kind="automation"))
    body.pop("id", None)
    body_src = render_literal(body)
    return f"@raw_automation(id={obj.identity!r})\ndef {ident}():\n{INDENT}return {body_src}\n"


def _automation_source(obj: AutomationConfig, ident: str) -> str:
    # Normalize legacy singular-form input (trigger/condition/action, service:)
    # to the canonical plural schema before decompiling (§7.1: "the decompiler
    # accepts both forms as input") -- codegen only ever has to reason about one
    # shape.
    body = dict(normalize_ha(obj.to_ha(), kind="automation"))
    blueprint_src = _blueprint_source(obj, ident)
    if blueprint_src is not None:
        return blueprint_src

    # Some real-world configs use shapes `@automation` structurally cannot
    # express at all -- e.g. the ancient inline single-trigger form (`platform`/
    # `entity_id`/`to` directly at the automation's top level, no `trigger:`
    # wrapper -- fixtures/configs/automation_legacy_platform_naming.json,
    # docs/ha-api-notes.md's M2 findings). `@automation`'s option set has no
    # room for arbitrary top-level fields like this; decompiling the whole
    # object to `raw_automation` is the only lossless option (DESIGN §5.8, I3).
    _ALLOWED_TOP_LEVEL = {
        "id",
        "alias",
        "description",
        "mode",
        "max",
        "max_exceeded",
        "initial_state",
        "triggers",
        "conditions",
        "actions",
        "trigger_variables",
        "variables",
    }
    if set(body) - _ALLOWED_TOP_LEVEL:
        return _raw_automation_source(obj, ident)

    func_name = ident
    decorator_kwargs: list[str] = []
    # Only emit an explicit id= when the body id differs from what the function
    # name would already produce (bundle.py: `options.get("id") or func.__name__`)
    # -- keeps the common case (`id == snake_case(alias-derived name)`) terse.
    body_id = body.pop("id", None)
    if body_id is not None and str(body_id) != func_name:
        decorator_kwargs.append(f"id={body_id!r}")
    for key in ("alias", "description", "mode", "max", "max_exceeded", "initial_state"):
        if key in body:
            decorator_kwargs.append(f"{key}={body.pop(key)!r}")
    # Any remaining scalar option (trigger_variables, variables, ...) not
    # explicitly modeled above still round-trips via a generic kwarg.
    triggers = body.pop("triggers", [])
    conditions = body.pop("conditions", [])
    actions = body.pop("actions", [])
    for key, value in body.items():
        decorator_kwargs.append(f"{key}={render_literal(value)}")

    lines: list[str] = []
    lines.append(f"@automation({', '.join(decorator_kwargs)})")
    lines.append(f"def {func_name}():")
    body_lines: list[str] = []

    # `raw_trigger`/`raw_condition` are recording *verbs* (they call
    # record_trigger/record_condition themselves and return None) -- they
    # cannot be nested as arguments inside when(...)/only_if(...). Any typed
    # (non-raw) triggers/conditions are collected into one when()/only_if()
    # call; raw ones become separate statements alongside it, in original order
    # (whether emitted before or after doesn't change the recorded set, since
    # `when`/`only_if`/`raw_trigger`/`raw_condition` all append to the same
    # list -- but preserving relative order keeps the generated source legible
    # and, on a splice, minimizes the visible diff).
    if triggers:
        typed: list[str] = []
        raw_stmts: list[str] = []
        for trig in triggers:
            src = (
                decompile_trigger(cast("dict[str, Any]", trig)) if isinstance(trig, dict) else None
            )
            if src is not None:
                typed.append(src)
            else:
                raw_stmts.append(f"raw_trigger({render_literal(trig)})")
        if typed:
            if len(typed) == 1:
                body_lines.append(f"when({typed[0]})")
            else:
                body_lines.append("when(")
                for src in typed:
                    body_lines.append(f"{INDENT}{src},")
                body_lines.append(")")
        body_lines.extend(raw_stmts)

    if conditions:
        typed = []
        raw_stmts = []
        for cond in conditions:
            src = (
                decompile_condition(cast("dict[str, Any]", cond))
                if isinstance(cond, dict)
                else None
            )
            if src is not None:
                typed.append(src)
            else:
                raw_stmts.append(f"raw_condition({render_literal(cond)})")
        if typed:
            if len(typed) == 1:
                body_lines.append(f"only_if({typed[0]})")
            else:
                body_lines.append("only_if(")
                for src in typed:
                    body_lines.append(f"{INDENT}{src},")
                body_lines.append(")")
        body_lines.extend(raw_stmts)

    for action in actions:
        if isinstance(action, dict):
            body_lines.extend(decompile_action(action))
        else:
            body_lines.append(f"raw_action({render_literal(action)})")

    if not body_lines:
        body_lines = ["pass"]

    for line in body_lines:
        lines.append(f"{INDENT}{line}" if line else line)
    return "\n".join(lines) + "\n"


def _script_source(obj: ScriptConfig, ident: str) -> str:
    body = dict(normalize_ha(obj.to_ha(), kind="script"))
    object_id = obj.identity or ident
    decorator_kwargs: list[str] = []
    if str(object_id) != ident:
        decorator_kwargs.append(f"id={object_id!r}")
    for key in ("alias", "mode", "icon", "fields"):
        if key in body:
            decorator_kwargs.append(f"{key}={render_literal(body.pop(key))}")
    sequence = body.pop("sequence", [])
    for key, value in body.items():
        decorator_kwargs.append(f"{key}={render_literal(value)}")

    lines = [f"@script({', '.join(decorator_kwargs)})", f"def {ident}():"]
    body_lines: list[str] = []
    for action in sequence:
        if isinstance(action, dict):
            body_lines.extend(decompile_action(action))
        else:
            body_lines.append(f"raw_action({render_literal(action)})")
    if not body_lines:
        body_lines = ["pass"]
    for line in body_lines:
        lines.append(f"{INDENT}{line}" if line else line)
    return "\n".join(lines) + "\n"


_HELPER_BUILDER_NAMES = {domain: domain for domain in HELPER_DOMAINS}


def _helper_source(obj: HelperConfig, ident: str) -> str:
    body = dict(obj.to_ha())
    domain = obj.kind()
    builder = _HELPER_BUILDER_NAMES[domain]
    kwargs = [f"{k}={render_literal(v)}" for k, v in body.items()]
    return f"{ident} = {builder}({', '.join(kwargs)})\n"


def decompile_object(object_key: str, obj: IRObject) -> str:
    """Decompile a single IR object to its DSL source (a `def` or an assignment).

    No trailing blank-line separation is added here (the caller controls
    inter-object spacing); the returned text ends with exactly one newline.
    """
    ident = _identifier(object_key)
    if isinstance(obj, AutomationConfig):
        return _automation_source(obj, ident)
    if isinstance(obj, ScriptConfig):
        return _script_source(obj, ident)
    if isinstance(obj, HelperConfig):
        return _helper_source(obj, ident)
    raise TypeError(f"cannot decompile object of type {type(obj).__name__}")  # pragma: no cover


def _format_with_ruff(source: str) -> str:
    """Run ``ruff format -`` over ``source`` (deterministic, no network)."""
    proc = subprocess.run(
        ["ruff", "format", "-"],
        input=source,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        # ruff format failing on generated code is a decompiler bug, not a
        # user-facing situation; surface the unformatted source rather than
        # silently swallowing a formatting error.
        return source
    return proc.stdout


def decompile_bundle(objects: dict[str, IRObject]) -> str:
    """Decompile every object in ``objects`` into one ruff-formatted module.

    Deterministic (R8): objects are emitted in sorted-key order regardless of
    the input mapping's iteration order, so the same IR always produces
    byte-identical source.
    """
    import_line = f"from hassle import {', '.join(_ALL_BUILDER_NAMES)}\n"
    parts = [import_line, ""]
    for key in sorted(objects):
        parts.append(decompile_object(key, objects[key]))
    source = "\n".join(parts) + "\n"
    return _format_with_ruff(source)
