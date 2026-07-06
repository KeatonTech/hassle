"""Guards the `hassle-dev docs` CI gate (MILESTONES M9 tests 1-2):

- fails if any `hassle.__all__` name lacks a documented pair (test 1),
- fails if the cookbook bundle doesn't compile/validate/simulate clean
  (test 2),
- `--update` writes `docs/DSL.md` and `docs/COOKBOOK.md` in place (R3-style:
  mirrors `hassle-dev goldens --update`), a bare run checks for drift.
"""

from __future__ import annotations

from pathlib import Path

from hassle_dev.docs import find_repo_root, run_docs

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_find_repo_root_locates_real_repo() -> None:
    root = find_repo_root(Path(__file__).parent)
    assert root is not None
    assert (root / "fixtures" / "dsl").is_dir()
    assert (root / "fixtures" / "cookbook").is_dir()


def test_run_docs_against_real_repo_reports_no_missing_names() -> None:
    report = run_docs(REPO_ROOT, update=False)
    assert report.missing_dsl_names == set(), report.missing_dsl_names


def test_run_docs_against_real_repo_reports_no_cookbook_findings() -> None:
    report = run_docs(REPO_ROOT, update=False)
    assert report.cookbook_findings == [], report.cookbook_findings


def test_run_docs_against_real_repo_has_at_least_20_recipes() -> None:
    report = run_docs(REPO_ROOT, update=False)
    assert report.cookbook_recipe_count >= 20


def test_run_docs_update_writes_files_matching_generators(tmp_path: Path) -> None:
    import shutil

    # Work on a throwaway copy so this test never mutates the real repo's
    # docs/ (a second CI-parity safety net -- the real `--update` run is
    # exercised by `hassle-dev docs --update` in CI directly).
    work = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "fixtures", work / "fixtures")
    shutil.copytree(
        REPO_ROOT / "packages" / "hassle-core" / "src",
        work / "packages" / "hassle-core" / "src",
    )
    (work / "docs").mkdir()

    report = run_docs(work, update=True)
    assert report.missing_dsl_names == set()
    assert (work / "docs" / "DSL.md").is_file()
    assert (work / "docs" / "COOKBOOK.md").is_file()
    assert "state" in (work / "docs" / "DSL.md").read_text(encoding="utf-8")


def test_run_docs_detects_drift_without_update(tmp_path: Path) -> None:
    import shutil

    shutil.copytree(REPO_ROOT / "fixtures", tmp_path / "fixtures")
    shutil.copytree(
        REPO_ROOT / "packages" / "hassle-core" / "src",
        tmp_path / "packages" / "hassle-core" / "src",
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "DSL.md").write_text("stale", encoding="utf-8")
    (tmp_path / "docs" / "COOKBOOK.md").write_text("stale", encoding="utf-8")

    report = run_docs(tmp_path, update=False)
    assert report.dsl_drifted is True
    assert report.cookbook_drifted is True
    # A bare (non-update) run must never overwrite the stale files.
    assert (tmp_path / "docs" / "DSL.md").read_text(encoding="utf-8") == "stale"
