"""MILESTONES M9 test 3 (real gate): `hassle-dev acceptance-bundle --out DIR`.

Covers:
1. The generator produces a real, freshly-`hassle pull`ed bundle (AGENTS.md,
   docs/, hassle.toml, .hassle/registry.json, canonical decompiled sources) --
   not a hand-written fixture (`hassle_dev.bundle_gen` module docstring).
2. Determinism (R8): same output basename -> byte-identical tree across
   independent generations.
3. The untouched bundle is a legitimate `score_task` scoring floor: `hassle
   validate` and `hassle test` both pass (the seeded bug's test is `xfail`,
   not a bare failure -- see the scoring-nuance test below).
4. Every one of `emit_tasks`'s 10 prompts' presuppositions holds against the
   generated bundle BY CONSTRUCTION -- this is the permanent regression
   pinning prompts to the bundle the milestone asks for ("makes emit_tasks'
   docstring true by construction").
5. The `diagnose_failing_test` scoring nuance itself: untouched (xfailed, not
   a failure) / half-fixed (XPASS -> strict failure) / fully fixed (green).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hassle_dev.acceptance import emit_tasks, score_task
from hassle_dev.bundle_gen import generate_sample_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def sample_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One generated bundle, shared read-only across this module's tests
    (generation drives a real subprocess-free but still real `hassle pull` --
    not free, so avoid re-running it once per test)."""
    out = tmp_path_factory.mktemp("acceptance_bundle_gen") / "sample_house"
    generate_sample_bundle(out, repo_root=REPO_ROOT)
    return out


# -- 1. real-pipeline artifacts ----------------------------------------------


def test_generated_bundle_has_agent_docs_and_config(sample_bundle: Path) -> None:
    assert (sample_bundle / "AGENTS.md").is_file()
    assert (sample_bundle / "docs" / "DSL.md").is_file()
    assert (sample_bundle / "docs" / "COOKBOOK.md").is_file()
    assert (sample_bundle / "hassle.toml").is_file()
    assert (sample_bundle / ".hassle" / "registry.json").is_file()
    assert (sample_bundle / ".hassle" / "manifest.lock").is_file()


def test_generated_bundle_has_no_fake_backend_token_or_pycache(sample_bundle: Path) -> None:
    toml_text = (sample_bundle / "hassle.toml").read_text(encoding="utf-8")
    assert "fake://" not in toml_text
    assert not list(sample_bundle.rglob("__pycache__"))


# -- MILESTONES M17: uv-project scaffold determinism -------------------------


def test_generated_bundle_has_pyproject_without_absolute_path(sample_bundle: Path) -> None:
    # `hassle pull` (driven by this generator) now scaffolds `pyproject.toml`
    # (MILESTONES M17) -- it must use the bare-dependency shape here (no
    # [tool.uv.sources]), never embedding a path specific to the machine/
    # checkout that happened to run this generator (R8/M9 test 3 precondition).
    pyproject = sample_bundle / "pyproject.toml"
    assert pyproject.is_file()
    text = pyproject.read_text(encoding="utf-8")
    assert "[tool.uv.sources]" not in text
    assert 'dependencies = ["hassle-cli"]' in text


def test_generated_bundle_contains_no_absolute_path_anywhere(sample_bundle: Path) -> None:
    repo_root_str = str(REPO_ROOT)
    for path in sample_bundle.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert repo_root_str not in text, path
        assert str(sample_bundle) not in text, path


def test_generated_sources_are_decompiled_not_handwritten(sample_bundle: Path) -> None:
    # The decompiler's own canonical form (`@automation(...)`, `e.<domain>.<id>`
    # entity refs, `from hassle import *`) -- proof this came out of the real
    # pull/decompile pipeline, not a hand-authored fixture file.
    misc_src = (sample_bundle / "misc.py").read_text(encoding="utf-8")
    assert "from hassle import *" in misc_src
    assert "hall_light_on_motion" in misc_src
    assert "e.light.hallway" in misc_src


def test_manifest_lock_tracks_every_seeded_object(sample_bundle: Path) -> None:
    manifest = json.loads((sample_bundle / ".hassle" / "manifest.lock").read_text(encoding="utf-8"))
    assert set(manifest["objects"]) == {
        "automation:hall_light_on_motion",
        "automation:front_door_opened_notify",
        "automation:back_door_opened_notify",
        "automation:landing_light_on_motion",
        "input_boolean:guest_mode",
        "script:flash_porch_light",
    }


# -- 2. determinism (R8) -----------------------------------------------------


def test_generation_is_byte_identical_across_runs(tmp_path: Path) -> None:
    out_a = tmp_path / "run_a" / "sample_house"
    out_b = tmp_path / "run_b" / "sample_house"
    generate_sample_bundle(out_a, repo_root=REPO_ROOT)
    generate_sample_bundle(out_b, repo_root=REPO_ROOT)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*") if p.is_file())
    assert files_a == files_b

    for rel in files_a:
        assert (out_a / rel).read_bytes() == (out_b / rel).read_bytes(), rel


