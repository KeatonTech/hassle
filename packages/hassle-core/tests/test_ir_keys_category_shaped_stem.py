"""`category_shaped_stem`: a mixed-kind category file lives directly at the
bundle root (``<slug>.py``), not under a per-kind tree
(``automations/<slug>.py`` etc, the RETIRED per-kind-tree shape).

Binding shape ("CATEGORY global... applies to root-level `<slug>.py` files;
`category_shaped_stem` recognizes root-level, stem != `misc`, excluding
`lib/`/`tests/`/`docs/`/dot-dirs"):

- root-level ``<stem>.py``, ``stem != "misc"`` -> category-shaped, stem returned.
- root-level ``misc.py`` -> not category-shaped (the uncategorized fallback).
- anything nested (``lib/x.py``, ``tests/test_x.py``, ``docs/x.py``,
  ``automations/hvac.py`` -- the OLD tree shape, now just an ordinary nested
  path like any other) -> not category-shaped.
- a dotfile-directory path (``.hassle/x.py``) -> not category-shaped (also
  never reached by the compiler's own file walk, but the predicate itself
  must still say no, since `hassle.registry.validate` and
  `category_writeback` call it directly on arbitrary strings).
"""

from __future__ import annotations

from hassle.ir.keys import category_shaped_stem


def test_root_level_file_is_category_shaped() -> None:
    assert category_shaped_stem("hvac.py") == "hvac"


def test_root_level_misc_is_not_category_shaped() -> None:
    assert category_shaped_stem("misc.py") is None


def test_old_tree_shaped_paths_are_no_longer_category_shaped() -> None:
    # The RETIRED work-item-A shape: now just an ordinary nested path.
    assert category_shaped_stem("automations/hvac.py") is None
    assert category_shaped_stem("scripts/chores.py") is None
    assert category_shaped_stem("helpers/hvac.py") is None


def test_nested_paths_are_never_category_shaped() -> None:
    assert category_shaped_stem("lib/constants.py") is None
    assert category_shaped_stem("tests/test_x.py") is None
    assert category_shaped_stem("docs/x.py") is None
    assert category_shaped_stem(".hassle/x.py") is None
    assert category_shaped_stem("sub/x.py") is None


def test_non_py_file_is_never_category_shaped() -> None:
    assert category_shaped_stem("hvac.txt") is None


def test_empty_stem_is_not_category_shaped() -> None:
    assert category_shaped_stem(".py") is None


def test_dashboards_directory_is_not_category_shaped() -> None:
    # docs/internals/dashboards-design.md §7: `dashboards/<module_name>.py` is
    # a per-dashboard default placement, not a category package -- pull never
    # creates a `dashboards/__init__.py` (see the scaffolding tests in
    # `packages/hassle-cli/tests/test_pull_dashboards_placement.py`), so
    # `dashboards/x.py` is just an ordinary nested path like `lib/x.py`: never
    # in `package_roots`, hence never category-shaped. No dashboard-specific
    # logic exists in (or is needed by) this predicate -- pinned here so a
    # future change can't accidentally special-case the kind.
    assert category_shaped_stem("dashboards/climate_control.py") is None
    assert category_shaped_stem("dashboards/climate_control.py", package_roots=frozenset()) is None
