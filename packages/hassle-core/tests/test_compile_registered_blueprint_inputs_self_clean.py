"""Regression: the dead-declaration sweep must be self-cleaning too.

The sibling of `test_compile_registered_pending_self_clean.py`, and the same
seam: `compile_bundle` clears the blueprint-input declaration list at the START
of every compile, so the CLI path is safe, but a DIRECT `compile_registered`
caller has no such protection. Without the sweep clearing the list on its way
out, every module-scope declaration from a previous compile stays behind — and
because a blueprint-less direct compile reaches none of them, ALL of them get
reported as `blueprint-input-never-used`, against a file the second caller's
bundle does not even contain.

That is a false positive with no way for the caller to see it coming, so the
sweep cleans up after itself (in a `finally`) rather than asking every future
direct caller to remember. No teardown between the two compiles here, on
purpose: that is the thing being pinned.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler.blueprint_dsl import _DECLARATIONS  # pyright: ignore[reportPrivateUsage]
from hassle.compiler.bundle import compile_bundle, compile_registered

DEAD = """\
from hassle import blueprint, bp_input, service, state, when

ORPHAN = bp_input("orphan", selector={"entity": {"domain": "light"}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state("binary_sensor.x").to("on"))
    service("light.turn_on", target={"entity_id": "light.hall"})
"""


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    root.mkdir(parents=True, exist_ok=True)
    (root / "shared.py").write_text(DEAD, encoding="utf-8")
    return root


def test_a_direct_compile_after_a_bundle_compile_reports_no_ghost_declarations(
    tmp_path: Path,
) -> None:
    first = compile_bundle(_bundle(tmp_path))
    assert [ref.input_name for ref in first.unused_blueprint_inputs] == ["orphan"]

    # Same process, NO manual reset in between (the point of the regression).
    second = compile_registered([])
    assert second.unused_blueprint_inputs == []


def test_the_sweep_clears_the_declaration_list_on_the_way_out(tmp_path: Path) -> None:
    compile_bundle(_bundle(tmp_path))
    assert _DECLARATIONS == []
