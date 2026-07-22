"""`hassle-dev docs [--update]` (mirrors
`hassle-dev goldens`'s check/--update convention -- golden files are
regenerated, never hand-edited).

Builds `docs/DSL.md` (from `fixtures/dsl/`, gated on `hassle.__all__`
coverage) and `docs/COOKBOOK.md` (from `fixtures/cookbook/`, gated on the
cookbook bundle compiling/validating/simulating clean) -- CI's docs gate.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import hassle
from hassle.docs.construct_map import missing_names
from hassle.docs.cookbook import generate_cookbook as _generate_cookbook
from hassle.docs.cookbook import load_recipes
from hassle.docs.dsl_reference import generate_dsl_reference as _generate_dsl_reference


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (or cwd) looking for the repo root (has both
    ``fixtures/dsl`` and ``fixtures/cookbook``)."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        if (directory / "fixtures" / "dsl").is_dir() and (
            directory / "fixtures" / "cookbook"
        ).is_dir():
            return directory
    return None


@dataclass
class DocsReport:
    missing_dsl_names: set[str] = field(default_factory=set)
    cookbook_recipe_count: int = 0
    cookbook_findings: list[str] = field(default_factory=list)
    cookbook_tests_passed: bool = True
    cookbook_test_output: str = ""
    dsl_drifted: bool = False
    cookbook_drifted: bool = False
    dsl_written: bool = False
    cookbook_written: bool = False

    @property
    def ok(self) -> bool:
        return (
            not self.missing_dsl_names
            and not self.cookbook_findings
            and self.cookbook_tests_passed
            and not self.dsl_drifted
            and not self.cookbook_drifted
        )


def _validate_cookbook(cookbook_bundle: Path, registry_path: Path) -> list[str]:
    from hassle.compiler.bundle import compile_bundle
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    result = compile_bundle(cookbook_bundle)
    if not registry_path.is_file():
        return [f"registry snapshot not found at {registry_path}"]
    snapshot = RegistrySnapshot.load(registry_path)
    findings = validate_bundle(result, snapshot)
    return [str(f) for f in findings]


def _run_cookbook_tests(cookbook_bundle: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(cookbook_bundle / "tests")],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0, proc.stdout + proc.stderr


def _static_dir(repo_root: Path) -> Path:
    """The `hassle` package's own bundled copy (`hassle
    init`/`hassle pull` write these into every bundle, but the installed
    package doesn't carry `fixtures/` -- so a checked-in copy ships as
    package data, refreshed by this same `--update` run, same golden-file
    convention as `expected_ir.json`: never hand-edited)."""
    return repo_root / "packages" / "hassle-core" / "src" / "hassle" / "docs" / "_static"


def run_docs(repo_root: Path, *, update: bool) -> DocsReport:
    """Run the docs gate against ``repo_root``.

    ``update``: write `docs/DSL.md`/`docs/COOKBOOK.md` in place (creating
    `docs/` if needed), AND refresh the packaged static copy under
    `hassle/docs/_static/` that `hassle init`/`hassle pull` ship into every
    user bundle. Golden-file convention: both copies are only ever
    written through this path.
    """
    report = DocsReport()

    dsl_fixtures = repo_root / "fixtures" / "dsl"
    cookbook_bundle = repo_root / "fixtures" / "cookbook" / "bundle"
    registry_path = repo_root / "fixtures" / "registry" / "home.json"
    docs_dir = repo_root / "docs"
    static_dir = _static_dir(repo_root)

    # -- test 1: DSL.md coverage -------------------------------------------
    report.missing_dsl_names = missing_names(list(hassle.__all__))
    dsl_text = _generate_dsl_reference(dsl_fixtures)
    dsl_path = docs_dir / "DSL.md"
    if update:
        docs_dir.mkdir(parents=True, exist_ok=True)
        dsl_path.write_text(dsl_text, encoding="utf-8")
        report.dsl_written = True
    elif dsl_path.is_file():
        report.dsl_drifted = dsl_path.read_text(encoding="utf-8") != dsl_text
    else:
        report.dsl_drifted = True

    # -- test 2: cookbook -----------------------------------------------------
    recipes = load_recipes(cookbook_bundle)
    report.cookbook_recipe_count = len(recipes)
    report.cookbook_findings = _validate_cookbook(cookbook_bundle, registry_path)
    passed, output = _run_cookbook_tests(cookbook_bundle)
    report.cookbook_tests_passed = passed
    report.cookbook_test_output = output

    cookbook_text = _generate_cookbook(recipes)
    cookbook_path = docs_dir / "COOKBOOK.md"
    if update:
        docs_dir.mkdir(parents=True, exist_ok=True)
        cookbook_path.write_text(cookbook_text, encoding="utf-8")
        report.cookbook_written = True
    elif cookbook_path.is_file():
        report.cookbook_drifted = cookbook_path.read_text(encoding="utf-8") != cookbook_text
    else:
        report.cookbook_drifted = True

    # -- packaged static copy (shipped into every user bundle) ----------------
    if update and static_dir.parent.is_dir():
        static_dir.mkdir(parents=True, exist_ok=True)
        (static_dir / "DSL.md").write_text(dsl_text, encoding="utf-8")
        (static_dir / "COOKBOOK.md").write_text(cookbook_text, encoding="utf-8")

    return report
