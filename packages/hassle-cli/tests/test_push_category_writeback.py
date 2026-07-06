"""M11 -- end-to-end (`FakeBackend`): `hassle push` creating a brand-new
automation/script whose source file names a category assigns that category
in HA, and a category-assignment failure surfaces as a warning without
failing the push (I6: never silently dropped).
"""

from __future__ import annotations

from pathlib import Path


def test_push_create_assigns_category_from_source_file(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    backend.seed_category("automation", "cat_hvac", "Automatic HVAC")

    (git_repo / "automations" / "automatic_hvac.py").write_text(
        """
from hassle import automation, service, state, when

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
    assert backend.categories_for("automation", "auto_hvac_1") == {"automation": "cat_hvac"}


def test_push_create_from_misc_file_assigns_no_category(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

    # `hallway.py` (the git_repo fixture's seed automation) lives at the
    # bundle root, not under a category-shaped `automations/<slug>.py` path --
    # push it and confirm no category is ever created.
    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert backend.list_categories("automation") == {}


def test_push_warns_but_succeeds_when_category_assignment_fails(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated entity registry failure")

    backend.assign_category = _boom  # type: ignore[method-assign]

    (git_repo / "automations" / "automatic_hvac.py").write_text(
        """
from hassle import automation, service, state, when

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
    assert "category" in result.output.lower()
    assert "auto_hvac_1" in result.output or "automatic_hvac" in result.output
