"""Shared helpers for the M4 simulator test spec.

``compile_source`` writes a DSL snippet to a throwaway bundle directory and
compiles it through the real M1 pipeline (``compile_bundle``), then builds a
:class:`~hassle.testing.Simulator` from the result -- so every simulator test
exercises the same DSL-to-IR-to-simulator path a real bundle would (I5: the
simulator consumes compiled IR, never DSL Python directly; going through
``compile_bundle`` here is a *test convenience* for authoring concise DSL
snippets, not a violation -- the simulator itself is handed only the
``CompileResult`` it produces, exactly as :func:`test_sim_runs_compiled_ir_only`
proves by skipping this helper entirely and handing the simulator raw HA JSON).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from hassle.compiler import compile_bundle
from hassle.compiler.bundle import CompileResult
from hassle.testing import Simulator


def compile_source(tmp_path: Path, source: str, *, filename: str = "bundle.py") -> CompileResult:
    """Write ``source`` (dedented) to a fresh bundle dir and compile it."""
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir(exist_ok=True)
    (bundle_dir / filename).write_text(textwrap.dedent(source), encoding="utf-8")
    return compile_bundle(bundle_dir)


def build_sim(tmp_path: Path, source: str, *, filename: str = "bundle.py") -> Simulator:
    """Compile a DSL snippet and hand the result to a fresh :class:`Simulator`."""
    result = compile_source(tmp_path, source, filename=filename)
    return Simulator(result)
