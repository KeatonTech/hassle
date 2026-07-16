"""``hassle.services`` — typed domain-namespaced service calls (DESIGN §5.2/§5.3).

::

    from hassle.services import cover
    cover.close_cover(target=e.cover.x, position=60)

A **non-star module** (NOT part of ``from hassle import *`` -- see
docs/dsl-extensions.md): domains are instance-dynamic
(this instance's registry snapshot decides what exists), the same reason
``hassle.registry.entities`` gets its own import rather than joining
``hassle.__all__``.

Two-level PEP 562 module ``__getattr__``: this module's own ``__getattr__``
accepts ANY domain name and returns a :class:`_ServiceDomain` namespace
object; that object's ``__getattr__`` accepts ANY service name and returns a
callable that records the identical action a
``service("<domain>.<service_name>", ...)`` call would. Offline compile never
fails on an unknown domain/service -- catching a typo is validate's job
(``hassle.registry.validate``'s ``unknown-service`` Finding, wired through the
existing did-you-mean machinery), not the compiler's.

Delegates to :func:`hassle.compiler.actions.service` (never re-implements the
action-building/recording logic) so IR shape and span capture are
byte-identical to the ``service(...)`` and entity-method forms by
construction -- ``capture_span`` walks outward past every ``hassle.*`` frame
regardless of how many intermediate calls happened inside this module.
"""

from __future__ import annotations

from typing import Any

__all__: list[str] = []  # nothing here is star-exported; attributes are dynamic


class _ServiceDomain:
    """``hassle.services.<domain>`` -- ``<domain>.<service_name>(...)`` records
    a service-call action, exactly like ``service("<domain>.<service_name>",
    ...)``. Accepts any service name at compile time (an unknown one is a
    validate-time Finding, never a compile-time failure)."""

    def __init__(self, domain: str) -> None:
        self._domain = domain

    def __getattr__(self, service_name: str) -> Any:
        if service_name.startswith("__") and service_name.endswith("__"):  # pragma: no cover
            raise AttributeError(service_name)

        domain = self._domain

        def _call(**fields: Any) -> None:
            from hassle.compiler.actions import service

            service(f"{domain}.{service_name}", **fields)

        return _call

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"_ServiceDomain({self._domain!r})"


def __getattr__(domain: str) -> _ServiceDomain:
    """PEP 562 module-level dynamic attribute: ``from hassle.services import
    <any domain>`` always resolves (offline compile never fails on an unknown
    domain -- see module docstring)."""
    if domain.startswith("__") and domain.endswith("__"):  # pragma: no cover
        raise AttributeError(domain)
    return _ServiceDomain(domain)
