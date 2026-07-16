"""Shared fixtures for the CLI test suite.

Everything here runs against `hassle.backend.fake.FakeBackend` (unit tests
never touch the network) and `click.testing.CliRunner` for exit-code +
output-snapshot assertions. `run_cli` always passes `NO_COLOR=1` (a
plain-text capture mode; error messages state what/where/fix and snapshots
are the UX contract) unless a test explicitly wants to check color/rich
behavior.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from hassle_cli.cli import main

REPO_ROOT = Path(__file__).resolve().parents[3]
HOME_REGISTRY = REPO_ROOT / "fixtures" / "registry" / "home.json"


class RealKeyringUsedInUnitTestError(AssertionError):
    """A unit test reached the real OS keyring (CI-stabilization guard).

    This suite must run identically on a laptop with macOS Keychain and a
    headless Linux CI runner with zero keyring backends installed -- the
    latter used to raise `keyring.errors.NoKeyringError` from deep inside
    `hassle_cli.token.resolve_token` on every `fake://`-backed CLI test,
    which macOS silently masked (Keychain always answers). Tests that
    legitimately want to exercise keyring-touching code paths (`hassle
    login`, `hassle_cli.token` unit tests) monkeypatch `hassle_cli.token`'s
    `_keyring_get`/`_keyring_set`/`_keyring_delete` directly -- that is the
    supported opt-in seam and never reaches this guard. Anything that
    reaches the real `keyring` module in a unit test is a bug: either a
    missing `fake://` short-circuit (see `hassle_cli.token.resolve_token`)
    or a test that forgot to use the `fake_backend`/`toml_writer` fixtures.
    """


def _raise_real_keyring_used(*args: object, **kwargs: object) -> None:
    raise RealKeyringUsedInUnitTestError(
        "a unit test reached the real OS keyring via the `keyring` package. "
        "Fix: `fake://` URLs must resolve without the keyring (see "
        "hassle_cli.token.resolve_token), and tests that intentionally exercise "
        "keyring-touching code must monkeypatch hassle_cli.token._keyring_get/"
        "_keyring_set/_keyring_delete instead of relying on a real backend."
    )


@pytest.fixture(autouse=True)
def _forbid_real_keyring_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """Autouse guard (CI stabilization): replace the real `keyring` module's
    entry points with a fake that RAISES on any use, for every test in this
    suite. No unit test may depend on a real OS keyring being present --
    that dependency is exactly what made main red on ubuntu CI while staying
    green on macOS (Keychain silently masks a missing keyring backend)."""
    monkeypatch.setattr("keyring.get_password", _raise_real_keyring_used)
    monkeypatch.setattr("keyring.set_password", _raise_real_keyring_used)
    monkeypatch.setattr("keyring.delete_password", _raise_real_keyring_used)


@pytest.fixture
def registry_snapshot_json() -> dict[str, Any]:
    return json.loads(HOME_REGISTRY.read_text(encoding="utf-8"))


@pytest.fixture
def bundle_dir(tmp_path: Path, registry_snapshot_json: dict[str, Any]) -> Path:
    """A minimal, valid bundle dir with `.hassle/registry.json` seeded.

    DSL sources live directly at the bundle root (`hallway.py`, not
    `automations/hallway.py`) -- a flat bundle is still fully supported
    (docs/ha-api-notes.md §17.9 RESOLVED: the loader recurses into
    subdirectories too, but never requires them). Kept flat here because many
    tests in this suite reference `bundle_dir / "hallway.py"` directly; an
    empty `automations/` dir sits alongside it, matching what a real
    `hassle init` scaffolds.
    """
    root = tmp_path / "my-house"
    root.mkdir()
    (root / "automations").mkdir()
    (root / "tests").mkdir()
    (root / ".hassle").mkdir()
    (root / ".hassle" / "registry.json").write_text(
        json.dumps(registry_snapshot_json), encoding="utf-8"
    )
    (root / "hassle.toml").write_text(
        '# ha_url = "http://homeassistant.local:8123"\nformat_version = 1\nmirror = false\n',
        encoding="utf-8",
    )
    (root / "hallway.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )
    return root


def run_cli(
    args: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    input: str | None = None,
) -> Result:
    runner = CliRunner()
    full_env = {"NO_COLOR": "1", "HASSLE_CONFIG_HOME": str(cwd / "_global_config")}
    if env:
        full_env.update(env)
    old_cwd = Path.cwd()
    os.chdir(cwd)
    try:
        return runner.invoke(main, args, env=full_env, input=input, catch_exceptions=False)
    finally:
        os.chdir(old_cwd)


@pytest.fixture
def cli(tmp_path: Path):
    def _run(
        args: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        input: str | None = None,
    ) -> Result:
        return run_cli(args, cwd or tmp_path, env, input=input)

    return _run


def write_hassle_toml(bundle: Path, *, backend_token: str, mirror: bool = False) -> None:
    """Write a `hassle.toml` pointing at a fake-backend test seam.

    `ha_url`/`ha_token_ref` are meaningless placeholders in test mode: the CLI's
    `backend_factory` recognizes `ha_url == "fake://<token>"` and returns the
    registered `FakeBackend` instead of constructing a `DirectBackend`.
    """
    content = f"""ha_url = "fake://{backend_token}"
format_version = 1
mirror = {"true" if mirror else "false"}
"""
    (bundle / "hassle.toml").write_text(content, encoding="utf-8")


@pytest.fixture
def toml_writer():
    """Fixture wrapper around `write_hassle_toml` (importable via the `tests`
    package is not set up in this test tree -- plain pytest fixtures are the
    cross-file sharing mechanism, matching the sibling packages' convention)."""
    return write_hassle_toml


@pytest.fixture
def output_normalizer():
    return normalize_output


@pytest.fixture
def fake_backend(registry_snapshot_json):
    """A `FakeBackend`, registered so the CLI picks it up in-process instead of
    building a real `DirectBackend` (test-only seam; see `hassle_cli.backend_factory`
    module docstring -- `ha_url = "fake://<token>"` is never written by production
    code, only by this fixture / `write_hassle_toml`).

    Serves the SAME registry snapshot the bundle fixtures seed on disk, so
    pull's refresh-on-every-pull (DESIGN §9.2) is a content no-op in tests --
    exactly like a real HA whose registry hasn't changed since the last pull."""
    from hassle.backend.fake import FakeBackend
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle_cli.backend_factory import register_fake_backend, unregister_fake_backend

    backend = FakeBackend()
    backend.registry_snapshot = RegistrySnapshot.model_validate(registry_snapshot_json)
    token = register_fake_backend(backend)
    try:
        yield backend, token
    finally:
        unregister_fake_backend(token)


@pytest.fixture
def git_repo(bundle_dir: Path) -> Path:
    """Turn `bundle_dir` into a clean git repo (for pull/status --clean-tree tests)."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=bundle_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=bundle_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=bundle_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=bundle_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=bundle_dir, check=True)
    return bundle_dir


def normalize_output(text: str, tmp_path: Path | None = None) -> str:
    """Strip volatile bits (tmp paths, timestamps) from CLI output for snapshotting."""
    import re

    if tmp_path is not None:
        text = text.replace(str(tmp_path), "<TMP>")
    text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?", "<TIMESTAMP>", text)
    return text
