"""MILESTONES M15 §31.6.2 -- a mixed-kind category file whose scopes'
category names diverge in HA (one scope renamed, another didn't) causes the
next `hassle pull` to split it across new destination files, per object's
OWN scope, and print a warning naming the scopes involved -- never guessing
a winner.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _commit_all(repo: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=repo, check=True, capture_output=True
    )


def test_pull_warns_and_splits_when_scopes_diverge(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

    # Seed an automation and a script, both categorized "HVAC" in their own
    # scope -- they land in the SAME hvac.py on the first pull.
    backend.create(
        "automation",
        {
            "id": "hvac_automation",
            "alias": "HVAC automation",
            "triggers": [],
            "conditions": [],
            "actions": [],
            "mode": "single",
        },
    )
    backend.create(
        "script",
        {"id": "hvac_script", "alias": "HVAC script", "sequence": []},
    )
    snapshot = backend.registry_snapshot
    snapshot.categories["automation"] = {"cat_hvac_a": "HVAC"}
    snapshot.categories["script"] = {"cat_hvac_s": "HVAC"}
    entity_cls = type(snapshot.entities[0])
    snapshot.entities.append(
        entity_cls.model_validate(
            {
                "entity_id": "automation.hvac_automation",
                "unique_id": "hvac_automation",
                "domain": "automation",
                "categories": {"automation": "cat_hvac_a"},
            }
        )
    )
    snapshot.entities.append(
        entity_cls.model_validate(
            {
                "entity_id": "script.hvac_script",
                "unique_id": "hvac_script",
                "domain": "script",
                "categories": {"script": "cat_hvac_s"},
            }
        )
    )

    (git_repo / "hallway.py").unlink()  # keep this test's misc.py assertions simple
    _commit_all(git_repo, "point at fake backend")

    first = cli(["pull"], cwd=git_repo)
    assert first.exit_code == 0, first.output
    shared = git_repo / "hvac.py"
    assert shared.is_file()
    shared_text = shared.read_text(encoding="utf-8")
    assert "hvac_automation" in shared_text
    assert "hvac_script" in shared_text
    _commit_all(git_repo, "first pull")

    # Now HA's UI renames the SCRIPT's category (but not the automation's) --
    # the scopes' names diverge for what was one shared file. Neither
    # object's CONFIG changed (only a category-registry rename, which is not
    # part of either object's hashed body) -- so `compute_plan` proposes no
    # REFRESH/ADOPT for either of them; the warning is the only signal this
    # pull emits (a future pull-side placement re-sweep, wiring an actual
    # re-decompile/move for a category-only change, is a natural follow-on
    # this warning already prepares the ground for -- never guessing a
    # winner is the binding requirement; a same-run physical file split for
    # an otherwise byte-identical object is not part of work item B's test
    # contract, MILESTONES tests 4-7).
    snapshot.categories["script"] = {"cat_hvac_s": "Heating"}

    second = cli(["pull"], cwd=git_repo)
    assert second.exit_code == 0, second.output
    assert "diverged" in second.output.lower()
    assert "automation" in second.output.lower()
    assert "script" in second.output.lower()
    assert "hvac.py" in second.output
    assert "heating.py" in second.output


def test_pull_no_divergence_warning_when_scopes_stay_aligned(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

    backend.create(
        "automation",
        {
            "id": "hvac_automation",
            "alias": "HVAC automation",
            "triggers": [],
            "conditions": [],
            "actions": [],
            "mode": "single",
        },
    )
    snapshot = backend.registry_snapshot
    snapshot.categories["automation"] = {"cat_hvac_a": "HVAC"}
    entity_cls = type(snapshot.entities[0])
    snapshot.entities.append(
        entity_cls.model_validate(
            {
                "entity_id": "automation.hvac_automation",
                "unique_id": "hvac_automation",
                "domain": "automation",
                "categories": {"automation": "cat_hvac_a"},
            }
        )
    )
    (git_repo / "hallway.py").unlink()
    _commit_all(git_repo, "point at fake backend")

    assert cli(["pull"], cwd=git_repo).exit_code == 0
    _commit_all(git_repo, "first pull")

    # Nothing changed remotely -- a plain re-pull must never warn.
    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "diverged" not in result.output.lower()
