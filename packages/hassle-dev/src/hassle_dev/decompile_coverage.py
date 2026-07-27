"""`hassle-dev decompile-coverage` — the DSL-coverage CI artifact.

Parses every fixture in ``fixtures/configs/`` to IR, runs the decompiler's coverage
analysis (``hassle.decompiler.analyze_coverage``), and writes a machine-readable
JSON report (per-fixture ``raw_*`` node counts + the overall clean fraction).
Exits non-zero when the corpus is below the >= 90% gate,
so CI fails loudly rather than silently regressing DSL coverage over time.

``_kind_for`` is shared with ``hassle_dev.corpus`` (the ``corpus-stats``
command) rather than duplicated, so the two never drift on the fixture-name
convention (dashboards-design.md §7's ``dashboard_*`` prefix landed in both at
once via that shared function).

**Dashboards are folded into the gate (docs/internals/dashboards-design.md
§6.2)**: with all 47 built-in card builders merged (workstream DB3) and the
registry-driven decompiler emitter handling the varargs-rows and
single-dict-child container conventions those builders use, the corpus-wide
clean fraction holds >= 90% with dashboards included -- no exclusion needed.
(An earlier, temporary revision of this module excluded ``"dashboard"`` from
the gate while ``CARD_REGISTRY`` was still empty on a pre-DB3 base; see git
history / the superseded note this replaced for that period's rationale.)
Dashboards still get their own reported percentage via ``by_kind`` below,
exactly as §6.2 asks for -- not because the gate needs the split anymore,
but because a per-kind breakdown is useful for spotting a future regression
in one specific kind even while the corpus-wide fraction holds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hassle.decompiler import analyze_coverage
from hassle.ir.models import IRObject, parse
from hassle_dev.corpus import _kind_for

GATE = 0.90


def load_configs_as_ir(configs_dir: Path) -> dict[str, IRObject]:
    objects: dict[str, IRObject] = {}
    for path in sorted(configs_dir.glob("*.json")):
        stem = path.stem
        kind = _kind_for(stem)
        config = json.loads(path.read_text(encoding="utf-8"))
        key_hint = stem if kind == "script" else None
        if kind == "automation" and "id" not in config:
            key_hint = stem
        obj = parse(config, kind=kind, key_hint=key_hint)
        objects[obj.object_key()] = obj
    return objects


def run_decompile_coverage(configs_dir: Path, out_file: Path) -> tuple[int, dict[str, Any]]:
    """Analyze ``configs_dir`` and write the JSON report to ``out_file``.

    Returns ``(exit_code, report_dict)``: exit code 0 if the corpus-wide
    clean fraction (every kind, dashboards included) meets the >= 90% gate,
    else 1. The JSON report additionally carries a `by_kind` breakdown --
    every kind's own clean fraction -- so a future regression in one
    specific kind is visible even while the blended fraction still holds.
    """
    objects = load_configs_as_ir(configs_dir)
    kind_of: dict[str, str] = {key: obj.kind() for key, obj in objects.items()}

    report = analyze_coverage(objects)

    kinds = sorted({kind_of[key] for key in objects})
    by_kind: dict[str, Any] = {}
    for kind in kinds:
        kind_objects = {key: obj for key, obj in objects.items() if kind_of[key] == kind}
        by_kind[kind] = analyze_coverage(kind_objects).to_json_dict()

    report_dict = report.to_json_dict()
    report_dict["by_kind"] = by_kind

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report_dict, indent=2) + "\n", encoding="utf-8")
    exit_code = 0 if report.clean_fraction >= GATE else 1
    return exit_code, report_dict
