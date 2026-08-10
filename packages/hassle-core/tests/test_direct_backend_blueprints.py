"""`DirectBackend`'s blueprint dispatch (blueprints-design §2), unit-level
against a fake `_client` exposing async `ws_command` only -- every blueprint
command §2 probed is WebSocket, like the dashboard family and unlike the
config-entry flows.

The wire mapping under test (all four commands probed live 2026-08-10,
ha-api-notes §40):

| Protocol call | Wire |
|---|---|
| `list_remote("blueprint")` | `blueprint/list` once per domain -> metadata only |
| `create` | `blueprint/save {domain, path, yaml, allow_override: False}` |
| `update` | `blueprint/save {..., allow_override: True}` |
| `delete` | `blueprint/delete {domain, path}` |
| `blueprint_substitute` (non-Protocol) | `blueprint/substitute {domain, path, input}` |

`blueprint/source`, `blueprint/get` and `blueprint/get_source` do NOT exist
(`unknown_command`), which is why nothing here ever tries to read a source
back.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from hassle.backend.direct import DirectBackend
from hassle.backend.errors import HaApiError
from hassle.ir import BLUEPRINT_KIND

SOURCE = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    switch_entity:
mode: restart
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions: []
"""

PATH = "local/room-switch-controls.yaml"


class _FakeClient:
    """Models the four probed WS shapes (§2).

    `blueprint/list` is keyed by path and carries `{"metadata": {...}}` per
    entry -- HA's real shape, and metadata ONLY: there is no source in it.
    """

    def __init__(self, stored: dict[str, dict[str, Any]] | None = None) -> None:
        # (domain, path) -> {"yaml": ..., "metadata": {...}}
        self.stored: dict[tuple[str, str], dict[str, Any]] = {}
        for key, value in (stored or {}).items():
            self.stored[("automation", key)] = value
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.substitute_result: Any = {"mode": "restart"}

    async def ws_command(self, type: str, **payload: Any) -> Any:
        self.calls.append((type, payload))
        if type == "blueprint/list":
            domain = payload["domain"]
            return {
                path: {"metadata": entry["metadata"]}
                for (stored_domain, path), entry in self.stored.items()
                if stored_domain == domain
            }
        if type == "blueprint/save":
            key = (payload["domain"], payload["path"])
            if key in self.stored and not payload.get("allow_override"):
                raise HaApiError("Blueprint already exists", code="unknown_error")
            self.stored[key] = {
                "yaml": payload["yaml"],
                "metadata": {"name": "Room Switch Controls"},
            }
            return {}
        if type == "blueprint/delete":
            key = (payload["domain"], payload["path"])
            if key not in self.stored:
                raise HaApiError(
                    f"No such file or directory: {payload['path']}", code="unknown_error"
                )
            del self.stored[key]
            return {}
        if type == "blueprint/substitute":
            return self.substitute_result
        raise AssertionError(f"unexpected ws command {type!r}")


def _backend(client: _FakeClient) -> DirectBackend:
    """A `DirectBackend` wired to ``client``, with a real running loop thread.

    `_run` bridges to the loop via `run_coroutine_threadsafe`, so the loop has
    to actually be running — exercising the SYNC Protocol methods (which is
    where the kind dispatch lives) rather than only the `_a*` coroutines.
    """
    backend = DirectBackend.__new__(DirectBackend)
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    backend._loop = loop  # type: ignore[attr-defined]
    backend._client = client  # type: ignore[attr-defined]
    return backend


@pytest.fixture
def client() -> _FakeClient:
    return _FakeClient(
        {PATH: {"yaml": SOURCE, "metadata": {"name": "Room Switch Controls", "input": {}}}}
    )


# --- blueprint/list --------------------------------------------------------


def test_list_remote_queries_every_blueprint_domain(client: _FakeClient) -> None:
    _backend(client).list_remote(BLUEPRINT_KIND)
    domains = [payload["domain"] for name, payload in client.calls if name == "blueprint/list"]
    assert domains == ["automation", "script"]


def test_list_remote_keys_by_domain_slash_path(client: _FakeClient) -> None:
    listed = _backend(client).list_remote(BLUEPRINT_KIND)
    assert set(listed) == {f"automation/{PATH}"}


def test_list_remote_carries_metadata_and_never_a_source(client: _FakeClient) -> None:
    """§2.1: HA cannot serve a blueprint's source back, so a remote body has
    no `source` key by construction -- that is what makes this kind
    push-authoritative."""
    body = _backend(client).list_remote(BLUEPRINT_KIND)[f"automation/{PATH}"]
    assert body == {
        "domain": "automation",
        "path": PATH,
        "metadata": {"name": "Room Switch Controls", "input": {}},
    }
    assert "source" not in body


