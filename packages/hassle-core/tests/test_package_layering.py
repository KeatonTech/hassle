"""Pin the dependency direction between hassle's subpackages.

The package has two conceptual halves — the Python <-> HA-config flows
(`ir`, `compiler`, `decompiler`, plus `registry`/`testing`/`docs` built on
them) and the sync/backend side (`sync`, `backend`). They ship as one
distribution, but the boundary must stay one-directional so the halves never
re-entangle (and so a future distribution split stays possible). This test
walks every module's import statements (both top-level and function-local,
since local imports are the usual cycle workaround) and fails on any edge
that points "upward" against the allowed order.
"""

from __future__ import annotations

import ast
from pathlib import Path

import hassle

SRC = Path(hassle.__file__).resolve().parent

# What each subpackage may import from `hassle.*` (its own subpackage is
# always allowed). `_markers` is a dependency-free leaf usable by anyone.
ALLOWED: dict[str, set[str]] = {
    "_markers": set(),
    "ir": set(),
    "compiler": {"ir"},
    "decompiler": {"ir", "compiler", "registry"},
    "registry": {"ir", "compiler"},
    "backend": {"ir", "registry"},
    "sync": {"ir", "compiler", "decompiler", "registry", "backend"},
    "testing": {"ir", "compiler"},
    "docs": {"ir", "compiler", "registry", "testing"},
    "services": {"ir", "compiler", "registry"},
    # `hassle.cards` is the public card-builder namespace (dashboards-design
    # §5.1) -- a thin re-export of `hassle.compiler.dashboards`, exactly the
    # shape `hassle.services` has.
    "cards": {"ir", "compiler", "registry"},
}


def _subpackage_of(module: str) -> str | None:
    """`hassle.compiler.builders` -> `compiler`; None for non-hassle imports."""
    parts = module.split(".")
    if parts[0] != "hassle" or len(parts) == 1:
        return None
    return parts[1]


def _imported_hassle_subpackages(path: Path) -> set[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                sub = _subpackage_of(alias.name)
                if sub:
                    found.add((sub, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            sub = _subpackage_of(node.module)
            if sub:
                found.add((sub, node.lineno))
            elif node.module == "hassle":
                # `from hassle import X` pulls the top-level DSL surface,
                # which imports the compiler; treat it as a compiler edge.
                found.add(("compiler", node.lineno))
    return found


def test_no_upward_imports_between_subpackages() -> None:
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC)
        owner = rel.parts[0].removesuffix(".py")
        if owner in {"__init__", "py"}:  # hassle/__init__.py re-exports the DSL
            continue
        allowed = ALLOWED.get(owner)
        if allowed is None:
            violations.append(f"{rel}: subpackage {owner!r} missing from ALLOWED map")
            continue
        for sub, lineno in _imported_hassle_subpackages(path):
            if sub == "_markers":
                continue  # dependency-free leaf, importable from anywhere
            if sub != owner and sub not in allowed:
                violations.append(
                    f"{rel}:{lineno}: {owner} imports hassle.{sub}, "
                    f"which is above it in the layering"
                )
    assert not violations, "layering violations:\n" + "\n".join(sorted(violations))
