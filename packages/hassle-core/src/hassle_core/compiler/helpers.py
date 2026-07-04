"""Helper declarations (DESIGN §5.7) -- the model/builder layer.

``input_boolean(id="guest_mode", name="Guest Mode", ...)`` builds a
:class:`~hassle_core.ir.models.HelperConfig` for one of the nine storage-
collection helper domains (``hassle_core.ir.HELPER_DOMAINS``, F1) and returns
an :class:`EntityRef` usable as an entity id wherever the DSL expects one
(triggers, templates, service calls) -- the "import-and-reference pattern"
(DESIGN §5.7: "referenced by import elsewhere").

**Scope note (contract gap, reported to the orchestrator/human):** this module
builds the ``HelperConfig`` objects correctly (:func:`declared_helpers` returns
everything declared so far in the process), but nothing here wires them into
``CompileResult.objects`` -- ``compile_bundle``/``compile_registered`` (in the
off-limits ``bundle.py``) only drain ``registry.Registry`` (automations and
scripts, "run a function, record trigger/condition/action calls into it").
A helper is not function-shaped: it is a plain declarative object, so it does
not fit that model, and there is no seam today to add a second object stream
into the same ``CompileResult`` without editing ``bundle.py``'s compile loop
(and, to register a non-function object at all, ``registry.py``). See
``raw.py``'s module docstring and the final report for the exact minimal
change needed. Until that lands, a bundle that calls ``input_boolean(...)`` at
module scope will have the helper *object* built correctly by this module, but
it will NOT appear in ``compile_bundle(...).objects`` -- only in
:func:`declared_helpers` (useful for this module's own unit tests, and for
whatever wires the gap shut later).
"""

from __future__ import annotations

from typing import Any

from hassle_core.ir import HELPER_DOMAINS
from hassle_core.ir.models import HelperConfig

# All HelperConfig instances built by this module's constructor functions, in
# declaration order, for the lifetime of the process (or since the last
# `reset_declared_helpers()`). This is the seam a future pipeline change would
# drain, exactly as `registry.Registry` is drained by `compile_registered`.
_DECLARED: list[HelperConfig] = []


class EntityRef(str):
    """An entity id, usable directly as a string (``"input_boolean.guest_mode"``)
    or introspected for its domain/object_id.

    Returned by every helper constructor function so a declared helper can be
    imported and used as an entity reference elsewhere in the bundle (DESIGN
    §5.7's "referenced by import elsewhere"), e.g. ``when(state(guest_mode).to("on"))``.
    """

    domain: str
    object_id: str

    def __new__(cls, domain: str, object_id: str) -> EntityRef:
        obj = str.__new__(cls, f"{domain}.{object_id}")
        obj.domain = domain
        obj.object_id = object_id
        return obj


def reset_declared_helpers() -> None:
    """Clear the process-wide declared-helpers list (tests / repeated compiles)."""
    _DECLARED.clear()


def declared_helpers() -> list[HelperConfig]:
    """Every helper declared so far (in declaration order)."""
    return list(_DECLARED)


def _declare_helper(domain: str, id: str, **fields: Any) -> EntityRef:
    if domain not in HELPER_DOMAINS:
        raise ValueError(
            f"unknown helper domain {domain!r} (expected one of {sorted(HELPER_DOMAINS)})"
        )
    # Omit unset optional kwargs (None) so they don't appear in to_ha() --
    # HelperConfig.to_ha() uses exclude_unset=True, which only excludes fields
    # never passed to model_validate at all, not fields explicitly set to None.
    body: dict[str, Any] = {"id": id, **{k: v for k, v in fields.items() if v is not None}}
    helper = HelperConfig.model_validate(body)
    helper.attach_domain(domain)
    _DECLARED.append(helper)
    return EntityRef(domain, id)


def input_boolean(
    *, id: str, name: str | None = None, icon: str | None = None, **fields: Any
) -> EntityRef:
    """Declare an ``input_boolean`` helper (DESIGN §5.7)."""
    return _declare_helper("input_boolean", id, name=name, icon=icon, **fields)


def input_number(
    *,
    id: str,
    name: str | None = None,
    icon: str | None = None,
    min: float | None = None,
    max: float | None = None,
    step: float | None = None,
    unit_of_measurement: str | None = None,
    mode: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare an ``input_number`` helper (DESIGN §5.7)."""
    return _declare_helper(
        "input_number",
        id,
        name=name,
        icon=icon,
        min=min,
        max=max,
        step=step,
        unit_of_measurement=unit_of_measurement,
        mode=mode,
        **fields,
    )


def input_select(
    *,
    id: str,
    name: str | None = None,
    icon: str | None = None,
    options: list[str] | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare an ``input_select`` helper (DESIGN §5.7)."""
    return _declare_helper("input_select", id, name=name, icon=icon, options=options, **fields)


def input_text(
    *,
    id: str,
    name: str | None = None,
    icon: str | None = None,
    min: int | None = None,
    max: int | None = None,
    pattern: str | None = None,
    mode: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare an ``input_text`` helper (DESIGN §5.7)."""
    return _declare_helper(
        "input_text",
        id,
        name=name,
        icon=icon,
        min=min,
        max=max,
        pattern=pattern,
        mode=mode,
        **fields,
    )


def input_datetime(
    *,
    id: str,
    name: str | None = None,
    icon: str | None = None,
    has_date: bool | None = None,
    has_time: bool | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare an ``input_datetime`` helper (DESIGN §5.7)."""
    return _declare_helper(
        "input_datetime", id, name=name, icon=icon, has_date=has_date, has_time=has_time, **fields
    )


def input_button(
    *, id: str, name: str | None = None, icon: str | None = None, **fields: Any
) -> EntityRef:
    """Declare an ``input_button`` helper (DESIGN §5.7)."""
    return _declare_helper("input_button", id, name=name, icon=icon, **fields)


def counter(
    *,
    id: str,
    name: str | None = None,
    icon: str | None = None,
    initial: int | None = None,
    step: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``counter`` helper (DESIGN §5.7)."""
    return _declare_helper(
        "counter",
        id,
        name=name,
        icon=icon,
        initial=initial,
        step=step,
        minimum=minimum,
        maximum=maximum,
        **fields,
    )


def timer(
    *,
    id: str,
    name: str | None = None,
    icon: str | None = None,
    duration: str | None = None,
    restore: bool | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``timer`` helper (DESIGN §5.7)."""
    return _declare_helper(
        "timer", id, name=name, icon=icon, duration=duration, restore=restore, **fields
    )


def schedule(
    *,
    id: str,
    name: str | None = None,
    icon: str | None = None,
    **fields: Any,
) -> EntityRef:
    """Declare a ``schedule`` helper (DESIGN §5.7)."""
    return _declare_helper("schedule", id, name=name, icon=icon, **fields)
