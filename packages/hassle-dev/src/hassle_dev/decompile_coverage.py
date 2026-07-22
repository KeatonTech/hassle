"""`hassle-dev decompile-coverage` — the DSL-coverage CI artifact.

Parses every fixture in ``fixtures/configs/`` to IR, runs the decompiler's coverage
analysis (``hassle.decompiler.analyze_coverage``), and writes a machine-readable
JSON report (per-fixture ``raw_*`` node counts + the overall clean fraction).
Exits non-zero when the corpus is below the >= 90% gate,
so CI fails loudly rather than silently regressing DSL coverage over time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hassle.decompiler import analyze_coverage
from hassle.ir.models import IRObject, parse

_HELPER_DOMAINS = frozenset(
    {
        "input_boolean",
        "input_number",
        "input_select",
        "input_text",
        "input_datetime",
        "input_button",
        "counter",
        "timer",
        "schedule",
    }
)

GATE = 0.90


def _kind_for(stem: str) -> str:
    if stem.startswith("automation"):
        return "automation"
    if stem.startswith("script"):
        return "script"
    if stem.startswith("helper_"):
        rest = stem[len("helper_") :]
        for dom in sorted(_HELPER_DOMAINS, key=len, reverse=True):
            if rest == dom or rest.startswith(dom + "_"):
                return dom
        raise ValueError(f"cannot determine helper domain from fixture name {stem!r}")
    raise ValueError(f"cannot determine object kind from fixture name {stem!r}")


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

    Returns ``(exit_code, report_dict)``: exit code 0 if the clean fraction
    meets the >= 90% gate, else 1.
    """
    objects = load_configs_as_ir(configs_dir)
    report = analyze_coverage(objects)
    report_dict = report.to_json_dict()
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report_dict, indent=2) + "\n", encoding="utf-8")
    exit_code = 0 if report.clean_fraction >= GATE else 1
    return exit_code, report_dict
