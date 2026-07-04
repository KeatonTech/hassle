"""DSL golden-pair regeneration for `hassle-dev goldens [--update]` (R3).

Each ``fixtures/dsl/<case>/`` with a ``bundle/`` and an ``expected_ir.json`` is a
golden pair: compiling ``bundle/`` must reproduce ``expected_ir.json`` exactly (the
canonical plural HA schema, §7.1). ``--update`` recompiles and rewrites the goldens;
without it the command *checks* the pairs and reports drift (CI gate).

Error cases (``expected_error.json`` instead of ``expected_ir.json``) are skipped
here — their contract is asserted in the test suite, not regenerated.

Golden files change **only** through this command, and the PR must show the diff
(R3): never hand-edit ``expected_ir.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hassle_core.compiler import compile_bundle


def find_dsl_dir(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (or cwd) looking for ``fixtures/dsl``."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / "fixtures" / "dsl"
        if candidate.is_dir():
            return candidate
    return None


def _compiled_ir(bundle_dir: Path) -> dict[str, Any]:
    result = compile_bundle(bundle_dir)
    return {key: obj.to_ha() for key, obj in result.objects.items()}


def _dump(ir: dict[str, Any]) -> str:
    # Human-readable, stable: 2-space indent, key-sorted, trailing newline.
    return json.dumps(ir, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


@dataclass
class GoldenReport:
    checked: int = 0
    updated: list[str] = field(default_factory=list)
    drifted: list[str] = field(default_factory=list)


def run_goldens(dsl_dir: Path, *, update: bool) -> GoldenReport:
    report = GoldenReport()
    for case_dir in sorted(p for p in dsl_dir.iterdir() if p.is_dir()):
        bundle = case_dir / "bundle"
        expected_path = case_dir / "expected_ir.json"
        if not bundle.is_dir() or not expected_path.is_file():
            continue  # error-only case or non-case dir
        report.checked += 1
        actual = _compiled_ir(bundle)
        actual_text = _dump(actual)
        current_text = expected_path.read_text(encoding="utf-8")
        # Compare structurally (indentation/key-order agnostic) but rewrite in the
        # canonical dumped form on update.
        if json.loads(current_text) != actual:
            if update:
                expected_path.write_text(actual_text, encoding="utf-8")
                report.updated.append(case_dir.name)
            else:
                report.drifted.append(case_dir.name)
    return report
