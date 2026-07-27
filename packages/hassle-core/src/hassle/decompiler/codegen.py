"""IR object -> DSL Python source (DESIGN §7.3): the top-level assembler.

``decompile_bundle`` takes every IR object in a compiled result (or a manifest
of any subset) and produces one deterministic, ruff-formatted Python module.
``decompile_object`` produces the source for a single object (a `def` or a
bare ``blueprint_automation(...)`` call), used both by ``decompile_bundle`` and
by the splice codemod (which replaces one object's def in an existing file).

Deterministic ordering: objects are emitted sorted by object key, so the same
IR always produces byte-identical source regardless of dict iteration order
(output must be byte-stable, with no wall-clock or other nondeterminism).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from hassle.compiler.enums import MaxExceeded, Mode
from hassle.decompiler.actions import (
    INDENT,
    CallResolver,
    CallTarget,
    decompile_action,
    indent_lines,
    shared_script_field_context,
)
from hassle.decompiler.dashboards import dashboard_source
from hassle.decompiler.exprs import decompile_condition, decompile_trigger, render_literal
from hassle.ir.keys import GROUP_DOMAINS, HELPER_DOMAINS, TEMPLATE_DOMAINS, slugify
from hassle.ir.models import (
    AutomationConfig,
    DashboardConfig,
    GroupHelperConfig,
    HelperConfig,
    IRObject,
    ScriptConfig,
    TemplateHelperConfig,
)
from hassle.ir.normalize import normalize_ha

if TYPE_CHECKING:
    from hassle.registry.snapshot import RegistrySnapshot

# A fresh whole-bundle decompile always emits a star import of the frozen DSL
# surface (`hassle.__all__` defines it, so pyright resolves `from hassle
# import *` fine) rather than an enumerated builder-name list -- see
# docs/internals/decompiler.md for why. The entity-registry accessor import
# stays explicit (DESIGN §5.3: `from hassle.registry import entities as e`,
# its own dedicated, non-`__all__` entry point).
_STAR_IMPORT_LINE = "from hassle import *\n"
_ENTITIES_IMPORT_LINE = "from hassle.registry import entities as e\n"

# `hassle.cards`/`hassle.cards.cond` are dedicated, non-star entry points
# (§5.1: card type names collide with frozen DSL names, e.g. `area`/
# `calendar`/`light`), so a dashboard's `c.tile(...)`/`with c.vertical_stack():`
# / `cond.state(...)` calls need their own import lines -- emitted ONLY when
# actually used, mirroring `TemplateExpr`'s own plain-substring-check
# convention below (simpler and just as deterministic as threading a used-flag
# out through `decompile_object`). `c`/`cond` are never emitted as any other
# kind of identifier by this decompiler, so the regexes can't false-positive
# against automation/script output.
_CARDS_IMPORT_LINE = "from hassle import cards as c\n"
_COND_IMPORT_LINE = "from hassle.cards import cond\n"
_USES_CARDS_NAMESPACE_RE = re.compile(r"(?<![\w.])c\.\w")
_USES_COND_NAMESPACE_RE = re.compile(r"(?<![\w.])cond\.\w")

# `mode=`/`max_exceeded=` enums: a recognized value decompiles to
# `Mode.RESTART`/`MaxExceeded.SILENT`; an unrecognized one (a future HA value
# this DSL doesn't know about yet) falls back to the raw string -- never a
# decompiler error.
_MODE_VALUES = {member.value: member for member in Mode}
_MAX_EXCEEDED_VALUES = {member.value: member for member in MaxExceeded}


def _mode_or_max_exceeded_src(key: str, value: Any) -> str:
    """Render a `mode`/`max_exceeded` option value: the enum member's
    attribute access (`Mode.RESTART`) for a recognized string value, else a
    plain literal (covers both an unrecognized string and a non-string value,
    which should never happen in practice but must never crash the decompiler
    either way)."""
    if key == "mode" and isinstance(value, str) and value in _MODE_VALUES:
        return f"Mode.{_MODE_VALUES[value].name}"
    if key == "max_exceeded" and isinstance(value, str) and value in _MAX_EXCEEDED_VALUES:
        return f"MaxExceeded.{_MAX_EXCEEDED_VALUES[value].name}"
    return render_literal(value)


@dataclass(frozen=True)
class ScriptRef:
    """Where a MANAGED script's decompiled function actually lives.

    Supplied by the pull layer (``hassle_cli.bundle_ops``, which already
    computes each object's destination ``source_path`` for placement, DESIGN
    §7.3) as the cross-reference table ``{script_object_id: ScriptRef}`` for
    every managed script in the current pull batch -- not just the ones being
    decompiled in this one :func:`decompile_bundle` call. A script in the SAME
    call needs no import (it's just a same-module function call); one is
    supplied for cross-file calls, where the decompiler must also emit
    ``from <module> import <function_name>``.

    ``known_fields`` is the callee's own declared field names, needed here too
    (not just for same-batch calls) to check "every data key is a declared
    field" for a cross-file callee this call never actually parses. Defaults
    to "anything goes" (``None``) so a hand-built ``ScriptRef`` (e.g. in a
    test) isn't forced to enumerate it; real pull-layer callers always supply
    it.

    ``is_shared_script`` and ``calls`` exist to avoid rewriting a caller into
    a call the callee can't accept, and to avoid emitting a circular import
    between two generated files -- see docs/internals/decompiler.md for the
    full rationale. ``is_shared_script=False`` means the ref must never
    resolve a rewrite, checked before ``known_fields``. A leaf script (calls
    nothing) passes an empty frozenset for ``calls``.
    """

    module: str
    function_name: str
    known_fields: frozenset[str] | None = None
    is_shared_script: bool = True
    calls: frozenset[str] = field(default_factory=lambda: cast("frozenset[str]", frozenset()))


def _reserved_names() -> dict[str, int]:
    """Seed a fresh ``used_names`` collision tracker with every name a
    generated module's ``from hassle import *`` / ``entities as e`` imports
    bring into scope, so an alias-derived function name that happens to match
    a builder verb (e.g. an automation aliased "Wait Template", which slugs to
    `wait_template` -- the same name as the `wait_template()` action builder)
    gets the same deterministic `_2` suffix as a same-alias collision, rather
    than silently shadowing the builder inside its own function body."""
    import hassle

    names = {name: 1 for name in hassle.__all__}
    names["e"] = 1
    return names


def _identifier(object_key: str) -> str:
    """Derive a snake_case Python identifier from an object key.

    ``"<kind>:<identity>"`` -> a safe identifier: non-identifier characters
    become underscores; a leading digit gets a leading underscore (Python
    identifiers can't start with a digit).

    Used for helper variable names (the id is right there already, DESIGN
    §7.3) and as the id-derived fallback for automations/scripts with no
    ``alias``.
    """
    _, _, identity = object_key.partition(":")
    raw = identity or object_key
    chars = [c if c.isalnum() else "_" for c in raw]
    ident = "".join(chars)
    if not ident or ident[0].isdigit():
        ident = f"_{ident}"
    return ident


def _slug_identifier(text: str) -> str:
    """Slugify ``text`` (``hassle.ir.keys.slugify``) into a valid Python
    identifier: a leading digit gets a leading underscore (Python identifiers
    can't start with a digit; ``slugify`` itself has no such guard since its
    other caller, HA storage-collection ids, allows a digit-leading id)."""
    slug = slugify(text)
    if slug[0].isdigit():
        slug = f"_{slug}"
    return slug


def _dedupe_name(base: str, used_names: dict[str, int]) -> str:
    """Return ``base``, or ``base`` with a deterministic ``_2``/``_3``/...
    suffix if ``base`` (or an earlier-suffixed form of it) was already used --
    tracked in ``used_names`` (mutated in place), keyed by the un-suffixed
    base name so repeated collisions on the same alias count up correctly."""
    count = used_names.get(base, 0) + 1
    used_names[base] = count
    if count == 1:
        return base
    return f"{base}_{count}"


def _sanitized_identity(object_key: str) -> str:
    """Non-identifier characters in the object key's identity portion become
    underscores -- no leading-digit guard (unlike :func:`_identifier`): this
    is only ever used behind a fixed alpha prefix (``automation_``/
    ``script_``), which already makes a leading digit into a valid
    identifier, so guarding here too would just double up the underscore."""
    _, _, identity = object_key.partition(":")
    raw = identity or object_key
    return "".join(c if c.isalnum() else "_" for c in raw)


def _automation_name(obj: AutomationConfig, used_names: dict[str, int]) -> str:
    """DESIGN §7.3: the function name derives from ``alias`` (slugified), not
    from ``id`` -- the id kwarg is preserved verbatim regardless (an existing
    object's HA id is never changed), this only changes what the generated
    Python identifier looks like. No alias -> ``automation_<id>`` fallback."""
    alias = obj.alias
    if isinstance(alias, str) and alias.strip():
        base = _slug_identifier(alias)
    else:
        base = f"automation_{_sanitized_identity(obj.object_key())}"
    return _dedupe_name(base, used_names)


def script_function_name(obj: ScriptConfig, used_names: dict[str, int]) -> str:
    """The Python function name a script decompiles to: same alias-derivation
    rule as automations, ``script_<id>`` fallback.

    Public: the pull layer (``hassle_cli.bundle_ops``) needs this exact name
    to build the cross-reference table for the caller-side function-call
    rewrite -- shared here rather than duplicated, since it must stay in
    lockstep with what this module's own ``_script_source`` actually emits.
    """
    alias = obj.alias
    if isinstance(alias, str) and alias.strip():
        base = _slug_identifier(alias)
    else:
        base = f"script_{_sanitized_identity(obj.object_key())}"
    return _dedupe_name(base, used_names)


def dashboard_function_name(obj: DashboardConfig, used_names: dict[str, int]) -> str:
    """The Python function name a dashboard decompiles to (docs/internals/
    dashboards-design.md §6.2): ``slugify(meta.title)``, falling back to
    ``slugify(url_path)``, falling back to ``dashboard_<n>`` -- the same
    dedup-suffix convention as automations/scripts, and computed identically
    regardless of whether the object ends up a typed ``@dashboard`` or the
    whole-object ``@raw_dashboard`` fallback (naming and the raw-ladder
    decision are orthogonal, exactly as for automations/blueprints)."""
    meta = obj.meta
    meta_dict = cast("dict[str, Any]", meta) if isinstance(meta, dict) else None
    title = meta_dict.get("title") if meta_dict is not None else None
    if isinstance(title, str) and title.strip():
        base = _slug_identifier(title)
    else:
        url_path = meta_dict.get("url_path") if meta_dict is not None else None
        if isinstance(url_path, str) and url_path.strip():
            base = _slug_identifier(url_path)
        else:
            base = f"dashboard_{_sanitized_identity(obj.object_key())}"
    return _dedupe_name(base, used_names)


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


def _automation_source(
    obj: AutomationConfig, ident: str, resolver: CallResolver | None = None
) -> str:
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
    # docs/internals/ha-api-notes.md). `@automation`'s option set has no room for
    # arbitrary top-level fields like this; decompiling the whole object to
    # `raw_automation` is the only lossless option (DESIGN §5.8: compile(decompile(x))
    # must equal x for any config).
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
    # Only emit an explicit id= when the id differs from what the function name
    # would already produce (bundle.py: `options.get("id") or func.__name__`)
    # -- keeps the common case terse. The id itself is never touched (an
    # existing object's HA id is never changed), only whether the (now
    # alias-derived) function name happens to make it redundant to spell out.
    # `obj.identity` (not just a literal `id` field in the body) is the true
    # identity -- it also covers a fixture whose id was supplied extrinsically
    # (`key_hint`, e.g. the corpus's hand-authored docs-example fixtures with
    # no `id` field at all): now that the function name is alias-derived
    # rather than id-derived, that identity would otherwise silently
    # disappear instead of round-tripping via id=.
    body.pop("id", None)
    body_id = obj.identity
    if body_id is not None and str(body_id) != func_name:
        decorator_kwargs.append(f"id={body_id!r}")
    for key in ("alias", "description", "mode", "max", "max_exceeded", "initial_state"):
        if key in body:
            decorator_kwargs.append(f"{key}={_mode_or_max_exceeded_src(key, body.pop(key))}")
    triggers = body.pop("triggers", [])
    conditions = body.pop("conditions", [])
    actions = body.pop("actions", [])

    # `triggers=` decorator metadata is the canonical decompiled form
    # (DESIGN §5.3/§5.5, docs/internals/dsl-extensions.md): subscription metadata lives
    # in the decorator, Python-idiom style (cf. `@app.route`).
    # Only TYPED triggers can be nested as a kwarg's list-literal expression --
    # `raw_trigger(...)` is a recording *verb* (it calls `record_trigger` itself
    # and returns None), so it cannot be an element of a list literal. A raw
    # trigger therefore stays a body statement, emitted first (before
    # conditions/actions), in original order -- it still composes correctly
    # with the decorator's `triggers=` list (bundle.py's `compile_registered`
    # records the decorator list first, then runs the body, so a raw_trigger()
    # body statement still lands after the decorator's typed triggers; since
    # the original recorded order interleaved them in the single `triggers`
    # list, preserving typed-then-raw here can only reorder relative to each
    # other, never drop data -- compile(decompile(x)) == x holds via the
    # underlying builder/verb semantics, not literal position).
    typed_trigger_srcs: list[str] = []
    raw_trigger_stmts: list[str] = []
    for trig in triggers:
        src = decompile_trigger(cast("dict[str, Any]", trig)) if isinstance(trig, dict) else None
        if src is not None:
            typed_trigger_srcs.append(src)
        else:
            raw_trigger_stmts.append(f"raw_trigger({render_literal(trig)})")
    if typed_trigger_srcs:
        if len(typed_trigger_srcs) == 1:
            decorator_kwargs.append(f"triggers=[{typed_trigger_srcs[0]}]")
        else:
            triggers_arg_lines = ["triggers=["]
            for src in typed_trigger_srcs:
                triggers_arg_lines.append(f"{INDENT}{src},")
            triggers_arg_lines.append("]")
            decorator_kwargs.append("\n".join(triggers_arg_lines))

    # Any remaining scalar option (trigger_variables, variables, ...) not
    # explicitly modeled above still round-trips via a generic kwarg.
    for key, value in body.items():
        decorator_kwargs.append(f"{key}={render_literal(value)}")

    lines: list[str] = []
    lines.append(f"@automation({', '.join(decorator_kwargs)})")
    lines.append(f"def {func_name}():")
    body_lines: list[str] = []

    # `raw_trigger`/`raw_condition` are recording *verbs* (they call
    # record_trigger/record_condition themselves and return None) -- they
    # cannot be nested as arguments inside when(...)/only_if(...)/`triggers=`.
    # Any raw_trigger() leftover is emitted plain, right at the top of the
    # body (no section header -- see below).
    #
    # No `# --- conditions ---`/`# --- actions ---` section comments: with
    # triggers living in the decorator and conditions emitted as the
    # `with only_if(...):` block form below whenever any are present, the
    # body's structure is already self-describing -- decorator = when,
    # only_if block = gate, plain statements = do -- so a section comment
    # would never point at anything a reader couldn't already tell at a
    # glance.
    body_lines.extend(raw_trigger_stmts)

    # Whenever this automation has ANY conditions, the block form
    # (`with only_if(...): <every action>`) is the canonical decompiled
    # shape -- it's the compiled IR's only accurate rendering, since HA's
    # automation-level conditions gate every action regardless of where in
    # the body they're textually written; the block form makes that visually
    # true instead of a bare `only_if(...)` call above a flat action list,
    # which reads like an empty `if`. No conditions -> no block at all,
    # actions are plain top-level statements.
    typed_conditions: list[str] = []
    raw_condition_stmts: list[str] = []
    for cond in conditions:
        src = decompile_condition(cast("dict[str, Any]", cond)) if isinstance(cond, dict) else None
        if src is not None:
            typed_conditions.append(src)
        else:
            raw_condition_stmts.append(f"raw_condition({render_literal(cond)})")

    action_lines: list[str] = []
    for action in actions:
        if isinstance(action, dict):
            action_lines.extend(decompile_action(action, resolver=resolver))
        else:
            action_lines.append(f"raw_action({render_literal(action)})")
    if not action_lines:
        action_lines = ["pass"]

    if conditions:
        # `raw_condition(...)` is a recording verb -- it cannot nest inside
        # `only_if(...)`'s own argument list, so any raw conditions are
        # emitted as their own statements immediately before the block opens
        # (original relative order preserved, same rationale as the
        # pre-existing raw-condition handling: legible source, minimal splice
        # diff). This is safe for item 1's "every action must be inside the
        # block" invariant regardless of order: `raw_condition()` only ever
        # appends to the automation's conditions list, never its actions.
        body_lines.extend(raw_condition_stmts)
        if len(typed_conditions) <= 1:
            args = typed_conditions[0] if typed_conditions else ""
            body_lines.append(f"with only_if({args}):")
        else:
            body_lines.append("with only_if(")
            for src in typed_conditions:
                body_lines.append(f"{INDENT}{src},")
            body_lines.append("):")
        body_lines.extend(indent_lines(action_lines))
    else:
        body_lines.extend(action_lines)

    if not body_lines:
        body_lines = ["pass"]

    for line in body_lines:
        lines.append(f"{INDENT}{line}" if line else line)
    return "\n".join(lines) + "\n"


# A script `fields` entry is *terse-signature*-expressible (the narrower rule:
# DESIGN §5.6/§5.7 parity with `hassle.compiler.scripts._fields_from_signature`)
# only if its own dict has EXACTLY the key `default` (never more, never fewer)
# -- in which case the decompiler can omit an explicit `fields=` kwarg
# entirely: the signature alone reproduces it. Any other shape (rich metadata,
# or no `default` at all) still decompiles to `@shared_script` via the wider
# rule below (real HA-UI-authored scripts carry `name`/`description`/
# `selector`/... on every field, making the terse form rare in practice on
# real bundles) -- `fields=` is emitted verbatim and every field still
# becomes a `None`-defaulted parameter.
_SIGNATURE_EXPRESSIBLE_FIELD_KEYS = frozenset({"default"})


def _fields_terse_signature_expressible(fields: Any) -> bool:
    if not isinstance(fields, dict):
        return False
    fields_dict = cast("dict[str, Any]", fields)
    for spec in fields_dict.values():
        if not isinstance(spec, dict):
            return False
        spec_dict = cast("dict[str, Any]", spec)
        if frozenset(spec_dict) != _SIGNATURE_EXPRESSIBLE_FIELD_KEYS:
            return False
    return True


def fields_signature_expressible(fields: Any) -> bool:
    """Whether a script's ``fields`` block can become a ``@shared_script``
    at all -- the ONLY remaining ``@script`` fallback triggers are a field
    name that isn't a valid Python identifier (can't become a matching
    parameter name at all) or a malformed ``fields`` value (not a dict of
    dicts) -- HA's UI never produces either, so the ``@script`` fallback is
    rare in practice on real bundles.

    Public: this is THE shared_script-vs-``@script``-fallback emit decision,
    and it must be the single source of truth for every caller that needs to
    know which one a given script decompiled to -- both same-batch
    (:func:`_build_resolver` below) and cross-file
    (`hassle_cli.bundle_ops.build_script_refs`) MUST gate `CallTarget`/
    `ScriptRef` creation on this, not just consult the raw field names, or a
    caller can be rewritten to call a function that was actually emitted with
    zero parameters -- a script whose fields forced the ``@script`` fallback
    has NO call-site kwargs at all, regardless of what its stored ``fields``
    names are.
    """
    if fields is None:
        return True  # no fields at all -- trivially expressible (empty signature)
    if not isinstance(fields, dict):
        return False
    fields_dict = cast("dict[str, Any]", fields)
    for name, spec in fields_dict.items():
        if not isinstance(spec, dict):
            return False
        if not name.isidentifier():
            return False
    return True


def script_is_shared_script(obj: ScriptConfig) -> bool:
    """Whether ``obj`` decompiles to ``@shared_script`` (vs. the ``@script``
    fallback) -- the single source of truth for the emit decision, from the
    IR object directly."""
    fields = obj.to_ha().get("fields")
    return fields_signature_expressible(fields)


def _shared_script_signature(fields: Any) -> str:
    """Build the parameter list for a ``@shared_script`` function definition
    from its ``fields`` block: ``name: TemplateExpr`` for a field with no
    declared default (a required field -- no ``=...`` at all, since the
    compiler always binds it to its ``param(name)`` marker before the body
    runs regardless), else ``name: TemplateExpr = field_default(<default>)``.

    Every parameter is emitted KEYWORD-ONLY (a leading ``*,``): a required
    field (no default) can legally follow a defaulted one in the stored
    ``fields`` dict's own order, but plain positional-or-keyword Python
    parameters cannot. See docs/internals/decompiler.md for the full
    rationale on ``TemplateExpr`` typing and keyword-only parameters.

    Only ever called when :func:`fields_signature_expressible` accepted
    ``fields``.
    """
    if not isinstance(fields, dict) or not fields:
        # No fields at all (``None``, or an explicit empty ``{}``) -- an
        # empty signature; a bare leading ``*,`` with nothing after it would
        # itself be a `SyntaxError` (keyword-only marker needs >= 1 param
        # following it), so this case must return an empty string, not `"*"`.
        return ""
    fields_dict = cast("dict[str, Any]", fields)
    params: list[str] = ["*"]
    for name, spec in fields_dict.items():
        spec_dict = cast("dict[str, Any]", spec) if isinstance(spec, dict) else {}
        if "default" not in spec_dict:
            params.append(f"{name}: TemplateExpr")
            continue
        default = spec_dict["default"]
        params.append(f"{name}: TemplateExpr = field_default({default!r})")
    return ", ".join(params)


def _script_source(obj: ScriptConfig, ident: str, resolver: CallResolver | None) -> str:
    body = dict(normalize_ha(obj.to_ha(), kind="script"))
    object_id = obj.identity or ident
    fields = body.get("fields")
    as_shared_script = fields_signature_expressible(fields)
    # The TERSE form (no explicit fields= kwarg -- DESIGN §5.6/§5.7 parity)
    # only for the narrow original shape (every field spec is exactly
    # {"default": ...}); any other shared_script-expressible shape (rich
    # metadata, or a field with no default) emits fields= verbatim so
    # recompiling reproduces the exact stored metadata, not just its
    # inferred defaults.
    terse = as_shared_script and _fields_terse_signature_expressible(fields)

    decorator_kwargs: list[str] = []
    if str(object_id) != ident:
        decorator_kwargs.append(f"id={object_id!r}")
    # fields stays in `decorator_keys` (so it's popped from `body` and
    # rendered in the same alias/mode/icon/fields order) only for the
    # @script fallback -- `@shared_script`'s own fields= (verbatim, non-terse
    # case) is appended separately below, from the `fields` local captured
    # above, not from `body` (which the shared_script branches strip it out
    # of unconditionally either way).
    decorator_keys = (
        ("alias", "mode", "icon") if as_shared_script else ("alias", "mode", "icon", "fields")
    )
    for key in decorator_keys:
        if key in body:
            decorator_kwargs.append(f"{key}={_mode_or_max_exceeded_src(key, body.pop(key))}")
    if as_shared_script:
        body.pop("fields", None)
        if not terse and fields is not None:
            decorator_kwargs.append(f"fields={render_literal(fields)}")
    sequence = body.pop("sequence", [])
    for key, value in body.items():
        decorator_kwargs.append(f"{key}={_mode_or_max_exceeded_src(key, value)}")

    decorator_name = "shared_script" if as_shared_script else "script"
    signature = _shared_script_signature(fields) if as_shared_script else ""
    lines = [f"@{decorator_name}({', '.join(decorator_kwargs)})", f"def {ident}({signature}):"]
    body_lines: list[str] = []
    # A `@shared_script`'s own field names are active while decompiling ITS
    # sequence -- a data value that's exactly a field read (or a larger
    # invertible expression over fields) decompiles to the bare parameter
    # form instead of the raw `"{{ ... }}"` string. `None` for the `@script`
    # fallback (no signature-bound fields to speak of) -- the bare-parameter
    # rewrite only ever makes sense for an actual `@shared_script`.
    field_names: frozenset[str] | None = (
        frozenset(cast("dict[str, Any]", fields))
        if as_shared_script and isinstance(fields, dict)
        else None
    )
    # No `# --- sequence ---` header (see `_automation_source`'s matching
    # note): a script's body is just its sequence, nothing else, so the
    # comment never disambiguated anything.
    with shared_script_field_context(field_names):
        for action in sequence:
            if isinstance(action, dict):
                body_lines.extend(decompile_action(action, resolver=resolver))
            else:
                body_lines.append(f"raw_action({render_literal(action)})")
    if not body_lines:
        body_lines = ["pass"]
    for line in body_lines:
        lines.append(f"{INDENT}{line}" if line else line)
    return "\n".join(lines) + "\n"


_HELPER_BUILDER_NAMES = {domain: domain for domain in HELPER_DOMAINS}
_TEMPLATE_HELPER_BUILDER_NAMES = {domain: domain for domain in TEMPLATE_DOMAINS}
_GROUP_HELPER_BUILDER_NAMES = {domain: domain for domain in GROUP_DOMAINS}


def _helper_source(obj: HelperConfig, ident: str) -> str:
    body = dict(obj.to_ha())
    domain = obj.kind()
    builder = _HELPER_BUILDER_NAMES[domain]
    kwargs = [f"{k}={render_literal(v)}" for k, v in body.items()]
    return f"{ident} = {builder}({', '.join(kwargs)})\n"


def _group_helper_source(obj: GroupHelperConfig, ident: str) -> str:
    """A group helper decompiles to the plain assignment call form, like the
    nine storage-collection helpers (:func:`_helper_source`) -- unlike
    template helpers, there is no Jinja `state=` field to defer into a
    decorator body, so no decorator form exists here at all.

    ``entities``'s member entity ids (which may themselves be another
    group's entity id -- nested groups, docs/internals/ha-api-notes.md §38.1) decompile
    as PLAIN string literals via ``render_literal``, never the `e.<domain>.
    <id>` cosmetic entity-reference form (`hassle.decompiler.exprs.
    render_entity_position`): plain entity references, no ordering games,
    list order preserved verbatim (compile(decompile(x)) == x).
    """
    body = dict(obj.to_ha())
    domain = obj.kind()
    builder = _GROUP_HELPER_BUILDER_NAMES[domain]
    kwargs = [f"{k}={render_literal(v)}" for k, v in body.items()]
    return f"{ident} = {builder}({', '.join(kwargs)})\n"


def _template_helper_call_form_source(obj: TemplateHelperConfig, ident: str) -> str:
    """The plain call form: ``ident = builder(name=..., state=..., ...)``.

    No longer the decompiler's own output for a template helper (both
    branches of :func:`_template_helper_source` emit the decorator form now)
    -- kept because the call form stays valid DSL input (the frozen DSL
    surface only ever grows; nothing is removed from it). There is no
    identity kwarg to rename, ``TemplateHelperConfig`` has no ``id``/
    ``unique_id`` field at all (docs/internals/ha-api-notes.md §26.6). Identity is
    derived from ``name`` (slugified) at both compile and decompile time."""
    body = dict(obj.to_ha())
    domain = obj.kind()
    builder = _TEMPLATE_HELPER_BUILDER_NAMES[domain]
    kwargs = [f"{k}={render_literal(v)}" for k, v in body.items()]
    return f"{ident} = {builder}({', '.join(kwargs)})\n"


def _raw_template_return_source(text: str) -> str:
    """Render ``text`` (a stored ``state=``/``options=`` Jinja string) as a
    Python string literal suitable for a decorator body's ``return`` -- the
    fallback branch's raw-string body, so hand-converting a helper to Python
    later means rewriting only the ``return`` expression.

    Byte-exact: the literal must parse back to EXACTLY ``text`` (compile(
    decompile(x)) == x), whatever it contains. Single-line text uses a plain
    ``repr()``; multi-line text uses a triple-double-quoted string with
    manual escaping. See docs/internals/decompiler.md for why each case is
    handled the way it is.
    """
    if "\n" not in text:
        return repr(text)
    escaped_chars: list[str] = []
    for ch in text:
        if ch == "\\":
            escaped_chars.append("\\\\")
        elif ch == '"':
            escaped_chars.append('\\"')
        elif ch == "\r":
            escaped_chars.append("\\r")
        else:
            escaped_chars.append(ch)
    return '"""' + "".join(escaped_chars) + '"""'


def _template_helper_source(obj: TemplateHelperConfig, ident: str) -> str:
    """The decorator form is canonical output for both branches: try the
    bounded Jinja inverter first (``hassle.decompiler.template_invert``);
    when it can't invert ``state`` byte-for-byte, fall back to a decorator
    whose body is ``return "<verbatim Jinja>"``
    (:func:`_raw_template_return_source`). Both branches share the exact
    same decorator-kwargs rendering (every field but ``state`` is unaffected
    either way) and the same ``ident`` (computed once, before this function
    is even called), so a helper flipping between branches keeps its
    function name.

    ``state``/``options``'s value is the only field ever spelled as a
    decorated function body -- every other kwarg (``set_value``,
    ``min``/``max``/``step``, ``unit_of_measurement``, ...) is unaffected and
    still rendered exactly as the call form renders it, just moved into the
    decorator's argument list. ``template_select.options=`` (the second
    template) stays a kwarg, unchanged.

    See docs/internals/decompiler.md for why the inversion/fallback split is
    safe by construction with respect to `compile(decompile(x)) == x`.
    """
    from hassle.decompiler.template_invert import invert_template

    body = dict(obj.to_ha())
    state = body.get("state")
    domain = obj.kind()
    builder = _TEMPLATE_HELPER_BUILDER_NAMES[domain]

    if not isinstance(state, str):
        # No `state=` at all (shouldn't happen for a real template-helper
        # object -- every one of the four domains requires it -- but never
        # crash the decompiler over a malformed/hand-built IR object; the
        # call form degrades gracefully since it has no body to speak of).
        return _template_helper_call_form_source(obj, ident)

    inverted = invert_template(state)
    decorator_kwargs = [f"{k}={render_literal(v)}" for k, v in body.items() if k != "state"]
    return_expr = inverted.source if inverted is not None else _raw_template_return_source(state)
    return (
        f"@{builder}({', '.join(decorator_kwargs)})\ndef {ident}():\n{INDENT}return {return_expr}\n"
    )


def _object_function_name(object_key: str, obj: IRObject, used_names: dict[str, int]) -> str:
    """The Python identifier ``obj`` decompiles to -- shared by the naming
    pre-pass (:func:`decompile_bundle` builds the call resolver from this
    before assembling any source) and :func:`decompile_object` itself, so the
    two can never disagree on a name."""
    if isinstance(obj, AutomationConfig):
        return _automation_name(obj, used_names)
    if isinstance(obj, ScriptConfig):
        return script_function_name(obj, used_names)
    if isinstance(obj, DashboardConfig):
        return dashboard_function_name(obj, used_names)
    return _identifier(object_key)


def decompile_object(
    object_key: str,
    obj: IRObject,
    *,
    used_names: dict[str, int] | None = None,
    resolver: CallResolver | None = None,
    _ident: str | None = None,
) -> str:
    """Decompile a single IR object to its DSL source (a `def` or an assignment).

    No trailing blank-line separation is added here (the caller controls
    inter-object spacing); the returned text ends with exactly one newline.

    ``used_names`` tracks alias-derived name collisions across a whole-bundle
    decompile (DESIGN §7.3: deterministic ``_2``/``_3`` suffixing) --
    :func:`decompile_bundle` shares one across all its objects; a standalone
    call (splice's single-object use, `hassle_cli.diffing`'s per-side decompile)
    passes none, so that one object's name is never collision-suffixed against
    objects it isn't being decompiled alongside -- it still starts from
    :func:`_reserved_names` either way, so a lone object never shadows a
    builder verb inside its own body regardless of what else it's decompiled
    alongside.

    ``resolver`` resolves a caller action's direct ``script.<id>`` call to a
    real function call -- see :func:`decompile_bundle`'s docstring for how
    it's built.

    ``_ident`` (internal): the precomputed function/variable name, when
    :func:`decompile_bundle`'s naming pre-pass already derived it (so the
    resolver and the emitted source are guaranteed to agree) -- computed
    fresh from ``used_names`` otherwise.
    """
    names = used_names if used_names is not None else _reserved_names()
    ident = _ident if _ident is not None else _object_function_name(object_key, obj, names)
    if isinstance(obj, AutomationConfig):
        return _automation_source(obj, ident, resolver)
    if isinstance(obj, ScriptConfig):
        return _script_source(obj, ident, resolver)
    if isinstance(obj, HelperConfig):
        return _helper_source(obj, ident)
    if isinstance(obj, TemplateHelperConfig):
        return _template_helper_source(obj, ident)
    if isinstance(obj, GroupHelperConfig):
        return _group_helper_source(obj, ident)
    if isinstance(obj, DashboardConfig):
        return dashboard_source(obj, ident)
    raise TypeError(f"cannot decompile object of type {type(obj).__name__}")  # pragma: no cover


class RuffNotFoundError(RuntimeError):
    """The `ruff` executable is required at runtime (every decompiled file is
    formatted with it) but could not be located."""


def _resolve_ruff_executable() -> str | None:
    """Locate the `ruff` binary: the running interpreter's own bin directory
    first (the venv / `uv tool install` case, where ruff is a dependency of
    this package but the venv's bin is NOT on PATH), then PATH."""
    import shutil
    import sys

    candidate = Path(sys.executable).parent / "ruff"
    if candidate.is_file():
        return str(candidate)
    return shutil.which("ruff")


def _format_with_ruff(source: str) -> str:
    """Run ``ruff format -`` over ``source`` (deterministic, no network)."""
    ruff = _resolve_ruff_executable()
    if ruff is None:
        raise RuffNotFoundError(
            "hassle needs the `ruff` executable to format decompiled Python, but it "
            "was not found next to the running interpreter or on PATH. This usually "
            "means hassle was installed without its dependencies. Fix: reinstall the "
            "CLI (`uv tool install --force -e <hassle repo>/packages/hassle-cli`) so "
            "ruff is included in its environment, or `uv tool install ruff` / add "
            "ruff to PATH."
        )
    proc = subprocess.run(
        [ruff, "format", "-"],
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


def _script_known_fields(obj: ScriptConfig) -> frozenset[str]:
    """The declared field names a caller's ``data`` may legally supply --
    every data key must be a declared field."""
    body = obj.to_ha()
    fields = body.get("fields")
    if not isinstance(fields, dict):
        return frozenset()
    return frozenset(cast("dict[str, Any]", fields))


def _script_object_id(object_key: str) -> str:
    return object_key.partition(":")[2]


def called_script_ids(node: Any) -> set[str]:
    """Every ``script.<id>`` (direct-call shorthand, not ``script.turn_on``)
    an object's actions reference anywhere, walked recursively (nested inside
    ``if``/``choose``/``repeat``/``parallel``/``wait_for_trigger`` bodies too)
    -- used to decide which ``script_refs`` entries are actually needed, so an
    UNUSED cross-reference-table entry never contributes a dangling unused
    import."""
    found: set[str] = set()
    if isinstance(node, dict):
        node_dict = cast("dict[str, Any]", node)
        action = node_dict.get("action")
        if isinstance(action, str) and action.startswith("script.") and action != "script.turn_on":
            found.add(action[len("script.") :])
        for value in node_dict.values():
            found |= called_script_ids(value)
    elif isinstance(node, list):
        for item in cast("list[Any]", node):
            found |= called_script_ids(item)
    return found


def _build_resolver(
    objects: dict[str, IRObject],
    script_names: dict[str, str],
    script_refs: dict[str, ScriptRef] | None,
    snapshot: RegistrySnapshot | None = None,
) -> tuple[CallResolver, list[str]]:
    """Build the :class:`CallResolver` for one :func:`decompile_bundle` call,
    plus the list of ``from <module> import <fn>`` lines it needs.

    Same-batch scripts (in ``script_names``, keyed by object_id) win over the
    externally-supplied ``script_refs`` table -- they need no import at all,
    being plain functions in the SAME module. A ``script_refs`` entry for a
    script NOT in this batch resolves to a cross-file call, contributing one
    import line (deduplicated, sorted for determinism).

    Cross-file cycle guard: if the target script's own ``ScriptRef.calls``
    set names an object_id THIS decompile batch is scripting (i.e., the
    callee calls back into a script defined here), that would require a
    circular import between the two files -- the edge is dropped from the
    resolver (falls back to `service()`) rather than ever emitting a
    mutually-importing pair of generated files.

    Only ``script_refs`` entries actually referenced by an object in
    ``objects`` (:func:`called_script_ids`) ever contribute a target/import
    -- an unused table entry must never surface as a dangling unused import.

    A script that fell back to plain ``@script`` (DESIGN §7.3's fallback rule
    -- rich field metadata, or a field with no ``default`` at all) has NO
    call-site parameters, whatever its ``fields`` block's key NAMES are -- it
    must never get a ``CallTarget`` at all, same-batch or cross-file, or a
    caller can be rewritten to invoke a function with kwargs it does not
    accept (``TypeError`` at compile time -- this is a real regression a
    script can hit: a script whose fields forced the ``@script`` fallback,
    with a caller still rewritten to pass it kwargs it can't accept).
    :func:`script_is_shared_script` (same-batch) / ``ScriptRef.
    is_shared_script`` (cross-file, since the callee isn't actually parsed in
    THIS call) gate target creation -- checked before ``known_fields``, which
    only matters once a script is confirmed callable at all.
    """
    script_ids_in_batch = {
        _script_object_id(key) for key, obj in objects.items() if isinstance(obj, ScriptConfig)
    }
    called_ids: set[str] = set()
    for obj in objects.values():
        called_ids |= called_script_ids(obj.to_ha())

    targets: dict[str, CallTarget] = {}
    import_lines: set[str] = set()
    cycle_broken: set[str] = set()
    for object_id, fn_name in script_names.items():
        script_obj = cast("ScriptConfig", objects[f"script:{object_id}"])
        if not script_is_shared_script(script_obj):
            continue  # @script fallback -- no call-site parameters at all
        known = _script_known_fields(script_obj)
        targets[object_id] = CallTarget(function_name=fn_name, import_line=None, known_fields=known)

    if script_refs:
        for object_id, ref in script_refs.items():
            if object_id in targets:
                continue  # same-batch call already resolved, no import needed
            if object_id not in called_ids:
                continue  # unused entry -- never surfaces an unused import
            if not ref.is_shared_script:
                continue  # @script fallback on the callee's side -- never a target
            # Cycle guard: the callee's own outgoing calls loop back into a
            # script THIS batch defines -> importing it would close a cross-
            # file circular import. Break this edge instead (stays service()).
            if ref.calls & script_ids_in_batch:
                cycle_broken.add(object_id)
                continue
            import_line = f"from {ref.module} import {ref.function_name}"
            targets[object_id] = CallTarget(
                function_name=ref.function_name,
                import_line=import_line,
                known_fields=ref.known_fields,
            )
            import_lines.add(import_line)

    return CallResolver(targets, frozenset(cycle_broken), snapshot=snapshot), sorted(import_lines)


def decompile_bundle(
    objects: dict[str, IRObject],
    *,
    script_refs: dict[str, ScriptRef] | None = None,
    snapshot: RegistrySnapshot | None = None,
) -> str:
    """Decompile every object in ``objects`` into one ruff-formatted module.

    Deterministic: objects are emitted in sorted-key order regardless of the
    input mapping's iteration order, so the same IR always produces
    byte-identical source -- including alias-collision suffixing, which walks
    objects in that same sorted-key order (never input/dict-iteration order)
    so two aliases that collide always get the same `_2`/`_3` assignment
    regardless of how the caller's mapping happened to be built.

    ``script_refs``: a ``{script_object_id: ScriptRef}`` cross-reference
    table -- supplied by the pull layer (``hassle_cli.bundle_ops``), which
    already knows every managed script's destination file -- for scripts NOT
    in ``objects`` (i.e. a different destination file than whatever's being
    decompiled here). A caller's direct ``{"action": "script.<id>", ...}``
    action decompiles to a real function call (with a
    ``from <module> import <fn>`` import, deduped and sorted) when ``<id>``
    resolves via ``objects`` (same file, no import) or ``script_refs``
    (cross-file); otherwise it stays ``service()`` -- an unknown script id
    never decompiles to ``raw``.

    ``snapshot``: when supplied, a plain service-call action whose literal
    ``"domain.service"`` exists in the snapshot and whose data is
    kwarg-expressible decompiles to the typed namespace form
    (``light.turn_on(target=..., **fields)``) with a per-file
    ``from hassle.services import <domains>`` import line (domains sorted,
    deduplicated, and only ever the ones actually used -- never a dangling
    unused import). ``None`` (the default) means every service call stays
    ``service(...)``.
    """
    # Naming pre-pass: derive every object's function/variable name ONCE, in
    # the same sorted-key order `decompile_object` itself would use, so the
    # call resolver (built from these names) can never disagree with what
    # actually gets emitted below -- a single shared `used_names` tracker.
    used_names: dict[str, int] = _reserved_names()
    idents: dict[str, str] = {}
    script_names: dict[str, str] = {}
    for key in sorted(objects):
        obj = objects[key]
        ident = _object_function_name(key, obj, used_names)
        idents[key] = ident
        if isinstance(obj, ScriptConfig):
            script_names[_script_object_id(key)] = ident

    resolver, import_lines = _build_resolver(objects, script_names, script_refs, snapshot)

    # Object bodies are decompiled BEFORE the import header is assembled: the
    # services-namespace import line depends on `resolver.used_service_domains`,
    # which is only known once every action has actually been decompiled
    # (a side effect of `decompile_action`).
    object_sources = [
        decompile_object(key, objects[key], resolver=resolver, _ident=idents[key])
        for key in sorted(objects)
    ]

    parts = [_STAR_IMPORT_LINE, _ENTITIES_IMPORT_LINE]
    # A decompiled `@shared_script` signature annotates every field parameter
    # `TemplateExpr` (body-true typing, `_shared_script_signature`'s own
    # docstring) -- `TemplateExpr` is not on the `hassle` star-import surface
    # (it's compiler-internal, exposed only via `hassle.compiler`/
    # `hassle.compiler.templates`), so an explicit import is needed whenever
    # at least one signature actually used it. `field_default` itself needs
    # no separate import -- it IS on the star-import surface (`hassle.__all__`).
    # A plain string check on the already-assembled object sources is simpler
    # and just as deterministic as threading a "did I emit a signature" flag
    # back out of `_script_source` through `decompile_object`.
    if any(": TemplateExpr" in source for source in object_sources):
        parts.append("from hassle.compiler.templates import TemplateExpr\n")
    if any(_USES_CARDS_NAMESPACE_RE.search(source) for source in object_sources):
        parts.append(_CARDS_IMPORT_LINE)
    if any(_USES_COND_NAMESPACE_RE.search(source) for source in object_sources):
        parts.append(_COND_IMPORT_LINE)
    if resolver.used_service_domains:
        # Each entry renders as `domain` (the common case) or `domain as
        # svc_domain` when `service_domain_name` aliased it to avoid
        # shadowing a star-imported name (e.g. `automation`/`script`/`zone`
        # collide with real DSL names) -- sorted by the DOMAIN (not the
        # possibly-aliased local name) for determinism independent of which
        # names happened to need aliasing.
        import_names = [
            domain if local_name == domain else f"{domain} as {local_name}"
            for domain, local_name in sorted(resolver.used_service_domains.items())
        ]
        parts.append(f"from hassle.services import {', '.join(import_names)}\n")
    parts.extend(f"{line}\n" for line in import_lines)
    parts.append("")
    parts.extend(object_sources)
    source = "\n".join(parts) + "\n"
    return _format_with_ruff(source)
