"""M9 error-message audit finding: `HaClient._ws_recv`'s close/error paths
previously raised `HaConnectionError` with no "Fix:" clause -- fixed to
follow the same what/where/fix rubric as every sibling `HaConnectionError`
site (R6). Exercised here with a minimal fake WS object (no real network,
R2) since `_ws_recv` only needs `.receive()`/`.exception()`/message `.type`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp
import pytest

from hassle.backend.client import HaClient
from hassle.backend.errors import HaConnectionError


@dataclass
class _FakeMsg:
    type: aiohttp.WSMsgType


class _FakeWs:
    def __init__(self, msg_type: aiohttp.WSMsgType, *, exc: Exception | None = None) -> None:
        self._msg_type = msg_type
        self._exc = exc

    async def receive(self) -> _FakeMsg:
        return _FakeMsg(type=self._msg_type)

    def exception(self) -> Exception | None:
        return self._exc


def _client() -> HaClient:
    return HaClient("http://ha.example", "test-token")


def test_ws_closed_raises_connection_error_with_fix() -> None:
    client = _client()
    ws = _FakeWs(aiohttp.WSMsgType.CLOSE)
    with pytest.raises(HaConnectionError) as excinfo:
        asyncio.run(client._ws_recv(ws))  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "closed the WebSocket" in msg  # what
    assert "Fix:" in msg


def test_ws_error_raises_connection_error_with_fix() -> None:
    client = _client()
    ws = _FakeWs(aiohttp.WSMsgType.ERROR, exc=RuntimeError("boom"))
    with pytest.raises(HaConnectionError) as excinfo:
        asyncio.run(client._ws_recv(ws))  # type: ignore[arg-type]
    msg = str(excinfo.value)
    assert "boom" in msg  # what
    assert "Fix:" in msg


def test_ws_send_failure_after_reconnect_raises_connection_error_with_fix() -> None:
    """`ws_command`'s reconnect-then-resend path: both sends fail -> a clean
    what/where/fix error, not a bare exception."""
    client = _client()

    class _AlwaysFailsWs:
        closed = False

        async def send_json(self, _payload: dict[str, Any]) -> None:
            raise ConnectionResetError("gone")

        async def close(self) -> None:
            pass

    async def _fake_ensure_ws() -> Any:
        return _AlwaysFailsWs()

    client._ensure_ws = _fake_ensure_ws  # type: ignore[method-assign]

    with pytest.raises(HaConnectionError) as excinfo:
        asyncio.run(client.ws_command("test_command"))
    msg = str(excinfo.value)
    assert "test_command" in msg  # what
    assert "Fix:" in msg
