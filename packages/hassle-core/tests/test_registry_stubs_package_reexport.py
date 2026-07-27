"""A `typings/hassle/` stub directory containing ONLY submodule stubs
(`registry/__init__.pyi`, `services.pyi`) with no top-level
`typings/hassle/__init__.pyi` risks pyright
treating `hassle` as a namespace/partial stub package for that dotted path --
which can make the REAL package's own top-level surface (`hassle.__all__`:
`automation`, `service`, `state`, `Mode`, ...) resolve as undefined in a
bundle file that does `from hassle import *`.

Fix: always generate (and write) a `typings/hassle/__init__.pyi` alongside
the registry/services stubs, re-exporting every `hassle.__all__` name from
its true defining module (grouped/sorted deterministically), so pyright
falls back to the real inline package for anything the stub doesn't shadow,
AND the stub package itself carries the full top-level surface regardless.
"""

from __future__ import annotations

import ast
import importlib
import shutil
import subprocess
from pathlib import Path

import pytest

from hassle.registry.stubs import generate_hassle_reexport_stub, generate_reexport_stub_lines


def test_reexport_stub_contains_every_all_name() -> None:
    import hassle

    stub = generate_hassle_reexport_stub()
    for name in hassle.__all__:
        assert f" {name} " in f" {stub} " or f" {name},\n" in stub or f"{name} as {name}" in stub, (
            f"{name!r} missing from the hassle re-export stub"
        )


def _parse_import_lines(stub: str) -> list[tuple[str, str]]:
    """Every ``(module, name)`` pair the generated stub's ``from <module>
    import <name> as <name>`` lines actually emit -- parsed with the real
    ``ast`` module (not a substring/regex guess) so this is robust to the
    multi-line-wrapped form long import lists use."""
    tree = ast.parse(stub)
    pairs: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module != "__future__"
        ):
            for alias in node.names:
                bound_name = alias.asname or alias.name
                pairs.append((node.module, bound_name))
    return pairs


def test_reexport_stub_every_import_is_actually_importable_and_correct() -> None:
    """GROUND-TRUTH check: an earlier version of this test derived its
    expectation the SAME WAY the generator computes it, so it could never
    fail for a generator bug -- vacuous by construction.

    For every ``from M import N as N`` line the generator actually emits,
    real `importlib.import_module(M)` must succeed AND `getattr(mod, N)`
    must be the identical object `hassle.__all__` itself exposes -- this is
    independent of whatever module-resolution algorithm the generator uses
    internally, so it catches the exact `__module__`-vs-true-binding-module
    bug: `E_`/`PI`/`TAU` are `TemplateExpr` INSTANCES built in
    `hassle.compiler.math_expr`, but `__module__` reports the CLASS's module,
    `hassle.compiler.templates`, which does not define these names at all.
    """
    import hassle

    stub = generate_hassle_reexport_stub()
    pairs = _parse_import_lines(stub)
    assert pairs, "expected at least one import line in the generated re-export stub"

    emitted_names = {name for _, name in pairs}
    all_names = set(hassle.__all__)
    assert emitted_names == all_names, (
        f"emitted names do not match hassle.__all__: "
        f"missing={all_names - emitted_names}, extra={emitted_names - all_names}"
    )

    for module_name, name in pairs:
        mod = importlib.import_module(module_name)  # raises ImportError if wrong/unimportable
        assert hasattr(mod, name), f"{module_name!r} has no attribute {name!r}"
        assert getattr(mod, name) is getattr(hassle, name), (
            f"from {module_name} import {name} -- resolves to a DIFFERENT object than hassle.{name}"
        )


def test_reexport_stub_is_deterministic() -> None:
    first = generate_hassle_reexport_stub()
    second = generate_hassle_reexport_stub()
    assert first == second


def test_reexport_stub_is_valid_python() -> None:
    stub = generate_hassle_reexport_stub()
    ast.parse(stub)


def test_reexport_stub_is_ruff_clean(tmp_path: Path) -> None:
    """Real, checked-in-adjacent Python (unlike a golden fixture) -- a user's
    own `ruff check`/`ruff format` run over their bundle's `typings/` tree
    must never want to reorder or reformat this generated file."""
    if shutil.which("ruff") is None:
        pytest.skip("ruff not available in this environment")

    stub = generate_hassle_reexport_stub()
    stub_path = tmp_path / "__init__.pyi"
    stub_path.write_text(stub, encoding="utf-8")

    fmt = subprocess.run(
        ["ruff", "format", "--check", str(stub_path)], capture_output=True, text=True
    )
    assert fmt.returncode == 0, f"ruff format --check failed:\n{fmt.stdout}\n{fmt.stderr}"
    lint = subprocess.run(["ruff", "check", str(stub_path)], capture_output=True, text=True)
    assert lint.returncode == 0, f"ruff check failed:\n{lint.stdout}\n{lint.stderr}"


def test_reexport_stub_grouped_and_sorted_by_module() -> None:
    """`from <module> import ...` lines must be sorted by module name
    (byte-stable/deterministic output) so the generated file never depends on
    `hassle.__all__`'s (or a dict's) iteration order."""
    stub = generate_hassle_reexport_stub()
    import_lines = [line for line in stub.splitlines() if line.startswith("from hassle.")]
    modules = [line.split(" import ")[0].removeprefix("from ") for line in import_lines]
    assert modules == sorted(modules)


# -- generate_reexport_stub_lines: the generic, reusable helper --------------
#
# `hassle_cli._generate_cards_reexport_stub` (packages/hassle-cli/tests/
# test_cards_reexport_stub.py) is this helper's other real caller -- it needs
# `import hassle.cards`, which `hassle.registry` may never do
# (test_package_layering.py: `cards` depends on `registry`, not the reverse),
# so it lives in `hassle_cli` instead and calls this generic, module-agnostic
# function. Covered here directly (module-agnostic, no `hassle.cards` import
# needed) so `hassle-core`'s own test suite still exercises it without that
# cross-package dependency.


def test_reexport_stub_lines_produces_the_same_import_lines_as_hassle_reexport_stub() -> None:
    """Ground truth: calling the generic helper with EXACTLY the same inputs
    `generate_hassle_reexport_stub` uses must reproduce that function's
    import-line block byte-for-byte -- proof this is really the same
    module-resolution logic, not a parallel reimplementation that could
    drift. (`generate_hassle_reexport_stub` additionally appends a trailing
    `__all__ = [...]` list the generic helper deliberately does not -- that
    list is specific to the top-level stub re-declaring `hassle.__all__` for
    `from hassle import *`, not something every re-export stub needs.)"""
    import hassle

    doc_lines = [
        '"""Generated by `hassle stubs` from `hassle.__all__`. Do not edit by hand.',
        "",
        "Re-exports every frozen DSL name from its true defining module so pyright",
        "never treats `hassle` as a namespace/partial stub package once a submodule",
        'stub (`hassle/registry/__init__.pyi`, `hassle/services.pyi`) exists."""',
    ]
    generic = generate_reexport_stub_lines(hassle, list(hassle.__all__), doc_lines=doc_lines)
    full = generate_hassle_reexport_stub()
    assert full.startswith(generic.rstrip("\n"))


def test_reexport_stub_lines_is_deterministic_and_valid_python() -> None:
    import hassle

    a = generate_reexport_stub_lines(hassle, list(hassle.__all__), doc_lines=['"""doc."""'])
    b = generate_reexport_stub_lines(hassle, list(hassle.__all__), doc_lines=['"""doc."""'])
    assert a == b
    ast.parse(a)
