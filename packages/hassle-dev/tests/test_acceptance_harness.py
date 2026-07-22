"""The agent-acceptance harness (build only -- running actual model sessions
against these tasks happens elsewhere).

`emit_tasks(bundle_dir)` returns the 10 representative task prompts a fresh
model session would be given (bundle + AGENTS.md only); `score_task` runs
the mechanical part of the rubric (`hassle validate && hassle test` against
the modified bundle) and reports pass/fail -- the harness never itself
judges whether the *diff* satisfies the task's intent, only whether the
bundle is left in a valid, green state (the mechanically-checkable half of
the acceptance bar).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hassle_dev.acceptance import AcceptanceTask, emit_tasks, score_task

REPO_ROOT = Path(__file__).resolve().parents[3]
HALLWAY_BUNDLE = REPO_ROOT / "fixtures" / "sim" / "hallway_bundle"


def _copy_as_real_bundle(src: Path, dest: Path) -> Path:
    """`fixtures/sim/hallway_bundle` is a pure sim-test fixture (no
    `hassle.toml`); `score_task`/the CLI need a real bundle root. Copy +
    seed a minimal `hassle.toml` so these tests exercise the CLI exactly as
    an orchestrator would against a real, freshly-pulled bundle."""
    import shutil

    shutil.copytree(src, dest)
    (dest / "hassle.toml").write_text("bundle_format = 1\nmirror = false\n", encoding="utf-8")
    return dest


def test_emit_tasks_returns_exactly_ten() -> None:
    tasks = emit_tasks(HALLWAY_BUNDLE)
    assert len(tasks) == 10


def test_every_task_has_a_unique_id_and_nonempty_prompt() -> None:
    tasks = emit_tasks(HALLWAY_BUNDLE)
    ids = [t.task_id for t in tasks]
    assert len(ids) == len(set(ids)), f"duplicate task ids: {ids}"
    for task in tasks:
        assert task.prompt.strip()
        assert task.category


def test_task_categories_cover_the_ten_representative_kinds() -> None:
    tasks = emit_tasks(HALLWAY_BUNDLE)
    categories = {t.category for t in tasks}
    expected = {
        "entity_swap",
        "add_helper_and_use_it",
        "add_condition",
        "write_sim_test",
        "diagnose_failing_test",
        "add_automation_purpose_trigger",
        "refactor_into_macro",
        "ignore_glob_addition",
        "explain_plan_diff",
        "fix_validation_finding",
    }
    assert categories == expected


def test_acceptance_task_is_a_frozen_shape() -> None:
    task = AcceptanceTask(task_id="x", category="entity_swap", prompt="do the thing")
    assert task.task_id == "x"
    assert task.category == "entity_swap"
    assert "do the thing" in task.prompt


def test_score_task_passes_on_a_clean_untouched_bundle(tmp_path: Path) -> None:
    work = _copy_as_real_bundle(HALLWAY_BUNDLE, tmp_path / "bundle")
    # This fixture bundle has no tests/ of its own (its sim tests live under
    # packages/hassle-core/tests/ instead) -- seed one trivial passing test
    # so "hassle test passes" is meaningfully exercised here, matching a
    # real bundle (which always has tests/, per hassle init's scaffold).
    tests_dir = work / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_smoke.py").write_text(
        "def test_smoke():\n    assert True\n", encoding="utf-8"
    )
    result = score_task(work)
    assert result.validate_passed is True
    assert result.test_passed is True
    assert result.passed is True


def test_score_task_fails_when_validate_would_fail(tmp_path: Path) -> None:
    work = _copy_as_real_bundle(HALLWAY_BUNDLE, tmp_path / "bundle")
    # Seed an unknown-entity mistake -- validate has no registry snapshot to
    # check against in this fixture bundle, so seed a compile-time break
    # instead (guaranteed to fail regardless of registry presence).
    (work / "hallway.py").write_text("this is not valid python(((", encoding="utf-8")
    result = score_task(work)
    assert result.passed is False
    assert result.validate_passed is False


def test_score_task_fails_when_a_test_fails(tmp_path: Path) -> None:
    work = _copy_as_real_bundle(HALLWAY_BUNDLE, tmp_path / "bundle")
    tests_dir = work / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_seeded_failure.py").write_text(
        "def test_seeded_failure():\n    assert False\n", encoding="utf-8"
    )
    result = score_task(work)
    assert result.test_passed is False
    assert result.passed is False


@pytest.mark.parametrize("category", ["entity_swap", "add_helper_and_use_it"])
def test_task_for_category_names_the_hallway_bundle_concretely(category: str) -> None:
    """Spot check: tasks are concrete (reference real entities/files in the
    given bundle), not generic placeholders -- an agent needs something to
    act on."""
    tasks = {t.category: t for t in emit_tasks(HALLWAY_BUNDLE)}
    prompt = tasks[category].prompt
    assert "hallway" in prompt.lower() or ".py" in prompt


def test_harness_module_documents_orchestrator_usage() -> None:
    """The module docstring must explain that each task maps to one model
    session."""
    import hassle_dev.acceptance as mod

    assert mod.__doc__ is not None
    assert "session" in mod.__doc__.lower()


def test_cli_json_output_is_stable_schema(tmp_path: Path) -> None:
    """`hassle-dev acceptance-tasks --bundle DIR --json` -- the machine-
    readable form an orchestrator script consumes."""
    import shutil

    work = tmp_path / "bundle"
    shutil.copytree(HALLWAY_BUNDLE, work)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "hassle_dev.cli",
            "acceptance-tasks",
            "--bundle",
            str(work),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert len(payload["tasks"]) == 10
    for task in payload["tasks"]:
        assert set(task.keys()) == {"task_id", "category", "prompt"}
