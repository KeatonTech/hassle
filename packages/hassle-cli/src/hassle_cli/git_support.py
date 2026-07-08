"""Git-aware flow helpers (DESIGN §8.4): clean-tree checks, `git init` offer,
and the ready-made push commit message.

None of this *requires* git (DESIGN §8.4: "the tool functions in a bare
directory and warns once") -- `is_git_repo` being `False` is a normal,
supported state, not an error.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def is_git_repo(path: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def is_clean(path: Path) -> bool:
    """True if the working tree has no uncommitted changes (tracked or
    untracked) UNDER ``path``. Scoped with ``-- .`` on purpose: a bundle
    nested inside an unrelated project repo must not inherit the enclosing
    repo's dirtiness (DESIGN §8.4's contract is about the bundle's own files
    landing as their own commit). Only meaningful when `is_git_repo(path)`."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", "."],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() == ""


def repo_toplevel(path: Path) -> Path | None:
    """The enclosing repo's toplevel, or None when not in a work tree."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


GITIGNORE_CONTENT = """\
# Hassle
.hassle/registry.json.bak
__pycache__/
*.pyc
.pytest_cache/

# Derived artifacts -- regenerated from .hassle/registry.json by `hassle pull`
# / `hassle stubs`; committing them is pure churn (owner decision, 2026-07-07).
# NOTE deliberately KEPT in git: .hassle/registry.json + manifest.lock (the
# offline sync/validate base -- and the superset of anything the stubs
# contain, so ignoring typings/ is about noise, not secrecy).
typings/

# Bundle uv project venv (MILESTONES M17)
.venv/
"""


def write_gitignore(path: Path) -> None:
    gitignore = path / ".gitignore"
    if not gitignore.is_file():
        gitignore.write_text(GITIGNORE_CONTENT, encoding="utf-8")


def commit_message_for_plan(summary: dict[str, int]) -> str:
    """A ready-made commit message summarizing an applied push plan (DESIGN
    §8.4: "prints a ready-made commit message summarizing the applied plan")."""
    parts = [f"{count} {action}" for action, count in sorted(summary.items()) if count]
    body = ", ".join(parts) if parts else "no changes"
    return f"sync: push ({body})"


def commit_message_for_pull(summary: dict[str, int]) -> str:
    parts = [f"{count} {action}" for action, count in sorted(summary.items()) if count]
    body = ", ".join(parts) if parts else "no changes"
    return f"sync: UI changes ({body})"
