"""End-to-end (FakeBackend): `hassle pull` places a newly-adopted, UI-categorized
automation/script into `automations/<slug(category)>.py` / `scripts/<slug(category)>.py`
instead of the flat `misc.py` fallback (DESIGN §7.3, owner feedback after first
real pull).

Uses the same `fake_backend`/`toml_writer`/`git_repo` fixtures as the rest of
the M7 CLI suite; the registry snapshot the backend serves (and that pull
writes to `.hassle/registry.json`) is extended in-place with a category
registry + an entity-registry row carrying that category for the seeded
automation/script.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler import compile_bundle


def test_pull_places_categorized_automation_by_category_name(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

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

    placed = git_repo / "automations" / "lighting.py"
    assert placed.is_file(), sorted(p.name for p in (git_repo / "automations").iterdir())
    assert "porch_light_at_dusk" in placed.read_text(encoding="utf-8")

    compiled = compile_bundle(git_repo)
    assert "automation:porch_light_at_dusk" in compiled.objects


def test_pull_places_categorized_script_by_category_name(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

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

    placed = git_repo / "scripts" / "chores.py"
    assert placed.is_file(), sorted(p.name for p in (git_repo / "scripts").iterdir())
    assert "morning_coffee" in placed.read_text(encoding="utf-8")


def test_pull_uncategorized_object_still_lands_in_misc(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

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

    placed = git_repo / "automations" / "misc.py"
    assert placed.is_file()
    assert "no_category_here" in placed.read_text(encoding="utf-8")
