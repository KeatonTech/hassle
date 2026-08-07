"""Decompile a single action dict to one or more DSL statements.

Unlike triggers/conditions (single expressions), actions decompile to
*statements* -- a plain service call is one line, but ``if``/``choose``/
``repeat``/``parallel`` need a ``with ...:`` block with a nested body. Each
``decompile_action`` call returns a list of source lines (already indented
relative to the block they're emitted into); the caller is responsible for the
surrounding indentation level.

Falls back to ``raw_action({...})`` for any action shape not modeled here
(DESIGN §5.8: compile(decompile(x)) must equal x for any config) -- never
drops data.
"""

from __future__ import annotations

import contextlib
import keyword
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from hassle.decompiler.exprs import decompile_condition, render_entity_position, render_literal

if TYPE_CHECKING:
    from hassle.registry.snapshot import RegistrySnapshot

INDENT = "    "

# The enclosing `@shared_script`'s own declared field names, while
# decompiling THAT script's own body -- `None` everywhere else (automation
# decompilation, a plain `@script`'s body, ...). Module-level
# rather than threaded as a parameter through every action-decompiling
# function (`_if_then`/`_choose`/`_repeat`/`_parallel`/...): decompiling one
# object's action tree is a single synchronous recursive call with no
# re-entrance (`hassle.decompiler.codegen.decompile_object` fully finishes one
# object before the next), so a push/pop context var is equivalent to (and far
# less invasive than) threading a new parameter through the whole recursive
# family -- same convention `hassle.compiler.scripts._ACTIVE_FIELDS` uses on
# the compile side, and explicitly scoped so it can never leak into an
# automation's own decompiled data values.
_active_shared_script_fields: frozenset[str] | None = None


@contextlib.contextmanager
def shared_script_field_context(field_names: frozenset[str] | None) -> Generator[None]:
    """Decompile a ``@shared_script``'s own body with ``field_names`` active
    -- a bare-name Jinja read matching one of these inverts to the bare
    parameter form instead of ``var(name)``/a raw string.
    ``field_names=None`` is a no-op (used for the ``@script`` fallback and
    every non-script-body decompile), so this context manager is safe to wrap
    around every :func:`~hassle.decompiler.codegen._script_source` call
    unconditionally."""
    global _active_shared_script_fields
    previous = _active_shared_script_fields
    _active_shared_script_fields = field_names
    try:
        yield
    finally:
        _active_shared_script_fields = previous


def _reserved_top_level_names() -> frozenset[str]:
    """Every name a fresh whole-bundle decompile already binds at module
    scope: the frozen DSL star-import surface (``hassle.__all__``) plus the
    entities accessor alias (``e``). Several REAL HA service domains are also
    frozen DSL names (``automation``, ``script``, ``zone``, ``time``,
    ``schedule``, ``event``, ``device``, ``sun``, ``tag``, ``template``,
    ``mqtt``, ``webhook``, ``calendar``, ``timer``, ``on``, ``area``, every
    ``input_*``/``counter`` helper builder, ...) -- a plain, unaliased
    ``from hassle.services import automation`` would silently SHADOW the
    ``@automation`` decorator import above it (both are module-level
    ``automation``, and Python import order means the later one wins),
    breaking every automation in the file. :func:`_service_domain_alias` uses
    this set to decide when a namespace import needs an alias instead.
    """
    import hassle

    return frozenset(hassle.__all__) | {"e"}


def indent_lines(lines: list[str], levels: int = 1) -> list[str]:
    prefix = INDENT * levels
    return [f"{prefix}{line}" if line else line for line in lines]


def _raw_action(body: Any) -> list[str]:
    return [f"raw_action({render_literal(body)})"]


