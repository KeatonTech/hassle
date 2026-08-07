"""``DashboardConfig`` -> DSL Python source (docs/internals/dashboards-design.md §6.2).

The dashboard sibling of ``hassle.decompiler.codegen``'s automation/script
emitters: :func:`dashboard_source` walks the §3.2 envelope (``meta``/``config``)
and emits the ``@dashboard(...)``/``@raw_dashboard(...)`` decorator plus a body
of ``with view(...):`` / ``with section():`` / badge / card statements,
choosing per §5.5's raw ladder at every level.

**The raw ladder, bottom-up (§5.5, container-recursion-tolerant per
ha-api-notes §20.4's precedent — a container never goes raw merely because a
child did):**

- an unknown card ``type`` (absent from ``CARD_REGISTRY``) -> ``raw_card``;
- a known container card whose CHILD required ``raw_card`` stays a typed
  container wrapping it (the child's fallback never propagates upward);
- a section whose own shape isn't exactly what ``section()`` can produce
  (a non-``"grid"`` type, a missing/non-list ``cards``, or ANY key the
  builder doesn't model) -> ``raw_section``;
- a view whose own structure ``view()`` cannot produce -- both a ``sections``
  AND a ``cards`` key, or neither (the F5 appendix's two coordination
  points, §6.1.1), a ``panel`` view without exactly one card, or a legacy
  bare-string badge entry (``badge()`` has no shape that reproduces a bare
  string, only the modern object form or a verbatim dict -- structure.py's
  own docstring) -> ``raw_view``. Ordinary unknown VIEW keys, by contrast,
  round-trip through ``view()``'s own ``extra={...}`` valve (§5.3) rather
  than forcing raw -- deliberately asymmetric with section's stricter rule
  (see ``_try_emit_section``'s docstring for why);
- a config whose top level isn't exactly ``{"views": [...]}`` (e.g. a
  ``strategy:`` key), or ``meta`` carrying anything outside the registry's
  five known fields, or an envelope with keys other than ``meta``/``config``
  -> the whole object falls to ``@raw_dashboard``.

**Card emission is generically driven by ``CARD_REGISTRY``** (§6.1.1's
frozen table): a stored card's ``type`` string is looked up, the row's
``builder`` name is resolved to the real callable and introspected
(``inspect.signature``) for its declared keyword names -- no card type is
ever hardcoded here. ``CardSpec.declared`` is the authoritative "known
kwarg" set when populated (every real DB3 registration populates it); a row
with no such field falls back to resolving only the builder's REQUIRED
parameters by name (Python cannot call a function while omitting one) and
routing every remaining OPTIONAL key through ``extra=`` wholesale -- both
shapes are always safe to call.

**Varargs-rows cards** (``entities``/``glance``/``history_graph``/
``statistics_graph``/``calendar``/``logbook``/``map``/``picture_glance``,
plus ``conditional``'s ``conditions=``): the builder's signature has exactly
one ``VAR_POSITIONAL`` parameter (``*rows``/``*entities``/``*conditions``),
which does not necessarily share its OWN Python name with the stored key
that feeds it (``entities``/``glance`` name theirs ``*rows`` while storing
under ``"entities"``; ``history_graph`` et al. name theirs ``*entities``,
matching the stored key directly; ``conditional`` names its ``*conditions``,
also matching). :func:`_resolve_rows_key` tries the varargs parameter's OWN
name against the stored body first (covers the name-matches-key cases),
then falls back to the one ``entity_params`` entry that is itself a stored
list (covers the name-differs-from-key cases, e.g. ``picture_glance`` whose
OTHER ``entity_params`` entry, ``camera_image``, is a plain scalar kwarg,
never the rows list). Each row renders through :func:`_render_row_item`,
which tries the ``cond`` inverter first (covers ``conditional``'s condition
rows) and falls back to the entity-position renderer for a string / a
verbatim literal for a dict (covers the entity-row families; a dict row is
stored by the compiler via ``copy.deepcopy`` verbatim, never rewritten, so
literal-rendering it is always byte-exact regardless of what's inside).

**Container cards with a single-dict child** (``container="card"``,
``conditional``/``entity_filter``): the compiler's own
``push_container(..., child_is_list=False)`` convention (a DB3 review-round
fix) stores the child key ABSENT for zero children, present as a bare dict
for one -- never a list. ``conditional`` additionally enforces "exactly
one" at compile time (`ConditionalCardArityError`), but that is a
compile-time-only guard this module has no static way to see per row;
treating "absent -> zero children" uniformly for every ``container="card"``
row is what makes ``entity_filter``'s legitimate zero-children shape
decompile typed, and is harmless for ``conditional`` in practice (a
real/compiled conditional card always has its ``card:`` key -- the arity
guard prevented it from ever being saved without one).

**Always-materialized keys**: every varargs-rows builder (and
``conditional``'s ``conditions=``) unconditionally writes its stored key
even for zero rows (``body["entities"] = normalize_rows(...)``, never
``put()``'s skip-on-``None`` convention) -- a stored card missing that key
entirely is therefore unrepresentable through the typed builder (recompiling
would materialize a key the original never had) and falls back to
``raw_card``, exactly like any other required-parameter gap.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, cast

from hassle.compiler.dashboards.card_registry import (
    CARD_REGISTRY,
    CardSpec,
    ensure_builtin_families_loaded,
)
from hassle.compiler.dashboards.decorators import DEFAULT_IDENTITY
from hassle.compiler.dashboards.structure import (
    _VIEW_OPTION_ORDER,  # pyright: ignore[reportPrivateUsage]
)
from hassle.decompiler.actions import INDENT, indent_lines
from hassle.decompiler.exprs import render_entity_position, render_literal
from hassle.ir.models import DashboardConfig

# The registry rows are an import side effect of the family modules; a process
# that never imported the public `hassle.cards` namespace would otherwise see
# an EMPTY registry here and raw-fall every card (`hassle-dev
# decompile-coverage` did exactly that). The loader lives in card_registry —
# importing `hassle.cards` from the decompiler would be an upward import the
# package-layering test rejects. Regression:
# test_decompile_dashboards.py::test_typed_emission_does_not_depend_on_import_order.
ensure_builtin_families_loaded()

# The registry metadata kwargs, in the decorator's own emission order
# (decorators.py's `DASHBOARD_OPTIONS`, duplicated here as a plain literal
# tuple to avoid importing a private-by-convention compiler constant for
# something this small; `url_path` first always, since it's the identity).
_META_KEY_ORDER: tuple[str, ...] = ("url_path", "title", "icon", "show_in_sidebar", "require_admin")

# Sentinel distinguishing "key entirely absent" from "key present with value
# `None`" when popping an optional modeled key out of a stored dict --
# `dict.pop(key, None)` conflates the two, and every card/section/view/meta
# builder's own `put()` (or `put()`-equivalent, `build_meta`'s `is not None`
# filter) convention treats an explicitly-passed `None` kwarg IDENTICALLY to
# omitting it: neither one ever reaches the stored body. A key PRESENT with
# an explicit JSON `null` is therefore a DIFFERENT stored shape than the key
# being absent (the two dicts have a different key set), but no typed-
# builder call can reproduce the "present as null" shape -- there is no
# kwarg spelling for it. Silently treating them the same up-converts a
# present-null key into a dropped one on recompile, an I3 violation (BLOCK-1,
# a review-round finding). Every site below therefore pops with `_MISSING`
# and explicitly rejects (escalates the whole node to its raw form) whenever
# the popped value `is None` -- never just "falsy" or "absent".
_MISSING: Any = object()

_SECTIONS_VIEW_TYPE = "sections"


# ---------------------------------------------------------------------------
# Entity + condition rendering
# ---------------------------------------------------------------------------


def _entity_arg(value: Any) -> str:
    """An entity-position argument: ``e.<domain>.<object_id>`` for a value
    matching the entity-id shape (or a list of them), a plain literal
    otherwise -- ``render_entity_position`` already degrades gracefully."""
    return render_entity_position(value)


def _try_dashboard_condition(item: Any) -> str | None:
    """Decompile one Lovelace condition dict to a ``cond.*`` call, or ``None``
    when it isn't one of the known shapes (§5.4) -- the caller falls back to
    a verbatim dict literal, which is always accepted anywhere a condition
    is (I3)."""
    if not isinstance(item, dict):
        return None
    body = cast("dict[str, Any]", item)
    ctype = body.get("condition")
    if not isinstance(ctype, str):
        return None
    handler = _COND_HANDLERS.get(ctype)
    if handler is None:
        return None
    return handler(body)


def _cond_state(body: dict[str, Any]) -> str | None:
    known = {"condition", "entity", "state", "state_not"}
    if not set(body) <= known or "entity" not in body:
        return None
    entity = body["entity"]
    if not isinstance(entity, str):
        return None
    entity_src = _entity_arg(entity)
    has_state = "state" in body
    has_not = "state_not" in body
    if has_state and has_not:
        state_src = render_literal(body["state"])
        not_src = render_literal(body["state_not"])
        return f"cond.state({entity_src}, {state_src}, not_={not_src})"
    if has_state:
        return f"cond.state({entity_src}, {render_literal(body['state'])})"
    if has_not:
        return f"cond.state({entity_src}, not_={render_literal(body['state_not'])})"
    return f"cond.state({entity_src})"


def _cond_numeric(body: dict[str, Any]) -> str | None:
    known = {"condition", "entity", "above", "below"}
    if not set(body) <= known or "entity" not in body:
        return None
    entity = body["entity"]
    if not isinstance(entity, str):
        return None
    parts = [_entity_arg(entity)]
    for key in ("above", "below"):
        if key in body:
            parts.append(f"{key}={render_literal(body[key])}")
    return f"cond.numeric({', '.join(parts)})"


def _cond_screen(body: dict[str, Any]) -> str | None:
    if set(body) != {"condition", "media_query"}:
        return None
    media_query = body["media_query"]
    if not isinstance(media_query, str):
        return None
    return f"cond.screen({media_query!r})"


def _cond_user(body: dict[str, Any]) -> str | None:
    if set(body) != {"condition", "users"}:
        return None
    users = body["users"]
    if not isinstance(users, list) or not all(isinstance(u, str) for u in cast("list[Any]", users)):
        return None
    return f"cond.user({', '.join(repr(u) for u in cast('list[str]', users))})"


def _cond_combine(name: str) -> Any:
    def _handler(body: dict[str, Any]) -> str | None:
        if set(body) != {"condition", "conditions"}:
            return None
        inner = body["conditions"]
        if not isinstance(inner, list):
            return None
        sub_srcs: list[str] = []
        for sub in cast("list[Any]", inner):
            src = _try_dashboard_condition(sub)
            if src is None:
                return None
            sub_srcs.append(src)
        return f"{name}({', '.join(sub_srcs)})"

    return _handler


_COND_HANDLERS: dict[str, Any] = {
    "state": _cond_state,
    "numeric_state": _cond_numeric,
    "screen": _cond_screen,
    "user": _cond_user,
    "and": _cond_combine("cond.all"),
    "or": _cond_combine("cond.any"),
    "not": _cond_combine("cond.not_"),
}


def _render_condition_item(item: Any) -> str:
    src = _try_dashboard_condition(item)
    return src if src is not None else render_literal(item)


def _try_visibility_kwarg(visibility_raw: Any) -> str | None:
    """``visibility=[...]`` source for a stored ``visibility`` list, or
    ``None`` if the stored value isn't a list at all (the ONE shape
    ``normalize_visibility`` can ever produce -- possibly empty, since an
    explicit ``visibility=[]`` call reproduces that)."""
    if not isinstance(visibility_raw, list):
        return None
    items = cast("list[Any]", visibility_raw)
    return "[" + ", ".join(_render_condition_item(item) for item in items) + "]"


# ---------------------------------------------------------------------------
# Badges
# ---------------------------------------------------------------------------

_BADGE_ENTITY_SHAPE_KEYS = frozenset({"type", "entity", "visibility"})


def _try_emit_one_badge(entry: Any) -> str | None:
    """One ``badges[]`` entry -> a ``badge(...)`` statement, or ``None`` when
    the entry is a bare string -- the ONE badge shape ``badge()`` cannot
    reproduce (it only ever builds the modern object form or copies a dict
    verbatim, structure.py's own docstring; a real HA install can still
    write a legacy bare-string badge, §2.2 item 6). Any dict shape ALWAYS
    succeeds (dict passthrough is unconditional), so this only ever returns
    ``None`` for a non-dict entry."""
    if not isinstance(entry, dict):
        return None
    body = cast("dict[str, Any]", entry)
    if (
        body.get("type") == "entity"
        and isinstance(body.get("entity"), str)
        and set(body) <= _BADGE_ENTITY_SHAPE_KEYS
    ):
        entity_src = _entity_arg(body["entity"])
        if "visibility" in body:
            vis_src = _try_visibility_kwarg(body["visibility"])
            if vis_src is not None:
                return f"badge({entity_src}, visibility={vis_src})"
            # Malformed visibility -- fall through to verbatim passthrough.
        else:
            return f"badge({entity_src})"
    # Verbatim dict passthrough: badge()'s "legacy/unknown badge shapes"
    # branch (structure.py) copies the WHOLE dict unchanged, so this always
    # reproduces `entry` exactly regardless of its shape.
    return f"badge({render_literal(entry)})"


def _try_emit_badges(badges_raw: Any) -> list[str] | None:
    if not isinstance(badges_raw, list) or not badges_raw:
        # `view()` only ever sets `badges` when at least one was recorded
        # (`if node.badges:` in structure.py) -- an empty list (or non-list)
        # can never be reproduced, so the whole view must escalate to
        # `raw_view` instead (handled by the caller).
        return None
    stmts: list[str] = []
    for entry in cast("list[Any]", badges_raw):
        stmt = _try_emit_one_badge(entry)
        if stmt is None:
            return None
        stmts.append(stmt)
    return stmts


# ---------------------------------------------------------------------------
# Cards -- generically driven by CARD_REGISTRY (§6.1.1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BuilderSignature:
    names: frozenset[str]
    required: frozenset[str]
    #: The one VAR_POSITIONAL parameter's own Python name (``"rows"``,
    #: ``"entities"``, ``"conditions"``, ...), or ``None`` for a builder with
    #: no varargs parameter at all. Never counted in `names`/`required` --
    #: it is never itself a stored body key (see module docstring).
    varargs_name: str | None = None


def _resolve_builder_callable(builder: str) -> Any | None:
    """The real callable a ``CardSpec.builder`` name refers to (``"c.tile"``
    -> ``hassle.cards.tile``, a bare ``"view"`` -> ``hassle.view``), or
    ``None`` if it can't be resolved (never crashes the decompiler)."""
    try:
        if builder.startswith("c."):
            from hassle import cards as cards_module

            return getattr(cards_module, builder[2:])
        import hassle

        return getattr(hassle, builder)
    except AttributeError:
        return None


