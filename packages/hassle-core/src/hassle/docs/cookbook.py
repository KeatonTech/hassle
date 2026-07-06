"""`docs/COOKBOOK.md` generator (DESIGN §12, MILESTONES M9 deliverable 1:
">= 20 recipes, each recipe = automation + passing test, compiled in CI").

Sources every recipe directly from `fixtures/cookbook/bundle/automations/*.py`
(each file's module docstring supplies the title/description; its own source
is shown verbatim) so the doc can never show a recipe that doesn't actually
compile/simulate -- the CI gate (`hassle-dev docs`) compiles the same bundle
these recipes live in and runs its test suite (MILESTONES M9 test 2).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CookbookRecipe:
    """One recipe: a title (from the file's module docstring), the filename
    it lives in, and its full source (shown verbatim in the generated doc)."""

    title: str
    filename: str
    source: str


def _title_from_docstring(docstring: str | None, fallback: str) -> str:
    if not docstring:
        return fallback
    first_line = docstring.strip().splitlines()[0]
    # "Cookbook recipe 1: motion light, night-only." -> "motion light, night-only"
    title = first_line.split(":", 1)[1].strip() if ":" in first_line else first_line.strip()
    return title.rstrip(".")


def load_recipes(bundle_dir: Path) -> list[CookbookRecipe]:
    """Load every recipe under ``bundle_dir/automations/*.py``, sorted by
    filename for deterministic (R8) output."""
    automations_dir = bundle_dir / "automations"
    recipes: list[CookbookRecipe] = []
    for path in sorted(automations_dir.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        docstring = ast.get_docstring(ast.parse(source))
        title = _title_from_docstring(docstring, fallback=path.stem.replace("_", " "))
        recipes.append(CookbookRecipe(title=title, filename=path.name, source=source))
    return recipes


_HEADER = """\
# docs/COOKBOOK.md — Hassle cookbook

**Generated** by `hassle.docs.cookbook.generate_cookbook` from `fixtures/cookbook/` —
every recipe below is a real automation (or script) that compiles, validates against
the fixture registry, and has a passing simulator test in CI (MILESTONES M9 test 2).
Do not hand-edit; regenerate via `hassle-dev docs --update`.

Copy a recipe's source into your bundle, then adjust the entity ids to match your
own `.hassle/registry.json`.

"""


def generate_cookbook(recipes: list[CookbookRecipe]) -> str:
    """Generate the full contents of `docs/COOKBOOK.md` from ``recipes``
    (use :func:`load_recipes` to build that list from a bundle directory).

    Deterministic (R8): same recipe list -> byte-identical output.
    """
    parts = [_HEADER]
    for i, recipe in enumerate(recipes, start=1):
        parts.append(f"## {i}. {recipe.title}\n")
        parts.append(f"`fixtures/cookbook/bundle/automations/{recipe.filename}`\n")
        parts.append(f"```python\n{recipe.source.strip()}\n```\n")
    return "\n".join(parts)
