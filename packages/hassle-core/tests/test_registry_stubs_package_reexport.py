"""Coordinator-flagged hardening (M18 round): a `typings/hassle/` stub
directory containing ONLY submodule stubs (`registry/__init__.pyi`,
`services.pyi`) with no top-level `typings/hassle/__init__.pyi` risks pyright
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

from hassle.registry.stubs import generate_hassle_reexport_stub


def test_reexport_stub_contains_every_all_name() -> None:
    import hassle

    stub = generate_hassle_reexport_stub()
    for name in hassle.__all__:
        assert f" {name} " in f" {stub} " or f" {name},\n" in stub or f"{name} as {name}" in stub, (
            f"{name!r} missing from the hassle re-export stub"
        )


def test_reexport_stub_reexports_from_true_defining_module() -> None:
    import hassle

    stub = generate_hassle_reexport_stub()
    for name in hassle.__all__:
        obj = getattr(hassle, name)
        module = getattr(obj, "__module__", None)
        assert module is not None
        assert f"from {module} import" in stub, (
            f"{name!r} (module {module}) not re-exported from its defining module"
        )


def test_reexport_stub_is_deterministic() -> None:
    first = generate_hassle_reexport_stub()
    second = generate_hassle_reexport_stub()
    assert first == second


def test_reexport_stub_is_valid_python() -> None:
    stub = generate_hassle_reexport_stub()
    ast.parse(stub)


def test_reexport_stub_grouped_and_sorted_by_module() -> None:
    """`from <module> import ...` lines must be sorted by module name (R8
    determinism) so the generated file never depends on `hassle.__all__`'s
    (or a dict's) iteration order."""
    stub = generate_hassle_reexport_stub()
    import_lines = [line for line in stub.splitlines() if line.startswith("from hassle.")]
    modules = [line.split(" import ")[0].removeprefix("from ") for line in import_lines]
    assert modules == sorted(modules)
