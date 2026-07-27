"""`hassle validate --live` (DESIGN §9 tier 4): a real server-side check for
automations (HA's `validate_config`), and the dashboards tier-4-absence
notice this workstream (DB7, docs/internals/dashboards-design.md §8) owns --
dashboards must never silently pass a check that never actually ran for them.

Unit-tested against a hand-rolled stub backend (`validate_config` is a
`DirectBackend`-only method, not `FakeBackend`'s surface -- see
`hassle.backend.fake`'s docstring), registered via the same
`backend_factory.register_fake_backend` seam `test_run_live_command.py` uses.
No network in unit tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


class _StubValidateBackend:
    """Minimal stand-in for `DirectBackend.validate_config` -- the only
    method `hassle validate --live` calls on the backend."""

    def __init__(self, *, invalid: dict[str, str] | None = None) -> None:
        # block -> error message, for blocks that should report invalid.
        self._invalid = invalid or {}
        self.validate_config_calls: list[dict[str, Any]] = []

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        self.validate_config_calls.append(config)
        report: dict[str, Any] = {}
        for block in ("triggers", "conditions", "actions"):
            error = self._invalid.get(block)
            report[block] = {"valid": error is None, "error": error}
        return report


@pytest.fixture
def _registered_stub_backend():
    from hassle_cli import backend_factory

    tokens: list[str] = []

    def _register(backend: _StubValidateBackend) -> str:
        token = backend_factory.register_fake_backend(backend)  # type: ignore[arg-type]
        tokens.append(token)
        return token

    yield _register

    for token in tokens:
        backend_factory.unregister_fake_backend(token)


def _write_bundle(root: Path, *, token: str, extra_dashboard: bool = False) -> None:
    root.mkdir(exist_ok=True)
    (root / "hassle.toml").write_text(
        f'ha_url = "fake://{token}"\nformat_version = 1\n', encoding="utf-8"
    )
    (root / "a.py").write_text(
        """
from hassle import automation, service, state, when

@automation(id="a", alias="A")
def a():
    when(state("binary_sensor.trigger").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )
    if extra_dashboard:
        (root / "dash.py").write_text(
            """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="a-b")
def d():
    with view(title="V"), section():
        c.tile("light.hallway")
""",
            encoding="utf-8",
        )


def test_live_validate_prints_dashboard_notice_once_when_dashboards_present(
    tmp_path: Path, cli, _registered_stub_backend
) -> None:
    root = tmp_path / "house"
    backend = _StubValidateBackend()
    token = _registered_stub_backend(backend)
    _write_bundle(root, token=token, extra_dashboard=True)

    result = cli(["validate", "--live"], cwd=root)
    assert result.exit_code == 0, result.output
    assert result.output.count("dashboards have no server-side validation tier") == 1
    # The automation still gets a real server-side check.
    assert backend.validate_config_calls


def test_live_validate_no_dashboard_notice_when_no_dashboards(
    tmp_path: Path, cli, _registered_stub_backend
) -> None:
    root = tmp_path / "house"
    backend = _StubValidateBackend()
    token = _registered_stub_backend(backend)
    _write_bundle(root, token=token, extra_dashboard=False)

    result = cli(["validate", "--live"], cwd=root)
    assert result.exit_code == 0, result.output
    assert "server-side validation tier" not in result.output


def test_live_validate_surfaces_ha_rejected_automation_block(
    tmp_path: Path, cli, _registered_stub_backend
) -> None:
    root = tmp_path / "house"
    backend = _StubValidateBackend(invalid={"actions": "not a valid service call"})
    token = _registered_stub_backend(backend)
    _write_bundle(root, token=token)

    result = cli(["validate", "--live"], cwd=root)
    assert result.exit_code == 1, result.output
    assert "not a valid service call" in result.output
    assert "live-invalid-config" in result.output


def test_live_validate_notice_printed_once_with_multiple_dashboards(
    tmp_path: Path, cli, _registered_stub_backend
) -> None:
    root = tmp_path / "house"
    backend = _StubValidateBackend()
    token = _registered_stub_backend(backend)
    _write_bundle(root, token=token, extra_dashboard=True)
    (root / "dash2.py").write_text(
        """
from hassle import dashboard, section, view
from hassle import cards as c

@dashboard(url_path="c-d")
def d2():
    with view(title="V2"), section():
        c.tile("light.hallway")
""",
        encoding="utf-8",
    )

    result = cli(["validate", "--live"], cwd=root)
    assert result.exit_code == 0, result.output
    # Once per RUN, never once per dashboard -- two dashboards in this bundle.
    assert result.output.count("dashboards have no server-side validation tier") == 1


def test_live_validate_json_mode_never_prints_the_notice(
    tmp_path: Path, cli, _registered_stub_backend
) -> None:
    root = tmp_path / "house"
    backend = _StubValidateBackend()
    token = _registered_stub_backend(backend)
    _write_bundle(root, token=token, extra_dashboard=True)

    result = cli(["validate", "--live", "--json"], cwd=root)
    assert "server-side validation tier" not in result.output
    import json

    payload = json.loads(result.output)
    assert set(payload) == {"findings"}


def test_without_live_flag_never_calls_validate_config(
    tmp_path: Path, cli, _registered_stub_backend
) -> None:
    root = tmp_path / "house"
    backend = _StubValidateBackend()
    token = _registered_stub_backend(backend)
    _write_bundle(root, token=token, extra_dashboard=True)

    result = cli(["validate"], cwd=root)
    assert result.exit_code == 0, result.output
    assert not backend.validate_config_calls
    assert "server-side validation tier" not in result.output
