"""Loader for the M1 DSL golden cases under ``fixtures/dsl/``.

Each case is a directory:

    fixtures/dsl/<case>/
        bundle/*.py           the DSL bundle to compile
        expected_ir.json      {object_key: ha_json} the compile must reproduce
        expected_error.json   (error cases) {error_type, contains: [...]}

The compiler emits the plural HA schema (§7.1); ``expected_ir.json`` is stored in
that canonical plural form. Golden files change only via
``hassle-dev goldens --update`` (R3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    # _dsl_cases.py -> tests -> hassle-core -> packages -> repo root
    return Path(__file__).resolve().parents[3]


def dsl_dir() -> Path:
    return repo_root() / "fixtures" / "dsl"


@dataclass(frozen=True)
class DslCase:
    name: str
    bundle_dir: Path
    expected_ir: dict[str, Any] | None
    expected_error: dict[str, Any] | None


def load_cases() -> list[DslCase]:
    root = dsl_dir()
    cases: list[DslCase] = []
    if not root.is_dir():
        return cases
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        bundle_dir = case_dir / "bundle"
        if not bundle_dir.is_dir():
            continue
        ir_path = case_dir / "expected_ir.json"
        err_path = case_dir / "expected_error.json"
        expected_ir = json.loads(ir_path.read_text(encoding="utf-8")) if ir_path.is_file() else None
        expected_error = (
            json.loads(err_path.read_text(encoding="utf-8")) if err_path.is_file() else None
        )
        cases.append(DslCase(case_dir.name, bundle_dir, expected_ir, expected_error))
    return cases


def ir_cases() -> list[DslCase]:
    return [c for c in load_cases() if c.expected_ir is not None]


def error_cases() -> list[DslCase]:
    return [c for c in load_cases() if c.expected_error is not None]
