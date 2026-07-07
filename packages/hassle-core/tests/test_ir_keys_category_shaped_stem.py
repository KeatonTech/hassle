"""MILESTONES M15 work item B, test 4 (predicate half): `category_shaped_stem`
learns the new root-level, cross-kind shape -- a mixed-kind category file lives
directly at the bundle root (``<slug>.py``), not under a per-kind tree
(``automations/<slug>.py`` etc, the RETIRED shape work item A still used).

Binding shape (MILESTONES M15 "CATEGORY global... now applying to root-level
`<slug>.py` files; `category_shaped_stem` learns the new shape (root-level,
stem != `misc`, excluding `lib/`/`tests/`/`docs/`/dot-dirs)"):

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
