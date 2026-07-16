"""The frozen `Backend` Protocol — DESIGN §8, §4.

`Backend` is the seam between the sync engine (plan/apply, pure logic) and
whatever actually talks to Home Assistant. It is a structural `typing.Protocol`
so that `FakeBackend` (in-memory) and `DirectBackend` (real REST + WebSocket
transport) can each be built and tested independently against the same
contract — neither needs to inherit from anything.

Scope (deliberately minimal — see docs/backend.md for the full rationale):

- `list_remote(kind)` — every object of a given kind, already in HA's stored
  plural/normalized form (or the backend normalizes internally, since
  `DirectBackend` just proxies real HA, which normalizes on its own).
- `create` / `update` / `delete` — the three mutations the sync engine's apply
  step needs, keyed by the object's *identity* (the part of the object key
  after ``"<kind>:"`` — e.g. an automation's ``id``, a script's object_id, a
  helper's ``id``). Helper domains' `{domain}_id` payload-key convention
  (docs/ha-api-notes.md §4) is a `DirectBackend`/`FakeBackend` *internal*
  implementation detail — it does not leak into this Protocol's signatures.

Deliberately NOT here (`DirectBackend`-only concerns, unrelated to sync):
registry snapshot fetch (plan/apply doesn't need registry data — see DESIGN
§8.2/§8.3, neither table references the registry), trace access, template
rendering, media mirror operations, server-side `validate_config`.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Backend(Protocol):
    """What the sync engine needs from a Home Assistant transport."""

    def list_remote(self, kind: str) -> dict[str, dict[str, Any]]:
        """Return every object of ``kind`` currently stored in HA.

        Keyed by identity (not the full object key), value is the config body
        already in HA's normalized/plural storage form.
        """
        ...

    def create(self, kind: str, config: dict[str, Any]) -> str:
        """Create a new object of ``kind``; return its identity."""
        ...

    def update(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        """Overwrite the object ``kind:identity`` with ``config``."""
        ...

    def delete(self, kind: str, identity: str) -> None:
        """Delete the object ``kind:identity``."""
        ...