def _builder_signature(fn: Any) -> _BuilderSignature | None:
    """Introspect ``fn``'s declared keyword names, or ``None`` if its shape
    can't be driven generically (``**kwargs``/positional-only/more than one
    ``*args`` parameter): the caller falls back to ``raw_card`` for that
    node, never guessing at a card-specific call convention this table
    doesn't describe (item 8: no hardcoded card type list). Exactly one
    ``VAR_POSITIONAL`` parameter IS supported (the varargs-rows convention,
    §5.3/module docstring) -- its own name is reported separately via
    ``varargs_name``, never folded into `names`/`required`."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    names: set[str] = set()
    required: set[str] = set()
    varargs_name: str | None = None
    for name, param in sig.parameters.items():
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            if varargs_name is not None:
                return None  # more than one *args -- not a shape this module models
            varargs_name = name
            continue
        if param.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY):
            return None
        names.add(name)
        if param.default is inspect.Parameter.empty:
            required.add(name)
    return _BuilderSignature(
        names=frozenset(names), required=frozenset(required), varargs_name=varargs_name
    )


def _render_card_kwarg_value(key: str, value: Any, spec: CardSpec) -> str:
    if key in spec.entity_params:
        return render_entity_position(value)
    return render_literal(value)


def _resolve_rows_key(varargs_name: str, spec: CardSpec, body: dict[str, Any]) -> str | None:
    """Which stored key in ``body`` feeds a builder's ``*varargs_name``
    parameter, or ``None`` if it can't be determined unambiguously.

    Tries the varargs parameter's OWN name against the stored body first
    (``conditional``'s ``*conditions`` -> stored ``"conditions"``: name
    matches key directly), then falls back to the ONE ``entity_params``
    entry that is itself list-valued in ``body`` (``entities``/``glance``'s
    ``*rows`` -> stored ``"entities"``: name and key differ, but
    ``entity_params`` names the real key; ``picture_glance``'s OTHER
    ``entity_params`` entry, ``camera_image``, is a plain scalar kwarg, so it
    never matches this list-valued filter)."""
    if isinstance(body.get(varargs_name), list):
        return varargs_name
    candidates = [name for name in spec.entity_params if isinstance(body.get(name), list)]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _render_row_item(item: Any) -> str:
    """One varargs-row element -> its source expression. Tries the ``cond``
    inverter first (covers ``conditional``'s condition rows -- a dict with a
    ``condition`` key that ``_try_dashboard_condition`` recognizes), then the
    entity-position renderer for a string (covers the entity-row families),
    else a verbatim literal (a dict row is stored by ``normalize_rows`` via
    ``copy.deepcopy`` -- never rewritten -- so rendering it as a literal is
    always byte-exact regardless of its own contents)."""
    cond_src = _try_dashboard_condition(item)
    if cond_src is not None:
        return cond_src
    if isinstance(item, str):
        return _entity_arg(item)
    return render_literal(item)


_CHILD_KEY_FOR_CONTAINER: dict[str, str] = {
    "cards": "cards",
    "card": "card",
    "sections": "sections",
}


def _try_emit_registry_card(card: dict[str, Any], spec: CardSpec) -> list[str] | None:
    body = dict(card)
    body.pop("type", None)

    child_key = _CHILD_KEY_FOR_CONTAINER.get(spec.container)
    children_raw: Any = None
    has_single_child = False
    if child_key is not None:
        if spec.container == "card":
            # `push_container(..., child_is_list=False)` (a DB3 review-round
            # fix) leaves this key entirely ABSENT for zero children, a bare
            # dict for exactly one -- never a list. Absent is a legitimate,
            # everyday shape (`entity_filter` with no presentation card), so
            # unlike `cards`/`sections` below, a missing key here is NOT a
            # reason to fall back to raw_card (module docstring).
            if child_key in body:
                children_raw = body.pop(child_key)
                if not isinstance(children_raw, dict):
                    return None
                has_single_child = True
        else:
            if child_key not in body:
                return None  # the compiler always materializes cards/sections, even empty
            children_raw = body.pop(child_key)
            if not isinstance(children_raw, list):
                return None

    visibility_raw = body.pop("visibility", _MISSING)
    visibility_src: str | None = None
    if visibility_raw is not _MISSING:
        # BLOCK-1: called even when `visibility_raw` is an explicit `None`
        # (present-but-null) -- `_try_visibility_kwarg` already returns
        # `None` for any non-list value, `None` included, so this correctly
        # escalates instead of silently treating "present as null" the same
        # as "absent" (the sentinel-vs-`None` distinction is what fixes it).
        visibility_src = _try_visibility_kwarg(visibility_raw)
        if visibility_src is None:
            return None

    fn = _resolve_builder_callable(spec.builder)
    if fn is None:
        return None
    sig = _builder_signature(fn)
    if sig is None:
        return None

    # Varargs-rows cards (module docstring): the ONE VAR_POSITIONAL parameter
    # maps onto some stored list key, rendered as positional arguments rather
    # than a `key=[...]` kwarg. Resolved and popped BEFORE the known-kwargs
    # loop below so it's never double-counted there.
    positional_args_src: list[str] = []
    if sig.varargs_name is not None:
        rows_key = _resolve_rows_key(sig.varargs_name, spec, body)
        if rows_key is None or rows_key not in body:
            return None  # always-materialized key absent, or ambiguous -- unsafe to call
        rows_value = body.pop(rows_key)
        if not isinstance(rows_value, list):
            return None
        positional_args_src = [_render_row_item(row) for row in cast("list[Any]", rows_value)]

    # Forward-compat with an optional registry backfill: `CardSpec.declared`
    # (module docstring) is the authoritative known-kwarg set WHEN a family
    # has populated it; a bare/older row (this base) has none, so every
    # OPTIONAL leftover key routes through `extra=` wholesale instead --
    # correct either way, and automatically sharper once `declared` lands.
    # Required params are ALWAYS resolved by name regardless of `declared`
    # (never inside `extra=`): Python cannot call a function while omitting
    # a required positional-or-keyword argument, so a required param must be
    # a real kwarg or the emitted call is simply invalid -- correctness
    # (I3, compile(decompile(x)) == x) is never traded for a nicer-looking
    # `extra=` grouping.
    empty_declared: frozenset[str] = frozenset()
    declared = cast("frozenset[str]", getattr(spec, "declared", empty_declared))
    known_names = (declared & sig.names) if declared else frozenset(sig.required)

    known_kwargs: list[tuple[str, Any]] = []
    leftover: dict[str, Any] = {}
    for key, value in body.items():
        if key in known_names:
            known_kwargs.append((key, value))
        else:
            leftover[key] = value

    missing_required = sig.required - {k for k, _ in known_kwargs}
    if missing_required:
        return None  # a required positional param has no source value -- unsafe to call

    kwargs_src = [
        f"{key}={_render_card_kwarg_value(key, value, spec)}" for key, value in known_kwargs
    ]
    if leftover:
        kwargs_src.append(f"extra={render_literal(leftover)}")
    if visibility_src is not None:
        kwargs_src.append(f"visibility={visibility_src}")

    call_args_src = [*positional_args_src, *kwargs_src]
    call_name = spec.builder
    if not spec.context_manager:
        return [f"{call_name}({', '.join(call_args_src)})"]

    header = f"with {call_name}({', '.join(call_args_src)}):"
    inner_lines: list[str]
    if spec.container == "card":
        inner_lines = _emit_card(children_raw) if has_single_child else []
    else:
        inner_lines = []
        for child in cast("list[Any]", children_raw):
            inner_lines.extend(_emit_card(child))
    if not inner_lines:
        inner_lines = ["pass"]
    return [header, *indent_lines(inner_lines)]


def _emit_card(card: Any) -> list[str]:
    """One card node -> its source statement(s). Never fails: an unknown
    type, or any shape ``_try_emit_registry_card`` can't safely drive,
    degrades to ``raw_card`` for exactly that node (container-recursion
    tolerant -- an ancestor container is never forced raw by this)."""
    if isinstance(card, dict):
        card_dict = cast("dict[str, Any]", card)
        card_type = card_dict.get("type")
        if isinstance(card_type, str):
            spec = CARD_REGISTRY.get(card_type)
            if spec is not None:
                result = _try_emit_registry_card(card_dict, spec)
                if result is not None:
                    return result
    return [f"raw_card({render_literal(card)})"]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _try_emit_section(section: Any) -> list[str] | None:
    """A ``sections[]`` entry -> ``with section(...):`` + its cards, or
    ``None`` (caller falls back to ``raw_section``).

    Deliberately asymmetric with ``view()``'s own ``extra={...}`` valve: ANY
    key ``section()`` doesn't itself model (`type`/`column_span`/`visibility`/
    `cards`) forces the whole section to ``raw_section`` here, rather than an
    `extra=` passthrough -- a stricter rule than the view/card generic
    ``extra=`` treatment (docs/internals/dashboards-design.md §5.5's own
    wording draws this line at "own keys", not "structural keys" alone).
    """
    if not isinstance(section, dict):
        return None
    body = dict(cast("dict[str, Any]", section))
    if body.pop("type", None) != "grid":
        return None
    if "cards" not in body:
        return None  # `section()` always materializes `cards`, even empty
    cards_raw = body.pop("cards")
    if not isinstance(cards_raw, list):
        return None

    visibility_raw = body.pop("visibility", _MISSING)
    visibility_src: str | None = None
    if visibility_raw is not _MISSING:
        # BLOCK-1: called even when `visibility_raw` is an explicit `None`
        # (present-but-null) -- `_try_visibility_kwarg` already returns
        # `None` for any non-list value, `None` included, so this correctly
        # escalates instead of silently treating "present as null" the same
        # as "absent" (the sentinel-vs-`None` distinction is what fixes it).
        visibility_src = _try_visibility_kwarg(visibility_raw)
        if visibility_src is None:
            return None

    column_span = body.pop("column_span", _MISSING)
    if column_span is None:
        # BLOCK-1: present-but-null -- put()'s skip-on-None convention can
        # never reproduce this through the typed builder.
        return None
    if body:
        return None  # any leftover unmodeled key -> raw_section

    kwargs: list[str] = []
    if column_span is not _MISSING:
        kwargs.append(f"column_span={render_literal(column_span)}")
    if visibility_src is not None:
        kwargs.append(f"visibility={visibility_src}")

    child_lines: list[str] = []
    for card in cast("list[Any]", cards_raw):
        child_lines.extend(_emit_card(card))
    if not child_lines:
        child_lines = ["pass"]
    return [f"with section({', '.join(kwargs)}):", *indent_lines(child_lines)]


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def _try_emit_view(view: Any) -> list[str] | None:
    """A ``views[]`` entry -> ``with view(...):`` + its badges/children, or
    ``None`` (caller falls back to ``raw_view``). Structural eligibility
    (the F5 appendix's two coordination points, §6.1.1): a stored view must
    carry EXACTLY the child key its own ``type`` implies (``sections`` for a
    ``sections``-type view, ``cards`` otherwise) -- never both, never
    neither -- and a ``panel`` view must hold exactly one card
    (``PanelViewArityError`` at compile time otherwise). Ordinary unknown
    top-level keys round-trip via ``extra={...}`` instead (§5.3)."""
    if not isinstance(view, dict):
        return None
    body = dict(cast("dict[str, Any]", view))

    raw_type = body.pop("type", _MISSING)
    if raw_type is None:
        # BLOCK-1: present-but-null. `view()`'s `type=None` sentinel means
        # "the `type` key is entirely ABSENT" (the legacy masonry shape,
        # its own default is `"sections"`, never `None`) -- there is no
        # call shape that reproduces `type` PRESENT with an explicit null,
        # a different stored dict than one missing the key outright.
        return None
    if raw_type is not _MISSING and not isinstance(raw_type, str):
        return None
    view_type: str | None = None if raw_type is _MISSING else cast("str", raw_type)
    is_sections = view_type == _SECTIONS_VIEW_TYPE
    child_key = "sections" if is_sections else "cards"
    other_key = "cards" if is_sections else "sections"
    if other_key in body:
        return None  # both keys present -- unrepresentable (F5 coordination point)
    if child_key not in body:
        return None  # neither key present -- unrepresentable (F5 coordination point)
    raw_children = body.pop(child_key)
    if not isinstance(raw_children, list):
        return None
    children_raw = cast("list[Any]", raw_children)
    if view_type == "panel" and len(children_raw) != 1:
        return None  # PanelViewArityError would fire at recompile

    badges_raw = body.pop("badges", _MISSING)
    badge_stmts: list[str] = []
    if badges_raw is not _MISSING:
        # BLOCK-1: called even for an explicit `None` -- `_try_emit_badges`
        # already rejects any non-list value (`None` included), so this
        # correctly escalates a present-but-null `badges` key instead of
        # silently treating it as "zero badges recorded" (absent).
        result = _try_emit_badges(badges_raw)
        if result is None:
            return None
        badge_stmts = result

    visibility_raw = body.pop("visibility", _MISSING)
    visibility_src: str | None = None
    if visibility_raw is not _MISSING:
        # BLOCK-1: called even when `visibility_raw` is an explicit `None`
        # (present-but-null) -- `_try_visibility_kwarg` already returns
        # `None` for any non-list value, `None` included, so this correctly
        # escalates instead of silently treating "present as null" the same
        # as "absent" (the sentinel-vs-`None` distinction is what fixes it).
        visibility_src = _try_visibility_kwarg(visibility_raw)
        if visibility_src is None:
            return None

    kwargs: list[str] = []
    if not is_sections:
        kwargs.append(f"type={view_type!r}" if view_type is not None else "type=None")
    for key in _VIEW_OPTION_ORDER:
        if key in body:
            value = body.pop(key)
            if value is None:
                # BLOCK-1: present-but-null. `put()`'s skip-on-None
                # convention means `view(title=None, ...)` is IDENTICAL, at
                # compile time, to omitting `title=` entirely -- there is no
                # call shape that reproduces `title` PRESENT with an
                # explicit null.
                return None
            kwargs.append(f"{key}={render_literal(value)}")
    if visibility_src is not None:
        kwargs.append(f"visibility={visibility_src}")
    if body:
        # Any remaining key is genuinely unknown to `view()` -- §5.3's
        # `extra=` forward-compatibility valve, not a raw fallback.
        kwargs.append(f"extra={render_literal(body)}")

    child_lines: list[str] = []
    if is_sections:
        for section in children_raw:
            result = _try_emit_section(section)
            child_lines.extend(
                result if result is not None else [f"raw_section({render_literal(section)})"]
            )
    else:
        for card in children_raw:
            child_lines.extend(_emit_card(card))

    inner_lines = [*badge_stmts, *child_lines]
    if not inner_lines:
        inner_lines = ["pass"]
    return [f"with view({', '.join(kwargs)}):", *indent_lines(inner_lines)]


def _emit_view(view: Any) -> list[str]:
    result = _try_emit_view(view)
    if result is not None:
        return result
    return [f"raw_view({render_literal(view)})"]


# ---------------------------------------------------------------------------
# The whole dashboard: @dashboard vs. @raw_dashboard
# ---------------------------------------------------------------------------


def _try_typed_decorator_kwargs(meta: Any) -> list[str] | None:
    if meta is None:
        return ["default=True"]
    if not isinstance(meta, dict):
        return None
    meta_dict = cast("dict[str, Any]", meta)
    if set(meta_dict) - set(_META_KEY_ORDER):
        return None  # an envelope-`meta` key `@dashboard` has no kwarg for
    if not isinstance(meta_dict.get("url_path"), str):
        return None  # covers url_path present-but-null too (fails isinstance(str))
    kwargs: list[str] = []
    for key in _META_KEY_ORDER:
        if key in meta_dict:
            value = meta_dict[key]
            if value is None:
                # BLOCK-1: present-but-null. `build_meta`'s own `is not
                # None` filter (decorators.py) means `@dashboard(icon=None,
                # ...)` is IDENTICAL, at compile time, to omitting `icon=`
                # entirely -- no call shape reproduces `icon` PRESENT with
                # an explicit null. Realistic trigger: `DirectBackend.
                # _dashboard_registry_payload` sends `icon: None` on every
                # update.
                return None
            kwargs.append(f"{key}={render_literal(value)}")
    return kwargs


def _raw_dashboard_source(obj: DashboardConfig, ident: str) -> str:
    """Whole-object fallback: ``@raw_dashboard(...)`` over a function
    returning the verbatim envelope (§5.5's top rung), mirroring
    ``codegen._raw_automation_source``."""
    identity = obj.identity
    decorator_kwarg = "default=True" if identity == DEFAULT_IDENTITY else f"url_path={identity!r}"
    body_src = render_literal(obj.to_ha())
    return f"@raw_dashboard({decorator_kwarg})\ndef {ident}():\n{INDENT}return {body_src}\n"


def dashboard_source(obj: DashboardConfig, ident: str) -> str:
    """Decompile one ``DashboardConfig`` to its DSL source (§6.2)."""
    envelope = obj.to_ha()
    if set(envelope) - {"meta", "config"}:
        # An envelope key besides meta/config is unrepresentable through
        # EITHER dashboard construct (`build_raw_envelope` only ever reads
        # those two) -- an extremely unlikely shape in practice (the
        # envelope is Hassle-composed, never fetched verbatim from HA), but
        # never crash: fall back to the whole-object form regardless.
        return _raw_dashboard_source(obj, ident)

    decorator_kwargs = _try_typed_decorator_kwargs(envelope.get("meta"))
    if decorator_kwargs is None:
        return _raw_dashboard_source(obj, ident)

    config = envelope.get("config")
    if not isinstance(config, dict):
        return _raw_dashboard_source(obj, ident)
    config_dict = cast("dict[str, Any]", config)
    if set(config_dict) - {"views"} or not isinstance(config_dict.get("views"), list):
        return _raw_dashboard_source(obj, ident)

    body_lines: list[str] = []
    for view in cast("list[Any]", config_dict["views"]):
        body_lines.extend(_emit_view(view))
    if not body_lines:
        body_lines = ["pass"]

    lines = [f"@dashboard({', '.join(decorator_kwargs)})", f"def {ident}():"]
    for line in body_lines:
        lines.append(f"{INDENT}{line}" if line else line)
    return "\n".join(lines) + "\n"
