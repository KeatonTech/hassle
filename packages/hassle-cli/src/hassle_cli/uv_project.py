"""`hassle init`/`hassle pull` scaffold the bundle root as its own tiny uv
project (MILESTONES M17): `pyproject.toml` declaring `dependencies =
["hassle-cli"]`, plus a `[tool.uv.sources]` local-path entry when a toolchain
source checkout can be resolved -- so `uv run hassle ...` works standalone
inside a bundle directory without the user knowing this is (or was generated
from) a monorepo workspace member.

**Never touches an existing `pyproject.toml`** (I6: pyproject is user
territory once created, unlike `.vscode/settings.json` which this project
freely rewrites) -- existence is the only thing ever checked; the content is
never parsed, so even a malformed existing file is left completely alone.

**Toolchain path resolution order** (first hit wins; see `resolve_toolchain_path`):
1. An explicit ``toolchain_path`` key in `hassle.toml` (`hassle_cli.config`).
2. Auto-detect: walk up from ``hassle_cli.__file__`` looking for a directory
   containing a `pyproject.toml` whose ``[project].name == "hassle-cli"`` --
   i.e. the running CLI is itself an editable install from a source checkout
   (this repo's own dev loop). The `[tool.uv.sources]` path then points at
   that checkout's `packages/hassle-cli`.
3. Neither resolves -> no sources table at all (bare dependency; the shape
   that works once `hassle-cli` is published to PyPI).

The auto-detected path is machine-specific BY DESIGN (documented here and in
docs/ha-api-notes.md) -- callers that need deterministic output regardless of
the running machine's checkout layout (`hassle-dev acceptance-bundle`) pass
``suppress_sources=True`` to `scaffold_pyproject`, which always emits the
bare-dependency shape (see that generator's module docstring for why).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from hassle.ir.keys import slugify

PYPROJECT_FILENAME = "pyproject.toml"

#: Printed (by `init`/`pull`) whenever scaffolding falls back to the bare
#: dependency shape -- neither an explicit `toolchain_path` nor auto-detection
#: resolved a source checkout.
NO_TOOLCHAIN_NOTE = (
    "hassle: scaffolded pyproject.toml without a [tool.uv.sources] entry for "
    "hassle-cli (no toolchain checkout found). `uv run hassle` needs either a "
    "published `hassle-cli` package or a `toolchain_path` set in hassle.toml."
)


def resolve_toolchain_path(
    *, configured_path: str | None, hassle_cli_file: str | None = None
) -> Path | None:
    """Resolution order (first hit wins):

    1. ``configured_path`` (the `hassle.toml` ``toolchain_path`` key, already
       loaded by the caller -- this function never reads config itself, so
       tests can drive it directly).
    2. Auto-detect from ``hassle_cli_file`` (defaults to this running CLI's
       own ``__file__``): walk upward looking for a directory containing a
       `pyproject.toml` with ``[project].name == "hassle-cli"``.

    Returns the *checkout root* (the directory containing `packages/`), not
    the `packages/hassle-cli` path itself -- callers append that themselves
    (`scaffold_pyproject`), since a doctor-style caller may want the checkout
    root for other checks too.
    """
    if configured_path:
        return Path(configured_path)

    start = Path(hassle_cli_file) if hassle_cli_file is not None else Path(__file__)
    start = start.resolve()
    for directory in start.parents:
        candidate = directory / PYPROJECT_FILENAME
        if not candidate.is_file():
            continue
        try:
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            continue
        if data.get("project", {}).get("name") == "hassle-cli":
            # `candidate`'s directory is `.../packages/hassle-cli`; the
            # checkout root is two levels up (`packages/` then the repo root).
            return directory.parent.parent
    return None


@dataclass(frozen=True)
class PyprojectScaffoldResult:
    wrote: bool
    note: str | None  # NO_TOOLCHAIN_NOTE when scaffolding fell back, else None


def _pyproject_text(*, project_name: str, toolchain_root: Path | None) -> str:
    lines = [
        "[project]",
        f'name = "{project_name}"',
        'version = "0.0.0"',
        'requires-python = ">=3.12"',
        'dependencies = ["hassle-cli"]',
        "",
    ]
    if toolchain_root is not None:
        cli_path = (toolchain_root / "packages" / "hassle-cli").as_posix()
        lines += [
            "[tool.uv.sources]",
            "# This path is specific to the machine that ran `hassle init`/`hassle",
            "# pull` -- it points at a local source checkout of Hassle (MILESTONES",
            "# M17). Once `hassle-cli` is published to PyPI, delete this table (or",
            "# re-run init/pull after removing this file) to use the published package.",
            f'hassle-cli = {{ path = "{cli_path}", editable = true }}',
            "",
        ]
    return "\n".join(lines)


def scaffold_pyproject(
    root: Path,
    *,
    toolchain_path: str | None = None,
    suppress_sources: bool = False,
) -> PyprojectScaffoldResult:
    """Write `pyproject.toml` at `root` IF MISSING; never touch an existing
    one (I6 -- see module docstring). `toolchain_path` is the already-loaded
    `hassle.toml` ``toolchain_path`` config value (or `None`); auto-detection
    is consulted only when it's absent.

    `suppress_sources=True` (used by `hassle-dev acceptance-bundle`, MILESTONES
    M17 determinism requirement) always scaffolds the bare-dependency shape,
    regardless of what `resolve_toolchain_path` would otherwise find -- so the
    generator's output never embeds a machine/checkout-specific path.
    """
    path = root / PYPROJECT_FILENAME
    if path.is_file():
        return PyprojectScaffoldResult(wrote=False, note=None)

    toolchain_root = (
        None if suppress_sources else resolve_toolchain_path(configured_path=toolchain_path)
    )
    project_name = slugify(root.name)
    text = _pyproject_text(project_name=project_name, toolchain_root=toolchain_root)
    path.write_text(text, encoding="utf-8")
    note = None if toolchain_root is not None else NO_TOOLCHAIN_NOTE
    return PyprojectScaffoldResult(wrote=True, note=note)


def _sources_path_for_hassle_cli(pyproject_data: dict[str, object]) -> str | None:
    tool = pyproject_data.get("tool")
    if not isinstance(tool, dict):
        return None
    uv = tool.get("uv")
    if not isinstance(uv, dict):
        return None
    sources = uv.get("sources")
    if not isinstance(sources, dict):
        return None
    entry = sources.get("hassle-cli")
    if not isinstance(entry, dict):
        return None
    path = entry.get("path")
    return path if isinstance(path, str) else None


def doctor_report_lines(bundle_root: Path) -> list[str]:
    """MILESTONES M17: `hassle doctor`'s uv-project status report -- three
    OFFLINE, filesystem-only checks (never spawns `uv`, or any subprocess):

    1. Is `pyproject.toml` present at all?
    2. If present, does it declare a `[tool.uv.sources]` `hassle-cli` path,
       and if so, does that path exist on disk right now?
    3. A one-line summary derived purely from (1)+(2) -- mentions `uv run
       hassle` in its text as a suggestion, but never actually invokes it.
    """
    path = bundle_root / PYPROJECT_FILENAME
    if not path.is_file():
        return [
            "doctor: no pyproject.toml found -- `uv run hassle` won't work standalone here. "
            "Fix: re-run `hassle init` or `hassle pull` in this bundle to scaffold one."
        ]

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return [
            "doctor: pyproject.toml exists but is not valid TOML -- Hassle never edits it "
            "(I6), so this is unrelated to Hassle's own scaffolding; fix the syntax error to "
            "use it with `uv run hassle`."
        ]

    sources_path = _sources_path_for_hassle_cli(data)
    if sources_path is None:
        return [
            "doctor: pyproject.toml present, no [tool.uv.sources] entry for hassle-cli "
            "(bare-dependency shape) -- `uv run hassle` will work once `hassle-cli` is "
            "published, or after setting `toolchain_path` in hassle.toml and re-scaffolding."
        ]

    if Path(sources_path).is_dir():
        return [
            f"doctor: pyproject.toml present, [tool.uv.sources] hassle-cli path resolves "
            f"({sources_path}) -- `uv run hassle` should work here."
        ]

    return [
        f"doctor: pyproject.toml present, but [tool.uv.sources] hassle-cli path does not "
        f"resolve ({sources_path} does not exist -- stale toolchain checkout?). Fix: update "
        "`toolchain_path` in hassle.toml (or remove the [tool.uv.sources] table) and re-run "
        "`hassle init`/`hassle pull`."
    ]
