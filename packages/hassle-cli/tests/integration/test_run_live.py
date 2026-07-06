"""MILESTONES M7 test 5: `run --live` integration test (Dockerized HA).

Shadow automation created ENABLED with a never-fires event trigger (revised
design, docs/ha-api-notes.md §27 addendum -- NOT `initial_state: off`, which
turned out not to be what actually mattered here), triggered with
`skip_condition: false` by default (HA's own default is `true` -- assert we
override it), trace rendered with correct source lines, the action's real
side effect observed (a counter helper increments -- M0.V pattern, proves the
automation actually RAN, not just that the service call was accepted), shadow
deleted -- also on failure (inject a trace-stream error; assert cleanup).

`test_run_live_creates_shadow_triggers_and_cleans_up` is two-phase (docs/
ha-api-notes.md §27 addendum, round 3): condition unsatisfied (HA's default
`input_boolean` state) -> `failed_conditions` in the trace + counter
unchanged, proving `skip_condition: false` actually gates the run; then
condition satisfied -> `action/0` + counter incremented, proving the action
executes. One test now pins the entire §10.4 semantic surface.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hassle.backend import DirectBackend


def test_cli_runner_invoke_rejects_cwd_kwarg_regression(tmp_path: Path) -> None:
    """CI regression (root cause of the FAILED test_run_live_creates_shadow_
    triggers_and_cleans_up on both HA stable and dev): `click.testing.
    CliRunner.invoke` has never accepted a `cwd` kwarg -- `**extra` is
    forwarded all the way to `click.Context.__init__`, which raises
    `TypeError: Context.__init__() got an unexpected keyword argument 'cwd'`
    before the command body runs at all. This is a click-API misuse in the
    test, not an HA-version behavior difference (the CI logs show the
    identical failure on both `HA stable` and `HA dev` runners) -- this unit
    test reproduces it without touching the network so it runs in the
    ordinary (non-integration) unit job.
    """
    import click
    from click.testing import CliRunner

    @click.command()
    def _noop() -> None:
        click.echo("ran")

    runner = CliRunner()
    result = runner.invoke(_noop, [], cwd=str(tmp_path))
    assert result.exit_code != 0
    assert isinstance(result.exception, TypeError)
    assert "cwd" in str(result.exception)


def _invoke_in_dir(main: object, args: list[str], *, cwd: Path, env: dict[str, str]):
    """`CliRunner.invoke` has no `cwd` support (see the regression test
    above) -- change directory around the call instead, exactly like the
    unit-test suite's `packages/hassle-cli/tests/conftest.py::run_cli`.

    `catch_exceptions` is left at its default (`True`, unlike the unit-test
    `run_cli` helper): `test_run_live_cleans_up_shadow_on_trace_stream_failure`
    relies on an injected `RuntimeError` from inside the command surfacing as
    a non-zero `Result.exit_code` rather than propagating out of `invoke` --
    exactly what a real CLI invocation's top-level exception handling would
    do for an unexpected error."""
    from click.testing import CliRunner

    runner = CliRunner()
    old_cwd = Path.cwd()
    os.chdir(cwd)
    try:
        return runner.invoke(main, args, env=env)
    finally:
        os.chdir(old_cwd)


def _shadow_ids(ha: DirectBackend) -> list[str]:
    return [
        identity
        for identity in ha.list_remote("automation")
        if identity.startswith("hassle_shadow_")
    ]


def _write_bundle(tmp_path: Path, *, counter_entity_id: str) -> Path:
    root = tmp_path / "live-bundle"
    root.mkdir()
    (root / "hassle.toml").write_text("format_version = 1\nmirror = false\n", encoding="utf-8")
    # A flat bundle (DSL sources directly at the bundle root) is still fully
    # supported (docs/ha-api-notes.md §17.9 RESOLVED: the loader also
    # recurses into subdirectories now, but never requires them).
    # The counter.increment action (M0.V pattern, coordinator ask point 3):
    # separates "the automation.trigger service call was accepted" from "the
    # automation's action script actually ran" -- the ambiguity that let the
    # missing-trace bug hide as long as it did. A trace appearing is now
    # corroborated by an independently observable side effect.
    (root / "a.py").write_text(
        f"""
from hassle import automation, only_if, service, state, when

@automation(id="live_test_automation", alias="Live test automation")
def live_test_automation():
    when(state("input_boolean.hassle_flag").to("on"))
    only_if(state("input_boolean.hassle_flag_2").is_("on"))
    service("input_boolean.turn_off", target={{"entity_id": "input_boolean.hassle_flag"}})
    service("counter.increment", target={{"entity_id": "{counter_entity_id}"}})
