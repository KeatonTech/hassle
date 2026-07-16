"""`HaClient` — the async REST + WebSocket transport to Home Assistant Core.

One long-lived access token, straight to HA's own APIs (DESIGN §4, §13). This is
the low-level async layer; :class:`hassle.backend.direct.DirectBackend` wraps it
in a synchronous facade that satisfies the frozen `Backend` protocol.

Design points:

- **REST** (`/api/...`) for automations, scripts, templates, media upload, and
  `get_config`. Transient failures (connection refused, disconnects, timeouts)
  retry with exponential backoff; a 401 is *not* retried — it is a logical
  `HaAuthError` (DESIGN §4: token validity is proven by a call).
- **WebSocket** (`/api/websocket`) for helpers, registries, `get_services`,
  `validate_config`, traces, template render, media resolve/remove, and the
  purpose-vocabulary enumeration. The connection auto-(re)connects and
  re-authenticates on demand; commands are id-multiplexed.
- **Request timeouts** everywhere, so a wedged instance can never hang the CLI.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any

import aiohttp

from hassle.backend.errors import HaApiError, HaAuthError, HaConnectionError

_RETRYABLE = (
    aiohttp.ClientConnectorError,
    aiohttp.ServerDisconnectedError,
    aiohttp.ClientOSError,
    asyncio.TimeoutError,
)

# Errors `ws.send_json` raises when the socket is already gone. A failure here
# means the command never reached HA, so a single reconnect+resend is safe even
# for non-idempotent writes.
_WS_SEND_FAILURES = (
    ConnectionResetError,
    aiohttp.ClientError,
    RuntimeError,
)


class HaClient:
    """Async transport to one HA instance (REST + WS)."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        request_timeout: float = 15.0,
        max_retries: int = 4,
        backoff_base: float = 0.5,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._base = url.rstrip("/")
        self._token = token
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._auth_header = {"Authorization": f"Bearer {token}"}

        self._session = session
        self._owns_session = session is None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_id = 0
        self._ha_version: str | None = None
        self._ws_lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------

    @property
    def ha_version(self) -> str | None:
        return self._ha_version

    async def __aenter__(self) -> HaClient:
        await self._ensure_session()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    # -- retry -------------------------------------------------------------

    async def _sleep_backoff(self, attempt: int) -> None:
        # 0.5s, 1s, 2s, 4s ... — deterministic, no randomness/jitter.
        await asyncio.sleep(self._backoff_base * (2**attempt))

    # -- REST --------------------------------------------------------------

    def _rest_url(self, path: str) -> str:
        return f"{self._base}/{path.lstrip('/')}"

    async def _rest(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: aiohttp.FormData | None = None,
        expect: str = "json",
    ) -> Any:
        session = await self._ensure_session()
        url = self._rest_url(path)
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                async with session.request(
                    method, url, json=json, data=data, headers=self._auth_header
                ) as resp:
                    if resp.status == 401:
                        raise HaAuthError(f"{method} {path}")
                    if resp.status >= 400:
                        body = await resp.text()
                        raise HaApiError(
                            f"HA returned {resp.status} for {method} {path}: {body[:400]}"
                        )
                    if expect == "text":
                        return await resp.text()
                    if expect == "bytes":
                        return await resp.read()
                    if resp.status == 204 or resp.content_length == 0:
                        return None
                    return await resp.json()
            except _RETRYABLE as err:
                last_exc = err
                if attempt + 1 < self._max_retries:
                    await self._sleep_backoff(attempt)
                    continue
        raise HaConnectionError(
            f"could not reach Home Assistant for {method} {path} after "
            f"{self._max_retries} attempts ({last_exc}). Fix: check the HA URL "
            "and that the instance is reachable from here."
        )

    async def rest_get(self, path: str, *, expect: str = "json") -> Any:
        return await self._rest("GET", path, expect=expect)

    async def rest_post(self, path: str, json: Any = None, *, expect: str = "json") -> Any:
        return await self._rest("POST", path, json=json, expect=expect)

    async def rest_delete(self, path: str) -> Any:
        return await self._rest("DELETE", path)

    async def rest_post_multipart(self, path: str, data: aiohttp.FormData) -> Any:
        return await self._rest("POST", path, data=data)

    # -- WebSocket ---------------------------------------------------------

    def _ws_url(self) -> str:
        scheme = "wss" if self._base.startswith("https") else "ws"
        host = self._base.split("://", 1)[-1]
        return f"{scheme}://{host}/api/websocket"

    async def _connect_ws(self) -> aiohttp.ClientWebSocketResponse:
        session = await self._ensure_session()
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                ws = await session.ws_connect(self._ws_url(), heartbeat=30.0)
            except _RETRYABLE as err:
                last_exc = err
                if attempt + 1 < self._max_retries:
                    await self._sleep_backoff(attempt)
                    continue
                raise HaConnectionError(
                    f"could not open the HA WebSocket after {self._max_retries} "
                    f"attempts ({err}). Fix: check the HA URL and reachability."
                ) from err
            # Auth handshake.
            required = await self._ws_recv(ws)
            if required.get("ha_version"):
                self._ha_version = required["ha_version"]
            await ws.send_json({"type": "auth", "access_token": self._token})
            ack = await self._ws_recv(ws)
            if ack.get("type") == "auth_ok":
                if ack.get("ha_version"):
                    self._ha_version = ack["ha_version"]
                return ws
            await ws.close()
            raise HaAuthError("WebSocket auth rejected")
        raise HaConnectionError(
            f"could not open the HA WebSocket after {self._max_retries} attempts "
            f"({last_exc}). Fix: check the HA URL and that the instance is reachable "
            "from here."
        )

    async def _ws_recv(self, ws: aiohttp.ClientWebSocketResponse) -> dict[str, Any]:
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=self._timeout.total)
        except TimeoutError as err:
            # A wedged instance that accepted a command but never replies: surface
            # a what/where/fix connection error, not a bare TimeoutError.
            raise HaConnectionError(
                f"Home Assistant did not respond on the WebSocket within "
                f"{self._timeout.total}s. Fix: check that the instance is healthy "
                "and reachable."
            ) from err
        if msg.type in (
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSING,
            aiohttp.WSMsgType.CLOSED,
        ):
            raise HaConnectionError(
                "Home Assistant closed the WebSocket connection unexpectedly. "
                "Fix: check that the instance is still running and reachable, then "
                "retry -- a fresh connection will be opened automatically."
            )
        if msg.type is aiohttp.WSMsgType.ERROR:
            raise HaConnectionError(
                f"Home Assistant WebSocket error: {ws.exception()}. Fix: check that "
                "the instance is healthy and reachable, then retry."
            )
        return msg.json()

    async def _ensure_ws(self) -> aiohttp.ClientWebSocketResponse:
        if self._ws is None or self._ws.closed:
            self._ws = await self._connect_ws()
        return self._ws

    def _next_id(self) -> int:
        self._ws_id += 1
        return self._ws_id

    async def ws_command(self, type: str, **payload: Any) -> Any:
        """Send a WS command and return its ``result`` (raising on failure).

        A reconnect+resend happens **only when the send itself fails** on a stale
        socket (the command never reached HA, so resending is safe). If the socket
        drops *after* the send — while awaiting the result — the error propagates
        without resending: HA may already have processed the command, and a
        non-idempotent helper `create` must never be double-applied.
        """
        async with self._ws_lock:
            ws = await self._ensure_ws()
            msg_id = self._next_id()
            try:
                await ws.send_json({"id": msg_id, "type": type, **payload})
            except _WS_SEND_FAILURES:
                # Socket looked open but the write failed: reconnect and send once
                # more (the first attempt never landed on HA).
                self._ws = None
                ws = await self._ensure_ws()
                msg_id = self._next_id()
                try:
                    await ws.send_json({"id": msg_id, "type": type, **payload})
                except _WS_SEND_FAILURES as err:
                    self._ws = None
                    raise HaConnectionError(
                        f"could not send the WebSocket command {type!r} to Home Assistant "
                        f"even after reconnecting ({err}). Fix: check that the instance is "
                        "healthy and reachable, then retry."
                    ) from err
            return await self._await_result(ws, msg_id)

    async def _await_result(self, ws: aiohttp.ClientWebSocketResponse, msg_id: int) -> Any:
        while True:
            msg = await self._ws_recv(ws)
            if msg.get("id") != msg_id or msg.get("type") != "result":
                continue
            if not msg.get("success", False):
                error = msg.get("error", {})
                raise HaApiError(
                    f"WS command failed: {error.get('message', error)}",
                    code=error.get("code"),
                )
            return msg.get("result")

    async def ws_subscribe_first_event(self, type: str, **payload: Any) -> Any:
        """Fire a subscription, return its first ``event`` payload, unsubscribe.

        Used for one-shot snapshot subscriptions (the purpose-vocabulary
        `trigger_platforms/subscribe` etc., which ack then push a full snapshot
        event).
        """
        async with self._ws_lock:
            ws = await self._ensure_ws()
            msg_id = self._next_id()
            await ws.send_json({"id": msg_id, "type": type, **payload})
            # First the result ack, then the snapshot event.
            got_ack = False
            event_payload: Any = None
            while True:
                msg = await self._ws_recv(ws)
                if msg.get("id") != msg_id:
                    continue
                if msg.get("type") == "result":
                    if not msg.get("success", False):
                        error = msg.get("error", {})
                        raise HaApiError(
                            f"subscription {type} failed: {error.get('message', error)}",
                            code=error.get("code"),
                        )
                    got_ack = True
                elif msg.get("type") == "event" and got_ack:
                    event_payload = msg.get("event")
                    break
            # Best-effort unsubscribe; ignore if the socket is already gone.
            try:
                unsub_id = self._next_id()
                await ws.send_json(
                    {"id": unsub_id, "type": "unsubscribe_events", "subscription": msg_id}
                )
            except Exception:
                pass
            return event_payload
