"""`hassle init`: scaffold a fresh bundle directory (DESIGN §8.4: "`init`
offers `git init` + writes `.gitignore` + a CI workflow template").
"""

from __future__ import annotations

from pathlib import Path

from hassle_cli import git_support
from hassle_cli.config import CONFIG_FILENAME, write_default_config

CI_WORKFLOW = """\
name: hassle
on: [push, pull_request]
jobs:
  validate-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv tool install hassle
      - run: hassle validate
      - run: hassle test
"""


def init_bundle(root: Path) -> list[str]:
    """Scaffold `root` as a fresh Hassle bundle. Idempotent (safe to re-run).
    Returns a list of human-readable steps taken, for the CLI to print."""
    steps: list[str] = []

    # DESIGN §6's tree layout (docs/ha-api-notes.md §17.9 RESOLVED: the loader
    # recurses, so these are real importable packages, not just organizational
    # convenience). No `__init__.py` in any of them -- the bundle loader
    # relies on PEP 420 namespace packages (the bundle root is put on
    # `sys.path` at compile time), so none is needed for
    # `from helpers.modes import guest_mode`-style cross-file imports to work.
    for name in ("automations", "scripts", "helpers", "lib"):
        (root / name).mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / ".hassle").mkdir(exist_ok=True)

    config_path = root / CONFIG_FILENAME
    if not config_path.is_file():
        write_default_config(root)
        steps.append(f"wrote {CONFIG_FILENAME}")

    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflow_dir / "hassle.yml"
    if not workflow_path.is_file():
        workflow_path.write_text(CI_WORKFLOW, encoding="utf-8")
        steps.append("wrote .github/workflows/hassle.yml")

    if not git_support.is_git_repo(root):
        git_support.git_init(root)
        steps.append("ran `git init`")

    if not (root / ".gitignore").is_file():
        git_support.write_gitignore(root)
        steps.append("wrote .gitignore")

    return steps
