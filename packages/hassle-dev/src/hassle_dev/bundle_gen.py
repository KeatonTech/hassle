"""`hassle-dev acceptance-bundle --out DIR` (MILESTONES M9 test 3, real gate):
generate the "sample house" bundle that `hassle_dev.acceptance.emit_tasks`'s
10 task prompts are written against.

## Why this exists

MILESTONES M9 test 3 requires giving a fresh model session "the pulled sample
bundle + AGENTS.md only" plus the 10 prompts from `hassle-dev acceptance-tasks`.
Those prompts presuppose a specific, coherent "sample house" (a hallway motion
automation controlling `light.hallway`, an `input_boolean.guest_mode` helper, a
deliberately failing test, a deliberate validation-finding target, ...) -- see
`hassle_dev.acceptance`'s module docstring for the full list. Before this
module, no bundle satisfying those presuppositions existed anywhere in the
repo (`fixtures/sim/hallway_bundle` is a bare `hallway.py`, with no
`AGENTS.md`/`docs/`/`hassle.toml`/`tests/` -- not a bundle a real user, or a
fresh model session, would ever be handed).

## How it's built: the REAL pull pipeline, not hand-written files

`generate_sample_bundle` seeds a `FakeBackend` (`hassle.backend.fake`) with
raw HA-shaped config dicts for every object the sample house needs, then
drives the bundle into existence by invoking `hassle_cli.cli.main`'s real
`pull` subcommand in-process (via `click.testing.CliRunner`, same seam
`packages/hassle-cli/tests/conftest.py`'s `fake_backend`/`toml_writer`
fixtures use) -- the exact code path `hassle pull` runs against a real HA,
with only the transport swapped (`hassle_cli.backend_factory`'s `fake://`
seam). This produces `AGENTS.md`, `docs/DSL.md`, `docs/COOKBOOK.md`,
`hassle.toml`, `.hassle/registry.json`, `.hassle/manifest.lock`, and
canonical **decompiled** DSL sources for every seeded object -- nothing here
is a hand-written bundle file except the seeded `tests/` (see below), which
survive because `hassle pull` only ever touches `automations/`/`scripts/`/
`helpers/`-kind objects (`hassle.ir.keys.OBJECT_KINDS`) -- it has no notion of
a `tests/` directory at all, so anything placed there before the pull simply
sits untouched through it (the "tests survive sync" property this generator
relies on, rather than reimplements).

## Scoring nuance: `diagnose_failing_test` starts red BY DESIGN

`hassle_dev.acceptance.score_task` calls `hassle validate && hassle test`
against a session's resulting bundle and requires BOTH to exit 0. But
`diagnose_failing_test`'s entire premise is "one of the tests in `tests/` is
failing" -- so the bundle handed to every one of the 10 tasks (all 10 start
from independent copies of the SAME generated bundle, per
`hassle_dev.acceptance`'s module docstring) necessarily contains that failing
test too. If it were a plain failing `def test_...`, `hassle test` would
never exit 0 for the other 9 tasks either, regardless of how well a session
solved ITS task -- collapsing the whole harness to 0/10 by construction.

The fix: the seeded bug's test is marked `@pytest.mark.xfail(strict=True)`
(see `tests/test_seeded_bug.py` written by `_write_seed_tests`). Plain
`pytest`/`hassle test` treats a non-strict-violating `xfail` as a PASS (exit
0) -- so the other 9 tasks' `score_task` floor is genuinely "did this
session's own edit leave the bundle green", untouched by the pre-existing,
out-of-scope bug. `diagnose_failing_test` itself requires the session to fix
the underlying automation logic (not the test) so the test's assertion is
true; `strict=True` means if the session does that WITHOUT also removing the
now-inapplicable `xfail` marker, pytest reports it as `XPASS` and FAILS the
run anyway -- so a session can't half-fix this task and still score green; it
must actually clean up the marker once the bug is fixed, exactly like a human
would. This is standard, honest pytest usage, not a scoring workaround
specific to this harness.

## Scoring nuance: `fix_validation_finding` is a task the session performs
entirely within one session, not a pre-existing finding

Re-reading the prompt: "Introduce a typo ... run `hassle validate` ... then
fix the typo". The session itself both creates and resolves the finding --
there is nothing for this generator to pre-seed; the bundle just needs to
otherwise validate clean so the session's self-inflicted typo is the only
finding it will see. No special seeding needed beyond a normal clean bundle.

## Determinism (R8)

`generate_sample_bundle(out_dir)` is byte-for-byte stable across runs given
the same `out_dir` basename: no wall-clock, no randomness anywhere in the
seed data itself. The one wall-clock touchpoint in the pipeline is
`hassle pull`'s own `manifest.lock` `synced_at` field (`hassle_cli.manifest_io
.now_iso()`, explicitly the CLI-layer's one documented R8 exception -- core
logic never calls it). This generator normalizes that one field to a fixed
sentinel timestamp after the real pull completes (a post-processing
normalization of the generator's OWN output, not a hand-edit of "a bundle" in
the R3/golden-files sense) so the emitted tree is byte-identical seed-to-seed;
`__pycache__/` directories the loader's import machinery leaves behind are
also removed for the same reason (they are already `.gitignore`d,
docs/`hassle_cli.git_support.GITIGNORE_CONTENT`, and are not part of what a
git clone of a real pulled bundle would ever contain).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

_SENTINEL_SYNCED_AT = "1970-01-01T00:00:00Z"

# The registry snapshot every seeded object is drawn against: the project's
# existing canonical "home" fixture (`fixtures/registry/home.json`), already
# used across M0-M9 as the shared realistic-house registry -- reused here
# rather than inventing a parallel one, so `light.hallway`, `light.living_room`,
# `binary_sensor.hall_motion`, `input_boolean.guest_mode`, `sun.sun`, and the
# `notify`/`light` services below are all real, already-verified entries, not
# fixture-specific inventions.
_REPO_ROOT_MARKERS = ("fixtures", "packages", "DESIGN.md")


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (or cwd) looking for the repo root."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        if all((directory / marker).exists() for marker in _REPO_ROOT_MARKERS):
            return directory
    return None


def _registry_snapshot_json(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "fixtures" / "registry" / "home.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Seed data -- one function per object, in raw HA-normalized (plural) shape,
# the exact input `FakeBackend.create` expects (see `hassle.backend.fake`
# module docstring: normalization on write mirrors real HA's POST-then-GET
# round-trip). Every entity id referenced below exists in `home.json` (see
# `_registry_snapshot_json`) -- nothing here is invented.
# ---------------------------------------------------------------------------


def _hallway_motion_automation() -> dict[str, Any]:
    """The hallway motion automation `emit_tasks`'s prompts are written
    against (`entity_swap`, `add_helper_and_use_it`, `add_condition`,
    `write_sim_test`, `explain_plan_diff`).

    Deliberately has NO `input_boolean.guest_mode` condition yet -- task 3
    (`add_condition`)'s prompt is "currently has no guest-mode check", so the
    helper is declared (see `_guest_mode_helper`) but not yet wired in; the
    session is expected to add that condition itself. The `sun` gate (night
    only) is real DSL machinery (DESIGN §5.4/§10.1, the `fixtures/sim/
    hallway_bundle` precedent this mirrors) so `write_sim_test`'s "motion
    during the day does NOT turn the light on" has a real mechanism to test.
    """
    return {
        "id": "hall_light_on_motion",
        "alias": "Hallway: light on motion",
        "mode": "restart",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.hall_motion", "to": "on"}],
        "conditions": [{"condition": "sun", "after": "sunset", "after_offset": "-00:30:00"}],
        "actions": [
            {
                "action": "light.turn_on",
                "target": {"entity_id": "light.hallway"},
                "data": {"brightness_pct": 60},
            },
            {"delay": {"minutes": 5}},
            {"action": "light.turn_off", "target": {"entity_id": "light.hallway"}},
        ],
    }


def _front_door_notify_automation() -> dict[str, Any]:
    """First of two notify-sending automations (`refactor_into_macro`'s
    presupposition: "more than one automation sends the same kind of
    notification" so the extract-a-macro task has real duplication to act
    on, rather than falling back to its own "add a second one first" escape
    hatch). Uses `notify.notify` (a generic, always-present service in
    `home.json`'s registry -- no bundle-specific notify target needed)."""
    return {
        "id": "front_door_opened_notify",
        "alias": "Front door: notify when opened",
        "mode": "single",
        "triggers": [
            {"trigger": "state", "entity_id": "binary_sensor.front_door", "to": "open"}
        ],
        "conditions": [],
        "actions": [
            {"action": "notify.notify", "data": {"message": "Front door was opened"}},
        ],
    }


def _back_door_notify_automation() -> dict[str, Any]:
    """Second notify-sending automation -- same shape as
    `_front_door_notify_automation`, different trigger entity, so
    `refactor_into_macro` has two real call sites to extract into one
    `@macro` under `lib/`."""
    return {
        "id": "back_door_opened_notify",
        "alias": "Back door: notify when opened",
        "mode": "single",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.back_door", "to": "open"}],
        "conditions": [],
        "actions": [
            {"action": "notify.notify", "data": {"message": "Back door was opened"}},
        ],
    }


def _buggy_landing_light_automation() -> dict[str, Any]:
    """The `diagnose_failing_test` target: a deliberate automation-logic bug
    (an inverted condition, the same seeded-bug shape as `fixtures/sim/
    hallway_bundle_buggy` -- an `is_`/`to` check backwards from the stated
    intent), independent of the hallway motion automation so fixing it can
    never collide with the other 9 tasks' edits. Intent: "turn on the
    landing light when the landing motion sensor detects motion, unless
    holiday mode is on" (`input_boolean.holiday_mode`, `home.json`); the
    seeded bug fires it exactly backwards (only when holiday mode IS on).
    """
    return {
        "id": "landing_light_on_motion",
        "alias": "Landing: light on motion",
        "mode": "single",
        "triggers": [
            {"trigger": "state", "entity_id": "binary_sensor.bedroom_motion", "to": "on"}
        ],
        # BUG (deliberate, matching hallway_bundle_buggy's convention): should
        # be "off" -- fires only when holiday mode IS on instead of suppressing.
        "conditions": [{"condition": "state", "entity_id": "input_boolean.holiday_mode", "state": "on"}],
        "actions": [
            {
                "action": "light.turn_on",
                "target": {"entity_id": "light.bedroom"},
                "data": {"brightness_pct": 40},
            }
        ],
    }


def _guest_mode_helper() -> dict[str, Any]:
    """`input_boolean.guest_mode` -- declared/existing (real HA storage
    helper), but not yet referenced by the hallway automation (see
    `_hallway_motion_automation`'s docstring). Backs `add_helper_and_use_it`
    (a *second* new helper, `night_mode`, is the one the session adds) and
    `add_condition` (this one is what the session wires in)."""
    return {"id": "guest_mode", "name": "Guest Mode", "icon": "mdi:account-group"}


def _demo_script() -> dict[str, Any]:
    """At least one script, per the milestone's seeding requirement --
    otherwise unreferenced by any of the 10 prompts, so it's simple: toggle
    the porch light."""
    return {
        "id": "flash_porch_light",
        "alias": "Flash porch light",
        "mode": "single",
        "sequence": [
            {"action": "light.turn_on", "target": {"entity_id": "light.porch"}},
            {"delay": {"seconds": 1}},
            {"action": "light.turn_off", "target": {"entity_id": "light.porch"}},
        ],
    }


def _seed_backend() -> Any:
    from hassle.backend.fake import FakeBackend

    backend = FakeBackend()
    backend.create("automation", _hallway_motion_automation())
    backend.create("automation", _front_door_notify_automation())
    backend.create("automation", _back_door_notify_automation())
    backend.create("automation", _buggy_landing_light_automation())
    backend.create("input_boolean", _guest_mode_helper())
    backend.create("script", _demo_script())
    backend.reset_write_tracking()
    return backend


# ---------------------------------------------------------------------------
# tests/ -- written BEFORE the pull runs, so "tests survive sync" is exercised
# honestly (pull never touches tests/ at all -- see module docstring).
# ---------------------------------------------------------------------------

_TEST_HALLWAY = '''"""Sample-house tests for the hallway motion automation (see automations/)."""

from hassle.testing import simulate


def _sim():
    return simulate(__file__.rsplit("/tests/", 1)[0])


def test_hallway_light_fires_at_night():
    sim = _sim()
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 22:00")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    sim.advance(minutes=5)
    sim.assert_called("light.turn_off", entity_id="light.hallway")


def test_hallway_light_suppressed_during_the_day():
    sim = _sim()
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 12:00")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_not_called("light.turn_on")
'''

_TEST_SEEDED_BUG = '''"""MILESTONES M9 test 3's `diagnose_failing_test` target.

`landing_light_on_motion` (automations/misc.py) has a deliberate logic bug: its
holiday-mode condition is backwards (fires ONLY when holiday mode is ON,
instead of being suppressed by it). This test encodes the INTENDED behavior --
it currently fails for that reason, by design (see `hassle_dev.bundle_gen`'s
module docstring, "Scoring nuance: diagnose_failing_test starts red BY
DESIGN"). `xfail(strict=True)`: a plain `hassle test` run still exits 0 (the
other 9 acceptance tasks' scoring floor is untouched by this pre-existing,
out-of-scope bug), but this test FAILING TO FAIL (an XPASS) after a fix is
applied without removing the marker is itself reported as a failure -- so the
task genuinely requires both fixing the automation AND removing this marker,
same as a human would.
"""

import pytest
from hassle.testing import simulate


def _sim():
    return simulate(__file__.rsplit("/tests/", 1)[0])


@pytest.mark.xfail(strict=True, reason="seeded bug: holiday-mode condition is backwards")
def test_landing_light_suppressed_during_holiday_mode():
    sim = _sim()
    sim.set_state("input_boolean.holiday_mode", "off")
    sim.state_change("binary_sensor.bedroom_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.bedroom", brightness_pct=40)
'''


def _write_seed_tests(bundle_root: Path) -> None:
    tests_dir = bundle_root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_hallway.py").write_text(_TEST_HALLWAY, encoding="utf-8")
    (tests_dir / "test_seeded_bug.py").write_text(_TEST_SEEDED_BUG, encoding="utf-8")


# ---------------------------------------------------------------------------
# Determinism normalization (see module docstring).
# ---------------------------------------------------------------------------


def _normalize_for_determinism(bundle_root: Path) -> None:
    manifest_path = bundle_root / ".hassle" / "manifest.lock"
    if manifest_path.is_file():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["synced_at"] = _SENTINEL_SYNCED_AT
        from hassle.ir.canonical import canonical_json

        manifest_path.write_text(canonical_json(data) + "\n", encoding="utf-8")

    # `hassle.toml`'s `ha_url = "fake://<random-uuid-token>"` is this
    # generator's own test seam (`hassle_cli.backend_factory`'s module
    # docstring: "never written by production code"). A real distributed
    # sample bundle was never pulled from a live `ha_url` the recipient could
    # reach either -- AGENTS.md/docs/ frame the bundle as something a session
    # edits + validates + tests offline (DESIGN §12), never as something it
    # would `hassle push`. Rewriting to the same commented-out placeholder
    # `hassle_cli.config.write_default_config` produces for a fresh `hassle
    # init` both removes the nondeterministic token and matches what a real
    # user handing off a bundle (or a docs example) would actually ship.
    toml_path = bundle_root / "hassle.toml"
    if toml_path.is_file():
        lines = toml_path.read_text(encoding="utf-8").splitlines()
        rewritten = [
            '# ha_url = "http://homeassistant.local:8123"' if line.startswith("ha_url") else line
            for line in lines
        ]
        toml_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    for pycache in bundle_root.rglob("__pycache__"):
        shutil.rmtree(pycache, ignore_errors=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate_sample_bundle(out_dir: Path, *, repo_root: Path | None = None) -> None:
    """Generate the sample-house acceptance bundle at ``out_dir`` (created if
    missing; must not already exist with conflicting content -- callers that
    want a fresh bundle should remove ``out_dir`` first, matching
    `hassle-dev goldens --update`'s convention of the caller owning cleanup).

    Drives the REAL `hassle pull` pipeline against a seeded `FakeBackend`
    (see module docstring) -- everything under ``out_dir`` afterward is
    exactly what a user would get from `hassle init` + `hassle pull` against
    a real house shaped like `_seed_backend`, except the seeded `tests/`
    (written first, and never touched by pull -- see module docstring).
    """
    from click.testing import CliRunner
    from hassle_cli.backend_factory import register_fake_backend, unregister_fake_backend
    from hassle_cli.cli import main
    from hassle_cli.config import write_default_config
    from hassle.registry.snapshot import RegistrySnapshot

    root = repo_root or find_repo_root()
    if root is None:
        raise FileNotFoundError(
            "hassle-dev acceptance-bundle: could not locate the repo root "
            "(pass --repo-root DIR)"
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    backend = _seed_backend()
    backend.registry_snapshot = RegistrySnapshot.model_validate(_registry_snapshot_json(root))
    token = register_fake_backend(backend)
    try:
        # tests/ first: pull must never touch it (see module docstring) --
        # writing it first proves that honestly rather than assuming it.
        _write_seed_tests(out_dir)

        write_default_config(out_dir)
        (out_dir / "hassle.toml").write_text(
            f'ha_url = "fake://{token}"\nbundle_format = 1\nmirror = false\n',
            encoding="utf-8",
        )

        # Not a git repo (this generator never runs `git init` -- the caller
        # decides whether/how the emitted bundle gets committed), so `pull`'s
        # clean-tree gate (git-repo-only) doesn't apply here; `--allow-dirty`
        # is passed anyway to make that explicit rather than incidental.
        runner = CliRunner()
        old_cwd = Path.cwd()
        os.chdir(out_dir)
        try:
            result = runner.invoke(
                main,
                ["pull", "--allow-dirty"],
                env={"NO_COLOR": "1"},
                catch_exceptions=False,
            )
        finally:
            os.chdir(old_cwd)
        if result.exit_code != 0:
            raise RuntimeError(
                f"hassle-dev acceptance-bundle: `hassle pull` failed while generating "
                f"{out_dir}: {result.output}"
            )
    finally:
        unregister_fake_backend(token)

    _normalize_for_determinism(out_dir)
