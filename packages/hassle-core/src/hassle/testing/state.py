"""The simulator's state machine: entity states + change notification (DESIGN §10.1)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


def _empty_str_any_dict() -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class EntityState:
    entity_id: str
    state: str
    attributes: dict[str, Any] = field(default_factory=_empty_str_any_dict)


@dataclass(frozen=True)
class StateChange:
    entity_id: str
    old: EntityState | None
    new: EntityState


class StateStore:
    """Holds current entity states; notifies listeners of every ``set`` transition."""

    def __init__(self) -> None:
        self._states: dict[str, EntityState] = {}
        self._listeners: list[Callable[[StateChange], None]] = []

    def get(self, entity_id: str) -> EntityState | None:
        return self._states.get(entity_id)

    def seed(self, entity_id: str, state: str, attributes: dict[str, Any] | None = None) -> None:
        """Set a state with **no** change notification (no triggers fire).

        Used to establish a "prior" state before an observed transition (e.g.
        ``sim.state_change``'s ``from_state``) without that seeding step
        itself being mistaken for a real transition.
        """
        self._states[entity_id] = EntityState(entity_id, state, dict(attributes or {}))

    def set(
        self, entity_id: str, state: str, attributes: dict[str, Any] | None = None
    ) -> StateChange | None:
        """Set ``entity_id`` to ``state`` and notify listeners of the transition.

        The **first** observation of an entity (no prior state at all) is
        treated as baseline seeding, not a live transition -- it never
        notifies listeners (matching HA: an entity's initial state at startup
        does not itself fire triggers). Every subsequent ``set`` notifies,
        even when the new state string equals the old one (attributes may
        have changed).

        Returns the :class:`StateChange` that was (or would have been)
        published, or ``None`` for a silent first-observation seed.
        """
        old = self._states.get(entity_id)
        new = EntityState(entity_id, state, dict(attributes or {}))
        self._states[entity_id] = new
        if old is None:
            return None
        change = StateChange(entity_id, old, new)
        for listener in list(self._listeners):
            listener(change)
        return change

    def on_change(self, listener: Callable[[StateChange], None]) -> None:
        self._listeners.append(listener)
