"""Shared fixtures for the M7 `run --live` integration suite (real HA).

Same env-gating convention as `packages/hassle-core/tests/integration/conftest.py`
(MILESTONES M6): both `HASSLE_TEST_HA_URL` and `HASSLE_TEST_HA_TOKEN` must be set
or the whole suite skips, so `pytest -m "not integration"` (unit CI) never
touches the network (R2). The CI integration job runs this alongside the M6
suite against Dockerized HA `stable` and `dev`.
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


def _wipe(backend: DirectBackend) -> None:
    for kind in OBJECT_KINDS:
        for identity in list(backend.list_remote(kind)):
            with contextlib.suppress(Exception):
                backend.delete(kind, identity)


@pytest.fixture
def ha_url_token() -> tuple[str, str]:
    return _require_env()


@pytest.fixture
def ha() -> Iterator[DirectBackend]:
    url, token = _require_env()
    with DirectBackend(url, token) as backend:
        _wipe(backend)
        try:
            yield backend
        finally:
            _wipe(backend)
