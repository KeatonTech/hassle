"""Template-helper declarations (M10, DESIGN §5.7 extended + §13's config-entry
plugin) -- the model/builder layer for the ``template`` config-entry domain.

``template_number(id="active_hvac_zones", name="Active HVAC Zones",
state="{{ ... }}", min=0, max=8, step=1)`` builds a
:class:`~hassle.ir.models.TemplateHelperConfig` for one of the four template
domains (``hassle.ir.TEMPLATE_DOMAINS``, F1-additive) and returns an
:class:`~hassle.compiler.helpers.EntityRef`, exactly like the nine storage-
collection helper builders in :mod:`hassle.compiler.helpers` -- same
"import-and-reference pattern" (DESIGN §5.7), same prebuilt-object
registration path into the active bundle registry.

**Identity, frozen this PR:** the DSL's ``id=`` kwarg becomes the config
entry's ``unique_id`` (the declared identity used in the object key,
``"template_number:<id>"``) -- NOT the HA-assigned config-entry ``entry_id``,
which is transport/HA-side identity only and never appears in the DSL body
(docs/backend.md's config-entry addendum, docs/ha-api-notes.md §26). This
mirrors I2's spirit for a config-entry world: Hassle never re-derives or
changes an object's ``unique_id`` once declared, and the entry_id (stored only
in the manifest) is what lets an UPDATE become an options-flow update instead
of a destructive recreate.

Storage truth: ``state=`` takes a literal Jinja template string (the config
entry's actual stored ``state`` option). Expression-builder values (an `Expr`
built via the M1.1 template surface) are also accepted -- rendered to Jinja
at declaration time via ``str()`` -- since template strings are what HA's
config entry stores and what the decompiler reproduces (DESIGN M1.1: "the
expression sugar is one-way").
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.helpers import EntityRef
from hassle.compiler.spans import capture_span
from hassle.ir import TEMPLATE_DOMAINS
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


def _declare_template_helper(domain: str, id: str, **fields: Any) -> EntityRef:
    if domain not in TEMPLATE_DOMAINS:
        raise ValueError(
            f"unknown template helper domain {domain!r} "
            f"(expected one of {sorted(TEMPLATE_DOMAINS)})"
        )
    body: dict[str, Any] = {
        "unique_id": id,
        **{k: v for k, v in fields.items() if v is not None},
    }
    helper = TemplateHelperConfig.model_validate(body)
    helper.attach_domain(domain)
    _DECLARED.append(helper)
    # Same §12 registration path helpers.py uses: register into the active
    # bundle registry so the compiler lands this in CompileResult.objects.
    from hassle.compiler.registry import current_registry

    current_registry().add_object(helper, capture_span(depth=1))
    return EntityRef(domain, id)


def template_number(
    *,
    id: str,
    name: str | None = None,
    state: Any = None,
    min: float | None = None,
    max: float | None = None,
    step: float | None = None,
    unit_of_measurement: str | None = None,
    icon: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``template_number`` helper (M10, DESIGN §5.7): the owner's
    driving case, e.g. ``number.active_hvac_zones``."""
    return _declare_template_helper(
        "template_number",
        id,
        name=name,
        state=_render_state(state),
        min=min,
        max=max,
        step=step,
        unit_of_measurement=unit_of_measurement,
        icon=icon,
        **fields,
    )


def template_sensor(
    *,
    id: str,
    name: str | None = None,
    state: Any = None,
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    icon: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``template_sensor`` helper (M10, DESIGN §5.7)."""
    return _declare_template_helper(
        "template_sensor",
        id,
        name=name,
        state=_render_state(state),
        unit_of_measurement=unit_of_measurement,
        device_class=device_class,
        icon=icon,
        **fields,
    )


def template_binary_sensor(
    *,
    id: str,
    name: str | None = None,
    state: Any = None,
    device_class: str | None = None,
    icon: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``template_binary_sensor`` helper (M10, DESIGN §5.7)."""
    return _declare_template_helper(
        "template_binary_sensor",
        id,
        name=name,
        state=_render_state(state),
        device_class=device_class,
        icon=icon,
        **fields,
    )


def template_select(
    *,
    id: str,
    name: str | None = None,
    state: Any = None,
    options: Any = None,
    icon: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``template_select`` helper (M10, DESIGN §5.7).

    ``options`` is a Jinja template string rendering to a list (HA's own
    ``template_select`` options field shape) -- a plain Python list literal is
    also accepted for convenience and passed straight through unmodified
    (extra="allow" preserves it verbatim like any other IR field, I3)."""
    return _declare_template_helper(
        "template_select",
        id,
        name=name,
        state=_render_state(state),
        options=options,
        icon=icon,
        **fields,
    )
