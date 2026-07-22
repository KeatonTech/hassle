"""Unit tests for `hassle_cli.bundle_ops.category_divergence_warnings`'s
divergence policy, independent of a full pull
(`test_pull_category_divergence.py` covers the CLI-level end-to-end case).

The warning must only fire when the OLD shared path was ITSELF
category-derived (`category_shaped_stem(old_path) is not None`). A user who
hand-grouped a mixed-kind file under a name that doesn't slugify from any
category (e.g. `misc.py`, or an arbitrary hand-picked stem the user chose
with no HA category behind it) and later has ONE of those objects gain a
real HA category must not see a "categories diverged" warning -- there was
never a shared category to diverge from; the object simply moved because it
now has a placement of its own, exactly like ordinary re-categorization.
"""

from __future__ import annotations

from hassle_cli.bundle_ops import category_divergence_warnings


def test_warns_when_a_real_category_shaped_shared_file_splits_across_scopes() -> None:
    # Both objects used to share "hvac.py" (category-shaped: slugifies from a
    # real category name), and their scopes' category names have since
    # diverged in HA, landing them on different new paths.
    previous = {
        "automation:hvac_automation": "hvac.py",
        "script:hvac_script": "hvac.py",
    }
    new = {
        "automation:hvac_automation": "hvac.py",
        "script:hvac_script": "heating.py",
    }
    warnings = category_divergence_warnings(previous, new)
    assert len(warnings) == 1
    assert "hvac.py" in warnings[0]
    assert "heating.py" in warnings[0]


def test_no_warning_when_the_old_shared_file_was_hand_grouped_not_category_shaped() -> None:
    # Regression: the user manually put an automation
    # and a script together in a file that is NOT category-shaped at all
    # (e.g. "misc.py", the shared uncategorized fallback) -- one of them then
    # gains a real HA category and moves out. This is ordinary, expected
    # per-object re-categorization, not a "category names diverged" situation
    # (there was never a shared category for anything to diverge FROM).
    previous = {
        "automation:some_automation": "misc.py",
        "script:some_script": "misc.py",
    }
    new = {
        "automation:some_automation": "misc.py",
        "script:some_script": "hvac.py",  # gained a category, moved out
    }
    warnings = category_divergence_warnings(previous, new)
    assert warnings == []


def test_no_warning_when_the_old_shared_file_is_nested_hence_not_category_shaped() -> None:
    # `category_shaped_stem` also returns `None` for any nested path (the
    # retired per-kind trees, `lib/`, `tests/`, `docs/`, dot-dirs) -- a
    # hand-organized nested file splitting because one object gained a
    # category must not warn either, for the same reason as `misc.py` above.
    previous = {
        "automation:some_automation": "lib/shared.py",
        "script:some_script": "lib/shared.py",
    }
    new = {
        "automation:some_automation": "lib/shared.py",
        "script:some_script": "hvac.py",
    }
    assert category_divergence_warnings(previous, new) == []


def test_no_warning_for_a_same_kind_split_regardless_of_old_path_shape() -> None:
    # Unaffected by the item-4a change: a same-KIND split was never a
    # cross-scope divergence to begin with.
    previous = {
        "automation:a": "hvac.py",
        "automation:b": "hvac.py",
    }
    new = {
        "automation:a": "hvac.py",
        "automation:b": "heating.py",
    }
    assert category_divergence_warnings(previous, new) == []
