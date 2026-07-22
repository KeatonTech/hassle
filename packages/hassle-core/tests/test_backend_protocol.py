"""The frozen `Backend` Protocol shape (docs/internals/backend-protocol.md) — DESIGN §8, §4.

`Backend` is structural (typing.Protocol): both `FakeBackend` and
`DirectBackend` implement it independently. This test file only pins the
Protocol's shape (it is satisfied by a minimal hand-written stub) — `FakeBackend`
behavior itself is covered in test_fake_backend.py.
"""

from __future__ import annotations

from typing import Any

from hassle.backend import Backend


class _MinimalBackend:
    """A hand-written minimal stub — if this satisfies `Backend` structurally,
    the Protocol's shape is exactly as narrow as documented."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, dict[str, Any]]] = {}

    def list_remote(self, kind: str) -> dict[str, dict[str, Any]]:
        return dict(self._store.get(kind, {}))

    def create(self, kind: str, config: dict[str, Any]) -> str:
        identity = str(config.get("id") or config.get("name") or "x")
        self._store.setdefault(kind, {})[identity] = dict(config)
        return identity

    def update(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        self._store.setdefault(kind, {})[identity] = dict(config)

    def delete(self, kind: str, identity: str) -> None:
        self._store.setdefault(kind, {}).pop(identity, None)


def test_minimal_stub_satisfies_backend_protocol() -> None:
    backend: Backend = _MinimalBackend()
    identity = backend.create("automation", {"id": "a", "alias": "x"})
    assert identity == "a"
    assert backend.list_remote("automation") == {"a": {"id": "a", "alias": "x"}}
    backend.update("automation", "a", {"id": "a", "alias": "y"})
    assert backend.list_remote("automation")["a"]["alias"] == "y"
    backend.delete("automation", "a")
    assert backend.list_remote("automation") == {}


def test_backend_is_runtime_checkable_protocol() -> None:
    # isinstance() must work against the Protocol (runtime_checkable) so callers
    # can assert "this object looks like a Backend" without importing the ABC.
    assert isinstance(_MinimalBackend(), Backend)


def test_backend_protocol_excludes_trace_and_template_ops() -> None:
    # Backend is scoped to what sync needs (list/create/update/delete); trace,
    # template render, and media operations are DirectBackend-only concerns
    # and must not appear on the Protocol.
    import inspect

    members = {name for name, _ in inspect.getmembers(Backend) if not name.startswith("_")}
    for forbidden in ("trace", "render_template", "media", "validate_config"):
        message = f"unexpected Backend member matching {forbidden!r}"
        assert not any(forbidden in m for m in members), message