def _render_data_value(value: Any) -> str:
    """Render one action ``data``/``target`` value -- plain
    ``render_literal(v)``, EXCEPT a string that inverts through the bounded
    Jinja inverter (`hassle.decompiler.template_invert`) using the active
    shared-script's own field names: a bare field read (``"{{ tag }}"``) or a
    larger invertible expression over fields (``concat(tag, "_x")``)
    decompiles through that composed source instead of the raw string.
    Recurses into dicts/lists (matching a real corpus shape,
    ``shared_script_rich_fields``'s ``data={"actions": [{"title": "{{
    action_button }}", ...}], "tag": "{{ tag }}"}``) so a field read nested
    inside either still gets the bare-parameter treatment, not just a
    top-level value. Falls back to ``render_literal`` (the raw string) for
    anything the inverter doesn't accept -- never partial output, same
    acceptance rule `invert_template` already enforces for template-helper
    ``state=``. ``_active_shared_script_fields`` is ``None`` outside a
    shared-script body's own decompile (the common case, and every
    non-script-body call site), so this is a pure passthrough to
    ``render_literal`` there -- field-aware rewriting can never affect
    automation/plain-``@script`` decompilation.
    """
    if _active_shared_script_fields is None:
        return render_literal(value)
    if isinstance(value, str):
        from hassle.decompiler.template_invert import invert_template

        inverted = invert_template(value, field_names=_active_shared_script_fields)
        if inverted is not None:
            return inverted.source
        return render_literal(value)
    if isinstance(value, dict):
        as_dict = cast("dict[Any, Any]", value)
        items = ", ".join(
            f"{render_literal(k)}: {_render_data_value(v)}" for k, v in as_dict.items()
        )
        return "{" + items + "}"
    if isinstance(value, list):
        as_list = cast("list[Any]", value)
        return "[" + ", ".join(_render_data_value(v) for v in as_list) + "]"
    return render_literal(value)


# Per-step `alias`/`enabled` (docs/internals/ha-api-notes.md §20): the UI names and
# toggles individual steps. Every action shape below
# accepts both, layered onto its own `known` set, so a step carrying them is
# never forced to `raw_action` merely for that reason.
_STEP_OPTION_KEYS = frozenset({"alias", "enabled"})


@dataclass(frozen=True)
class CallTarget:
    """Where a MANAGED script's decompiled function call actually resolves:
    the function name, and the import line to emit for it (``None`` when the
    callee is decompiled in the SAME module -- a plain same-file function
    call, no import needed).

    ``known_fields`` is the callee's declared field names, used to check the
    "every data key is a declared field" rewrite condition; ``None`` means
    "not known here, don't gate on it" (accept any data keys)."""

    function_name: str
    import_line: str | None
    known_fields: frozenset[str] | None


class CallResolver:
    """Resolves a ``script.<object_id>`` action's call target for the
    function-call rewrite.

    Built once per :func:`~hassle.decompiler.codegen.decompile_bundle` call by
    ``codegen.py`` (which knows both the objects in THIS batch -- no import
    needed -- and the pull-supplied cross-file ``ScriptRef`` table), then
    threaded down through every action-decompiling function so the rewrite can
    fire at any nesting depth (inside ``if``/``choose``/``repeat``/``parallel``).

    ``cycle_broken`` names object_ids whose call edge was deliberately NOT
    resolved because doing so would have closed a cross-file import cycle
    (``codegen._build_resolver``'s cycle guard) -- distinct from an ordinary
    "unknown script" miss, this gets a one-line explanatory comment on the
    `service()` fallback rather than silently looking like any other
    not-yet-managed callee.
    """

    def __init__(
        self,
        targets: dict[str, CallTarget],
        cycle_broken: frozenset[str] = frozenset(),
        *,
        snapshot: RegistrySnapshot | None = None,
    ) -> None:
        self._targets = targets
        self._cycle_broken = cycle_broken
        # The registry snapshot backing the typed service-namespace canonical
        # form (`None` -- no snapshot supplied to `decompile_bundle` --
        # always falls back to `service(...)`).
        self.snapshot = snapshot
        # Domains the namespace form actually used across this decompile batch
        # (populated as a side effect of `decompile_action`), mapped to the
        # LOCAL NAME the call site binds to (the domain name itself, unless it
        # collides with the star-import surface -- see `service_domain_name`)
        # -- the source of truth for the `from hassle.services import
        # <domain>[ as <alias>]` header line, so an unused domain never
        # contributes a dangling import.
        self.used_service_domains: dict[str, str] = {}

    def resolve(self, object_id: str) -> CallTarget | None:
        return self._targets.get(object_id)

    def service_domain_name(self, domain: str) -> str:
        """The LOCAL NAME a ``domain`` namespace call binds to in this file:
        the domain name itself, unless it collides with the star-import
        surface (``_reserved_top_level_names``), in which case an
        ``svc_<domain>`` alias is used instead (``automation``/``script``/
        ``zone``/... are both real HA service domains AND frozen DSL names).
        Memoized per resolver instance so the
        SAME call within one decompile batch always renders the same name,
        and recorded in :attr:`used_service_domains` as a side effect."""
        if domain in self.used_service_domains:
            return self.used_service_domains[domain]
        name = f"svc_{domain}" if domain in _reserved_top_level_names() else domain
        self.used_service_domains[domain] = name
        return name

    def is_cycle_broken(self, object_id: str) -> bool:
        return object_id in self._cycle_broken


