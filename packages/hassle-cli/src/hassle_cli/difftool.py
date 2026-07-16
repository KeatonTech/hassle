"""External diff tool for `hassle push` conflicts (owner feature request,
`ux/conflict-difftool`).

The inline unified diff of decompiled DSL is unreadable for large objects
(the HVAC status template sensors are single 8KB Jinja strings), so the
interactive conflict prompt's `[d]iff` choice writes both sides' decompiled
DSL to two temp files and opens a real diff tool on them, blocking until it
exits, then returns to the prompt.

Tool resolution order (first hit wins):

1. ``$HASSLE_DIFFTOOL`` -- shlex-split, invoked as ``<tool> <remote-file>
   <local-file>`` (remote first, matching the inline diff's fromfile/tofile
   order). GUI tools must block until closed (``code --diff --wait``, not
   ``code --diff``) -- the temp files are deleted when the tool returns.
2. ``git difftool --no-index -y`` -- only when git actually has a
   ``diff.tool`` configured; without one, git difftool degrades to plain
   ``diff``, which is no better than the inline view.
3. ``diff -u <remote> <local> | $PAGER`` (``$PAGER`` defaulting to
   ``less``) -- always available on any POSIX box.
"""

from __future__ import annotations

import shlex
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hassle_cli.diffing import decompile_dsl


def resolve_difftool(env: Mapping[str, str], cwd: Path | None) -> list[str] | None:
    """The argv prefix to run on `(remote_file, local_file)`, or None for the
    `diff -u | $PAGER` fallback (see the module docstring for the order)."""
    tool = env.get("HASSLE_DIFFTOOL", "").strip()
    if tool:
        return shlex.split(tool)
    if _git_diff_tool_configured(cwd):
        return ["git", "difftool", "--no-index", "-y"]
    return None


def _git_diff_tool_configured(cwd: Path | None) -> bool:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "diff.tool"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False  # no git at all: the pager fallback still works
    return result.returncode == 0 and bool(result.stdout.strip())


def run_external_diff(
    remote_path: Path, local_path: Path, *, env: Mapping[str, str], cwd: Path | None = None
) -> str | None:
    """Run the resolved diff tool on the two files, blocking until it exits.

    Returns None on success, or a one-paragraph what/where/fix error message
    (R6) when the tool can't be launched -- the caller prints it and returns
    to the conflict prompt; a diff view failing must never eat the
    resolution flow.
    """
    argv = resolve_difftool(env, cwd)
    if argv is not None:
        source = "$HASSLE_DIFFTOOL" if env.get("HASSLE_DIFFTOOL", "").strip() else "git difftool"
        try:
            subprocess.run([*argv, str(remote_path), str(local_path)], cwd=cwd, check=False)
        except OSError as exc:
            return (
                f"hassle push: couldn't launch the external diff tool `{argv[0]}` "
                f"(from {source}): {exc.strerror or exc}. Fix: point $HASSLE_DIFFTOOL at an "
                "installed diff command that blocks until closed (e.g. `code --diff --wait`, "
                "`vimdiff`), or unset it to fall back to `git difftool` / `diff -u | $PAGER`."
            )
        return None
    # `$PAGER` is a shell fragment by convention (`less -R`, `cat > file`),
    # exactly as git treats GIT_PAGER -- so the fallback is a real shell
    # pipeline, with only the Hassle-controlled temp paths quoted.
    pager = env.get("PAGER", "").strip() or "less"
    pipeline = f"diff -u {shlex.quote(str(remote_path))} {shlex.quote(str(local_path))} | {pager}"
    try:
        subprocess.run(pipeline, shell=True, cwd=cwd, check=False)
    except OSError as exc:
        return (
            f"hassle push: couldn't run the fallback diff pipeline `{pipeline}`: "
            f"{exc.strerror or exc}. Fix: set $HASSLE_DIFFTOOL to a working diff command "
            "(e.g. `vimdiff`), or make `diff` and a pager available on PATH."
        )
    return None


def diff_conflict_externally(
    object_key: str,
    kind: str,
    *,
    local: dict[str, Any] | None,
    remote: dict[str, Any] | None,
    env: Mapping[str, str],
    cwd: Path | None = None,
) -> str | None:
    """Materialize both sides of a conflict as decompiled DSL temp files and
    open the external diff tool on them (remote first, local second).

    The files carry the byte-exact decompiled source -- no display wrapping
    (that is `hassle_cli.diffing.dsl_diff`'s inline-only concern). Returns
    None on success or the R6 error message from `run_external_diff`.
    """
    stem = object_key.replace(":", "__").replace("/", "_")
    with tempfile.TemporaryDirectory(prefix="hassle-conflict-") as tmp_dir:
        remote_path = Path(tmp_dir) / f"{stem}.remote.py"
        local_path = Path(tmp_dir) / f"{stem}.local.py"
        remote_path.write_text(decompile_dsl(object_key, kind, remote), encoding="utf-8")
        local_path.write_text(decompile_dsl(object_key, kind, local), encoding="utf-8")
        return run_external_diff(remote_path, local_path, env=env, cwd=cwd)
