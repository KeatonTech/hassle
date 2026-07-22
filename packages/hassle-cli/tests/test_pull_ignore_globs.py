"""End-to-end (FakeBackend): `hassle.toml`'s `ignore` globs actually keep
`pull`/`plan`/`push` from ever adopting, refreshing, or deleting a matching
object -- DESIGN §8.2 amendment.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _commit(bundle: Path, message: str) -> None:
    # git_repo's fixture tree is committed clean; re-commit whenever test setup
    # (writing hassle.toml, appending an ignore glob) touches a tracked file,
    # so the clean-tree check (DESIGN §8.4) doesn't trip on setup unrelated to
    # what each test actually exercises.
    if (bundle / ".git").is_dir():
        subprocess.run(["git", "add", "-A"], cwd=bundle, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", message], cwd=bundle, check=True, capture_output=True
        )


def _append_ignore(bundle: Path, *globs: str) -> None:
    content = (bundle / "hassle.toml").read_text(encoding="utf-8")
    globs_literal = ", ".join(f'"{g}"' for g in globs)
    content += f"\nignore = [{globs_literal}]\n"
    (bundle / "hassle.toml").write_text(content, encoding="utf-8")
    _commit(bundle, "add ignore glob")


def test_pull_never_adopts_an_ignored_remote_object(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _append_ignore(git_repo, "input_boolean:material_you_*")

    backend.create(
        "input_boolean", {"id": "material_you_primary_color", "name": "Material You Primary Color"}
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "material_you_primary_color" not in result.output

    helpers_misc = git_repo / "helpers" / "misc.py"
    if helpers_misc.is_file():
        assert "material_you_primary_color" not in helpers_misc.read_text(encoding="utf-8")


def test_push_never_deletes_an_ignored_object_absent_locally(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """THE safety test at the CLI layer: an ignored object that exists in HA
    but was never declared locally must survive `hassle push --yes` untouched
    -- a plan that could otherwise read as "local doesn't have it, delete it"
    must never even consider it."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _append_ignore(git_repo, "input_boolean:material_you_*")

    backend.create(
        "input_boolean", {"id": "material_you_primary_color", "name": "Material You Primary Color"}
    )
    hash_before = backend.hash_of("input_boolean", "material_you_primary_color")

    result = cli(["plan"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "material_you_primary_color" not in result.output

    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    # Still there, byte-identical -- push never created/updated/deleted it.
    assert "material_you_primary_color" in backend.list_remote("input_boolean")
    assert backend.hash_of("input_boolean", "material_you_primary_color") == hash_before


def test_pull_warns_on_locally_declared_ignored_object(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    _backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _append_ignore(git_repo, "automation:hall_light_on_motion")

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "hall_light_on_motion" in result.output
    assert "ignor" in result.output.lower()


def test_pull_migrates_manifest_when_glob_added_after_prior_sync(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit(git_repo, "point at fake backend")

    # First sync (no ignore yet): the helper gets adopted normally.
    backend.create(
        "input_boolean", {"id": "material_you_primary_color", "name": "Material You Primary Color"}
    )
    assert cli(["pull"], cwd=git_repo).exit_code == 0

    manifest_path = git_repo / ".hassle" / "manifest.lock"
    assert "material_you_primary_color" in manifest_path.read_text(encoding="utf-8")

    # Now the user adds the ignore glob after the fact.
    _append_ignore(git_repo, "input_boolean:material_you_*")

    result = cli(["pull", "--allow-dirty"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "material_you_primary_color" in result.output
    assert "manifest" in result.output.lower() or "no longer" in result.output.lower()

    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert "material_you_primary_color" not in manifest_text
