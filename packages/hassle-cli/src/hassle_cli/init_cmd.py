"""`hassle init`: scaffold a fresh bundle directory (DESIGN §8.4: "`init`
offers `git init` + writes `.gitignore` + a CI workflow template").
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle_cli import git_support
from hassle_cli.config import CONFIG_FILENAME, load_config, write_default_config
from hassle_cli.uv_project import scaffold_pyproject

# DESIGN §11 layer 1 ("free": generated stubs + shipped `.vscode/settings.json`
# -> Pylance autocompletion/typo-squiggles with zero configuration).
#
# `python.analysis.stubPath` MUST equal the directory `hassle stubs` actually
# writes into -- `typings/hassle/registry/__init__.pyi` (`hassle_cli.cli`'s
# `stubs` command; `hassle.registry.stubs.generate_entities_stub`). This is
# the M8 layer-1 finding: an earlier version of this generator/`stubs` wrote
# to `.hassle/entities.pyi`, a path no pyright config pointed at, so the
# generated types were silently never picked up by any real editor. Verified
# end-to-end (not just by convention) in
# `packages/hassle-core/tests/test_registry_stubs_pyright.py` (the mechanism)
# and `test_registry_stubs_pyright_init_template.py` (this exact template).
#
# `python.analysis.extraPaths` includes `.` (the bundle root) so Pylance
# resolves the same PEP 420 namespace-package cross-file imports
# (`from lib.x import y`, `from helpers.modes import guest_mode`) the
# compiler's own loader does (DESIGN §6, docs/ha-api-notes.md §17.9).
# `python.defaultInterpreterPath` points at the bundle's own uv-project venv
# (MILESTONES M17): without it, VS Code's Python extension may keep/select an
# interpreter that has no `hassle` installed, and every `from hassle import *`
# name shows as undefined even though the entity stubs (interpreter-
# independent) still resolve -- exactly the owner field report this line
# fixes. It is a DEFAULT: VS Code ignores it once a user explicitly selects
# an interpreter for the workspace.
VSCODE_SETTINGS = {
    "python.analysis.stubPath": "typings",
    "python.analysis.extraPaths": ["."],
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
}

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
      e.notify.mobile_app_kai(message=message)
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


def scaffold_agent_docs(root: Path) -> list[str]:
    """Write `AGENTS.md` + `docs/DSL.md` + `docs/COOKBOOK.md` (DESIGN §12,
    MILESTONES M9 deliverable 1). Unlike `lib/README.md`/`tests/README.md`
    (user territory, "only if missing"), these are wholly machine-generated
    content the user is never expected to hand-edit -- so they are
    REWRITTEN every time (same convention as `.vscode/settings.json`), which
    also means a bundle stays in sync with whatever Hassle version generated
    them after an upgrade + re-`init`/`pull`. `AGENTS.md` is bundle-specific
    (its header names the bundle directory); `docs/DSL.md`/`docs/COOKBOOK.md`
    are the same reference content for every bundle, shipped as package data
    (`hassle.docs.static`, refreshed only via `hassle-dev docs --update`,
    R3) since the installed CLI doesn't carry the fixture corpus these are
    generated from.

    Shared by `hassle init` and `hassle pull` (when it scaffolds directories
    a bundle predating this change never had)."""
    from hassle.docs.agents_md import generate_agents_md
    from hassle.docs.static import load_cookbook_md, load_dsl_md

    steps: list[str] = []

    agents_md_path = root / "AGENTS.md"
    agents_md_text = generate_agents_md(bundle_name=root.name)
    already_had_it = agents_md_path.is_file()
    agents_md_path.write_text(agents_md_text, encoding="utf-8")
    steps.append("refreshed AGENTS.md" if already_had_it else "wrote AGENTS.md")

    docs_dir = root / "docs"
    docs_dir.mkdir(exist_ok=True)
    dsl_path = docs_dir / "DSL.md"
    cookbook_path = docs_dir / "COOKBOOK.md"
    docs_existed = dsl_path.is_file() or cookbook_path.is_file()
    dsl_path.write_text(load_dsl_md(), encoding="utf-8")
    cookbook_path.write_text(load_cookbook_md(), encoding="utf-8")
    steps.append(
        "refreshed docs/DSL.md, docs/COOKBOOK.md"
        if docs_existed
        else "wrote docs/DSL.md, docs/COOKBOOK.md"
    )

    return steps


def scaffold_vscode_settings(root: Path) -> list[str]:
    """Write `.vscode/settings.json` (DESIGN §11 layer 1) pointing Pylance at
    `hassle stubs`'s actual output location. Idempotent -- never overwrites a
    file the user has since customized (same convention as
    `scaffold_lib_and_tests_readmes`). Shared by `hassle init` and `hassle
    pull` (when it scaffolds directories a bundle predating this change never
    had) so both paths get working autocompletion, not just freshly
    `init`-ed bundles."""
    steps: list[str] = []
    vscode_dir = root / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    settings_json = json.dumps(VSCODE_SETTINGS, indent=2) + "\n"
    if _write_if_missing(vscode_dir / "settings.json", settings_json):
        steps.append("wrote .vscode/settings.json")
    return steps


def scaffold_pyproject_file(root: Path) -> list[str]:
    """Write `pyproject.toml` at `root` IF MISSING (MILESTONES M17:
    bundle-as-uv-project) -- never touches an existing one (I6, same
    convention as `lib/README.md`/`tests/README.md`; unlike
    `.vscode/settings.json`, which is wholly machine-generated and always
    rewritten). Reads the bundle's `toolchain_path` config (if any) so an
    explicit setting beats auto-detection (`hassle_cli.uv_project`'s
    resolution order). Shared by `hassle init` and `hassle pull`."""
    steps: list[str] = []
    toolchain_path = load_config(root).toolchain_path
    result = scaffold_pyproject(root, toolchain_path=toolchain_path)
    if result.wrote:
        steps.append("wrote pyproject.toml")
        if result.note is not None:
            steps.append(result.note)
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
    # `from lib.x import y`-style cross-file imports to work.
    #
    # MILESTONES M15 work item B: the OLD per-kind trees (`automations/`,
    # `scripts/`, `helpers/`) are RETIRED and no longer scaffolded -- the
    # category-first layout is root-level `<slug>.py` files, created on
    # demand by the compiler/decompiler (`misc.py` for every uncategorized
    # object), never empty directories a fresh `init` pre-creates.
    (root / "lib").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / ".hassle").mkdir(exist_ok=True)
    steps.extend(scaffold_lib_and_tests_readmes(root))
    steps.extend(scaffold_vscode_settings(root))
    steps.extend(scaffold_agent_docs(root))

    config_path = root / CONFIG_FILENAME
    if not config_path.is_file():
        write_default_config(root)
        steps.append(f"wrote {CONFIG_FILENAME}")

    # MILESTONES M17: bundle-as-uv-project scaffold -- after hassle.toml
    # exists (a fresh one has no `toolchain_path`, but a pre-existing bundle
    # re-running `init` may already have one set by hand).
    steps.extend(scaffold_pyproject_file(root))

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
