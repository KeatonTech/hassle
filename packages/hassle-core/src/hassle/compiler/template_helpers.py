"""Template-helper declarations (M10, DESIGN §5.7 extended + §13's config-entry
plugin) -- the model/builder layer for the ``template`` config-entry domain.

``template_number(name="Active HVAC Zones", state="{{ ... }}", set_value=...,
min=0, max=8, step=1)`` builds a
:class:`~hassle.ir.models.TemplateHelperConfig` for one of the four template
domains (``hassle.ir.TEMPLATE_DOMAINS``, F1-additive) and returns an
:class:`~hassle.compiler.helpers.EntityRef`, exactly like the nine storage-
collection helper builders in :mod:`hassle.compiler.helpers` -- same
"import-and-reference pattern" (DESIGN §5.7), same prebuilt-object
registration path into the active bundle registry.

**Identity (redesigned 2026-07-05, docs/ha-api-notes.md §26.6): there is no
``id=``/``unique_id=`` kwarg.** CI found the real `template` config flow's
form schema rejects an unrecognized ``unique_id`` key outright -- a
flow-created entry has no caller-settable unique id at all. Identity is
derived from ``name`` (required), mirroring the nine storage helpers'
"id is a slug of name" rule (``hassle.ir.keys.slugify``) -- except here it's
the ONLY identity source; the object key is
``"<template domain>:<slugify(name)>"``. The HA-assigned config ``entry_id``
remains transport-side identity only (manifest-only, docs/backend.md).

Storage truth: ``state=`` takes a literal Jinja template string (the config
entry's actual stored ``state`` option). Expression-builder values (an `Expr`
built via the M1.1 template surface) are also accepted -- rendered to Jinja
at declaration time via ``str()`` -- since template strings are what HA's
config entry stores and what the decompiler reproduces (DESIGN M1.1: "the
expression sugar is one-way").

**Required write-target fields (CI finding, docs/ha-api-notes.md §26.6):** a
template NUMBER's form schema requires ``set_value`` (the action sequence run
when the entity is set from the UI/a service call -- a template number needs
a write target, since ``state`` alone only computes the displayed value); a
template SELECT likewise requires ``select_option`` (the sequence run when an
option is chosen) alongside ``options`` (the Jinja-or-list of choices).
Sensor/binary_sensor need only ``state`` (they are read-only, no write
target). ``set_value``/``select_option`` accept a single action dict or a
list of action dicts (HA's own action-sequence shape); stored verbatim
(I3 -- Hassle's DSL action builders are automation/script-scoped, not
reusable here without a recording context, so these are raw HA action dicts,
matching the ``raw_action`` escape hatch's shape).
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.helpers import EntityRef
from hassle.compiler.spans import capture_span
from hassle.ir import TEMPLATE_DOMAINS
from hassle.ir.keys import slugify
from hassle.ir.models import TemplateHelperConfig

# All TemplateHelperConfig instances built by this module's constructor
# functions, in declaration order, for the lifetime of the process (or since
# the last `reset_declared_template_helpers()`) -- mirrors
# `hassle.compiler.helpers._DECLARED`'s seam for this module's own unit tests.
_DECLARED: list[TemplateHelperConfig] = []


def reset_declared_template_helpers() -> None:
    """Clear the process-wide declared-template-helpers list (tests / repeated compiles)."""
    _DECLARED.clear()


def declared_template_helpers() -> list[TemplateHelperConfig]:
    """Every template helper declared so far (in declaration order)."""
    return list(_DECLARED)


def _render_state(state: Any) -> Any:
    """Accept either a literal Jinja string or an M1.1 expression-builder
    value (an `Expr`, which renders via `str()`) -- template strings are the
    storage truth either way (module docstring)."""
    if state is None or isinstance(state, str):
        return state
    return str(state)


def _declare_template_helper(domain: str, name: str, **fields: Any) -> EntityRef:
    if domain not in TEMPLATE_DOMAINS:
        raise ValueError(
            f"unknown template helper domain {domain!r} "
            f"(expected one of {sorted(TEMPLATE_DOMAINS)})"
        )
    identity = slugify(name)
    body: dict[str, Any] = {
        "name": name,
        **{k: v for k, v in fields.items() if v is not None},
    }
    helper = TemplateHelperConfig.model_validate(body)
    helper.attach_domain(domain)
    _DECLARED.append(helper)
    # Same §12 registration path helpers.py uses: register into the active
    # bundle registry so the compiler lands this in CompileResult.objects.
    from hassle.compiler.registry import current_registry

    current_registry().add_object(helper, capture_span(depth=1))
    return EntityRef(domain, identity)


def template_number(
    *,
    name: str,
    state: Any = None,
    set_value: Any = None,
    min: float | None = None,
    max: float | None = None,
    step: float | None = None,
    unit_of_measurement: str | None = None,
    icon: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``template_number`` helper (M10, DESIGN §5.7): the owner's
    driving case, e.g. ``number.active_hvac_zones``.

    ``set_value`` is REQUIRED by HA's form schema (module docstring): the
    action (a raw HA action dict, or a list of them) run when the number is
    set -- e.g. ``{"action": "input_number.set_value", "target": {...},
    "data": {"value": "{{ value }}"}}``, where ``{{ value }}`` is HA's
    template variable for the submitted value.
    """
    return _declare_template_helper(
        "template_number",
        name,
        state=_render_state(state),
        set_value=set_value,
        min=min,
        max=max,
        step=step,
        unit_of_measurement=unit_of_measurement,
        icon=icon,
        **fields,
    )


def template_sensor(
    *,
    name: str,
    state: Any = None,
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    icon: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``template_sensor`` helper (M10, DESIGN §5.7). Read-only
    (no write-target field -- ``state`` alone is HA's required schema)."""
    return _declare_template_helper(
        "template_sensor",
        name,
        state=_render_state(state),
        unit_of_measurement=unit_of_measurement,
        device_class=device_class,
        icon=icon,
        **fields,
    )


def template_binary_sensor(
    *,
    name: str,
    state: Any = None,
    device_class: str | None = None,
    icon: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``template_binary_sensor`` helper (M10, DESIGN §5.7).
    Read-only, like ``template_sensor``."""
    return _declare_template_helper(
        "template_binary_sensor",
        name,
        state=_render_state(state),
        device_class=device_class,
        icon=icon,
        **fields,
    )


def template_select(
    *,
    name: str,
    state: Any = None,
    options: Any = None,
    select_option: Any = None,
    icon: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``template_select`` helper (M10, DESIGN §5.7).

    ``options`` is a Jinja template string rendering to a list (HA's own
    ``template_select`` options field shape) -- a plain Python list literal is
    also accepted for convenience and passed straight through unmodified
    (extra="allow" preserves it verbatim like any other IR field, I3).
    ``select_option`` is REQUIRED by HA's form schema (module docstring): the
    action (or list of actions) run when an option is chosen, analogous to
    ``template_number``'s ``set_value``.
    """
    return _declare_template_helper(
        "template_select",
        name,
        state=_render_state(state),
        options=options,
        select_option=select_option,
        icon=icon,
        **fields,
    )