def decompile_action(body: Any, *, resolver: CallResolver | None = None) -> list[str]:
    """Decompile one action dict to source lines, or the ``raw_action`` fallback.

    ``resolver``: when supplied, a direct ``{"action": "script.<id>", ...}``
    call to a MANAGED script known to ``resolver`` decompiles to a real
    function call instead of ``service()`` (see :func:`_service_call`'s
    docstring for the exact rewrite conditions).
    """
    if not isinstance(body, dict):
        return _raw_action(body)
    action_body = cast("dict[str, Any]", body)

    if "action" in action_body and _is_plain_service_call(action_body):
        rewritten = _script_call(action_body, resolver) if resolver is not None else None
        if rewritten is not None:
            return rewritten
        if resolver is not None and resolver.snapshot is not None:
            namespace_lines = _namespace_service_call(action_body, resolver.snapshot, resolver)
            if namespace_lines is not None:
                return namespace_lines
        service_lines = _service_call(action_body)
        if resolver is not None:
            action = action_body.get("action")
            if isinstance(action, str) and action.startswith("script."):
                object_id = action[len("script.") :]
                if resolver.is_cycle_broken(object_id):
                    service_lines.append(
                        f"# hassle: {object_id} import would create a cross-file script call "
                        f"cycle -- kept as service() here to break it"
                    )
        return service_lines
    if "delay" in action_body and set(action_body) <= {"delay"} | _STEP_OPTION_KEYS:
        delay_src = _delay_source(action_body)
        if delay_src is not None:
            return [delay_src]
    if "if" in action_body:
        result = _if_then(action_body, resolver)
        if result is not None:
            return result
    if "choose" in action_body:
        result = _choose(action_body, resolver)
        if result is not None:
            return result
    if "repeat" in action_body and set(action_body) <= {"repeat"} | _STEP_OPTION_KEYS:
        result = _repeat(action_body, resolver)
        if result is not None:
            return result
    if "parallel" in action_body and set(action_body) <= {"parallel"} | _STEP_OPTION_KEYS:
        result = _parallel(action_body, resolver)
        if result is not None:
            return result
    if "wait_for_trigger" in action_body:
        result = _wait_for(action_body)
        if result is not None:
            return result
    if "wait_template" in action_body:
        return _wait_template(action_body)
    if "stop" in action_body:
        return _stop(action_body)
    if "variables" in action_body and set(action_body) == {"variables"}:
        return _variables(action_body)
    if "event" in action_body and set(action_body) <= {"event", "event_data"}:
        return _fire_event(action_body)

    return _raw_action(action_body)


# A direct script call's own known keys: only `data`/`metadata`/`alias`/
# `enabled` are reproducible via the call; ANY other key -- `target`,
# `data_template`, `response_variable`, `continue_on_error` -- falls back to
# service().
_SCRIPT_CALL_KNOWN_KEYS = frozenset({"action", "data", "metadata"}) | _STEP_OPTION_KEYS


def _script_call(body: dict[str, Any], resolver: CallResolver) -> list[str] | None:
    """Rewrite a direct ``{"action": "script.<id>", ...}`` call to
    ``<fn_name>(<data as kwargs>, metadata={...})`` when every condition
    holds; ``None`` falls back to :func:`_service_call` (``service()`` form --
    an unknown script id never decompiles to raw).

    Conditions: every ``data`` key is a declared field of the target script;
    the action is the direct ``script.<id>`` form (not ``script.turn_on``);
    no ``target``/``data_template``/``response_variable``/
    ``continue_on_error`` extras beyond what the call reproduces.
    """
    action = body["action"]
    if not isinstance(action, str) or not action.startswith("script."):
        return None
    object_id = action[len("script.") :]
    if not object_id or object_id == "turn_on":
        return None  # script.turn_on is the generic caller shape, never rewritten
    if not set(body) <= _SCRIPT_CALL_KNOWN_KEYS:
        return None
    target = resolver.resolve(object_id)
    if target is None:
        return None
    data = body.get("data")
    if "data" in body and data == {}:
        # An explicit, empty `data: {}` is NOT expressible in this form,
        # unlike `service()`/namespace calls (see `_service_call`): a script
        # call's kwargs are its DECLARED FIELDS, with no reserved `data=`
        # to pass through, and `ScriptCallAction.to_action` emits `data`
        # on truthiness. Decline so the caller falls back to a form that
        # can round-trip the key rather than silently dropping it.
        return None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None
    data_dict = cast("dict[str, Any]", data)
    if target.known_fields is not None and not set(data_dict) <= target.known_fields:
        return None

    parts = [f"{k}={render_literal(v)}" for k, v in data_dict.items()]
    if "metadata" in body:
        parts.append(f"metadata={render_literal(body['metadata'])}")
    parts.extend(_step_option_kwargs_src(body))
    return [f"{target.function_name}({', '.join(parts)})"]


