"""The repo-root README's examples are executed here so they cannot rot.

- Every fenced ``python`` block must compile as a real bundle.
- The opening motion-light example must actually behave as the README
  describes, on the simulator.
- Every ``hassle <subcommand>`` the README mentions (prose, quickstart, and
  the feature table) must exist in the real command tree, including any
  ``--flags`` shown next to it.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import click
import pytest

from hassle.compiler import compile_bundle
from hassle.testing import Simulator
from hassle_cli.cli import main

README = Path(__file__).resolve().parents[3] / "README.md"

_TOKEN = re.compile(r"[a-z][a-z0-9/-]*\Z")


def _fenced_blocks(lang: str) -> list[str]:
    text = README.read_text(encoding="utf-8")
    # dedent: a fence inside a markdown list item indents every line
    return [textwrap.dedent(m.group(1)) for m in re.finditer(rf"```{lang}\n(.*?)```", text, re.S)]


def _python_blocks() -> list[str]:
    blocks = _fenced_blocks("python")
    assert blocks, "README has no ```python blocks -- did the fence language change?"
    return blocks


def test_readme_python_examples_compile(tmp_path: Path) -> None:
    for index, block in enumerate(_python_blocks()):
        bundle = tmp_path / f"bundle{index}"
        bundle.mkdir()
        (bundle / "example.py").write_text(block, encoding="utf-8")
        result = compile_bundle(bundle)
        assert result.objects, f"README python block #{index} compiled to zero objects"


def test_readme_motion_light_example_behaves_as_described(tmp_path: Path) -> None:
    block = next(
        (b for b in _python_blocks() if "hall_light_on_motion" in b),
        None,
    )
    assert block is not None, (
        "README's opening example no longer defines hall_light_on_motion -- "
        "update this test to exercise whatever replaced it"
    )
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "example.py").write_text(block, encoding="utf-8")
    sim = Simulator(compile_bundle(bundle))
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 22:30")  # after sunset, inside the -00:30 offset window
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    sim.advance(minutes=5)
    sim.assert_called("light.turn_off", entity_id="light.hallway")


def _documented_invocations() -> list[str]:
    """Every `hassle ...` invocation the README shows, normalized to the part
    after the program name."""
    text = README.read_text(encoding="utf-8")
    found = [m.group(1).strip() for m in re.finditer(r"`hassle ([^`]+)`", text)]
    for sh_block in _fenced_blocks("sh"):
        for line in sh_block.splitlines():
            bare = line.split("#", 1)[0]
            for part in re.split(r"&&|\|\||;", bare):
                part = part.strip()
                if part.startswith("hassle "):
                    found.append(part[len("hassle ") :].strip())
    assert found, "README mentions no hassle commands at all?"
    return found


@pytest.mark.parametrize("invocation", sorted(set(_documented_invocations())))
def test_readme_documented_commands_exist(invocation: str) -> None:
    command: click.Command = main
    flags: list[str] = []
    for raw in invocation.split():
        token = raw.strip("[]")
        if token.startswith("--"):
            flags.append(token)
            continue
        if not _TOKEN.match(token):
            continue  # a <placeholder> or an argument value, not a command word
        if isinstance(command, click.Group):
            names = token.split("/")
            for name in names:
                assert name in command.commands, (
                    f"README documents `hassle {invocation}` but `{name}` is not a real subcommand"
                )
            if len(names) > 1:
                return  # alternatives like status/push: existence checked above
            command = command.commands[names[0]]
        # otherwise it's a positional value for a leaf command -- ignore
    assert command is not main, f"could not resolve a subcommand in `hassle {invocation}`"
    valid = {opt for param in command.params for opt in param.opts}
    for flag in flags:
        assert flag in valid, (
            f"README shows `hassle {invocation}`, but `{command.name}` has no {flag} option"
        )
