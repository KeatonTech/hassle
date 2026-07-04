"""``hassle.registry`` — the entity indexing form (DESIGN §5.2/§5.3).

::

    from hassle.registry import entities as e
    when(state(e.sensor.hall_motion).to("on"))       # attribute form
    when(state(e.sensor["hall_motion"]).to("on"))     # index form — identical

A separate module (not re-exported from ``hassle`` itself) because DESIGN §5.3
imports it under its own name (``e``), distinct from the ``hassle.__all__``
verb/builder surface. See ``hassle_core.registry`` for the implementation and
the digit-leading object_id rule (DESIGN §5.2).
"""

from __future__ import annotations

from hassle_core.registry import entities

__all__ = ["entities"]
