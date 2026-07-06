"""M12 test 4 -- `hassle pull` emits the `CATEGORY = "..."` global when it
CREATES a brand-new category file, is byte-stable across a re-pull, and the
splicer's REFRESH/DROP never duplicate or move an existing `CATEGORY` line
(DESIGN §7.3's placement, MILESTONES M12).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True
    )


def _seed_categorized_automation(backend, category_name: str, slug_key: str) -> None:
    backend.create(
        "automation",
        {
            "id": slug_key,
            "alias": f"{slug_key} automation",
            "triggers": [{"trigger": "sun", "event": "sunset"}],
            "conditions": [],
            "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.porch"}}],
            "mode": "single",
        },
    )
    snapshot = backend.registry_snapshot
    snapshot.categories.setdefault("automation", {})[slug_key] = category_name
    snapshot.entities.append(
        type(snapshot.entities[0]).model_validate(
            {
                "entity_id": f"automation.{slug_key}",
                "unique_id": slug_key,
                "domain": "automation",
                "categories": {"automation": slug_key},
            }
        )
    )


def test_pull_creates_new_category_file_with_category_global(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")

    _seed_categorized_automation(backend, "Automatic HVAC", "hvac")

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    placed = git_repo / "automations" / "automatic_hvac.py"
    assert placed.is_file(), sorted(p.name for p in (git_repo / "automations").iterdir())
    content = placed.read_text(encoding="utf-8")
    assert 'CATEGORY = "Automatic HVAC"' in content, content

    # It still compiles (the global is legal top-level Python).
    from hassle.compiler import compile_bundle

    compiled = compile_bundle(git_repo)
    assert "automation:hvac" in compiled.objects


def test_repull_of_categorized_bundle_is_byte_stable(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")

    _seed_categorized_automation(backend, "Automatic HVAC", "hvac")

    assert cli(["pull"], cwd=git_repo).exit_code == 0
    placed = git_repo / "automations" / "automatic_hvac.py"
    first = placed.read_text(encoding="utf-8")
    _commit_all(git_repo, "first pull")

    # Re-pull with nothing changed remotely: byte-identical file.
    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    second = placed.read_text(encoding="utf-8")
    assert second == first


def test_pull_refresh_preserves_existing_category_global_line(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """The splicer's REFRESH must not duplicate or move a pre-existing
    `CATEGORY` line when the file's object drifts remotely and gets spliced."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")

    _seed_categorized_automation(backend, "Automatic HVAC", "hvac")
    assert cli(["pull"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "first pull")

    before = (git_repo / "automations" / "automatic_hvac.py").read_text(encoding="utf-8")
    assert before.count('CATEGORY = "Automatic HVAC"') == 1

    # Drift the automation remotely (simulate a UI edit) -- triggers REFRESH.
    remote = backend.list_remote("automation")["hvac"]
    backend.update("automation", "hvac", {**remote, "alias": "hvac automation (UI edit)"})

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    after = (git_repo / "automations" / "automatic_hvac.py").read_text(encoding="utf-8")
    # Exactly one CATEGORY line -- never duplicated, never moved to a
    # different position relative to the rest of the (single-object) file.
    assert after.count('CATEGORY = "Automatic HVAC"') == 1, after
    assert "hvac automation (UI edit)" in after, after

    from hassle.compiler import compile_bundle

    compiled = compile_bundle(git_repo)
    assert "automation:hvac" in compiled.objects


def test_pull_drop_preserves_category_global_line_for_remaining_objects(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """DROP removes only the deleted object's statement -- a `CATEGORY` line
    (and any sibling object still in the file) must survive untouched."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_all(git_repo, "point at fake backend")

    _seed_categorized_automation(backend, "Automatic HVAC", "hvac")
    _seed_categorized_automation(backend, "Automatic HVAC", "hvac_2")
    # Force both into the SAME category file (same category name) so the
    # sibling survives the drop of the other.
    assert cli(["pull"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "first pull")

    placed = git_repo / "automations" / "automatic_hvac.py"
    before = placed.read_text(encoding="utf-8")
    assert "hvac_2" in before  # both objects landed in the shared category file
    assert before.count('CATEGORY = "Automatic HVAC"') == 1

    # Delete `hvac_2` remotely (a UI delete) -- triggers DROP on next pull.
    backend.delete("automation", "hvac_2")

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    after = placed.read_text(encoding="utf-8")
    assert "hvac_2" not in after, after
    assert "hvac" in after, after  # the surviving sibling is untouched
    assert after.count('CATEGORY = "Automatic HVAC"') == 1, after

    from hassle.compiler import compile_bundle

    compiled = compile_bundle(git_repo)
    assert "automation:hvac" in compiled.objects
    assert "automation:hvac_2" not in compiled.objects
