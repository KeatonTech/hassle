"""Group-helper declarations (M21, mirrors M10's ``template_helpers.py``) --
the model/builder layer for the ``group`` config-entry domain.

``group_cover(name="Entryway Top", entities=["cover.a", "cover.b"])`` builds a
:class:`~hassle.ir.models.GroupHelperConfig` for one of the twelve group
domains (``hassle.ir.GROUP_DOMAINS``, F1-additive) and returns an
:class:`~hassle.compiler.helpers.EntityRef`, exactly like the nine storage-
collection helper builders in :mod:`hassle.compiler.helpers` -- same
"import-and-reference pattern" (DESIGN §5.7), same prebuilt-object
registration path into the active bundle registry.

**Identity:** there is no ``id=``/``unique_id=`` kwarg, mirroring template
helpers (docs/ha-api-notes.md §26.6/§38.1) -- real HA's `group` config flow
form schema rejects an unrecognized `unique_id` key outright. Identity is
derived from ``name`` (required), mirroring the nine storage helpers' "id is
a slug of name" rule -- the object key is ``"<group domain>:<slugify(name)>"``.

**No decorator form.** Unlike the template-helper builders (M13), a group
helper has no Jinja `state=` field to defer -- every group builder call is
the plain, immediate call form: build + register right now, at the call site.

**Three schema shapes (docs/ha-api-notes.md §38.1):** every flavor takes
``name=``/``entities=``/``hide_members=`` (default ``False``); three flavors
(``group_binary_sensor``/``group_light``/``group_switch``) additionally take
``all=`` (default ``False``); ``group_sensor`` additionally takes a required
``type=`` (the aggregation kind: min/max/mean/median/last/range/product/sum/
stdev). ``hide_members``/``all`` are ALWAYS materialized explicitly in the
compiled options body (never omitted just because they equal their default)
-- HA's own options-flow read-back always returns them explicitly too, so
this keeps a single canonical compiled form (I3/plan-noop, the same
one-canonical-form rule §38.1 documents).

``entities`` is a list of entity ids of the flavor's own domain, in the
EXACT order given -- never sorted/deduped (I3: order is caller-declared
data). Groups may nest (a group whose members are themselves group
entities) -- ``entities`` stores plain entity-id strings either way, no
special-casing needed here or in the decompiler.

``type=`` on ``group_sensor`` is a required keyword-only parameter with no
default (unlike ``hide_members=``/``all=``) -- Python itself raises
``TypeError`` on an omitted call, exactly the same "the signature IS the
required-field check" pattern every ``hassle.compiler.helpers`` builder
already uses for its own required ``id=`` kwarg. This differs from
`template_number`/`template_select`'s `set_value=`/`select_option=` (M10,
docs/ha-api-notes.md §26.11), which needed a dedicated compile-time
``CompileError`` subclass because those two kwargs had to stay optional at
the Python level (both call and decorator forms share one signature); a
group builder has no decorator form to accommodate, so a required
positional-or-keyword parameter is available and is the simpler mechanism.
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.helpers import EntityRef
from hassle.compiler.spans import capture_span
from hassle.ir import GROUP_DOMAINS
from hassle.ir.keys import slugify
from hassle.ir.models import GroupHelperConfig

# All GroupHelperConfig instances built by this module's constructor
# functions, in declaration order, for the lifetime of the process (or since
# the last `reset_declared_group_helpers()`) -- mirrors
# `hassle.compiler.template_helpers._DECLARED`'s seam for this module's own
# unit tests.
_DECLARED: list[GroupHelperConfig] = []


def reset_declared_group_helpers() -> None:
    """Clear the process-wide declared-group-helpers list (tests / repeated compiles)."""
    _DECLARED.clear()


def declared_group_helpers() -> list[GroupHelperConfig]:
    """Every group helper declared so far (in declaration order)."""
    return list(_DECLARED)


def _declare_group_helper(
    domain: str,
    name: str,
    *,
    entities: list[str],
    hide_members: bool,
    **fields: Any,
) -> EntityRef:
    if domain not in GROUP_DOMAINS:
        raise ValueError(
            f"unknown group helper domain {domain!r} (expected one of {sorted(GROUP_DOMAINS)})"
        )
    identity = slugify(name)
    body: dict[str, Any] = {
        "name": name,
        # `list(...)`, not the caller's own list object: a defensive copy so a
        # later caller-side mutation of their own `entities=` list can never
        # retroactively change an already-compiled/registered IR body (R8).
        "entities": list(entities),
        "hide_members": bool(hide_members),
        **{k: v for k, v in fields.items() if v is not None},
    }
    helper = GroupHelperConfig.model_validate(body)
    helper.attach_domain(domain)
    _DECLARED.append(helper)
    # Same §12 registration path helpers.py/template_helpers.py use: register
    # into the active bundle registry so the compiler lands this in
    # CompileResult.objects.
    from hassle.compiler.registry import current_registry

    current_registry().add_object(helper, capture_span(depth=1))
    return EntityRef(domain, identity)


def group_binary_sensor(
    *,
    name: str,
    entities: list[str],
    hide_members: bool = False,
    all: bool = False,
    **fields: Any,
) -> EntityRef:
    """Declare a ``group_binary_sensor`` helper (M21, docs/ha-api-notes.md §38.1).

    ``all=True`` mirrors HA's group "all entities must match" toggle (the
    group is ``on`` only when every member is ``on``, instead of the default
    "any member" OR semantics).
    """
    return _declare_group_helper(
        "group_binary_sensor",
        name,
        entities=entities,
        hide_members=hide_members,
        all=all,
        **fields,
    )


def group_button(
    *, name: str, entities: list[str], hide_members: bool = False, **fields: Any
) -> EntityRef:
    """Declare a ``group_button`` helper (M21, docs/ha-api-notes.md §38.1)."""
    return _declare_group_helper(
        "group_button", name, entities=entities, hide_members=hide_members, **fields
    )


def group_cover(
    *, name: str, entities: list[str], hide_members: bool = False, **fields: Any
) -> EntityRef:
    """Declare a ``group_cover`` helper (M21, docs/ha-api-notes.md §38.1).

    Groups may nest: a `group_cover`'s own ``entities=`` may name another
    group's entity id (e.g. the owner's `cover.entryway_top` group contains
    `cover.bay_window_top`, itself a group, §38.1).
    """
    return _declare_group_helper(
        "group_cover", name, entities=entities, hide_members=hide_members, **fields
    )


def group_event(
    *, name: str, entities: list[str], hide_members: bool = False, **fields: Any
) -> EntityRef:
    """Declare a ``group_event`` helper (M21, docs/ha-api-notes.md §38.1)."""
    return _declare_group_helper(
        "group_event", name, entities=entities, hide_members=hide_members, **fields
    )


def group_fan(
    *, name: str, entities: list[str], hide_members: bool = False, **fields: Any
) -> EntityRef:
    """Declare a ``group_fan`` helper (M21, docs/ha-api-notes.md §38.1)."""
    return _declare_group_helper(
        "group_fan", name, entities=entities, hide_members=hide_members, **fields
    )


def group_light(
    *,
    name: str,
    entities: list[str],
    hide_members: bool = False,
    all: bool = False,
    **fields: Any,
) -> EntityRef:
    """Declare a ``group_light`` helper (M21, docs/ha-api-notes.md §38.1).

    ``all=True`` mirrors HA's group "all entities must match" toggle (see
    :func:`group_binary_sensor`'s docstring).
    """
    return _declare_group_helper(
        "group_light", name, entities=entities, hide_members=hide_members, all=all, **fields
    )


def group_lock(
    *, name: str, entities: list[str], hide_members: bool = False, **fields: Any
) -> EntityRef:
    """Declare a ``group_lock`` helper (M21, docs/ha-api-notes.md §38.1)."""
    return _declare_group_helper(
        "group_lock", name, entities=entities, hide_members=hide_members, **fields
    )


def group_media_player(
    *, name: str, entities: list[str], hide_members: bool = False, **fields: Any
) -> EntityRef:
    """Declare a ``group_media_player`` helper (M21, docs/ha-api-notes.md §38.1)."""
    return _declare_group_helper(
        "group_media_player", name, entities=entities, hide_members=hide_members, **fields
    )


def group_notify(
    *, name: str, entities: list[str], hide_members: bool = False, **fields: Any
) -> EntityRef:
    """Declare a ``group_notify`` helper (M21, docs/ha-api-notes.md §38.1)."""
    return _declare_group_helper(
        "group_notify", name, entities=entities, hide_members=hide_members, **fields
    )


def group_sensor(
    *,
    name: str,
    entities: list[str],
    type: str,
    hide_members: bool = False,
    **fields: Any,
) -> EntityRef:
    """Declare a ``group_sensor`` helper (M21, docs/ha-api-notes.md §38.1).

    ``type=`` is REQUIRED (no default): the aggregation kind HA's form schema
    requires -- one of ``"min"``/``"max"``/``"mean"``/``"median"``/
    ``"last"``/``"range"``/``"product"``/``"sum"``/``"stdev"``. Omitting it
    is a plain Python ``TypeError`` at the call site (module docstring) --
    there is no decorator form to accommodate here, so the required-keyword
    signature itself is the compile-time check.
    """
    return _declare_group_helper(
        "group_sensor",
        name,
        entities=entities,
        hide_members=hide_members,
        type=type,
        **fields,
    )


def group_switch(
    *,
    name: str,
    entities: list[str],
    hide_members: bool = False,
    all: bool = False,
    **fields: Any,
) -> EntityRef:
    """Declare a ``group_switch`` helper (M21, docs/ha-api-notes.md §38.1).

    ``all=True`` mirrors HA's group "all entities must match" toggle (see
    :func:`group_binary_sensor`'s docstring).
    """
    return _declare_group_helper(
        "group_switch", name, entities=entities, hide_members=hide_members, all=all, **fields
    )


def group_valve(
    *, name: str, entities: list[str], hide_members: bool = False, **fields: Any
) -> EntityRef:
    """Declare a ``group_valve`` helper (M21, docs/ha-api-notes.md §38.1)."""
    return _declare_group_helper(
        "group_valve", name, entities=entities, hide_members=hide_members, **fields
    )