def _is_plain_service_call(body: dict[str, Any]) -> bool:
    known = {
        "action",
        "target",
        "data",
        "data_template",
        "response_variable",
        "continue_on_error",
        "metadata",
    } | _STEP_OPTION_KEYS
    return set(body) <= known and isinstance(body.get("action"), str)


def _step_option_kwargs_src(body: dict[str, Any]) -> list[str]:
    """Render `alias=`/`enabled=` present in ``body`` (docs/internals/ha-api-notes.md
    §20) as ``key=value`` source fragments."""
    parts: list[str] = []
    if "alias" in body:
        parts.append(f"alias={render_literal(body['alias'])}")
    if "enabled" in body:
        parts.append(f"enabled={render_literal(body['enabled'])}")
    return parts


_DURATION_UNIT_KEYS = frozenset({"hours", "minutes", "seconds", "milliseconds"})


def _delay_duration_kwargs(value: Any) -> list[str] | None:
    """Render any of HA's three delay duration forms as ``delay()`` kwargs.

    HA accepts a delay as a dict of units, an ``"HH:MM:SS"`` string, or a bare
    number of seconds -- all functionally equivalent. The typed ``delay()``
    builder only emits the dict form (docs/internals/ha-api-notes.md), so decompiling a
    string/numeric delay to it modernizes the representation -- cosmetic,
    same treatment as the trigger-discriminator modernization
    (test_roundtrip_corpus.py's ``_modernized`` documents and accounts for
    this for the round-trip test specifically).
    """
    if isinstance(value, dict):
        duration = cast("dict[str, Any]", value)
        if set(duration) <= _DURATION_UNIT_KEYS:
            return [f"{k}={v!r}" for k, v in duration.items()]
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return [f"seconds={value!r}"]
    if isinstance(value, str):
        pieces = value.split(":")
        if len(pieces) == 3 and all(p.isdigit() for p in pieces):
            h, m, s = (int(p) for p in pieces)
            units: list[tuple[str, int]] = [
                (k, v) for k, v in (("hours", h), ("minutes", m), ("seconds", s)) if v
            ]
            return [f"{k}={v!r}" for k, v in units] or ["seconds=0"]
    return None


def _delay_source(body: dict[str, Any]) -> str | None:
    """Build a ``delay(...)`` call, including any ``alias``/``enabled`` step options."""
    duration_kwargs = _delay_duration_kwargs(body["delay"])
    if duration_kwargs is None:
        return None
    parts = duration_kwargs + _step_option_kwargs_src(body)
    return f"delay({', '.join(parts)})"


def _target_src(target: Any) -> str:
    """Render a stored ``target`` dict as the bare entity-target sugar
    (DESIGN §7.3) when it has exactly one key --
    ``entity_id`` (a bare ref/list, reusing the entity-position renderer) or
    ``area_id``/``floor_id``/``label_id``/``device_id`` (an ``area()``/``floor()``/
    ``label()``/``device_id()`` call) -- else the plain dict literal (multi-key
    targets, e.g. ``entity_id`` + ``device_id`` together, keep the dict form)."""
    if isinstance(target, dict):
        target_dict = cast("dict[str, Any]", target)
        if set(target_dict) == {"entity_id"}:
            return render_entity_position(target_dict["entity_id"])
        if set(target_dict) == {"area_id"}:
            return f"area({target_dict['area_id']!r})"
        if set(target_dict) == {"floor_id"}:
            return f"floor({target_dict['floor_id']!r})"
        if set(target_dict) == {"label_id"}:
            return f"label({target_dict['label_id']!r})"
        if set(target_dict) == {"device_id"}:
            return f"device_id({target_dict['device_id']!r})"
    return render_literal(target)


