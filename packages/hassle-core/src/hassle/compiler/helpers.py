"""Helper declarations (DESIGN §5.7) -- the model/builder layer.

``input_boolean(id="guest_mode", name="Guest Mode", ...)`` builds a
:class:`~hassle.ir.models.HelperConfig` for one of the nine storage-
collection helper domains (``hassle.ir.HELPER_DOMAINS``, part of the frozen
IR schema) and returns
an :class:`EntityRef` usable as an entity id wherever the DSL expects one
(triggers, templates, service calls) -- the "import-and-reference pattern"
(DESIGN §5.7: "referenced by import elsewhere").

**Registration (§12 fix):** each constructor registers the
built :class:`HelperConfig` into the active bundle registry via
``Registry.add_object`` (registry.py), so ``compile_bundle`` lands it in
``CompileResult.objects`` under ``"<domain>:<id>"`` (bundle.py drains the
prebuilt stream alongside the function-shaped automations/scripts). The
process-wide :func:`declared_helpers` list is retained for this module's own
unit tests and is reset per compile by ``fresh()``.
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.spans import capture_span
from hassle.ir import HELPER_DOMAINS
from hassle.ir.models import HelperConfig

# All HelperConfig instances built by this module's constructor functions, in
# declaration order, for the lifetime of the process (or since the last
# `reset_declared_helpers()`). This is the seam a future pipeline change would
# drain, exactly as `registry.Registry` is drained by `compile_registered`.
_DECLARED: list[HelperConfig] = []


class _EntityServiceMethod:
    """The object ``e.<domain>.<object_id>.<service_name>`` evaluates to
    (entity-method sugar): callable, records the identical action a
    ``service("<domain>.<service_name>", target=..., **fields)`` call
    would, with ``target={"entity_id": "<domain>.<object_id>"}`` implicit.

    Only a CALL records anything ("bare attribute access stays an attribute
    ref ... only CALLS record actions") -- merely
    evaluating ``e.cover.x.close_cover`` (no parens) builds this object but
    calls no recording function at all, so it is inert until called, exactly
    like any other unbound method reference.

    Delegates to :func:`hassle.compiler.actions.service` (imported lazily to
    avoid a helpers<->actions import cycle: ``actions.py`` imports
    ``record_action`` from ``recording.py``, which does not import this
    module, but going through the actual verb -- rather than re-implementing
    it -- is what GUARANTEES byte-identical IR and span capture: ``capture_span``
    walks outward past every ``hassle.*`` frame regardless of nesting depth, so
    calling the real ``service()`` from here still lands the span on the
    user's own call site.
    """

    def __init__(self, entity_id: str, service_name: str) -> None:
        self._entity_id = entity_id
        self._service_name = service_name

    def __call__(self, **fields: Any) -> None:
        from hassle.compiler.actions import service

        domain = self._entity_id.partition(".")[0]
        service(f"{domain}.{self._service_name}", target={"entity_id": self._entity_id}, **fields)


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

    def attr(self, attribute: str) -> Any:
        """``entity.attr("name")`` -> ``state_attr('domain.object_id', 'name')``
        (DESIGN §5.4).

        An Expr leaf (a :class:`~hassle.compiler.templates.TemplateExpr`):
        composes with every operator like any other template leaf. Bare (no
        implicit ``| float``) since HA attribute values are heterogeneous --
        the same convention as this method's pinned golden
        (``fixtures/dsl/shade_tracks_sun``), which multiplies the result
        directly. Imported lazily to avoid a helpers<->templates import cycle
        (``templates.py`` imports from ``builders.py``, which this module does
        not touch).
        """
        from hassle.compiler.templates import TemplateExpr

        return TemplateExpr(f"state_attr({str(self)!r}, {attribute!r})")

    @property
    def state(self) -> Any:
        """``entity.state`` (entity-first conditions) -- a
        comparison accessor building NATIVE HA conditions (structured
        ``state``/``numeric_state``, never a template string): ``==``/``!=``
        for state equality, ``>``/``<`` for ``numeric_state`` above/below,
        ``.in_([...])`` for state-list membership. See
        :class:`~hassle.compiler.builders._StateAccessor` for the full
        operator table and the ``in``-operator trap it guards against.

        A DEFINED property, not resolved through ``__getattr__`` -- Python's
        attribute lookup finds a data descriptor (a ``property``) on the
        class before ever falling back to ``__getattr__`` (the entity-method
        sugar below), so this can never be shadowed by, or shadow,
        ``e.<domain>.<id>.state(...)`` as a service call -- and in fact no
        HA domain has a service literally named ``state``, so the
        ambiguity is moot in practice too.

        Distinct from ``state_of(entity)``: that is the Jinja
        TEMPLATE-STRING read (``states('x')``, for use inside a
        ``@template_sensor``/expression composition); this is the
        NATIVE-CONDITION read (a real ``state``/``numeric_state`` condition
        dict, for use in ``only_if(...)``/``if_then(...)``/etc.). The two
        never produce the same IR shape and are not interchangeable.

        Imported lazily (same helpers<->builders avoidance convention as
        ``.attr()``'s lazy ``templates`` import above).
        """
        from hassle.compiler.builders import (
            _StateAccessor,  # pyright: ignore[reportPrivateUsage]
        )

        return _StateAccessor(str(self))

    def __getattr__(self, name: str) -> _EntityServiceMethod:
        """Entity-method sugar (DESIGN §5.2/§5.3):
        ``e.cover.x.close_cover`` (any name not already a real attribute of
        ``EntityRef``/``str``, i.e. anything reaching ``__getattr__`` at all)
        returns a callable that records ``close_cover`` as a service call on
        this entity when actually invoked. ``__getattr__`` only fires on
        lookup MISS -- ``.attr(...)``, ``.domain``, ``.object_id``, and every
        ordinary ``str`` method are found by normal attribute lookup first and
        never reach here, so this can never shadow existing EntityRef/str
        behavior.
        """
        if name.startswith("__") and name.endswith("__"):  # pragma: no cover - dunder probes
            raise AttributeError(name)
        return _EntityServiceMethod(str(self), name)


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
    # §12 registration path: also register into the active bundle registry so the
    # compiler lands this helper in CompileResult.objects (bundle.py drains it).
    # Imported lazily to avoid a registry<->helpers import cycle at module load.
    from hassle.compiler.registry import current_registry

    current_registry().add_object(helper, capture_span(depth=1))
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
