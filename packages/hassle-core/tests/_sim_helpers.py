"""Shared helpers for the simulator test suite.

``compile_source`` writes a DSL snippet to a throwaway bundle directory and
compiles it through the real compiler pipeline (``compile_bundle``), then
builds a :class:`~hassle.testing.Simulator` from the result -- so every
simulator test exercises the same DSL-to-IR-to-simulator path a real bundle
would. The simulator executes compiled IR, never DSL Python: going through
``compile_bundle`` here is a *test convenience* for authoring concise DSL
snippets, not a violation -- the simulator itself is handed only the
``CompileResult`` it produces, exactly as :func:`test_sim_runs_compiled_ir_only`
proves by skipping this helper entirely and handing the simulator raw HA JSON).

``blueprints=`` writes bundle-local blueprint sources alongside the DSL, under
``<bundle>/blueprints/automation/<path>`` -- the layout
:mod:`hassle.testing.blueprints` resolves a ``use_blueprint`` path against
(mirroring HA's own ``config/blueprints/automation/``).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from hassle.compiler import compile_bundle
from hassle.compiler.bundle import CompileResult
from hassle.testing import Simulator


def write_blueprints(bundle_dir: Path, blueprints: dict[str, str]) -> None:
    """Write ``{use_blueprint path: yaml source}`` under ``<bundle>/blueprints/automation/``."""
    for path, source in blueprints.items():
        target = bundle_dir / "blueprints" / "automation" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source), encoding="utf-8")


def compile_source(
    tmp_path: Path,
    source: str,
    *,
    filename: str = "bundle.py",
    blueprints: dict[str, str] | None = None,
) -> CompileResult:
    """Write ``source`` (dedented) to a fresh bundle dir and compile it."""
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / filename).write_text(textwrap.dedent(source), encoding="utf-8")
    if blueprints:
        write_blueprints(bundle_dir, blueprints)
    return compile_bundle(bundle_dir)


def build_sim(
    tmp_path: Path,
    source: str,
    *,
    filename: str = "bundle.py",
    blueprints: dict[str, str] | None = None,
) -> Simulator:
    """Compile a DSL snippet and hand the result to a fresh :class:`Simulator`."""
    result = compile_source(tmp_path, source, filename=filename, blueprints=blueprints)
    return Simulator(result)
