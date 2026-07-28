"""Regression: `hassle test` must not put the bundle root on `sys.path`.

`python -m pytest` prepends its working directory to `sys.path`, and
`test_cmd` runs pytest with cwd at the bundle root (docs/internals/cli.md).
A bundle's root-level sources are named after the user's HA **categories**
(`hassle_cli.bundle_ops`, `<slug(category name)>.py`) with no reserved-word
guard -- so a category called "Calendar" produces `calendar.py`, which
shadows the stdlib `calendar` for anything imported afterwards. pytest's own
startup imports it (pydantic -> importlib.metadata -> email -> calendar) and
dies with a circular-import `AttributeError` naming neither Hassle nor the
user's file, before collection even begins.

`hassle test` therefore runs the subprocess with ``PYTHONSAFEPATH=1``, which
suppresses exactly that cwd entry. pytest still imports test modules fine
(it inserts each test file's own directory itself).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_AUTOMATION = """
from hassle import automation, service, state, when

@automation(id="hall_light_on_motion", alias="Hallway light on motion")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
"""

_BUNDLE_TEST = """
def test_motion_turns_on_light(sim):
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway")
"""


@pytest.mark.parametrize("extra_args", [[], ["tests/test_hallway.py"]], ids=["bare", "with-args"])
def test_stdlib_shadowing_root_file_does_not_break_hassle_test(
    tmp_path: Path, cli, extra_args: list[str]
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    assert cli(["init"], cwd=bundle).exit_code == 0

    # What `hassle pull` writes for an HA category named "Calendar".
    (bundle / "calendar.py").write_text(_AUTOMATION.replace("hall_light", "cal_light"), "utf-8")
    (bundle / "hallway.py").write_text(_AUTOMATION, encoding="utf-8")
    (bundle / "tests").mkdir(exist_ok=True)
    (bundle / "tests" / "test_hallway.py").write_text(_BUNDLE_TEST, encoding="utf-8")

    result = cli(["test", *extra_args], cwd=bundle)

    assert result.exit_code == 0, result.output
