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

**Dashboard exclusion from the gate (temporary, tracked, docs/internals/dashboards-design.md
§6.2):** ``CARD_REGISTRY`` (``hassle.compiler.dashboards.card_registry``) is
populated by the card-builder workstreams (DB3); on a base where none of them
have merged yet, every real dashboard fixture's actual cards (``tile``,
``heading``, ``button``, ...) are unmodeled and fall back to ``raw_card`` --
the corpus-wide ``>= 90%`` fraction would otherwise drop from ~95% to ~84%
purely because of a dependency this workstream doesn't own, not because
automation/script coverage regressed. The gate (``clean_fraction`` / exit
code) is therefore computed over every kind EXCEPT ``"dashboard"``, keeping
its established meaning (protect automation/script/helper coverage) intact;
dashboards get their OWN reported percentage instead (``by_kind["dashboard"]``
and the ``full_*`` fields), exactly as §6.2 asks for -- never silently
hidden, just not blocking on a gap this workstream can't close by itself.
Once a card family lands and ``CARD_REGISTRY`` covers the built-in inventory,
folding ``"dashboard"`` back into ``_GATE_KINDS`` (or removing the exclusion
entirely) is the natural follow-up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hassle.decompiler import analyze_coverage
from hassle.ir.models import IRObject, parse
from hassle_dev.corpus import _kind_for

GATE = 0.90

#: Kinds excluded from the pass/fail gate (see module docstring). Reported in
#: full regardless -- `by_kind` and the `full_*` fields never omit them.
_GATE_EXCLUDED_KINDS = frozenset({"dashboard"})


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

    Returns ``(exit_code, report_dict)``: exit code 0 if the GATE-relevant
    clean fraction (every kind except ``_GATE_EXCLUDED_KINDS``, see module
    docstring) meets the >= 90% gate, else 1. The JSON report additionally
    carries the full (every-kind) totals under `full_*` keys and a `by_kind`
    breakdown -- every kind's own clean fraction, dashboards included.
    """
    objects = load_configs_as_ir(configs_dir)
    kind_of: dict[str, str] = {key: obj.kind() for key, obj in objects.items()}

    full_report = analyze_coverage(objects)
    gated_objects = {
        key: obj for key, obj in objects.items() if kind_of[key] not in _GATE_EXCLUDED_KINDS
    }
    gate_report = analyze_coverage(gated_objects)

    kinds = sorted({kind_of[key] for key in objects})
    by_kind: dict[str, Any] = {}
    for kind in kinds:
        kind_objects = {key: obj for key, obj in objects.items() if kind_of[key] == kind}
        by_kind[kind] = analyze_coverage(kind_objects).to_json_dict()

    report_dict = gate_report.to_json_dict()
    report_dict["full_total_objects"] = full_report.total_objects
    report_dict["full_clean_objects"] = full_report.clean_objects
    report_dict["full_clean_fraction"] = full_report.clean_fraction
    report_dict["gate_excluded_kinds"] = sorted(_GATE_EXCLUDED_KINDS)
    report_dict["by_kind"] = by_kind

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report_dict, indent=2) + "\n", encoding="utf-8")
    exit_code = 0 if gate_report.clean_fraction >= GATE else 1
    return exit_code, report_dict
