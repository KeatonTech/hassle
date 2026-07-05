"""Builds the `Backend` (F2) a CLI invocation talks to.

Production path: `hassle.toml`'s `ha_url` + a resolved token (keyring/
`HASSLE_TOKEN`/`HASSLE_HA_URL`+`HASSLE_TOKEN` env overrides for `run --live`)
build a real `hassle.backend.DirectBackend`.

Test-only seam: `ha_url = "fake://<token>"` (never written by production code
-- only by `packages/hassle-cli/tests/conftest.py`) resolves to a `FakeBackend`
registered in-process via `register_fake_backend`. This keeps every CLI-level
test in `packages/hassle-cli/tests/` running against `FakeBackend` (R2: no
network in unit tests) while still exercising the *real* command code path
(argument parsing, plan rendering, manifest read/write, git checks, ...) --
only the actual HA transport is swapped.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from hassle.backend.protocol import Backend

_FAKE_BACKENDS: dict[str, Backend] = {}

_FAKE_URL_PREFIX = "fake://"


class UnregisteredFakeBackendError(Exception):
    """A `fake://<token>` URL was used but no `FakeBackend` is registered for
    that token (M7 review cleanup).

    Without this check, `connect()` would fall through to building a real
    `DirectBackend` against the literal string `fake://<token>` as if it were
    an HA base URL -- producing a confusing stack trace deep in the HTTP/WS
    client instead of a clean error naming the actual mistake.
    """

    def __init__(self, ha_url: str) -> None:
        self.ha_url = ha_url
        super().__init__(
            f"no FakeBackend is registered for the test URL {ha_url!r}. This URL only "
            "makes sense in a test process that called `register_fake_backend(...)` "
            "first (see hassle_cli.backend_factory / packages/hassle-cli/tests/"
            "conftest.py's `fake_backend` fixture) -- a bare `fake://` scheme is never "
            "valid outside tests. Fix: register the backend before connecting (or, if "
            "this is a real bundle, use a real `ha_url` in hassle.toml)."
        )


def register_fake_backend(backend: Backend) -> str:
    """Register `backend` for test-only lookup; returns a token to embed in
    a test `hassle.toml`'s `ha_url = "fake://<token>"`."""
    token = uuid.uuid4().hex
    _FAKE_BACKENDS[token] = backend
    return token


def unregister_fake_backend(token: str) -> None:
    _FAKE_BACKENDS.pop(token, None)


def is_fake_url(ha_url: str) -> bool:
    return ha_url.startswith(_FAKE_URL_PREFIX)


def fake_backend_for_url(ha_url: str) -> Backend | None:
    if not is_fake_url(ha_url):
        return None
    token = ha_url[len(_FAKE_URL_PREFIX) :]
    return _FAKE_BACKENDS.get(token)


@contextmanager
def connect(ha_url: str, token: str) -> Iterator[Backend]:
    """Yield the `Backend` for `ha_url` as a context manager.

    A `fake://` URL never reaches `DirectBackend`/the network (test-only seam,
    see module docstring) and is yielded as-is (no connection lifecycle to
    manage); any other URL builds a real `DirectBackend`, whose `__enter__`
    probes auth (`GET /api/config`) and whose `__exit__` tears down its
    background event loop.

    Raises `UnregisteredFakeBackendError` for a `fake://` URL with no
    registered backend, rather than falling through to `DirectBackend` (which
    would try -- and fail confusingly -- to treat the literal `fake://...`
    string as a real HA base URL).
    """
    if is_fake_url(ha_url):
        fake = fake_backend_for_url(ha_url)
        if fake is None:
            raise UnregisteredFakeBackendError(ha_url)
        yield fake
        return
    from hassle.backend import DirectBackend

    with DirectBackend(ha_url, token) as backend:
        yield backend