def _is_kwarg_safe_key(key: str) -> bool:
    """True if ``key`` can be written as a Python keyword-argument name
    (``light.turn_on(brightness_pct=60)``) -- a valid identifier that is not a
    reserved word (``class``, ``import``, ...). HA service field names are
    otherwise unconstrained strings; anything that fails this check keeps the
    action in `service(...)` form (every data key must be a valid Python
    kwarg to use the typed namespace form)."""
    return key.isidentifier() and not keyword.iskeyword(key)


def _namespace_service_call(
    body: dict[str, Any], snapshot: RegistrySnapshot, resolver: CallResolver
) -> list[str] | None:
    """Typed service-namespace canonical form: a plain service-call action
    whose literal ``"domain.service"`` exists in the registry snapshot AND
    whose ``data`` keys are all kwarg-expressible identifiers decompiles to
    ``<domain>.<service>(target=..., **fields)`` instead of ``service(...)``.
    Returns ``None`` (caller falls back to :func:`_service_call`) for: a
    templated service name (no dot-delimited literal to look up), a
    domain/service absent from the snapshot, or any non-kwarg-safe data key
    -- byte-exact through either branch, since both forms compile to the
    identical ``{"action": ..., ...}`` IR (the namespace form's builder is
    `hassle.services`, which delegates to the exact same `service()` verb).

    ``resolver.service_domain_name(domain)`` gives the LOCAL name this call
    binds to (aliased to ``svc_<domain>`` when ``domain`` collides with the
    star-import surface, e.g. ``automation``/``script``/``zone`` are both real
    HA service domains and frozen DSL names) -- called only once this
    function has committed to emitting the namespace form, so a domain that
    ultimately falls back to `service()` never contributes an alias/import.
    """
    action = body["action"]
    if "{{" in action:
        return None  # templated service name -- not a literal domain.service
    domain, dot, service_name = action.partition(".")
    if not dot:
        return None
    if snapshot.service_def(domain, service_name) is None:
        return None
    data = body.get("data")
    if data is not None and not isinstance(data, dict):
        return None  # e.g. a bare list/scalar `data:` -- not kwarg-expressible
    data_dict = cast("dict[str, Any]", data) if isinstance(data, dict) else {}
    if not all(_is_kwarg_safe_key(k) for k in data_dict):
        return None
    if "data_template" in body:
        # Legacy templated-data key: not reproducible via the namespace call's
        # kwarg form at all (there is no way to spell a *second*, sibling
        # `data_template` dict as kwargs) -- fall back to `service()`.
        return None

    parts: list[str] = []
    if "target" in body:
        parts.append(f"target={_target_src(body['target'])}")
    if isinstance(data, dict) and not data_dict:
        # An explicit, empty `data: {}` -- see `_service_call`. Expressible
        # here too: a namespace call forwards its kwargs straight to
        # `service()` (hassle/services.py `_ServiceDomain.__getattr__`),
        # whose `data=` is a real keyword-only parameter rather than another
        # bare field. `data` ABSENT stays absent (this branch needs the key
        # to have actually been there).
        parts.append("data={}")
    for k, v in data_dict.items():
        parts.append(f"{k}={_render_data_value(v)}")
    if "response_variable" in body:
        parts.append(f"response_variable={render_literal(body['response_variable'])}")
    if "continue_on_error" in body:
        parts.append(f"continue_on_error={render_literal(body['continue_on_error'])}")
    if "metadata" in body:
        parts.append(f"metadata={render_literal(body['metadata'])}")
    parts.extend(_step_option_kwargs_src(body))
    domain_name = resolver.service_domain_name(domain)
    return [f"{domain_name}.{service_name}({', '.join(parts)})"]


def _service_call(body: dict[str, Any]) -> list[str]:
    action = body["action"]
    parts = [repr(action)]
    if "target" in body:
        parts.append(f"target={_target_src(body['target'])}")
    data = body.get("data")
    if isinstance(data, dict):
        data_dict = cast("dict[str, Any]", data)
        if not data_dict:
            # Presence, not truthiness -- the same rule `metadata` follows
            # below and `ServiceAction._data_present` already implements on
            # the compiler side. HA stores `data: {}` verbatim on a
            # field-less call (it is not a spelling HA normalizes away), so
            # spreading an EMPTY dict as kwargs would emit nothing and drop
            # the key on recompile. Observed in the field 2026-08-06:
            # `hassle pull` refused a real bundle over exactly this.
            parts.append("data={}")
        for k, v in data_dict.items():
            parts.append(f"{k}={_render_data_value(v)}")
    elif data is not None:
        parts.append(f"data={render_literal(data)}")
    if "data_template" in body:
        # Legacy templated-data key: a sibling of `data`, never folded into
        # it -- round-trips exactly as HA stores it.
        parts.append(f"data_template={render_literal(body['data_template'])}")
    if "response_variable" in body:
        parts.append(f"response_variable={render_literal(body['response_variable'])}")
    if "continue_on_error" in body:
        parts.append(f"continue_on_error={render_literal(body['continue_on_error'])}")
    if "metadata" in body:
        # Emitted even when `{}`: every action the HA UI saves carries this
        # key, so eliding an empty metadata would hash-drift every
        # UI-authored action on recompile (compile(decompile(x)) == x).
        parts.append(f"metadata={render_literal(body['metadata'])}")
    parts.extend(_step_option_kwargs_src(body))
    return [f"service({', '.join(parts)})"]


