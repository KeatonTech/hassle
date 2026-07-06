"""M13 test 4 — refresh-overwrite consequence: a bundle has a decorator-form
template-helper function; the remote `state=` is edited (simulating a UI
edit) into something the bounded inverter (`hassle.decompiler.template_invert`)
cannot invert; `hassle pull`'s REFRESH splice replaces the function with the
call form via the real `SourceWriter`/LibCST splicer path, FakeBackend-driven,
end-to-end through the real CLI (mirrors
`test_pull_refresh_triggers_decorator_form.py`'s pattern for the trigger-
decorator feature).

Deliberate consequence (documented, MILESTONES M13): cleaner decorator-form
Python is an offer, not a guarantee -- once the remote value falls outside
the bounded grammar, the next pull silently downgrades the local source to
the (always-correct) call form. I6 still holds: nothing is lost, the
config is fully present in the fallback string.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True
    )


_DECORATOR_FORM_BUNDLE = """\
from hassle import expr, template_sensor
from hassle.registry import entities as e


@template_sensor(name="Average Temp", unit_of_measurement="degC")
def average_temp():
    return (expr(e.sensor.a) + expr(e.sensor.b)) / 2
"""


def test_pull_refresh_downgrades_noninvertible_template_helper_to_call_form(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    (git_repo / "sensor_helper.py").write_text(_DECORATOR_FORM_BUNDLE, encoding="utf-8")
    _commit_all(git_repo, "decorator-form template sensor")

    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "pushed")

    before = (git_repo / "sensor_helper.py").read_text(encoding="utf-8")
    assert "@template_sensor(" in before
    assert "def average_temp():" in before
    assert "state=" not in before

    # Drift the remote `state=` to something the bounded inverter cannot
    # invert (a `selectattr`/`list`/`count` filter chain -- structurally
    # outside the grammar `hassle.decompiler.template_invert` models),
    # simulating a UI edit through the HA template-helper options flow.
    remote = backend.list_remote("template_sensor")["average_temp"]
    non_invertible_state = (
        "{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}"
    )
    backend.update(
        "template_sensor", "average_temp", {**remote, "state": non_invertible_state}
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    after = (git_repo / "sensor_helper.py").read_text(encoding="utf-8")

    # The function is GONE -- replaced by the call form (I6: the config is
    # fully present in the fallback, just not as the decorator anymore).
    assert "def average_temp():" not in after, after
    assert "@template_sensor(" not in after, after
    assert "average_temp = template_sensor(" in after, after
    assert "state=" in after, after
    assert non_invertible_state in after, after

    # No data loss (I3/I6): the bundle still compiles and reproduces the
    # drifted remote state exactly.
    from hassle.compiler import compile_bundle

    compiled = compile_bundle(git_repo)
    obj = compiled.objects["template_sensor:average_temp"]
    assert obj.to_ha()["state"] == non_invertible_state


def test_pull_refresh_keeps_decorator_form_when_remote_state_still_inverts(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """Sanity companion: if the remote drift is STILL inside the bounded
    grammar (e.g. just a different, but still-invertible, expression), the
    refreshed source stays in decorator form -- the downgrade in the test
    above is specifically a consequence of falling OUTSIDE the grammar, not
    of drifting at all."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    (git_repo / "sensor_helper.py").write_text(_DECORATOR_FORM_BUNDLE, encoding="utf-8")
    _commit_all(git_repo, "decorator-form template sensor")

    assert cli(["push", "--yes"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "pushed")

    remote = backend.list_remote("template_sensor")["average_temp"]
    still_invertible_state = "{{ states('sensor.a') | float * 3 }}"
    backend.update(
        "template_sensor", "average_temp", {**remote, "state": still_invertible_state}
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    after = (git_repo / "sensor_helper.py").read_text(encoding="utf-8")
    assert "@template_sensor(" in after, after
    assert "def average_temp" in after, after
    assert "state=" not in after, after

    from hassle.compiler import compile_bundle

    compiled = compile_bundle(git_repo)
    obj = compiled.objects["template_sensor:average_temp"]
    assert obj.to_ha()["state"] == still_invertible_state
