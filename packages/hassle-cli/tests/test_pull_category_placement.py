"""End-to-end (FakeBackend): `hassle pull` places a newly-adopted, UI-categorized
automation/script/helper into root-level `<slug(category)>.py` instead of the
shared `misc.py` fallback (DESIGN §7.3, owner feedback after first real pull;
MILESTONES M15 work item B: root-level, cross-kind layout replacing the
per-kind-tree shape `automations/<slug>.py` / `scripts/<slug>.py`).

Uses the same `fake_backend`/`toml_writer`/`git_repo` fixtures as the rest of
the M7 CLI suite; the registry snapshot the backend serves (and that pull
writes to `.hassle/registry.json`) is extended in-place with a category
registry + an entity-registry row carrying that category for the seeded
automation/script/helper.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hassle.compiler import compile_bundle


def _commit_toml_change(bundle: Path) -> None:
    # `git_repo` already committed the fixture's placeholder hassle.toml;
    # `toml_writer` overwrites it with the fake-backend seam, which must land
    # as its own commit so the clean-tree check (DESIGN §8.4) doesn't trip on
    # test setup unrelated to what each test actually exercises.
    subprocess.run(["git", "add", "-A"], cwd=bundle, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=bundle,
        check=True,
        capture_output=True,
    )


def test_pull_places_categorized_automation_by_category_name(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_toml_change(git_repo)

    backend.create(
        "automation",
        {
            "id": "porch_light_at_dusk",
            "alias": "Porch light at dusk",
            "triggers": [{"trigger": "sun", "event": "sunset"}],
            "conditions": [],
            "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.porch"}}],
            "mode": "single",
        },
    )

    snapshot = backend.registry_snapshot
    snapshot.categories["automation"] = {"lighting": "Lighting"}
    snapshot.entities.append(
        type(snapshot.entities[0]).model_validate(
            {
                "entity_id": "automation.porch_light_at_dusk",
                "unique_id": "porch_light_at_dusk",
                "domain": "automation",
                "categories": {"automation": "lighting"},
            }
        )
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    placed = git_repo / "lighting.py"
    assert placed.is_file(), sorted(p.name for p in git_repo.iterdir())
    assert "porch_light_at_dusk" in placed.read_text(encoding="utf-8")

    compiled = compile_bundle(git_repo)
    assert "automation:porch_light_at_dusk" in compiled.objects


def test_pull_places_categorized_script_by_category_name(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_toml_change(git_repo)

    backend.create(
        "script",
        {
            "id": "morning_coffee",
            "alias": "Morning coffee",
            "sequence": [{"action": "switch.turn_on", "target": {"entity_id": "switch.kettle"}}],
            "mode": "single",
        },
    )

    snapshot = backend.registry_snapshot
    snapshot.categories["script"] = {"chores": "Chores"}
    snapshot.entities.append(
        type(snapshot.entities[0]).model_validate(
            {
                "entity_id": "script.morning_coffee",
                "unique_id": "morning_coffee",
                "domain": "script",
                "categories": {"script": "chores"},
            }
        )
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    placed = git_repo / "chores.py"
    assert placed.is_file(), sorted(p.name for p in git_repo.iterdir())
    assert "morning_coffee" in placed.read_text(encoding="utf-8")


def test_pull_places_categorized_helper_by_category_name(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """MILESTONES M15 work item B: helpers now get real category-shaped
    placement too, under the shared `"helpers"` scope (§31.2/§31.6) --
    extending the M12-era automation/script-only placement."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_toml_change(git_repo)

    backend.create("input_boolean", {"id": "guest_mode", "name": "Guest Mode"})

    snapshot = backend.registry_snapshot
    snapshot.categories["helpers"] = {"presence": "Presence"}
    snapshot.entities.append(
        type(snapshot.entities[0]).model_validate(
            {
                "entity_id": "input_boolean.guest_mode",
                "unique_id": "guest_mode",
                "domain": "input_boolean",
                "categories": {"helpers": "presence"},
            }
        )
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    placed = git_repo / "presence.py"
    assert placed.is_file(), sorted(p.name for p in git_repo.iterdir())
    assert "guest_mode" in placed.read_text(encoding="utf-8")


def test_pull_uncategorized_object_still_lands_in_misc(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_toml_change(git_repo)

    backend.create(
        "automation",
        {
            "id": "no_category_here",
            "alias": "No category here",
            "triggers": [],
            "conditions": [],
            "actions": [],
            "mode": "single",
        },
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    placed = git_repo / "misc.py"
    assert placed.is_file()
    assert "no_category_here" in placed.read_text(encoding="utf-8")
