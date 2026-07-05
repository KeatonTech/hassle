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
    """
    fake = fake_backend_for_url(ha_url)
    if fake is not None:
        yield fake
        return
    from hassle.backend import DirectBackend

    with DirectBackend(ha_url, token) as backend:
        yield backend