def test_list_remote_never_issues_a_source_read(client: _FakeClient) -> None:
    """`blueprint/source`/`blueprint/get`/`blueprint/get_source` are all
    `unknown_command` (§2). Sending one against real HA would be a hard
    error, so nothing may ever try."""
    _backend(client).list_remote(BLUEPRINT_KIND)
    assert {name for name, _ in client.calls} == {"blueprint/list"}


# --- blueprint/save --------------------------------------------------------


def test_create_saves_the_yaml_without_override(client: _FakeClient) -> None:
    backend = _backend(_FakeClient())
    identity = backend.create(
        BLUEPRINT_KIND, {"domain": "automation", "path": PATH, "source": SOURCE}
    )
    assert identity == f"automation/{PATH}"
    (name, payload) = backend._client.calls[-1]  # type: ignore[attr-defined]
    assert name == "blueprint/save"
    assert payload == {
        "domain": "automation",
        "path": PATH,
        "yaml": SOURCE,
        "allow_override": False,
    }


def test_create_refuses_to_clobber_an_existing_remote(client: _FakeClient) -> None:
    """`allow_override: False` is the server-side half of §3's `conflict` row:
    a create was planned because nothing was there, so anything there now is
    drift."""
    with pytest.raises(HaApiError):
        _backend(client).create(
            BLUEPRINT_KIND, {"domain": "automation", "path": PATH, "source": SOURCE}
        )


def test_update_saves_with_override(client: _FakeClient) -> None:
    backend = _backend(client)
    edited = SOURCE.replace("restart", "single")
    backend.update(
        BLUEPRINT_KIND,
        f"automation/{PATH}",
        {"domain": "automation", "path": PATH, "source": edited},
    )
    (name, payload) = client.calls[-1]
    assert name == "blueprint/save"
    assert payload["allow_override"] is True
    assert payload["yaml"] == edited


def test_save_sends_the_source_verbatim(client: _FakeClient) -> None:
    """Byte preservation reaches the wire, CRLF included -- HA stores what it
    is handed."""
    backend = _backend(_FakeClient())
    crlf = SOURCE.replace("\n", "\r\n")
    backend.create(BLUEPRINT_KIND, {"domain": "automation", "path": PATH, "source": crlf})
    assert backend._client.calls[-1][1]["yaml"] == crlf  # type: ignore[attr-defined]


def test_save_without_a_source_raises_before_the_wire() -> None:
    client_ = _FakeClient()
    with pytest.raises(ValueError, match="source"):
        _backend(client_).create(BLUEPRINT_KIND, {"domain": "automation", "path": PATH})
    assert client_.calls == []


# --- blueprint/delete ------------------------------------------------------


def test_delete_addresses_domain_and_path(client: _FakeClient) -> None:
    _backend(client).delete(BLUEPRINT_KIND, f"automation/{PATH}")
    assert client.calls[-1] == ("blueprint/delete", {"domain": "automation", "path": PATH})
    assert client.stored == {}


def test_delete_of_a_missing_path_propagates_the_error(client: _FakeClient) -> None:
    """§2: HA answers `unknown_error`/ENOENT -- an error, and one that stays
    distinguishable from `unknown_command`."""
    with pytest.raises(HaApiError) as excinfo:
        _backend(client).delete(BLUEPRINT_KIND, "automation/local/nope.yaml")
    assert excinfo.value.code == "unknown_error"


# --- blueprint/substitute --------------------------------------------------


def test_substitute_sends_domain_path_and_input(client: _FakeClient) -> None:
    backend = _backend(client)
    backend.blueprint_substitute("automation", PATH, {"switch_entity": "event.office"})
    assert client.calls[-1] == (
        "blueprint/substitute",
        {"domain": "automation", "path": PATH, "input": {"switch_entity": "event.office"}},
    )


def test_substitute_returns_the_expanded_config(client: _FakeClient) -> None:
    client.substitute_result = {"mode": "restart", "triggers": []}
    assert _backend(client).blueprint_substitute("automation", PATH, {}) == {
        "mode": "restart",
        "triggers": [],
    }


# --- identity round trip ---------------------------------------------------


def test_a_nested_path_survives_the_identity_round_trip(client: _FakeClient) -> None:
    """`<path>` carries slashes, so splitting an identity back into
    `(domain, path)` must split on the FIRST slash only."""
    backend = _backend(_FakeClient())
    backend.create(BLUEPRINT_KIND, {"domain": "automation", "path": "a/b/c.yaml", "source": SOURCE})
    backend.delete(BLUEPRINT_KIND, "automation/a/b/c.yaml")
    assert backend._client.calls[-1][1] == {  # type: ignore[attr-defined]
        "domain": "automation",
        "path": "a/b/c.yaml",
    }
