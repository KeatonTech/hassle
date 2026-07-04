"""``IR -> DSL Python`` decompiler (DESIGN §7.3, MILESTONES M2).

Public surface:

- :func:`decompile_bundle` — a mapping of object key -> :class:`~hassle.ir.models.IRObject`
  to a single, deterministic, ruff-formatted Python source file (DESIGN §7.3:
  "Deterministic codegen from IR: stable ordering, ruff-formatted output").
- :func:`decompile_object` — the single-object source for one IR object (used
  by the splice codemod to build a replacement top-level def).
- :func:`analyze_coverage` — the DSL-coverage metric (MILESTONES M2 test 3):
  walks the decompiled source per object and counts ``raw_*`` node usage.

Every construct the codegen doesn't model falls back to the granular
``raw_trigger``/``raw_condition``/``raw_action`` escape hatches, or (for a whole
object it cannot express as a typed decorator body) ``raw_automation`` — DESIGN
§5.8, I3: no data is ever dropped, only labeled as a coverage gap.
"""

from __future__ import annotations

from hassle.decompiler.codegen import decompile_bundle, decompile_object
from hassle.decompiler.coverage import CoverageException, CoverageReport, analyze_coverage

__all__ = [
    "CoverageException",
    "CoverageReport",
    "analyze_coverage",
    "decompile_bundle",
    "decompile_object",
]