""",
        encoding="utf-8",
    )
    return root


def _counter_value(ha: DirectBackend, entity_id: str) -> int:
    for state in ha.states():  # type: ignore[attr-defined]
        if state.get("entity_id") == entity_id:
            return int(state["state"])
    raise AssertionError(f"{entity_id} not found in /api/states")


@pytest.mark.integration
def test_run_live_creates_shadow_triggers_and_cleans_up(
    ha: DirectBackend, ha_url_token: tuple[str, str], tmp_path: Path
) -> None:
    """Two-phase (coordinator ask, round 3): the test's own condition-gating
    entity (`input_boolean.hassle_flag_2`, `only_if`'d in `_write_bundle`) is
    now owned by the test instead of left at HA's own default -- round 2's
    green trace (`failed_conditions`) proved `skip_condition: false`
    semantics live, but incidentally, by accident of a fixture that never set
    the gating entity to `"on"`. This test now exercises BOTH branches on
    purpose, pinning the entire DESIGN §10.4 semantic surface in one place:

    Phase 1 (condition unsatisfied -- HA's own default for a freshly created
    `input_boolean` is `"off"`, docs/ha-api-notes.md §4): trigger, assert the
    trace shows `failed_conditions` and the counter did NOT change --
    positive proof conditions are evaluated by default (skip_condition:
    false), not just "the run completed".

    Phase 2 (condition satisfied -- turn the gating entity on): trigger
    again, assert `action/0` in the rendered timeline and the counter DID
    increment -- the "service call accepted" vs "automation ran" distinction
    from round 2, now finally exercised on the branch where the action
    actually executes.
    """
    from hassle_cli.cli import main

    url, token = ha_url_token
    ha.create("input_boolean", {"name": "Hassle Flag", "icon": "mdi:flag"})
    ha.create("input_boolean", {"name": "Hassle Flag 2", "icon": "mdi:flag"})
    counter_id = ha.create("counter", {"name": "Hassle Live Run Counter"})
    counter_entity_id = f"counter.{counter_id}"

    bundle = _write_bundle(tmp_path, counter_entity_id=counter_entity_id)
    run_args = ["run", "a.py::live_test_automation", "--live", "--yes"]
    run_env = {"NO_COLOR": "1", "HASSLE_HA_URL": url, "HASSLE_TOKEN": token}

    # -- Phase 1: condition unsatisfied (input_boolean.hassle_flag_2 is "off",
    # HA's own default -- no service call needed to arrange this). --
    before_phase1 = _counter_value(ha, counter_entity_id)
    result = _invoke_in_dir(main, run_args, cwd=bundle, env=run_env)
    assert result.exit_code == 0, result.output
    assert "failed_conditions" in result.output.lower()
    assert "action/0" not in result.output
    assert "no trace became available" not in result.output.lower()
    # The action never ran -- the counter must NOT have moved. This is the
    # positive proof that Hassle's skip_condition: false default actually
    # gates the run rather than the condition being vacuously satisfied.
    assert _counter_value(ha, counter_entity_id) == before_phase1
    assert _shadow_ids(ha) == []  # cleaned up regardless of branch taken

    # -- Phase 2: satisfy the condition, trigger again. --
    ha.call_service(  # type: ignore[attr-defined]
        "input_boolean", "turn_on", entity_id="input_boolean.hassle_flag_2"
    )
    before_phase2 = _counter_value(ha, counter_entity_id)
    result = _invoke_in_dir(main, run_args, cwd=bundle, env=run_env)
    assert result.exit_code == 0, result.output
    # Structural assertion (coordinator finding, docs/ha-api-notes.md §27):
    # the word "trace" alone doesn't prove a timeline was actually rendered
    # -- a step path from the real automation must appear, and the "trace
    # never became available" warning must NOT (that would mean
    # stream_trace's poll gave up, which is the exact bug being regression-
    # tested here).
    assert "action/0" in result.output
    assert "no trace became available" not in result.output.lower()
    # §27 addendum (coordinator ask point 3): a rendered trace alone doesn't
    # prove the automation's action actually EXECUTED against real HA (that
    # ambiguity -- "service call accepted" vs "automation ran" -- is exactly
    # what let the entity_id-mismatch bug hide) -- an independently
    # observable side effect (M0.V pattern) closes that gap.
    assert _counter_value(ha, counter_entity_id) == before_phase2 + 1
    # Shadow cleaned up on success.
    assert _shadow_ids(ha) == []


@pytest.mark.integration
def test_run_live_cleans_up_shadow_on_trace_stream_failure(
    ha: DirectBackend,
    ha_url_token: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hassle_cli import run_live
    from hassle_cli.cli import main

    url, token = ha_url_token
    ha.create("input_boolean", {"name": "Hassle Flag", "icon": "mdi:flag"})
    ha.create("input_boolean", {"name": "Hassle Flag 2", "icon": "mdi:flag"})
    counter_id = ha.create("counter", {"name": "Hassle Live Run Counter"})

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected trace-stream failure")

    monkeypatch.setattr(run_live, "stream_trace", _boom)

    bundle = _write_bundle(tmp_path, counter_entity_id=f"counter.{counter_id}")
    result = _invoke_in_dir(
        main,
        ["run", "a.py::live_test_automation", "--live", "--yes"],
        cwd=bundle,
        env={"NO_COLOR": "1", "HASSLE_HA_URL": url, "HASSLE_TOKEN": token},
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
