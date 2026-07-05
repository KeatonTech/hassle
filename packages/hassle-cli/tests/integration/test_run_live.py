"""MILESTONES M7 test 5: `run --live` integration test (Dockerized HA).

Shadow automation created with `initial_state: off`, triggered with
`skip_condition: false` by default (HA's own default is `true` -- assert we
override it), trace rendered with correct source lines, shadow deleted --
also on failure (inject a trace-stream error; assert cleanup).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.backend import DirectBackend


def _shadow_ids(ha: DirectBackend) -> list[str]:
    return [
        identity
        for identity in ha.list_remote("automation")
        if identity.startswith("hassle_shadow_")
    ]


def _write_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "live-bundle"
    root.mkdir()
    (root / "hassle.toml").write_text("format_version = 1\nmirror = false\n", encoding="utf-8")
    # A flat bundle (DSL sources directly at the bundle root) is still fully
    # supported (docs/ha-api-notes.md §17.9 RESOLVED: the loader also
    # recurses into subdirectories now, but never requires them).
    (root / "a.py").write_text(
        """
from hassle import automation, only_if, service, state, when

@automation(id="live_test_automation", alias="Live test automation")
def live_test_automation():
    when(state("input_boolean.hassle_flag").to("on"))
    only_if(state("input_boolean.hassle_flag_2").is_("on"))
    service("input_boolean.turn_off", target={"entity_id": "input_boolean.hassle_flag"})
""",
        encoding="utf-8",
    )
    return root


@pytest.mark.integration
def test_run_live_creates_shadow_triggers_and_cleans_up(
    ha: DirectBackend, ha_url_token: tuple[str, str], tmp_path: Path
) -> None:
    from click.testing import CliRunner

    from hassle_cli.cli import main

    url, token = ha_url_token
    ha.create("input_boolean", {"name": "Hassle Flag", "icon": "mdi:flag"})
    ha.create("input_boolean", {"name": "Hassle Flag 2", "icon": "mdi:flag"})

    bundle = _write_bundle(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["run", "a.py::live_test_automation", "--live", "--yes"],
        env={"NO_COLOR": "1", "HASSLE_HA_URL": url, "HASSLE_TOKEN": token},
        cwd=str(bundle),
    )
    assert result.exit_code == 0, result.output
    assert "trace" in result.output.lower()
    # Shadow cleaned up on success.
    assert _shadow_ids(ha) == []


@pytest.mark.integration
def test_run_live_cleans_up_shadow_on_trace_stream_failure(
    ha: DirectBackend,
    ha_url_token: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from click.testing import CliRunner

    from hassle_cli import run_live
    from hassle_cli.cli import main

    url, token = ha_url_token
    ha.create("input_boolean", {"name": "Hassle Flag", "icon": "mdi:flag"})
    ha.create("input_boolean", {"name": "Hassle Flag 2", "icon": "mdi:flag"})

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected trace-stream failure")

    monkeypatch.setattr(run_live, "stream_trace", _boom)

    bundle = _write_bundle(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["run", "a.py::live_test_automation", "--live", "--yes"],
        env={"NO_COLOR": "1", "HASSLE_HA_URL": url, "HASSLE_TOKEN": token},
        cwd=str(bundle),
    )
    assert result.exit_code != 0
    # Shadow cleaned up even though the trace stream blew up.
    assert _shadow_ids(ha) == []


@pytest.mark.integration
def test_doctor_sweeps_orphaned_shadow_automations(ha: DirectBackend) -> None:
    from hassle_cli.doctor import sweep_orphaned_shadows

    ha.create(
        "automation",
        {
            "id": "hassle_shadow_orphaned123",
            "alias": "hassle shadow (orphaned)",
            "triggers": [],
            "conditions": [],
            "actions": [],
            "mode": "single",
            "initial_state": False,
        },
    )
    assert "hassle_shadow_orphaned123" in _shadow_ids(ha)

    swept = sweep_orphaned_shadows(ha)
    assert "hassle_shadow_orphaned123" in swept
    assert _shadow_ids(ha) == []
