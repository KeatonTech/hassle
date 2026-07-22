"""End-to-end (`FakeBackend`): `hassle push` creating a brand-new
automation/script whose source file names a category assigns that category
in HA, and a category-assignment failure surfaces as a warning without
failing the push (no local or UI edit is ever silently dropped).

Category-shaped files are root-level (`<slug>.py`), not under a per-kind
tree (`automations/<slug>.py`) -- these end-to-end tests write directly at
the bundle root. Note that the `git_repo`/`bundle_dir` fixture's OWN seed
file, `hallway.py`, is itself category-shaped under this layout (any
root-level name other than `misc.py` implies a category) --
`test_push_create_from_misc_file_assigns_no_category` below therefore
writes its new object at the actual `misc.py` fallback, not `hallway.py`,
to test the "uncategorized" case honestly.
"""

from __future__ import annotations

from pathlib import Path


def test_push_create_assigns_category_from_source_file(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    backend.seed_category("automation", "cat_hvac", "Automatic HVAC")

    (git_repo / "automatic_hvac.py").write_text(
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

    # The `git_repo` fixture's own seed file, `hallway.py`, is ITSELF
    # category-shaped under the new layout (any root-level name other than
    # `misc.py` implies a category) -- rename it out of the way so it can't
    # also spuriously create a "Hallway" category on this push, isolating
    # this test to the one thing it's actually about: a brand-new object at
    # the shared root-level `misc.py` fallback creates no category at all.
    (git_repo / "hallway.py").rename(git_repo / "misc.py")
    (git_repo / "misc.py").write_text(
        (git_repo / "misc.py").read_text(encoding="utf-8")
        + """

@automation(id="auto_misc_1", alias="Whatever")
def auto_misc_1():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )

    result = cli(["push", "--yes"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    assert "auto_misc_1" in backend.list_remote("automation")
    assert "hall_light_on_motion" in backend.list_remote("automation")
    assert backend.list_categories("automation") == {}


def test_push_warns_but_succeeds_when_category_assignment_fails(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated entity registry failure")

    backend.assign_category = _boom  # type: ignore[method-assign]

    (git_repo / "automatic_hvac.py").write_text(
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
