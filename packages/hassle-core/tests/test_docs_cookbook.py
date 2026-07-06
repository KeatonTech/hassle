"""docs/COOKBOOK.md generator (DESIGN §12, MILESTONES M9 deliverable 1):
>= 20 recipes, each = automation (decorator-form triggers) + passing sim
test, sourced from `fixtures/cookbook/` (never hand-written prose that could
drift from the actual recipe bundle).
"""

from __future__ import annotations

from pathlib import Path

from hassle.docs.cookbook import CookbookRecipe, generate_cookbook, load_recipes

REPO_ROOT = Path(__file__).resolve().parents[3]
COOKBOOK_BUNDLE = REPO_ROOT / "fixtures" / "cookbook" / "bundle"


def test_load_recipes_finds_at_least_20() -> None:
    recipes = load_recipes(COOKBOOK_BUNDLE)
    assert len(recipes) >= 20, f"only found {len(recipes)} recipes"


def test_each_recipe_has_a_title_and_source() -> None:
    for recipe in load_recipes(COOKBOOK_BUNDLE):
        assert recipe.title
        assert recipe.source.strip()


def test_each_recipe_compiles_cleanly() -> None:
    """Every recipe file must compile as part of the whole bundle (this is
    also exercised by CI's `hassle-dev docs` gate against the real bundle,
    MILESTONES M9 test 2)."""
    from hassle.compiler import compile_bundle

    result = compile_bundle(COOKBOOK_BUNDLE)
    assert len(result.objects) >= 20


def test_generate_cookbook_contains_every_recipe_title() -> None:
    recipes = load_recipes(COOKBOOK_BUNDLE)
    text = generate_cookbook(recipes)
    for recipe in recipes:
        assert recipe.title in text


def test_generate_cookbook_shows_source_and_is_deterministic() -> None:
    recipes = load_recipes(COOKBOOK_BUNDLE)
    text_a = generate_cookbook(recipes)
    text_b = generate_cookbook(recipes)
    assert text_a == text_b
    assert "```python" in text_a


def test_recipe_is_a_frozen_shape() -> None:
    # CookbookRecipe is a plain data holder -- pin the field names other
    # tooling (the generator, the CI gate) depends on.
    recipe = CookbookRecipe(title="x", filename="x.py", source="from hassle import automation")
    assert recipe.title == "x"
    assert recipe.filename == "x.py"
    assert "automation" in recipe.source
