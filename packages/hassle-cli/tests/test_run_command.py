"""`hassle run` without `--live` runs on the simulator (DESIGN §10.4 paragraph 5);
`--live` is covered by the one env-gated integration test
(tests/integration/test_run_live.py, MILESTONES M7 test 5). This file covers
the simulator path (FakeBackend-adjacent, no network) and the live-mode
plumbing that CAN be unit tested: skip_condition default, shadow id shape,
and cleanup-on-error being wired through a fake "live session" seam.
"""

from __future__ import annotations

from pathlib import Path


def test_run_without_live_uses_simulator(bundle_dir: Path, cli) -> None:
    result = cli(["run", "hallway.py::hall_light_on_motion"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert "light.turn_on" in result.output


def test_run_live_without_confirmation_flag_refuses(
    bundle_dir: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(bundle_dir, backend_token=token)
    # --live requires an explicit confirmation (real service calls on real
    # devices, DESIGN §10.4) -- refuses without --yes and without a tty to
    # prompt against in CliRunner's non-interactive invocation.
    result = cli(["run", "hallway.py::hall_light_on_motion", "--live"], cwd=bundle_dir)
    assert result.exit_code != 0
    assert "real service calls" in result.output.lower() or "--yes" in result.output


def test_shadow_id_is_hash_derived_and_prefixed() -> None:
    from hassle_cli.run_live import shadow_automation_id

    shadow_id = shadow_automation_id("automation:hall_light_on_motion")
    assert shadow_id.startswith("hassle_shadow_")
    # Deterministic (R8): same object key -> same shadow id.
    assert shadow_id == shadow_automation_id("automation:hall_light_on_motion")


def test_build_shadow_config_sets_initial_state_off() -> None:
    from hassle_cli.run_live import build_shadow_config

    body = {
        "id": "hall_light_on_motion",
        "alias": "Hallway light on motion",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [],
        "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
        "mode": "single",
    }
    shadow = build_shadow_config("automation:hall_light_on_motion", body)
    assert shadow["initial_state"] is False
    assert shadow["id"].startswith("hassle_shadow_")


def test_trigger_payload_defaults_skip_condition_false() -> None:
    from hassle_cli.run_live import trigger_payload

    payload = trigger_payload(skip_conditions=False)
    # HA's own default is `true` (skip_condition defaults to skipping
    # conditions); Hassle must send an explicit `false` unless --skip-conditions.
    assert payload["skip_condition"] is False


def test_trigger_payload_skip_conditions_flag_sets_true() -> None:
    from hassle_cli.run_live import trigger_payload

    payload = trigger_payload(skip_conditions=True)
    assert payload["skip_condition"] is True


def test_live_session_cleans_up_shadow_on_success(fake_backend) -> None:
    from hassle_cli.run_live import run_shadow_session

    backend, _token = fake_backend
    body = {
        "id": "hall_light_on_motion",
        "alias": "A",
        "triggers": [],
        "conditions": [],
        "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
        "mode": "single",
    }

    calls: list[str] = []

    def fake_trigger(shadow_id: str, **_: object) -> None:
        calls.append(shadow_id)

    def fake_get_trace(shadow_id: str) -> dict[str, object]:
        return {"trace": {}, "config": body}

    result = run_shadow_session(
        backend,
        "automation:hall_light_on_motion",
        body,
        trigger_fn=fake_trigger,
        get_trace_fn=fake_get_trace,
    )
    assert result.trace is not None
    assert calls  # the shadow was triggered
    assert backend.list_remote("automation") == {}  # cleaned up


def test_live_session_cleans_up_shadow_on_trace_failure(fake_backend) -> None:
    from hassle_cli.run_live import run_shadow_session

    backend, _token = fake_backend
    body = {
        "id": "hall_light_on_motion",
        "alias": "A",
        "triggers": [],
        "conditions": [],
        "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
        "mode": "single",
    }

    def fake_trigger(shadow_id: str, **_: object) -> None:
        return None

    def failing_get_trace(shadow_id: str) -> dict[str, object]:
        raise RuntimeError("injected trace-stream failure")

    try:
        run_shadow_session(
            backend,
            "automation:hall_light_on_motion",
            body,
            trigger_fn=fake_trigger,
            get_trace_fn=failing_get_trace,
        )
        raised = False
    except RuntimeError:
        raised = True

    assert raised
    # Cleaned up even though the trace-stream raised.
    assert backend.list_remote("automation") == {}
