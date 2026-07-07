"""M12 -- `hassle push` end-to-end (`FakeBackend`): a bundle file's `CATEGORY`
module global supplies the exact display name for a brand-new HA category
push-create has to create (MILESTONES M12).

Covers the milestone's push-side tests:

1. Push-create in a file with `CATEGORY = "Automatic HVAC"` -> created
   category's name is exactly that string.
2. `CATEGORY` that doesn't slugify to the file stem -> a validation Finding
   AND the write-back path ignores the global (falls back to
   `humanize_slug`), with a warning printed -- the object itself still
   applies successfully.
3. No `CATEGORY` -> unchanged M11 `humanize_slug` behavior (already covered
   by `test_push_category_writeback.py`; not duplicated here).
5. An existing category match is reused verbatim and never renamed, even
   when the file also carries a (matching) `CATEGORY` global.

MILESTONES M15 work item B: category-shaped files are root-level now
(`<slug>.py`). The `git_repo` fixture's own seed file, `hallway.py`, is ITSELF
category-shaped under the new layout -- every test below deletes it first so
its own "Hallway" category never pollutes the exact-category assertions here
(this suite is about the ONE file each test writes, not the fixture's seed).
"""

from __future__ import annotations

from pathlib import Path


def _remove_fixture_seed_file(git_repo: Path) -> None:
    """The `git_repo` fixture seeds a root-level `hallway.py`, which is
    itself category-shaped under MILESTONES M15's layout -- remove it so this
    module's exact-category assertions test only the ONE file each test
    writes, not an incidental second "Hallway" category."""
    (git_repo / "hallway.py").unlink()


def test_push_create_uses_category_global_as_exact_display_name(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _remove_fixture_seed_file(git_repo)

    (git_repo / "automatic_hvac.py").write_text(
        """
from hassle import automation, service, state, when

CATEGORY = "Automatic HVAC"


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
""",
        encoding="utf-8",
    )

    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "auto_hvac_1" in backend.list_remote("automation")

    categories = backend.list_categories("automation")
    assert list(categories.values()) == ["Automatic HVAC"]
    category_id = next(iter(categories))
    assert backend.categories_for("automation", "auto_hvac_1") == {"automation": category_id}


def test_push_create_uses_punctuated_category_global_verbatim(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """Regression (CI field failure on PR #7's integration test, round 2):
    the created category's display name must be stored VERBATIM, punctuation
    included, never re-derived from (or reconciled against) its own slug --
    `slugify("Automatic-HVAC!!!")` collapses right back to `automatic_hvac`
    (matching the file stem, so the override is accepted), but the point of
    this test is that the STORED name is the exact punctuated string, not
    some slug-derived approximation of it."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _remove_fixture_seed_file(git_repo)

    (git_repo / "automatic_hvac.py").write_text(
        """
from hassle import automation, service, state, when

CATEGORY = "Automatic-HVAC!!!"


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
""",
        encoding="utf-8",
    )

    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    assignment = backend.categories_for("automation", "auto_hvac_1")
    assert assignment.keys() == {"automation"}
    category_id = assignment["automation"]
    assert backend.list_categories("automation") == {category_id: "Automatic-HVAC!!!"}


def test_push_create_mismatched_category_global_ignored_with_warning(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _remove_fixture_seed_file(git_repo)

    (git_repo / "automatic_hvac.py").write_text(
        """
from hassle import automation, service, state, when

CATEGORY = "Something Else Entirely"


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
""",
        encoding="utf-8",
    )

    result = cli(["push", "--yes"], cwd=git_repo)
    # The object apply itself still succeeds (M11 test-3-style isolation) --
    # a CATEGORY mismatch is never fatal to the push.
    assert result.exit_code == 0, result.output
    assert "auto_hvac_1" in backend.list_remote("automation")

    # The mismatched global is never trusted -- humanize_slug fallback is
    # used instead of the (untrustworthy) declared name.
    categories = backend.list_categories("automation")
    assert list(categories.values()) == ["Automatic Hvac"]

    # A warning was surfaced (I6: never silently ignored).
    assert "category" in result.output.lower()
    assert "automatic_hvac" in result.output.lower() or "auto_hvac_1" in result.output


def test_push_existing_category_match_never_renamed_even_with_category_global(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _remove_fixture_seed_file(git_repo)
    # Slugifies to the SAME slug the source path implies ("automatic_hvac")
    # but is spelled differently from the CATEGORY global below, so a
    # renaming write-back would be observable if it (wrongly) happened.
    backend.seed_category("automation", "cat_hvac", "automatic hvac")

    (git_repo / "automatic_hvac.py").write_text(
        """
from hassle import automation, service, state, when

CATEGORY = "Automatic HVAC"


@automation(id="auto_hvac_1", alias="Keep temp steady")
def auto_hvac_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("climate.turn_on", target={"entity_id": "climate.living_room"})
""",
        encoding="utf-8",
    )

    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    # No new category created, and the existing one's name is untouched --
    # HA's UI owns renames (MILESTONES M12: "an existing HA category is NEVER
    # renamed by push").
    categories = backend.list_categories("automation")
    assert categories == {"cat_hvac": "automatic hvac"}
    assert backend.categories_for("automation", "auto_hvac_1") == {"automation": "cat_hvac"}
