"""`typings/hassle/cards.pyi` -- the same namespace/partial-stub-package fix
`packages/hassle-core/tests/test_registry_stubs_package_reexport.py`
documents for the top-level `typings/hassle/__init__.pyi`, applied to
`hassle.cards`.

docs/internals/dashboards-design.md §10 originally read "nothing to
generate" for card builders (`hassle.cards` is fully static, already-typed
source). That is true in isolation, but once ANY stub exists under
`typings/hassle/` (`__init__.pyi`, `services.pyi`, `registry/__init__.pyi` --
always written together), pyright treats `typings/hassle` as a COMPLETE stub
package for that dotted path: a real submodule with no stub of its own
(`hassle.cards`) becomes an unresolvable "unknown import symbol" in any
bundle file doing `from hassle import cards as c` -- discovered via
`packages/hassle-dev/tests/test_annotation_truth_pyright_gate.py`'s real
pyright run over the acceptance sample bundle once it gained a dashboard
(DB8). Fix: generate `typings/hassle/cards.pyi`, re-exporting every
`hassle.cards.__all__` name from its true defining module.

Lives in `hassle_cli` (`_generate_cards_reexport_stub`), not
`hassle.registry.stubs` alongside `generate_hassle_reexport_stub`: it must
`import hassle.cards`, which `hassle.registry` may never do
(`packages/hassle-core/tests/test_package_layering.py`: `hassle.cards`
depends on `hassle.registry`, not the reverse).
"""

from __future__ import annotations

import ast
import importlib
import shutil
import subprocess
from pathlib import Path

import pytest

from hassle_cli.cli import _generate_cards_reexport_stub


def test_cards_reexport_stub_contains_every_all_name() -> None:
    import hassle.cards as cards

    stub = _generate_cards_reexport_stub()
    for name in cards.__all__:
        assert f"{name} as {name}" in stub, f"{name!r} missing from the cards re-export stub"


def _parse_import_lines(stub: str) -> list[tuple[str, str]]:
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


def test_cards_reexport_stub_every_import_is_actually_importable_and_correct() -> None:
    """Ground-truth check: for every `from M import N as N` line the
    generator emits, real `importlib.import_module(M)` must succeed AND
    `getattr(mod, N)` must be the identical object `hassle.cards` itself
    exposes."""
    import hassle.cards as cards

    stub = _generate_cards_reexport_stub()
    pairs = _parse_import_lines(stub)
    assert pairs, "expected at least one import line in the generated cards re-export stub"

    emitted_names = {name for _, name in pairs}
    all_names = set(cards.__all__)
    assert emitted_names == all_names, (
        f"emitted names do not match hassle.cards.__all__: "
        f"missing={all_names - emitted_names}, extra={emitted_names - all_names}"
    )

    for module_name, name in pairs:
        mod = importlib.import_module(module_name)
        assert hasattr(mod, name), f"{module_name!r} has no attribute {name!r}"
        assert getattr(mod, name) is getattr(cards, name), (
            f"from {module_name} import {name} -- resolves to a DIFFERENT object than "
            f"hassle.cards.{name}"
        )


def test_cards_reexport_stub_is_deterministic() -> None:
    first = _generate_cards_reexport_stub()
    second = _generate_cards_reexport_stub()
    assert first == second


def test_cards_reexport_stub_is_valid_python() -> None:
    stub = _generate_cards_reexport_stub()
    ast.parse(stub)


def test_cards_reexport_stub_is_ruff_clean(tmp_path: Path) -> None:
    if shutil.which("ruff") is None:
        pytest.skip("ruff not available in this environment")

    stub = _generate_cards_reexport_stub()
    stub_path = tmp_path / "cards.pyi"
    stub_path.write_text(stub, encoding="utf-8")

    fmt = subprocess.run(
        ["ruff", "format", "--check", str(stub_path)], capture_output=True, text=True
    )
    assert fmt.returncode == 0, f"ruff format --check failed:\n{fmt.stdout}\n{fmt.stderr}"
    lint = subprocess.run(["ruff", "check", str(stub_path)], capture_output=True, text=True)
    assert lint.returncode == 0, f"ruff check failed:\n{lint.stdout}\n{lint.stderr}"


def test_cards_reexport_stub_grouped_and_sorted_by_module() -> None:
    stub = _generate_cards_reexport_stub()
    import_lines = [line for line in stub.splitlines() if line.startswith("from hassle.")]
    modules = [line.split(" import ")[0].removeprefix("from ") for line in import_lines]
    assert modules == sorted(modules)