def _actions_block(items: Any, resolver: CallResolver | None) -> list[list[str]] | None:
    if not isinstance(items, list):
        return None
    item_list = cast("list[Any]", items)
    result: list[list[str]] = []
    for item in item_list:
        if not isinstance(item, dict):
            return None
        result.append(decompile_action(item, resolver=resolver))
    return result


def _flatten(blocks: list[list[str]]) -> list[str]:
    out: list[str] = []
    for block in blocks:
        out.extend(block)
    return out


def _if_then(body: dict[str, Any], resolver: CallResolver | None) -> list[str] | None:
    known = {"if", "then", "else"} | _STEP_OPTION_KEYS
    if not set(body) <= known:
        return None
    raw_conds = body.get("if")
    then = body.get("then")
    if not isinstance(raw_conds, list):
        return None
    conds = cast("list[Any]", raw_conds)
    if len(conds) != 1 or not isinstance(conds[0], dict):
        return None
    cond_dict = cast("dict[str, Any]", conds[0])
    cond_src = decompile_condition(cond_dict)
    if cond_src is None:
        return None
    then_lines = _actions_block(then, resolver)
    if then_lines is None:
        return None
    header_parts = [cond_src, *_step_option_kwargs_src(body)]
    out = [f"with if_then({', '.join(header_parts)}):"]
    if not then_lines:
        out.extend(indent_lines(["pass"]))
    else:
        out.extend(indent_lines(_flatten(then_lines)))
    if "else" in body:
        else_lines = _actions_block(body["else"], resolver)
        if else_lines is None:
            return None
        out.append("with else_then():")
        if not else_lines:
            out.extend(indent_lines(["pass"]))
        else:
            out.extend(indent_lines(_flatten(else_lines)))
    return out


def _choose(body: dict[str, Any], resolver: CallResolver | None) -> list[str] | None:
    known = {"choose", "default"} | _STEP_OPTION_KEYS
    if not set(body) <= known:
        return None
    branches = body.get("choose")
    if not isinstance(branches, list):
        return None
    branch_list = cast("list[Any]", branches)
    branch_srcs: list[tuple[str, list[str]]] = []
    for branch in branch_list:
        if not isinstance(branch, dict):
            return None
        branch_dict = cast("dict[str, Any]", branch)
        # A `choose` branch may carry its own `alias`/`enabled`
        # (docs/internals/ha-api-notes.md §21): the HA UI names/toggles individual
        # branches, distinct from the whole `choose` block's own alias/enabled
        # (already handled below) and from any step's own alias/enabled inside
        # the branch's sequence.
        if set(branch_dict) - _STEP_OPTION_KEYS != {"conditions", "sequence"}:
            return None
        raw_conds = branch_dict["conditions"]
        if not isinstance(raw_conds, list):
            return None
        conds = cast("list[Any]", raw_conds)
        # 0..n conditions: [] is the UI's unconditional final branch (distinct
        # from `default:`, preserved exactly); 2+ is HA's implicit AND.
        cond_srcs: list[str] = []
        for cond in conds:
            if not isinstance(cond, dict):
                return None
            cond_src = decompile_condition(cast("dict[str, Any]", cond))
            if cond_src is None:
                return None
            cond_srcs.append(cond_src)
        seq_lines = _actions_block(branch_dict["sequence"], resolver)
        if seq_lines is None:
            return None
        when_parts = [*cond_srcs, *_step_option_kwargs_src(branch_dict)]
        branch_srcs.append((", ".join(when_parts), _flatten(seq_lines)))

    choose_header_parts = _step_option_kwargs_src(body)
    out = [f"with choose({', '.join(choose_header_parts)}) as c:"]
    for when_args, seq_lines in branch_srcs:
        out.extend(indent_lines([f"with c.when_({when_args}):"]))
        if not seq_lines:
            out.extend(indent_lines(["pass"], levels=2))
        else:
            out.extend(indent_lines(seq_lines, levels=2))
    if "default" in body:
        default_lines = _actions_block(body["default"], resolver)
        if default_lines is None:
            return None
        out.extend(indent_lines(["with c.default():"]))
        flat_default = _flatten(default_lines)
        if not flat_default:
            out.extend(indent_lines(["pass"], levels=2))
        else:
            out.extend(indent_lines(flat_default, levels=2))
    return out


