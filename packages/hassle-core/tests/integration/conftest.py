"""Shared fixtures for the integration suite (talks to a real HA instance).

Every test here is ``integration``-marked (auto-applied below) and targets **any**
HA instance via two environment variables: ``HASSLE_TEST_HA_URL``
and ``HASSLE_TEST_HA_TOKEN``. With either unset, the whole suite skips — so unit
CI (``pytest -m "not integration"``) never touches the network, and the CI
integration job (``.github/workflows/ci.yml``) is the only place these run,
against the Dockerized ``stable`` **and** ``dev`` images.

The ``ha`` fixture yields a connected :class:`hassle.backend.DirectBackend` and
guarantees a clean slate: every automation, script, and storage-collection
helper Hassle manages is deleted before **and** after each test, so tests never
leak state into one another regardless of which HA image they run against.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from hassle.backend import DirectBackend
from hassle.ir.keys import OBJECT_KINDS

_HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark every test collected under this directory ``integration``.

    A module-level ``pytestmark`` in a conftest does not propagate to sibling
    test modules, so we add the marker here. This is a session-level hook and
    sees *all* collected items, so we filter to this directory's subtree — then
    ``pytest -m "not integration"`` deselects the whole suite and unit CI never
    touches the network.
    """
    for item in items:
        if _HERE in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.integration)


def _require_env() -> tuple[str, str]:
    url = os.environ.get("HASSLE_TEST_HA_URL")
    token = os.environ.get("HASSLE_TEST_HA_TOKEN")
    if not url or not token:
        pytest.skip(
            "integration tests need HASSLE_TEST_HA_URL and HASSLE_TEST_HA_TOKEN "
            "pointing at a live Home Assistant instance"
        )
    return url, token


# The one object this suite must NEVER delete (docs/internals/ha-api-notes.md
# §39.11): HA's migrated default dashboard at `url_path: "lovelace"` cannot be
# recreated through the public API -- `dashboards/create` rejects that url_path
# unconditionally, because `_async_ensure_default_panel` guarantees a panel
# always exists there. Deleting it is therefore IRREVERSIBLE, and unlike every
# other object here the suite could not put it back. Any instance that has been
# through HA's startup migration has one, so a plain "wipe everything" teardown
# would silently destroy the operator's real default dashboard the first time
# this suite ran against a non-disposable instance. (Observed for real during
# DB0 -- this exclusion is the fix.)
_UNDELETABLE = {("dashboard", "lovelace")}


def _wipe(backend: DirectBackend) -> None:
    """Delete every Hassle-managed object of every kind, except the one that
    could never be restored (see `_UNDELETABLE`)."""
    for kind in OBJECT_KINDS:
        for identity in list(backend.list_remote(kind)):
            if (kind, identity) in _UNDELETABLE:
                continue
            with contextlib.suppress(Exception):  # best-effort teardown
                backend.delete(kind, identity)


@pytest.fixture
def ha() -> Iterator[DirectBackend]:
    url, token = _require_env()
    with DirectBackend(url, token) as backend:
        _wipe(backend)
        try:
            yield backend
        finally:
            _wipe(backend)
