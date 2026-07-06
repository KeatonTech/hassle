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


def test_build_shadow_config_replaces_triggers_with_never_fires_event() -> None:
    """Revised design (docs/ha-api-notes.md §27 addendum): the shadow is
    created ENABLED (no `initial_state`) with its own trigger list replaced
    by a single event trigger using a run-unique event type nothing on the
    real bus will ever fire -- the same "never fires on its own" guarantee
    DESIGN §10.4 point 1 wants, without relying on disabled-automation
    semantics (which turned out not to be what actually broke `run --live`;
    see the addendum for the real root cause)."""
    from hassle_cli.run_live import SHADOW_ID_PREFIX, build_shadow_config

    body = {
        "id": "hall_light_on_motion",
        "alias": "Hallway light on motion",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [],
        "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
        "mode": "single",
    }
    shadow = build_shadow_config("automation:hall_light_on_motion", body)
    assert "initial_state" not in shadow
    assert shadow["id"].startswith(SHADOW_ID_PREFIX)
    assert len(shadow["triggers"]) == 1
    trigger = shadow["triggers"][0]
    assert trigger["trigger"] == "event"
    assert trigger["event_type"].startswith("hassle_shadow_never_")
    # The original trigger (state on binary_sensor.hall_motion) must be gone
    # -- that's the whole point: nothing on the real bus can fire this.
    assert "entity_id" not in trigger
    # Conditions/actions/mode are preserved unchanged -- only triggers +
    # id + (absence of) initial_state are shadow-specific.
    assert shadow["conditions"] == body["conditions"]
    assert shadow["actions"] == body["actions"]
    assert shadow["mode"] == body["mode"]


def test_never_fires_event_type_is_unique_per_call() -> None:
    from hassle_cli.run_live import never_fires_event_type

    a = never_fires_event_type()
    b = never_fires_event_type()
    assert a != b
    assert a.startswith("hassle_shadow_never_")
    assert b.startswith("hassle_shadow_never_")


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


class _FakeClock:
    """Deterministic clock/sleep for `stream_trace`'s bounded poll (R8: no
    real wall-clock waits in tests) -- `sleep()` just advances the fake
    clock's `now` rather than actually blocking."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleep_calls = 0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls += 1
        self.now += seconds


def test_stream_trace_polls_until_trace_appears() -> None:
    """CI regression (coordinator finding): `trace/list` racing HA's async
    trace persistence used to make `get_trace_fn` return `{}` once and
    `stream_trace` accepted that immediately, so a live run silently rendered
    no trace at all even though one showed up moments later. A fake
    `get_trace_fn` that returns `{}` for the first few calls then a real
    trace must have its trace polled for and returned, not dropped."""
    from hassle_cli.run_live import stream_trace

    calls: list[int] = []
    real_trace = {"run_id": "abc123", "script_execution": "finished", "trace": {"action/0": [{}]}}

    def flaky_get_trace(shadow_id: str) -> dict[str, object]:
        calls.append(1)
        if len(calls) < 3:
            return {}
        return real_trace

    clock = _FakeClock()
    trace = stream_trace(
        flaky_get_trace,
        "hassle_shadow_abc",
        poll_timeout=5.0,
        poll_interval=0.25,
        sleep_fn=clock.sleep,
        monotonic_fn=clock.monotonic,
    )
    assert trace == real_trace
    assert len(calls) == 3
    assert clock.sleep_calls == 2  # slept between polls 1->2 and 2->3, not after success


def test_stream_trace_gives_up_after_poll_timeout_returns_empty() -> None:
    """A permanently-empty trace (never persisted) must not poll forever --
    bounded by `poll_timeout`, then return `{}` (still the "no trace" signal;
    it's `execute_live_run`'s job to turn that into an explicit warning, see
    `test_run_live_command.py`)."""
    from hassle_cli.run_live import stream_trace

    clock = _FakeClock()
    trace = stream_trace(
        lambda shadow_id: {},
        "hassle_shadow_abc",
        poll_timeout=1.0,
        poll_interval=0.25,
        sleep_fn=clock.sleep,
        monotonic_fn=clock.monotonic,
    )
    assert trace == {}
    # Bounded: stopped polling once the fake clock crossed poll_timeout, not
    # an unbounded/infinite loop.
    assert clock.sleep_calls == 4
    assert clock.now >= 1.0


def test_render_trace_timeline_lists_step_paths() -> None:
    """DESIGN §10.4 point 3: a step-by-step timeline, not a raw dict repr.
    Structural assertion (a step path like `action/0` appears), matching the
    coordinator's ask to assert on the rendered structure, not just the word
    'trace'."""
    from hassle_cli.run_live import render_trace_timeline

    trace = {
        "run_id": "abc123",
        "script_execution": "finished",
        "trace": {
            "trigger": [{}],
            "condition/0": [{}],
            "action/0": [{}],
        },
    }
    rendered = render_trace_timeline(trace)
    assert "action/0" in rendered
    assert "condition/0" in rendered
    assert "trigger" in rendered
    assert "abc123" in rendered


def test_render_trace_timeline_empty_steps_says_so() -> None:
    from hassle_cli.run_live import render_trace_timeline

    rendered = render_trace_timeline(
        {"run_id": "abc123", "script_execution": "finished", "trace": {}}
    )
    assert "no steps recorded" in rendered.lower()


def test_render_trace_timeline_failed_conditions_has_no_action_step() -> None:
    """Round-3 coordinator finding: the live integration test's condition
    gated on an entity left at HA's own default state, so the run always hit
    `failed_conditions` -- the trace WAS real, just never reached `action/0`.
    Pins the rendering shape a `failed_conditions` run actually produces
    (M0.V §7 capture: `trigger` + `condition/0` + `condition/0/entity_id/0`,
    no `action/*` steps at all) so the integration test's phase-1 assertions
    (`"failed_conditions" in output`, `"action/0" not in output`) are
    verified against real rendering behavior, not just asserted blind."""
    from hassle_cli.run_live import render_trace_timeline

    trace = {
        "run_id": "554711d1",
        "script_execution": "failed_conditions",
        "trace": {
            "trigger": [{}],
            "condition/0": [{}],
            "condition/0/entity_id/0": [{}],
        },
    }
    rendered = render_trace_timeline(trace)
    assert "failed_conditions" in rendered
    assert "condition/0" in rendered
    assert "action/0" not in rendered


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