# -- 3. the untouched bundle is a legitimate scoring floor -------------------


def test_untouched_bundle_passes_validate_and_test(sample_bundle: Path) -> None:
    result = score_task(sample_bundle)
    assert result.validate_passed is True, result.validate_output
    assert result.test_passed is True, result.test_output
    assert result.passed is True


def test_untouched_bundle_test_output_shows_the_seeded_xfail(sample_bundle: Path) -> None:
    result = score_task(sample_bundle)
    assert "xfail" in result.test_output.lower()


# -- 4. emit_tasks' 10 prompts' presuppositions, pinned against this bundle --


def _misc_source(bundle: Path) -> str:
    """MILESTONES M15: every seeded object here is uncategorized, so ALL of
    them (automations, the helper, the script) share the one root-level
    misc.py -- this helper is named for that shared file, not any one kind."""
    return (bundle / "misc.py").read_text(encoding="utf-8")


def test_presupposition_entity_swap(sample_bundle: Path) -> None:
    """Task 1: hallway motion automation controls `light.hallway` with
    `brightness_pct`, and the swap target `light.living_room` is a real,
    validate-able entity (present in the registry snapshot)."""
    src = _misc_source(sample_bundle)
    assert "hall_light_on_motion" in src or "hallway_light_on_motion" in src
    assert "e.light.hallway" in src
    assert "brightness_pct=60" in src
    registry = json.loads((sample_bundle / ".hassle" / "registry.json").read_text(encoding="utf-8"))
    entity_ids = {e["entity_id"] for e in registry["entities"]}
    assert "light.living_room" in entity_ids


def test_presupposition_add_helper_and_use_it(sample_bundle: Path) -> None:
    """Task 2: the bundle must NOT already have `input_boolean.night_mode`
    (the session adds it) -- and the hallway automation must be a real target
    to wire it into."""
    helpers_src = (sample_bundle / "misc.py").read_text(encoding="utf-8")
    assert "night_mode" not in helpers_src
    assert "hall_light_on_motion" in _misc_source(sample_bundle)


def test_presupposition_add_condition(sample_bundle: Path) -> None:
    """Task 3: hallway automation currently has NO guest-mode check, but
    `input_boolean.guest_mode` already exists as a declared helper (so the
    session only needs to add the condition, not the helper)."""
    src = _misc_source(sample_bundle)
    # Isolate the hallway automation's own source block from the file (the
    # file has multiple @automation defs) -- crude but sufficient: guest_mode
    # must not appear anywhere near the hallway function body.
    start = src.index("def hallway_light_on_motion")
    end = src.find("\n@automation", start)
    hallway_block = src[start : end if end != -1 else len(src)]
    assert "guest_mode" not in hallway_block

    helpers_src = (sample_bundle / "misc.py").read_text(encoding="utf-8")
    assert 'id="guest_mode"' in helpers_src


def test_presupposition_write_sim_test(sample_bundle: Path) -> None:
    """Task 4: the hallway automation has a real day/night gate (a `sun`
    condition) so "motion during the day does NOT turn the light on" is a
    real, testable claim -- and the `sim` fixture convention is already used
    in tests/ for the session to pattern-match on."""
    src = _misc_source(sample_bundle)
    assert "sun(after=" in src
    hallway_test = (sample_bundle / "tests" / "test_hallway.py").read_text(encoding="utf-8")
    assert "simulate(" in hallway_test


def test_presupposition_diagnose_failing_test(sample_bundle: Path) -> None:
    """Task 5: a test in tests/ is failing (mechanically: xfailed, not
    collection-erroring) because of a deliberate, isolated automation-logic
    bug the session must find and fix."""
    seeded_bug_src = (sample_bundle / "tests" / "test_seeded_bug.py").read_text(encoding="utf-8")
    assert "xfail" in seeded_bug_src
    assert "landing_light" in seeded_bug_src
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_seeded_bug.py"],
        cwd=sample_bundle / "tests",
        capture_output=True,
        text=True,
    )
    assert "xfailed" in (proc.stdout + proc.stderr).lower()


def test_presupposition_add_automation_purpose_trigger(sample_bundle: Path) -> None:
    """Task 6: no bundle-specific presupposition beyond the DSL supporting
    purpose triggers and a registry with a `motion.detected` vocabulary entry
    and at least one area to target -- verified against the registry
    snapshot this bundle ships."""
    registry = json.loads((sample_bundle / ".hassle" / "registry.json").read_text(encoding="utf-8"))
    assert "motion.detected" in registry["purpose_vocabulary"]["triggers"]
    assert registry["areas"]