def _repeat(body: dict[str, Any], resolver: CallResolver | None) -> list[str] | None:
    raw_repeat = body.get("repeat")
    if not isinstance(raw_repeat, dict) or "sequence" not in raw_repeat:
        return None
    repeat = cast("dict[str, Any]", raw_repeat)
    seq_lines = _actions_block(repeat["sequence"], resolver)
    if seq_lines is None:
        return None
    flat_seq = _flatten(seq_lines)
    step_kwargs = _step_option_kwargs_src(body)

    header: str | None = None
    if "count" in repeat and set(repeat) == {"count", "sequence"}:
        # `count` is the blessed spelling for a shared-script runtime repeat
        # count (`repeat_count(times)`, the marker HA natively supports as a
        # template string) -- field-aware so a bare field read decompiles to
        # the bare parameter, not the raw `"{{ times }}"`.
        args = ", ".join([_render_data_value(repeat["count"]), *step_kwargs])
        header = f"with repeat_count({args}):"
    elif "while" in repeat and set(repeat) == {"while", "sequence"}:
        raw_conds = repeat["while"]
        if isinstance(raw_conds, list):
            conds = cast("list[Any]", raw_conds)
            if len(conds) == 1 and isinstance(conds[0], dict):
                cond_dict = cast("dict[str, Any]", conds[0])
                cond_src = decompile_condition(cond_dict)
                if cond_src is not None:
                    args = ", ".join([cond_src, *step_kwargs])
                    header = f"with repeat_while({args}):"
    elif "until" in repeat and set(repeat) == {"until", "sequence"}:
        raw_conds = repeat["until"]
        if isinstance(raw_conds, list):
            conds = cast("list[Any]", raw_conds)
            if len(conds) == 1 and isinstance(conds[0], dict):
                cond_dict = cast("dict[str, Any]", conds[0])
                cond_src = decompile_condition(cond_dict)
                if cond_src is not None:
                    args = ", ".join([cond_src, *step_kwargs])
                    header = f"with repeat_until({args}):"
    elif "for_each" in repeat and set(repeat) == {"for_each", "sequence"}:
        args = ", ".join([render_literal(repeat["for_each"]), *step_kwargs])
        header = f"with repeat_for_each({args}):"

    if header is None:
        return None
    out = [header]
    if not flat_seq:
        out.extend(indent_lines(["pass"]))
    else:
        out.extend(indent_lines(flat_seq))
    return out


