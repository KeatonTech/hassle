"""``hassle.registry`` — the entity indexing form (DESIGN §5.2/§5.3).

::

    from hassle.registry import entities as e
    when(state(e.sensor.hall_motion).to("on"))       # attribute form
    when(state(e.sensor["hall_motion"]).to("on"))     # index form — identical

A separate module (not re-exported from ``hassle`` itself) because DESIGN §5.3
imports it under its own name (``e``), distinct from the ``hassle.__all__``
verb/builder surface.

``entities.<domain>`` gives ``e.<domain>`` a domain accessor exposing every
object_id both as an attribute (``e.sensor.hall_motion``) and by indexing
(``e.sensor["hall_motion"]``), always resolving to the same entity reference
(an :class:`~hassle.compiler.helpers.EntityRef`, the same ``str``-subclass type
helper declarations already return — accepted anywhere the DSL expects an
entity id).

This module is the M1 *runtime* shape only. M3 layers typed ``.pyi`` stub classes
(generated from the registry snapshot) on top of the same attribute/index surface
so pyright can catch a typo (``e.light.halway``) before any tool runs; nothing
here depends on a registry snapshot — it works for any domain/object_id name,
the "universal escape hatch" DESIGN §5.2 describes.

**Digit-leading object_id rule (DESIGN §5.2):** a real HA object_id matches
``(?!_)[\\da-z_]+(?<!_)`` — it may start with a digit but never with (or end
with) an underscore. Python identifiers can't start with a digit, so the stub/
accessor convention is to prefix a digit-leading object_id with one underscore
(``e.sensor._3d_printer``). The attribute accessor therefore strips **one**
leading underscore *only when the next character is a digit*; any other
attribute name (including one that merely starts with ``_``, which cannot be a
real object_id) passes through unchanged. Indexing (``e.sensor["3d_printer"]``)
never needs this rule — the given string is used verbatim — and both forms
resolve to the identical :class:`~hassle.compiler.helpers.EntityRef`.
"""

from __future__ import annotations

from hassle.compiler.helpers import EntityRef

__all__ = ["entities"]


def _strip_digit_leading_underscore(object_id: str) -> str:
    if len(object_id) >= 2 and object_id[0] == "_" and object_id[1].isdigit():
        return object_id[1:]
    return object_id


class _DomainAccessor:
    """``entities.<domain>`` — attribute *and* index access to one HA domain.

    Both forms build the same :class:`EntityRef` for a given object_id; neither
    form validates the object_id against a live registry (that is M3's job).
    """

    def __init__(self, domain: str) -> None:
        # Leading-underscore attribute access on the instance itself must not
        # collide with this accessor's own dunder/private attributes; using
        # object.__setattr__ once here is unnecessary since we don't set
        # per-object_id attributes at all -- __getattr__ handles every lookup.
        self._domain = domain

    def __getattr__(self, name: str) -> EntityRef:
        if name.startswith("__") and name.endswith("__"):  # pragma: no cover - dunder probes
            raise AttributeError(name)
        object_id = _strip_digit_leading_underscore(name)
        return EntityRef(self._domain, object_id)

    def __getitem__(self, object_id: str) -> EntityRef:
        return EntityRef(self._domain, object_id)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"_DomainAccessor({self._domain!r})"


class _EntitiesRegistry:
    """``entities`` — ``entities.<domain>`` returns a :class:`_DomainAccessor`.

    Domains are open-ended in M1 (no registry snapshot backs this); any
    attribute name is accepted as a domain. M3's generated stubs give this the
    same shape but with real, typed domain/entity classes.
    """

    def __getattr__(self, domain: str) -> _DomainAccessor:
        if domain.startswith("__") and domain.endswith("__"):  # pragma: no cover
            raise AttributeError(domain)
        return _DomainAccessor(domain)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "entities"


entities = _EntitiesRegistry()
