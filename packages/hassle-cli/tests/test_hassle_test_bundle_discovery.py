"""Regression: `hassle test` inside a bundle scaffolded by `hassle init`
(docs/internals/cli.md, "`hassle test`: bundle discovery must not go through
pytest's rootdir").

The `sim` fixture used to resolve the bundle as "one level above pytest's
rootdir", and `hassle test` set cwd to `<bundle>/tests` to make that land on
the bundle root. pytest doesn't take rootdir from cwd -- it walks up for a
config anchor, and `hassle init` writes a `pyproject.toml` at the bundle
root, which pytest 9 selects. rootdir was the bundle root, so `.parent` was
the bundle's PARENT, and the fixture compiled -- i.e. IMPORTED AND EXECUTED --
every `.py` file sitting next to the bundle.

These tests scaffold exactly that layout (a bundle with a side-effecting
script as its sibling) and assert the sibling is never executed, for both
`hassle test` invocation shapes (bare, and with pytest args -- which run from
different working directories, see `test_cmd`).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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


def _scaffold(tmp_path: Path, cli, *, test_body: str = _BUNDLE_TEST) -> tuple[Path, Path]:
    """An `init`-scaffolded bundle with a side-effecting script as its SIBLING.

    Returns `(bundle, receipt)`; `receipt` is the file the sibling script
    writes at import time -- its existence proves something imported code from
    outside the bundle.
    """
    workspace = tmp_path / "workspace"
    bundle = workspace / "bundle"
    bundle.mkdir(parents=True)

    receipt = workspace / "executed.txt"
    # A perfectly ordinary script that happens to live NEXT TO the bundle --
    # not part of it, and never something `hassle test` may import.
    (workspace / "unrelated_script.py").write_text(
        f"from pathlib import Path\n\nPath({str(receipt)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    assert cli(["init"], cwd=bundle).exit_code == 0
    assert (bundle / "pyproject.toml").is_file()  # the rootdir anchor that caused the bug
    (bundle / "hallway.py").write_text(_AUTOMATION, encoding="utf-8")
    (bundle / "tests").mkdir(exist_ok=True)
    (bundle / "tests" / "test_hallway.py").write_text(test_body, encoding="utf-8")
    return bundle, receipt


def test_hassle_test_never_executes_python_outside_the_bundle(tmp_path: Path, cli) -> None:
    bundle, receipt = _scaffold(tmp_path, cli)

    result = cli(["test"], cwd=bundle)

    assert result.exit_code == 0, result.output
    assert not receipt.exists(), "hassle test imported a .py file from outside the bundle"


def test_hassle_test_with_pytest_args_resolves_the_same_bundle(tmp_path: Path, cli) -> None:
    """`hassle test tests/test_hallway.py` runs with cwd at the bundle root
    (see `test_cmd`), not `tests/`. Bundle discovery starts from the test FILE,
    so both invocation shapes agree."""
    bundle, receipt = _scaffold(tmp_path, cli)

    result = cli(["test", "tests/test_hallway.py"], cwd=bundle)

    assert result.exit_code == 0, result.output
    assert not receipt.exists(), "hassle test imported a .py file from outside the bundle"


def test_hassle_bundle_marker_emits_no_unknown_mark_warning(tmp_path: Path, cli) -> None:
    """The marker is the documented override, so the plugin must register it --
    a scaffolded bundle's pyproject.toml declares no markers of its own, so an
    unregistered marker there means `PytestUnknownMarkWarning` in the user's
    face."""
    bundle, _ = _scaffold(tmp_path, cli)
    (bundle / "tests" / "test_hallway.py").write_text(
        f"import pytest\n\npytestmark = pytest.mark.hassle_bundle({str(bundle)!r})\n"
        + _BUNDLE_TEST,
        encoding="utf-8",
    )

    result = cli(["test", "--", "-W", "error::pytest.PytestUnknownMarkWarning"], cwd=bundle)

    assert result.exit_code == 0, result.output


def test_sim_outside_any_bundle_fails_with_a_clear_error(tmp_path: Path) -> None:
    """Plain `pytest` (DESIGN §10.2: "plain pytest works too") on a `sim` test
    with no `hassle.toml` above it: a failure naming the file and the fix,
    never a silent compile of whatever directory happened to be guessed."""
    stray = tmp_path / "stray"
    (stray / "tests").mkdir(parents=True)
    (stray / "pyproject.toml").write_text(
        '[project]\nname = "stray"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    (stray / "tests" / "test_stray.py").write_text(_BUNDLE_TEST, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=stray / "tests",
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "hassle.toml" in result.stdout
    assert "test_stray.py" in result.stdout
    assert "Fix:" in result.stdout