def _parallel(body: dict[str, Any], resolver: CallResolver | None) -> list[str] | None:
    branches = body.get("parallel")
    if not isinstance(branches, list):
        return None
    branch_list = cast("list[Any]", branches)
    # Two branch shapes decompile without an explicit `p.branch(...)`: a bare
    # one-action sequence with no alias/enabled (the original "one action per
    # branch" compiler-emitted shape, matching
    # fixtures/configs/automation_parallel_action.json) becomes a top-level
    # statement inside `with parallel():`. Any other branch shape -- more than
    # one step in its sequence, or the branch itself carrying `alias`/`enabled`
    # (docs/internals/ha-api-notes.md §21: the HA UI can name/toggle a whole multi-step
    # parallel branch, distinct from any one step's own alias/enabled) --
    # needs the explicit `with p.branch(...):` form, so `with parallel() as
    # p:` is used instead of the bare `with parallel():`.
    branch_plans: list[tuple[bool, dict[str, Any], list[str]]] = []
    any_explicit = False
    for branch in branch_list:
        if not isinstance(branch, dict):
            return None
        branch_dict = cast("dict[str, Any]", branch)
        if set(branch_dict) - _STEP_OPTION_KEYS != {"sequence"}:
            return None
        raw_seq = branch_dict["sequence"]
        if not isinstance(raw_seq, list):
            return None
        seq = cast("list[Any]", raw_seq)
        if not all(isinstance(step, dict) for step in seq):
            return None
        seq_lines = _actions_block(seq, resolver)
        if seq_lines is None:
            return None
        flat_seq = _flatten(seq_lines)
        has_branch_options = bool(_STEP_OPTION_KEYS & set(branch_dict))
        is_bare = len(seq) == 1 and not has_branch_options
        if not is_bare:
            any_explicit = True
        branch_plans.append((is_bare, branch_dict, flat_seq))

    header_parts = _step_option_kwargs_src(body)
    if not any_explicit:
        out = [f"with parallel({', '.join(header_parts)}):"]
        flat: list[str] = []
        for _, _, seq_lines in branch_plans:
            flat.extend(seq_lines)
        if not flat:
            out.extend(indent_lines(["pass"]))
        else:
            out.extend(indent_lines(flat))
        return out

    p_args = ", ".join(header_parts)
    out = [f"with parallel({p_args}) as p:"]
    for is_bare, branch_dict, seq_lines in branch_plans:
        if is_bare:
            out.extend(indent_lines(seq_lines))
            continue
        branch_kwargs = _step_option_kwargs_src(branch_dict)
        out.extend(indent_lines([f"with p.branch({', '.join(branch_kwargs)}):"]))
        if not seq_lines:
            out.extend(indent_lines(["pass"], levels=2))
        else:
            out.extend(indent_lines(seq_lines, levels=2))
    return out


def _wait_for(body: dict[str, Any]) -> list[str] | None:
    from hassle.decompiler.exprs import decompile_trigger

    known = {"wait_for_trigger", "timeout", "continue_on_timeout"} | _STEP_OPTION_KEYS
    if not set(body) <= known:
        return None
    triggers = body["wait_for_trigger"]
    if not isinstance(triggers, list):
        return None
    trigger_list = cast("list[Any]", triggers)
    trigger_srcs: list[str] = []
    for trig in trigger_list:
        if not isinstance(trig, dict):
            return None
        trig_dict = cast("dict[str, Any]", trig)
        src = decompile_trigger(trig_dict)
        if src is None:
            return None
        trigger_srcs.append(src)
    parts = list(trigger_srcs)
    if "timeout" in body:
        parts.append(f"timeout={render_literal(body['timeout'])}")
    if "continue_on_timeout" in body:
        parts.append(f"continue_on_timeout={render_literal(body['continue_on_timeout'])}")
    parts.extend(_step_option_kwargs_src(body))
    return [f"wait_for({', '.join(parts)})"]


def _wait_template(body: dict[str, Any]) -> list[str]:
    known = {"wait_template", "timeout", "continue_on_timeout"} | _STEP_OPTION_KEYS
    if not set(body) <= known:
        return _raw_action(body)
    parts = [repr(body["wait_template"])]
    if "timeout" in body:
        parts.append(f"timeout={render_literal(body['timeout'])}")
    if "continue_on_timeout" in body:
        parts.append(f"continue_on_timeout={render_literal(body['continue_on_timeout'])}")
    parts.extend(_step_option_kwargs_src(body))
    return [f"wait_template({', '.join(parts)})"]


def _stop(body: dict[str, Any]) -> list[str]:
    known = {"stop", "error", "response_variable"}
    if not set(body) <= known:
        return _raw_action(body)
    parts: list[str] = []
    message = body.get("stop")
    if message:
        parts.append(repr(message))
    if "error" in body:
        parts.append(f"error={render_literal(body['error'])}")
    if "response_variable" in body:
        parts.append(f"response_variable={render_literal(body['response_variable'])}")
    return [f"stop({', '.join(parts)})"]


def _variables(body: dict[str, Any]) -> list[str]:
    raw_kwargs = body["variables"]
    if not isinstance(raw_kwargs, dict):
        return _raw_action(body)
    kwargs = cast("dict[str, Any]", raw_kwargs)
    parts = [f"{k}={render_literal(v)}" for k, v in kwargs.items()]
    return [f"variables({', '.join(parts)})"]


def _fire_event(body: dict[str, Any]) -> list[str]:
    event_type = body["event"]
    if not isinstance(event_type, str):
        return _raw_action(body)
    parts = [repr(event_type)]
    event_data = body.get("event_data")
    if isinstance(event_data, dict):
        data_dict = cast("dict[str, Any]", event_data)
        for k, v in data_dict.items():
            parts.append(f"{k}={render_literal(v)}")
    return [f"fire_event({', '.join(parts)})"]
