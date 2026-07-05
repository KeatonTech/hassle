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

# DESIGN §5.6/§6: `lib/` is yours, never auto-regenerated -- macros (`@macro`,
# compile-time inlined), shared scripts (`@shared_script`, a real HA script
# entity), and plain constants, all imported cross-file as `from lib.x import y`.
LIB_README = """\
# lib/

Your own code -- Hassle never generates or overwrites anything here (beyond
writing this file once, if it's missing).

Put here:

- **Macros** (`@macro`): small glue that expands into each caller's action
  list at compile time. Zero HA-side footprint.

  ```python
  # lib/notify.py
  from hassle import macro

  @macro
  def notify_adults(message: str):
      e.notify.mobile_app_keaton(message=message)
      e.notify.mobile_app_spouse(message=message)
  ```

- **Shared scripts** (`@shared_script`): becomes a real HA script entity with
  typed fields -- visible/runnable/editable in the HA UI, and callable from
  UI-authored automations too.

  ```python
  @shared_script(id="flash_lights", alias="Flash lights", icon="mdi:alarm-light")
  def flash_lights(times: int = 3):
      ...
  ```

- **Plain constants**: anything else you want to share across automations,
  scripts, and helpers -- area names, default brightness levels, whatever.

Import from anywhere else in the bundle with `from lib.x import y`.
"""

TESTS_README = """\
# tests/

Your pytest files live here and persist in git like everything else. Write
tests against the `sim` fixture (`hassle.testing.simulate`) -- see the DSL
cookbook for examples. `hassle test` runs pytest with the simulator plugin
preloaded; plain `pytest` works too.
"""


def _write_if_missing(path: Path, content: str) -> bool:
    """Write `content` to `path` only if it doesn't already exist. Returns
    whether a write happened -- never overwrites a file the user may have
    edited (idempotent, safe to call on every `init`/`pull`)."""
    if path.is_file():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def scaffold_lib_and_tests_readmes(root: Path) -> list[str]:
    """Write `lib/README.md` (always, once) and `tests/README.md` (only when
    `tests/` is otherwise empty -- a bundle with real test files doesn't need
    a placeholder). Idempotent: never overwrites an existing file. Shared by
    `hassle init` and `hassle pull` (when it creates the scaffold dirs), so
    both paths document `lib/`'s purpose the same way (DESIGN §5.6/§6)."""
    steps: list[str] = []

    lib_dir = root / "lib"
    lib_dir.mkdir(exist_ok=True)
    if _write_if_missing(lib_dir / "README.md", LIB_README):
        steps.append("wrote lib/README.md")

    tests_dir = root / "tests"
    tests_dir.mkdir(exist_ok=True)
    tests_is_empty = not any(tests_dir.iterdir())
    if tests_is_empty and _write_if_missing(tests_dir / "README.md", TESTS_README):
        steps.append("wrote tests/README.md")

    return steps


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
    steps.extend(scaffold_lib_and_tests_readmes(root))

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
    else:
        toplevel = git_support.repo_toplevel(root)
        if toplevel is not None and toplevel != root.resolve():
            steps.append(
                f"nested inside the enclosing repo at {toplevel} -- your bundle "
                "rides that repo's history (no nested repo created); clean-tree "
                "checks only consider files under the bundle"
            )

    if not (root / ".gitignore").is_file():
        git_support.write_gitignore(root)
        steps.append("wrote .gitignore")

    return steps