def test_presupposition_refactor_into_macro(sample_bundle: Path) -> None:
    """Task 7: MORE THAN ONE automation sends the same kind of notification
    (same service, same shape) -- real duplication to extract, not falling
    back to "add a second one first".

    MILESTONES M18: `notify.notify` exists in the acceptance snapshot, so a
    real `hassle pull` now decompiles it to the typed namespace form
    (`notify.notify(...)`) rather than `service("notify.notify", ...)` --
    the duplication presupposition itself is unaffected (still MORE THAN ONE
    call site), only the literal call-site spelling changed.
    """
    src = _misc_source(sample_bundle)
    assert src.count("notify.notify(") >= 2
    assert (sample_bundle / "lib" / "README.md").is_file()


def test_presupposition_ignore_glob_addition(sample_bundle: Path) -> None:
    """Task 8: a real, writable `hassle.toml` the session can add an `ignore`
    glob to."""
    toml_text = (sample_bundle / "hassle.toml").read_text(encoding="utf-8")
    assert "bundle_format" in toml_text


def test_presupposition_explain_plan_diff(sample_bundle: Path) -> None:
    """Task 9: purely conceptual, but needs the hallway automation's
    `brightness_pct=60` to exist so "changed locally from 60 to 80" makes
    sense (same presupposition as task 1)."""
    assert "brightness_pct=60" in _misc_source(sample_bundle)


def test_presupposition_fix_validation_finding(sample_bundle: Path) -> None:
    """Task 10: the bundle must validate CLEAN before the session introduces
    its own typo (so the only finding it ever sees is self-inflicted) -- and
    needs a registry snapshot for tier-2 entity-id validation to even run."""
    assert (sample_bundle / ".hassle" / "registry.json").is_file()
    result = score_task(sample_bundle)
    assert result.validate_passed is True, result.validate_output


def test_all_ten_categories_have_a_presupposition_test() -> None:
    """Meta-check: every category `emit_tasks` returns has a same-named
    presupposition test above (keeps this file honest as the tasks evolve)."""
    tasks = emit_tasks(Path("irrelevant-for-this-check"))
    categories = {t.category for t in tasks}
    this_module_tests = {
        name[len("test_presupposition_") :]
        for name in globals()
        if name.startswith("test_presupposition_")
    }
    assert categories == this_module_tests


# -- 5. the diagnose_failing_test scoring nuance, all three states ----------


def test_scoring_nuance_untouched_bundle_is_xfailed_not_failing(sample_bundle: Path) -> None:
    result = score_task(sample_bundle)
    assert result.test_passed is True


def test_scoring_nuance_fixing_logic_without_removing_xfail_still_fails(
    tmp_path: Path, sample_bundle: Path
) -> None:
    import shutil

    work = tmp_path / "half_fixed"
    shutil.copytree(sample_bundle, work)
    automations_path = work / "misc.py"
    text = automations_path.read_text(encoding="utf-8")
    assert 'state(e.input_boolean.holiday_mode).is_("on")' in text
    automations_path.write_text(
        text.replace(
            'state(e.input_boolean.holiday_mode).is_("on")',
            'state(e.input_boolean.holiday_mode).is_("off")',
        ),
        encoding="utf-8",
    )

    result = score_task(work)
    assert result.test_passed is False
    assert "xpass" in result.test_output.lower()


def test_scoring_nuance_fixing_logic_and_removing_xfail_passes(
    tmp_path: Path, sample_bundle: Path
) -> None:
    import shutil

    work = tmp_path / "fully_fixed"
    shutil.copytree(sample_bundle, work)

    automations_path = work / "misc.py"
    automations_path.write_text(
        automations_path.read_text(encoding="utf-8").replace(
            'state(e.input_boolean.holiday_mode).is_("on")',
            'state(e.input_boolean.holiday_mode).is_("off")',
        ),
        encoding="utf-8",
    )
    seeded_bug_path = work / "tests" / "test_seeded_bug.py"
    text = seeded_bug_path.read_text(encoding="utf-8")
    marker_line = next(
        line for line in text.splitlines() if line.strip().startswith("@pytest.mark.xfail")
    )
    seeded_bug_path.write_text(text.replace(marker_line + "\n", ""), encoding="utf-8")

    result = score_task(work)
    assert result.validate_passed is True, result.validate_output
    assert result.test_passed is True, result.test_output
    assert result.passed is True


# -- CLI ----------------------------------------------------------------------


def test_cli_acceptance_bundle_writes_a_fresh_bundle(tmp_path: Path) -> None:
    out = tmp_path / "cli_out"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "hassle_dev.cli",
            "acceptance-bundle",
            "--out",
            str(out),
            "--repo-root",
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert (out / "AGENTS.md").is_file()


def test_cli_acceptance_bundle_refuses_a_nonempty_out_dir(tmp_path: Path) -> None:
    out = tmp_path / "cli_out"
    out.mkdir()
    (out / "placeholder.txt").write_text("already something here", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "hassle_dev.cli",
            "acceptance-bundle",
            "--out",
            str(out),
            "--repo-root",
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "already exists" in proc.stdout
