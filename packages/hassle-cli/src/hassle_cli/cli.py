"""`hassle` -- the daily-driver CLI (DESIGN §8.4, §10.4, §14).

Framework choice (click, not typer) is documented in the `hassle_cli` package
docstring and docs/internals/cli.md.

Command surface (DESIGN §8.4 loop + §10.4 + §14):
  init, login, pull, status, plan, push, validate, test, run, fmt, stubs,
  explain, render, doctor
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import click

from hassle_cli import bundle_ops, git_support, init_cmd, manifest_io
from hassle_cli.config import CURRENT_BUNDLE_FORMAT, find_bundle_root, load_config
from hassle_cli.render import get_console, safe_render, sanitize_for_terminal

if TYPE_CHECKING:
    from hassle.compiler.errors import CompileError


def _esc(value: object) -> str:
    """Sanitize + escape ``str(value)`` for safe interpolation into a
    rich-markup f-string passed to ``Console.print``.

    Rich's default `Console.print` parses `[...]`-bracketed substrings as
    markup tags -- silently swallowing them (or raising, for a malformed
    tag) if they happen to appear in interpolated data Hassle does not
    control (a bundle's own `CATEGORY` name, an object key, an exception
    message, a validator Finding's text, an HA version string, ...). Every
    call site below that embeds such data inside a still-markup-enabled
    `console.print(f"[style]...{data}...[/style]")` call must route ``data``
    through this first. Static, Hassle-authored text (the surrounding
    `[style]`/`[/style]` tags and plain English) is never escaped -- only the
    dynamic segment. See docs/internals/cli.md for the markup bug this
    discipline exists to prevent.

    Delegates to `hassle_cli.render.safe_render` (the shared choke point
    every remote-string print in this CLI routes through, `plan_render.py`
    included), which ALSO strips C0/C1 control characters before escaping
    markup -- markup-escaping alone does not stop an HA-supplied string from
    carrying a raw ANSI escape sequence (Rich's own control-code stripping
    does not cover ESC either); see that module's docstring.
    """
    return safe_render(value)


def _bundle_root_or_fail(explicit: Path | None = None) -> Path:
    root = explicit or find_bundle_root()
    if root is None:
        click.echo(
            "hassle: no hassle.toml found in this directory or any parent. "
            "Fix: run `hassle init` here, or `cd` into your bundle directory.",
            err=True,
        )
        raise SystemExit(2)
    # Refuse a NEWER major bundle_format before doing ANY work (no partial
    # operation) -- checked here, the single choke point every subcommand
    # except `init`/`login` routes through, so there is no way to reach
    # compile/validate/plan/push logic on an unrecognized format.
    bundle_format = load_config(root).bundle_format
    if bundle_format > CURRENT_BUNDLE_FORMAT:
        click.echo(
            f"hassle: this bundle's bundle_format ({bundle_format}) is NEWER than what "
            f"this CLI build understands ({CURRENT_BUNDLE_FORMAT}). Fix: upgrade Hassle "
            "(`uv tool upgrade hassle` or reinstall from a newer release) before running "
            "any command against this bundle -- nothing has been read or written.",
            err=True,
        )
        raise SystemExit(2)
    return root


def _relative_finding_path(file: str | None, root: Path) -> str | None:
    """`Finding.file` (from `hassle.compiler.spans.SourceSpan`) is always an
    **absolute** path -- captured from CPython's frame `co_filename` at
    compile time (`spans.py`'s module docstring). `hassle validate`'s
    plain-text output doesn't mind (a human reads it in the same terminal
    they ran the command from), but the `--json` contract is consumed by an
    editor extension that may run the CLI from a different mount point/CI
    checkout than the one that produced a snapshot -- bundle-root-relative
    paths are the portable, useful form there, and match every other
    file:line the CLI shows a human elsewhere. Absolute paths outside `root`
    (shouldn't normally happen -- would mean a Finding pointing outside the
    bundle) are left absolute rather than producing a `../../..` mess."""
    if file is None:
        return None
    path = Path(file)
    try:
        return str(path.relative_to(root))
    except ValueError:
        return file


def _report_compile_error(exc: CompileError, root: Path, *, as_json: bool = False) -> NoReturn:
    """Report a `CompileError` the same clean way a tier-2/3 `Finding` is --
    what/where/fix, exit 1, never a raw traceback -- and raise `SystemExit(1)`.

    Shared by every command that compiles the bundle before doing its own
    work (`validate`, and `_build_plan` on behalf of `plan`/`status`/`push`):
    `compile_bundle` runs before any Finding-producing check or plan
    computation even starts, so this is always the earliest possible exit
    point. `as_json` only applies to commands that actually expose a
    `--json` contract (currently just `validate`) -- callers without one
    always pass the default `False`.
    """
    console = get_console()
    span = getattr(exc, "span", None)
    file = _relative_finding_path(span.file, root) if span is not None else None
    line = span.line if span is not None else None
    if as_json:
        import json as _json

        payload = {
            "findings": [
                {
                    "code": type(exc).__name__,
                    "severity": "error",
                    "file": file,
                    "line": line,
                    "message": str(exc),
                    "fix": str(exc),
                }
            ]
        }
        click.echo(_json.dumps(payload))
    else:
        console.print(f"[red]{type(exc).__name__}[/red]: {_esc(exc)}")
    raise SystemExit(1) from exc


def _warn_if_plaintext_http(url: str) -> None:
    """DESIGN §14: warn (never block) when `url` is plain http to a host that
    doesn't look private/local -- see `hassle_cli.http_warning` for why this
    fires every invocation rather than "once"."""
    from hassle_cli.http_warning import plaintext_http_warning

    warning = plaintext_http_warning(url)
    if warning is not None:
        get_console().print(f"[yellow]{_esc(warning)}[/yellow]")


def _require_backend_config(root: Path) -> tuple[str, str]:
    import os

    from hassle_cli.token import TokenResolutionError, resolve_token_or_raise

    # HASSLE_HA_URL + HASSLE_TOKEN env override (same convention as the
    # integration suite's HASSLE_TEST_HA_URL/_TOKEN): lets `run --live`'s one
    # integration test point at a Dockerized HA without needing a hassle.toml
    # ha_url or a keyring entry.
    env_url = os.environ.get("HASSLE_HA_URL")
    if env_url:
        env_token = os.environ.get("HASSLE_TOKEN", "")
        _warn_if_plaintext_http(env_url)
        return env_url, env_token

    config = load_config(root)
    if not config.ha_url:
        click.echo(
            "hassle: no ha_url configured in hassle.toml. "
            "Fix: run `hassle login --url <your-ha-url>` first.",
            err=True,
        )
        raise SystemExit(2)
    try:
        token = resolve_token_or_raise(config.ha_url)
    except TokenResolutionError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(2) from exc
    _warn_if_plaintext_http(config.ha_url)
    return config.ha_url, token


@click.group()
@click.version_option(package_name="hassle-cli", prog_name="hassle")
@click.option(
    "--plain", is_flag=True, default=False, help="Plain-text output (no color/rich formatting)."
)
@click.pass_context
def main(ctx: click.Context, plain: bool) -> None:
    """Hassle: bring your Home Assistant automations under version control."""
    ctx.ensure_object(dict)
    ctx.obj["plain"] = plain


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@main.command()
@click.option("--path", type=click.Path(path_type=Path), default=None)
def init(path: Path | None) -> None:
    """Scaffold a fresh bundle directory."""
    root = (path or Path.cwd()).resolve()
    steps = init_cmd.init_bundle(root)
    console = get_console()
    if steps:
        for step in steps:
            console.print(f"[green]+[/green] {step}")
    else:
        console.print("[dim]already initialized[/dim]")


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@main.command()
@click.option("--url", required=True, help="HA base URL, e.g. http://homeassistant.local:8123")
@click.option(
    "--token",
    envvar="HASSLE_TOKEN",
    prompt="Long-lived access token",
    hide_input=True,
    help=(
        "A long-lived access token. Optional -- prefer leaving it out: precedence is "
        "--token (lands in shell history and `ps`/`/proc/<pid>/cmdline` -- only for "
        "scripts/CI) > HASSLE_TOKEN env var > an interactive hidden prompt (the "
        "documented path; never echoed, never on the command line)."
    ),
)
def login(url: str, token: str) -> None:
    """Validate a token against HA and store it in the system keyring."""
    from hassle.backend.errors import HaAuthError, HaConnectionError
    from hassle_cli.commands.login import DirectBackend
    from hassle_cli.token import store_token

    console = get_console()
    _warn_if_plaintext_http(url)
    try:
        with DirectBackend(url, token):
            pass
    except HaAuthError as exc:
        console.print(
            f"[red]hassle login: authentication failed (401) against "
            f"{_esc(url)}: {_esc(exc)}[/red]\n"
            "Fix: double-check the long-lived access token (Profile -> Security -> "
            "Long-Lived Access Tokens in HA) and re-run `hassle login`."
        )
        raise SystemExit(1) from exc
    except HaConnectionError as exc:
        console.print(
            f"[red]hassle login: could not connect to {_esc(url)}: {_esc(exc)}[/red]\n"
            "Fix: check the URL is reachable from this machine."
        )
        raise SystemExit(1) from exc

    store_token(url, token)
    from hassle_cli.config import find_bundle_root, persist_ha_url

    root = find_bundle_root(Path.cwd()) or Path.cwd()
    persist_ha_url(root, url)
    console.print(
        f"[green]hassle login: token verified and stored for {_esc(url)}[/green]\n"
        f"[dim]ha_url written to {root / 'hassle.toml'} (token stays in the keyring)[/dim]"
    )


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------


@main.command()
@click.option("--allow-dirty", is_flag=True, default=False)
def pull(allow_dirty: bool) -> None:
    """Merge UI-side edits into the working tree (never writes to HA)."""
    from hassle.ir.keys import OBJECT_KINDS
    from hassle.sync.plan import compute_plan
    from hassle.sync.pull_apply import (
        DecompiledBatchDoesNotCompileError,
        DecompiledValueMismatchError,
        apply_pull_with_decompiler,
    )
    from hassle.sync.source_writer import (
        SourceWriteOutsideBundleRootError,
        SplicingSourceWriter,
        SymlinkWriteRefusedError,
    )
    from hassle_cli import backend_factory
    from hassle_cli.doctor import find_committed_tokens
    from hassle_cli.git_support import commit_message_for_pull

    console = get_console()
    root = _bundle_root_or_fail()

    committed = find_committed_tokens(root)
    if committed:
        path, reason = committed[0]
        console.print(
            f"[red]hassle pull: found a possible committed secret in {_esc(path.name)} "
            f"({_esc(reason)}). Fix: remove it, run `hassle login` to store the token in the "
            "system keyring instead, and rotate the exposed token in HA.[/red]"
        )
        raise SystemExit(1)

    is_git = git_support.is_git_repo(root)
    if is_git and not allow_dirty and not git_support.is_clean(root):
        console.print(
            "[red]hassle pull: working tree is not clean. UI-side changes must land as "
            "their own commit, never tangled with in-progress edits. "
            "Fix: commit or stash your changes, or pass --allow-dirty.[/red]"
        )
        raise SystemExit(1)
    if not is_git:
        console.print(
            "[yellow]hassle pull: this directory is not a git repository -- pulling will "
            "still work, but you won't get a separate commit for UI-side changes. "
            "Fix (optional): `git init` (or `hassle init` in a fresh directory).[/yellow]"
        )

    # DESIGN §5.6/§6: a bundle that never ran `hassle init` (or predates this
    # scaffolding) still gets `lib/README.md`/`tests/README.md` on its first
    # pull, same as init -- idempotent, never overwrites an existing file.
    from hassle_cli.init_cmd import (
        scaffold_agent_docs,
        scaffold_lib_and_tests_readmes,
        scaffold_pyproject_file,
        scaffold_vscode_settings,
    )

    scaffold_lib_and_tests_readmes(root)
    scaffold_vscode_settings(root)
    scaffold_agent_docs(root)
    # Same idempotent-scaffold contract -- a bundle predating the
    # bundle-as-uv-project change gets `pyproject.toml` on its first pull
    # too, never overwriting one the user already created.
    for pyproject_step in scaffold_pyproject_file(root):
        console.print(f"[dim]{pyproject_step}[/dim]")

    ha_url, token = _require_backend_config(root)
    config = load_config(root)
    manifest = manifest_io.load_manifest(root)

    # DESIGN §8.2 amendment: an `ignore` glob added since the last sync leaves
    # stale manifest entries for now-ignored keys -- drop them (no HA write)
    # before planning, and tell the user (§8.1's migration notice).
    from hassle_cli.ignore_filter import apply_ignore_globs, migrate_manifest_for_ignores

    migration = migrate_manifest_for_ignores(manifest, ignore_globs=config.ignore)
    manifest = migration.manifest
    for dropped_key in migration.dropped_keys:
        console.print(
            f"[yellow]hassle pull: {dropped_key} matches an `ignore` glob in hassle.toml -- "
            "dropped from the manifest (HA untouched); it is no longer managed by Hassle.[/yellow]"
        )

    from contextlib import nullcontext

    # Visible heartbeat for the slow compile+fetch phase -- a big bundle plus
    # a slow HA link used to look hung here.
    heartbeat = (
        console.status("pulling from Home Assistant...") if _interactive() else nullcontext()
    )
    with heartbeat:
        local_objects, compile_result = bundle_ops.compile_local_objects(root)

        with backend_factory.connect(ha_url, token) as backend:
            remote_objects = bundle_ops.remote_objects_from_backend(backend, list(OBJECT_KINDS))
            # DESIGN §9.2: the registry snapshot is refreshed on every pull
            # (tier-2/3 validation and stubs depend on it). Best-effort:
            # skipped when the backend lacks the registry surface. Also drives
            # DESIGN §7.3's category-based placement for newly-adopted
            # objects (below).
            registry_snapshot = _write_registry_snapshot(backend, root)

    # `typings/hassle/registry/__init__.pyi` is regenerated from the
    # just-refreshed registry snapshot on every pull (write-if-changed, same
    # convention as `_write_registry_snapshot` itself), so stubs can never go
    # stale -- a bundle that never ran `hassle stubs` by hand used to have NO
    # `typings/` dir at all, even after many pulls. `hassle stubs` stays
    # available for a manual, on-demand refresh. Best-effort: skipped when the
    # backend lacked the registry surface (`registry_snapshot is None`, same
    # guard the category-placement code below uses). See docs/internals/cli.md
    # for what the three generated stub files are and why.
    if registry_snapshot is not None:
        stub_changed = _stub_changed(registry_snapshot, root)
        stub_path = _write_stub_if_changed(registry_snapshot, root)
        if stub_changed:
            # Root-relative (matches `scaffold_pyproject_file`'s "wrote
            # pyproject.toml" convention, `hassle_cli.init_cmd`) -- shorter,
            # never wraps mid-word in a narrow CI console, and nicer than an
            # absolute /tmp-in-tests or /home/user path in real UX.
            console.print(f"[cyan]hassle pull: wrote {_esc(stub_path.relative_to(root))}[/cyan]")

    # An old-layout bundle (the retired `automations/`/`scripts/`/`helpers/`
    # per-kind trees) is migrated into the category-first, root-level layout
    # on this pull -- BEFORE the rest of the pull pipeline runs, so every
    # downstream step (plan, manifest advance) sees each migrated object
    # already at its new home. Never touches HA or the manifest itself
    # (source-only reorganization, DESIGN §7.3/§8.2: the plan diffs on
    # compiled-JSON hash, never on `source_path`, so this is a pure no-op for
    # compute_plan). See docs/internals/cli.md for the full migration design.
    from hassle_cli.layout_migration import bundle_has_old_layout, migrate_old_layout

    if bundle_has_old_layout(root):
        new_paths = {
            key: bundle_ops.default_source_path(key, registry=registry_snapshot)
            for key in compile_result.objects
        }
        migration_report = migrate_old_layout(
            root, compile_result, registry=registry_snapshot, new_source_path_for=new_paths
        )
        for move in migration_report.moves:
            console.print(
                f"[cyan]  migrated[/cyan]  {move.object_key}: {move.old_path} -> {move.new_path}"
            )
        for deleted in migration_report.deleted_files:
            console.print(f"[cyan]   deleted[/cyan]  {deleted} (no content left after migration)")
        for orphan in migration_report.orphaned_category_globals:
            # markup=False + no [...]-bearing f-string: `orphan.path`/
            # `orphan.category` are bundle-controlled data, never trusted as
            # rich markup (see docs/internals/cli.md).
            console.print(
                f"  kept {orphan.path} with an orphaned CATEGORY = {orphan.category!r} global "
                "(no longer category-shaped under the new layout -- clean it up by hand; "
                "any now-unused import left in that file is also left as-is for you to clean up)",
                style="yellow",
                markup=False,
            )
        if migration_report.migrated:
            # The working tree just changed under compile_result's feet --
            # recompile so the rest of this pull sees each object's NEW
            # source_path (source_path_for below reads decl_span_for, which
            # is only valid against the just-compiled tree).
            local_objects, compile_result = bundle_ops.compile_local_objects(root)
            from hassle_cli.config import CURRENT_BUNDLE_FORMAT, bump_bundle_format

            if load_config(root).bundle_format < CURRENT_BUNDLE_FORMAT:
                bump_bundle_format(root)
                console.print(
                    f"[cyan]hassle pull: bundle_format upgraded to {CURRENT_BUNDLE_FORMAT} "
                    "(category-first layout).[/cyan]"
                )

    ignore_result = apply_ignore_globs(
        local_objects=local_objects, remote_objects=remote_objects, ignore_globs=config.ignore
    )
    for finding in ignore_result.findings:
        console.print(f"[yellow]hassle pull: {_esc(finding)}[/yellow]")

    plan = compute_plan(
        manifest=manifest,
        local_objects=ignore_result.local_objects,
        remote_objects=ignore_result.remote_objects,
    )
    source_paths = bundle_ops.build_source_paths(
        root, compile_result, [e.object_key for e in plan.entries], registry=registry_snapshot
    )
    plan = plan.model_copy(
        update={
            "entries": [
                entry.model_copy(update={"source_path": source_paths.get(entry.object_key)})
                for entry in plan.entries
            ]
        }
    )

    # A mixed-kind category file that used to be shared by objects of
    # different category-registry scopes may have split this pull, if
    # HA-side renames made those scopes' category names diverge --
    # placement itself already handles the split correctly (each
    # object is placed by its OWN scope, independently); this only detects
    # that it happened and warns, naming the scopes, never guessing a winner.
    # Checked over EVERY manifest-tracked object (not just this pull's plan
    # entries): a pure category-registry rename never changes an object's
    # compiled hash, so `compute_plan` reports "nothing to merge" for it --
    # divergence can happen with no other plan action at all.
    previous_source_paths = {key: entry.source for key, entry in manifest.objects.items()}
    # Deliberately `default_source_path` (the fresh, category-derived
    # placement), never `source_path_for`/`source_paths` above (which read
    # the object's EXISTING declaration site -- unchanged for an object no
    # plan action touched, so it could never reveal a divergence on its own).
    recomputed_source_paths = {
        key: bundle_ops.default_source_path(key, registry=registry_snapshot)
        for key in manifest.objects
        if registry_snapshot is not None
    }
    for warning in bundle_ops.category_divergence_warnings(
        previous_source_paths, recomputed_source_paths
    ):
        console.print(f"[yellow]{_esc(warning)}[/yellow]")

    # The REAL splicer-backed writer: REFRESH/DROP touch exactly one object's
    # statement, so sibling objects sharing a source file survive (no local
    # or UI edit is ever silently lost -- the `test_pull_refresh_splice.py`
    # regression: `WholeFileSourceWriter` here rewrote the whole file per
    # refreshed object). The marker date is stamped at this CLI edge (core
    # logic never calls a clock; the CLI edge is the one documented exception,
    # same as `manifest_io`'s `last_synced`). `bundle_root=root` is this
    # writer's defense-in-depth containment check (`hassle.sync.source_writer`
    # module docstring) -- every write it performs for this pull is now
    # refused if it would land outside `root`, or if the destination is a
    # symlink (dangling or not).
    from datetime import UTC, datetime

    writer = SplicingSourceWriter(
        updated_on=datetime.now(UTC).strftime("%Y-%m-%d"), bundle_root=root
    )
    # Real HA display names for every categorized object in this plan, keyed
    # by destination path -- `apply_pull_with_decompiler`
    # only actually emits `CATEGORY` for a path that doesn't exist on disk
    # yet (a brand-new category file), so harmlessly including
    # already-existing destinations here is fine. `registry_snapshot` is
    # `None` when the backend lacks the registry surface at all (best-effort,
    # same guard `_write_registry_snapshot` itself uses) -- category
    # placement/display names simply aren't available in that case.
    category_display_names = (
        bundle_ops.category_display_names_for_paths(
            [e.object_key for e in plan.entries], registry_snapshot
        )
        if registry_snapshot is not None
        else {}
    )
    # `apply_pull_with_decompiler` self-checks every ADOPT destination
    # together BEFORE writing any of them (`hassle.sync.pull_apply` module
    # docstring) -- a decompiler coordination bug here is caught pre-write,
    # so nothing from this pull's adopt set has touched disk yet. Distinct
    # from the post-write backstop below (which also
    # covers REFRESH's single-object splice, the one path the pre-write
    # self-check can't cover -- see that module's docstring).
    try:
        result = apply_pull_with_decompiler(
            plan,
            writer,
            category_display_names=category_display_names,
            snapshot=registry_snapshot,
        )
    except (DecompiledBatchDoesNotCompileError, DecompiledValueMismatchError) as exc:
        console.print(
            f"[bold red]hassle pull: {_esc(exc)}[/bold red]\n"
            "[bold red]This is a bug in Hassle's decompiler, not a mistake in your HA "
            "configuration. Fix: please report this, then re-run `hassle pull` (or "
            "`--allow-dirty` if needed) once a fix lands -- nothing was written for the "
            "affected file(s), so there is nothing to clean up.[/bold red]"
        )
        raise SystemExit(1) from exc
    except (SymlinkWriteRefusedError, SourceWriteOutsideBundleRootError) as exc:
        # Defense-in-depth (`hassle.sync.source_writer` module docstring):
        # not reachable from real HA data today (category/entity names are
        # slugified before they ever become a path component), but a stale
        # manifest or a declaration span outside the bundle could still
        # trigger it -- the error itself is already what/where/fix.
        console.print(f"[bold red]hassle pull: {_esc(exc)}[/bold red]")
        raise SystemExit(1) from exc

    # A loop-splice reconcile -- `writer.reconcile_warnings`
    # (SplicingSourceWriter, `hassle.sync.source_writer`) is populated when a
    # REFRESH's append path fired for a metaprogrammed object (a compile-time
    # loop, so the splicer had no single literal statement to replace) -- the
    # very next compile of this bundle will raise `DuplicateObjectError`
    # (which also names this same reconcile flow) until the user reconciles
    # it by hand. `markup=False` + no f-string interpolation into a
    # `[...]`-bearing string: the warning text embeds a bundle-relative path
    # and object key, neither escaped for rich markup -- interpolated
    # user/bundle data is never trusted as markup (see docs/internals/cli.md).
    # `sanitize_for_terminal`: the embedded object key can be HA-supplied
    # (an id) -- `markup=False` stops Rich from parsing `[tag]`s but not a
    # raw ANSI escape from reaching the terminal (`hassle_cli.render` module
    # docstring).
    for warning in writer.reconcile_warnings:
        console.print(
            f"hassle pull: {sanitize_for_terminal(warning)}", style="yellow", markup=False
        )

    # Safety backstop: pull just wrote real DSL source from the decompiler --
    # recompile the bundle it produced before trusting it (manifest
    # bookkeeping below establishes the new three-way-merge baseline, so it
    # must not run against a bundle that doesn't even compile). A
    # coordination bug in the decompiler (a caller rewritten to call a script
    # whose own emitted signature can't accept it) raises here instead of
    # silently leaving the user with a broken bundle discovered only on their
    # next `hassle test`/`hassle push`. Files are left in place (never rolled
    # back) -- the user needs them to file a useful bug report, and the fix
    # is always just a `hassle pull --allow-dirty` once it lands.
    #
    # Also compares VALUES, not just "does it compile": every REFRESH/ADOPT
    # entry's original stored `remote` config is compared against what the
    # bundle just written recompiles to, via
    # `hassle.sync.pull_apply.values_match` (canonical-JSON value comparison)
    # -- the single shared comparison this backstop and the pre-write
    # self-check both use, so they can never disagree. See
    # docs/internals/cli.md for why "does it compile" alone isn't enough.
    try:
        _, post_write_result = bundle_ops.compile_local_objects(root)
    except Exception as exc:
        from hassle.compiler.errors import DuplicateObjectError

        # A `DuplicateObjectError` here for an object key this same pull
        # already flagged in `writer.reconcile_warnings` is the EXPECTED
        # consequence of a loop-splice reconcile (module docstring: the
        # append path landed a UI edit next to its metaprogrammed original)
        # -- never a Hassle bug. `DuplicateObjectError.object_key` names
        # exactly which object collided.
        if isinstance(exc, DuplicateObjectError) and any(
            exc.object_key in warning for warning in writer.reconcile_warnings
        ):
            console.print(
                f"hassle pull: {sanitize_for_terminal(str(exc))}", style="bold red", markup=False
            )
            console.print(
                "hassle pull: this is expected, not a Hassle bug -- see the reconcile "
                "warning above. The files just written are left in place; reconcile the "
                "duplicate id by hand, then re-run `hassle validate`.",
                style="bold red",
            )
            raise SystemExit(1) from exc

        console.print(
            f"[bold red]hassle pull: the bundle just written to {_esc(root)} does not compile "
            f"({_esc(type(exc).__name__)}: {_esc(exc)}). This is a bug in Hassle's "
            "decompiler, not a mistake in your HA configuration -- the files just written "
            "are left in place for you to inspect. Fix: please report this (include the "
            "error above and, if possible, the object(s) involved) at "
            "https://github.com/KeatonTech/hassle/issues; once a fix lands, "
            "`hassle pull --allow-dirty` is safe to re-run and will overwrite the broken "
            "file(s).[/bold red]"
        )
        raise SystemExit(1) from exc

    from hassle.sync.models import ManifestEntry, PlanAction
    from hassle.sync.pull_apply import values_match

    mismatched_keys = [
        entry.object_key
        for entry in plan.entries
        if entry.action in (PlanAction.REFRESH, PlanAction.ADOPT)
        and entry.remote is not None
        and entry.object_key in post_write_result.objects
        and not values_match(post_write_result.objects[entry.object_key], entry.remote)
    ]
    if mismatched_keys:
        keys = _esc(", ".join(sorted(mismatched_keys)))
        console.print(
            f"[bold red]hassle pull: the bundle just written to {_esc(root)} does not "
            f"reproduce the original stored configuration for object(s): {keys} (it "
            "compiles, but does not recompile to the same value). This is a bug in "
            "Hassle's decompiler, not a mistake "
            "in your HA configuration -- the files just written are left in place for you to "
            "inspect. Fix: please report this (include the object(s) listed) at "
            "https://github.com/KeatonTech/hassle/issues; once a fix lands, "
            "`hassle pull --allow-dirty` is safe to re-run and will overwrite the broken "
            "file(s).[/bold red]"
        )
        raise SystemExit(1)

    pull_actions = (PlanAction.REFRESH, PlanAction.ADOPT, PlanAction.DROP)
    for entry in plan.entries:
        if entry.action in pull_actions:
            console.print(f"[cyan]{entry.action.value:>10}[/cyan]  {_esc(entry.object_key)}")
    if result.conflicts:
        for conflict in result.conflicts:
            console.print(
                f"[bold red]conflict[/bold red]  {_esc(conflict.object_key)} (see written markers)"
            )

    # Pull mutates only the working tree (apply_pull never touches HA or the
    # manifest, DESIGN §8.3) -- but a `refresh`/`adopt`/`drop` DOES establish
    # (or remove) this object's three-way-merge baseline, or the very next
    # `plan` would see "no base" and perpetually re-propose the same
    # adopt/create. Advancing the manifest for pull-side actions is this
    # CLI's own bookkeeping (no core-layer test covers it: `apply_pull`
    # deliberately never accepts a manifest).
    from hassle.ir.canonical import sha256_hash, storage_canonical
    from hassle.sync.category_move import local_category_for_source_path

    new_objects = dict(manifest.objects)
    for entry in plan.entries:
        if entry.action in (PlanAction.REFRESH, PlanAction.ADOPT):
            assert entry.remote is not None
            existing = manifest.objects.get(entry.object_key)
            source_path = source_paths.get(entry.object_key)
            new_objects[entry.object_key] = ManifestEntry(
                source=source_path,
                compiled_hash=sha256_hash(storage_canonical(entry.kind, entry.remote)),
                kind=existing.kind if existing is not None else "dsl",
                # The base category this object was JUST placed under on this
                # pull -- so the very next push's category-on-move sync
                # (`hassle.sync.category_move`) starts from the right base
                # instead of `None` (which would misfire as "local changed"
                # even though nothing moved yet).
                category=local_category_for_source_path(entry.kind, source_path),
            )
        elif entry.action is PlanAction.DROP:
            new_objects.pop(entry.object_key, None)
    # `migration.dropped_keys` forces a save even when pull-side actions alone
    # wouldn't have changed anything -- otherwise a bundle whose only change
    # this pull is "an `ignore` glob newly matches a manifest entry" never
    # gets the migrated (smaller) manifest written to disk.
    if new_objects != manifest.objects or migration.dropped_keys:
        from hassle.sync.models import Manifest

        new_manifest = Manifest(
            synced_at=manifest_io.now_iso(), ha_version=manifest.ha_version, objects=new_objects
        )
        manifest_io.save_manifest(root, new_manifest)

    summary = {entry.action.value: 1 for entry in plan.entries if entry.action in pull_actions}
    if any(entry.action in pull_actions for entry in plan.entries):
        console.print(f"[dim]{commit_message_for_pull(summary)}[/dim]")
    else:
        console.print("[dim]pull: nothing to merge[/dim]")


# ---------------------------------------------------------------------------
# plan / status
# ---------------------------------------------------------------------------


def _build_plan_with_compile_result(root: Path):
    """`_build_plan`'s implementation, additionally returning the
    `CompileResult` the plan was computed from (`push` needs it to build
    `apply_plan`'s `category_overrides` from the bundle's `CATEGORY` globals;
    `plan`/`status` just discard the second value via the `_build_plan`
    wrapper below)."""
    from hassle.compiler.errors import CompileError
    from hassle.ir.keys import OBJECT_KINDS
    from hassle.sync.plan import compute_plan
    from hassle_cli import backend_factory
    from hassle_cli.ignore_filter import apply_ignore_globs, migrate_manifest_for_ignores

    ha_url, token = _require_backend_config(root)
    config = load_config(root)
    manifest = migrate_manifest_for_ignores(
        manifest_io.load_manifest(root), ignore_globs=config.ignore
    ).manifest
    try:
        local_objects, compile_result = bundle_ops.compile_local_objects(root)
    except CompileError as exc:
        # `plan`/`status`/`push` all share this helper and all compile the
        # bundle before doing anything else -- report a compile-time error
        # the same clean way `validate` does (what/where/fix, exit 1, no raw
        # traceback) instead of letting it escape uncaught. None of these
        # three commands has a `--json` mode, so `as_json` stays at its
        # default (plain-text only).
        _report_compile_error(exc, root)
    with backend_factory.connect(ha_url, token) as backend:
        remote_objects = bundle_ops.remote_objects_from_backend(backend, list(OBJECT_KINDS))
    ignore_result = apply_ignore_globs(
        local_objects=local_objects, remote_objects=remote_objects, ignore_globs=config.ignore
    )
    the_plan = compute_plan(
        manifest=manifest,
        local_objects=ignore_result.local_objects,
        remote_objects=ignore_result.remote_objects,
    )
    # `source_path` drives category write-back on CREATE (`hassle.sync.
    # category_writeback`, via `apply_plan`) -- a CREATE always has a real
    # bundle source (it's local-only at plan time), so no registry snapshot
    # is needed here (unlike pull's adopt-placement fallback, which needs one
    # for objects that have never been declared in the bundle at all).
    source_paths = bundle_ops.build_source_paths(
        root, compile_result, [e.object_key for e in the_plan.entries]
    )
    the_plan = the_plan.model_copy(
        update={
            "entries": [
                entry.model_copy(update={"source_path": source_paths.get(entry.object_key)})
                for entry in the_plan.entries
            ]
        }
    )
    return the_plan, compile_result


def _build_plan(root: Path):
    the_plan, _compile_result = _build_plan_with_compile_result(root)
    return the_plan


@main.command()
@click.pass_context
def plan(ctx: click.Context) -> None:
    """Preview the three-way sync plan (DESIGN §8.2)."""
    from hassle_cli.plan_render import render_plan

    root = _bundle_root_or_fail()
    the_plan = _build_plan(root)
    console = get_console(force_plain=ctx.obj.get("plain", False))
    render_plan(console, the_plan)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Plan preview + git status in one view (DESIGN §8.4)."""
    from hassle_cli.plan_render import render_plan

    root = _bundle_root_or_fail()
    the_plan = _build_plan(root)
    console = get_console(force_plain=ctx.obj.get("plain", False))
    render_plan(console, the_plan)
    if git_support.is_git_repo(root):
        result = subprocess.run(
            ["git", "status", "--short", "--", "."],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        console.print("[bold]git status:[/bold]")
        console.print(result.stdout or "[dim](clean)[/dim]")
    else:
        console.print("[yellow]not a git repository[/yellow]")


def _interactive() -> bool:
    """A human is at the terminal: prompts beat flags. Both ends must be
    TTYs -- piped stdin or redirected stdout means scripts/CI, where behavior
    stays flag-driven and byte-compatible."""
    import sys

    return sys.stdin.isatty() and sys.stdout.isatty()


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


@main.command()
@click.option("--yes", is_flag=True, default=False)
@click.option(
    "--accept-local",
    "accept_local",
    multiple=True,
    help="Object key(s) to resolve using the local version.",
)
@click.option(
    "--accept-remote",
    "accept_remote",
    multiple=True,
    help="Object key(s) to resolve using the remote version.",
)
@click.pass_context
def push(
    ctx: click.Context, yes: bool, accept_local: tuple[str, ...], accept_remote: tuple[str, ...]
) -> None:
    """Plan, confirm, and apply to HA (DESIGN §8.2)."""
    from hassle.sync.apply import apply_plan
    from hassle.sync.models import PlanAction, PlanEntry
    from hassle_cli import backend_factory
    from hassle_cli.plan_render import plan_summary, render_plan

    console = get_console(force_plain=ctx.obj.get("plain", False))
    root = _bundle_root_or_fail()
    if _interactive() and not ctx.obj.get("plain", False):
        # The visible heartbeat for the slow phase (compile + remote fetch):
        # without it a big bundle looks hung.
        with console.status("planning against Home Assistant..."):
            the_plan, compile_result = _build_plan_with_compile_result(root)
    else:
        the_plan, compile_result = _build_plan_with_compile_result(root)
    # `category_overrides` (bundle-relative source path -> exact display
    # name) from every file's `CATEGORY` global that actually
    # slugifies to its own file stem; a mismatched file's global is left out
    # (never trusted) and instead reported here as its own warning, alongside
    # a `category-slug-mismatch` Finding from `hassle validate`/`plan`.
    category_overrides, category_global_warnings = bundle_ops.category_overrides_and_warnings(
        compile_result
    )
    for warning in category_global_warnings:
        console.print(f"[yellow]{_esc(warning)}[/yellow]")

    adopts = the_plan.entries_with_action(PlanAction.ADOPT)
    if adopts:
        # Adopt rows look actionable but push ignores them -- they are
        # remote objects nothing local owns (a common point of confusion).
        console.print(
            f"[yellow]{len(adopts)} object(s) exist in HA that this bundle doesn't "
            "manage (the `adopt` rows) -- not touched by push. `hassle pull` would "
            "import them into the bundle; delete them in the HA UI if they're "
            "unwanted (e.g. duplicates).[/yellow]"
        )

    unresolved_conflicts = [
        e
        for e in the_plan.entries_with_action(PlanAction.CONFLICT)
        if e.object_key not in accept_local and e.object_key not in accept_remote
    ]
    plan_already_rendered = False
    if unresolved_conflicts and _interactive() and not yes:
        # Resolve each conflict at the prompt instead of demanding
        # --accept-local/--accept-remote round trips.
        render_plan(console, the_plan)
        plan_already_rendered = True
        accept_local, accept_remote = list(accept_local), list(accept_remote)
        for entry in unresolved_conflicts:
            choice = click.prompt(
                f"{entry.object_key}: keep [l]ocal (push it), keep [r]emote, or [a]bort",
                type=click.Choice(["l", "r", "a"]),
                show_choices=False,
            )
            if choice == "a":
                console.print("[bold red]hassle push: aborted, nothing applied.[/bold red]")
                raise SystemExit(1)
            (accept_local if choice == "l" else accept_remote).append(entry.object_key)
        unresolved_conflicts = []
    if unresolved_conflicts:
        render_plan(console, the_plan)
        console.print(
            "[bold red]hassle push: unresolved conflict(s). Fix: re-run with "
            "--accept-local KEY or --accept-remote KEY for each conflicting object "
            "key above (or pull-and-merge in the editor, then push again).[/bold red]"
        )
        raise SystemExit(1)

    resolved_entries = []
    for entry in the_plan.entries:
        if entry.action is PlanAction.CONFLICT:
            if entry.object_key in accept_local:
                # "Keep local" means push whatever the LOCAL side of the
                # conflict is -- which may be a deletion (local is None) or a
                # recreate (remote is None), not only an edit. Hardcoding
                # UPDATE here crashed mid-apply on `entry.local is not None`
                # for a locally-deleted object -- regression-tested.
                if entry.local is None:
                    resolved_action = PlanAction.DELETE
                elif entry.remote is None:
                    resolved_action = PlanAction.CREATE
                else:
                    resolved_action = PlanAction.UPDATE
                entry = entry.model_copy(update={"action": resolved_action})
            elif entry.object_key in accept_remote:
                continue  # keep remote as-is: nothing to push for this key
        resolved_entries.append(entry)
    from hassle.sync.models import Plan

    resolved_plan = Plan(entries=resolved_entries)

    # Deletion gate over the RESOLVED plan: a keep-local conflict resolution
    # can INTRODUCE a deletion, and DESIGN §8.2 says deletions always require
    # the confirm step (or --yes) -- the gate must not consult the
    # pre-resolution plan where that object was still a CONFLICT row.
    has_deletions = bool(resolved_plan.entries_with_action(PlanAction.DELETE))
    if not yes and _interactive():
        # Plan-then-confirm at the terminal: deletions default to NO (they
        # need a deliberate yes), everything else defaults to YES.
        if not plan_already_rendered:
            render_plan(console, the_plan)
        prompt = (
            "This plan includes deletion(s). Apply it?"
            if has_deletions
            else f"Apply? ({plan_summary(the_plan)})"
        )
        if not click.confirm(prompt, default=not has_deletions):
            console.print("[bold red]hassle push: declined, nothing applied.[/bold red]")
            raise SystemExit(1)
    elif has_deletions and not yes:
        render_plan(console, the_plan)
        console.print(
            "[bold red]hassle push: this plan includes deletion(s), which require "
            "explicit confirmation. Fix: re-run with --yes to apply.[/bold red]"
        )
        raise SystemExit(1)

    ha_url, token = _require_backend_config(root)
    manifest = manifest_io.load_manifest(root)

    def _progress(index: int, total: int, entry: PlanEntry) -> None:
        # One honest line per applied entry -- TTY or not -- so a long apply
        # is visibly alive.
        console.print(f"[{index}/{total}] {entry.action.value} {_esc(entry.object_key)}")

    with backend_factory.connect(ha_url, token) as backend:
        result = apply_plan(
            resolved_plan,
            backend,
            manifest,
            synced_at=manifest_io.now_iso(),
            category_overrides=category_overrides,
            on_progress=_progress,
        )

    if not result.succeeded:
        if result.failure_message:
            console.print(f"[bold red]hassle push: {_esc(result.failure_message)}[/bold red]")
        console.print(
            f"[bold red]hassle push: apply failed/aborted: {_esc(result.outcomes)}[/bold red]"
        )
        raise SystemExit(1)

    if result.manifest is not None:
        # accept-remote resolutions (flag or interactive [r]) never reach
        # `apply_plan` -- there is nothing to push for them -- but they DO
        # resolve the conflict, so the manifest base must advance or the
        # IDENTICAL conflict re-surfaces on every subsequent plan forever
        # (false conflicts train the user to stop reading conflict prompts,
        # defeating the "no local or UI edit is ever silently lost" rule). A
        # kept remote is a
        # remote-side edit accepted as-is: record base := the LOCAL side's
        # canonical hash, so the next plan reads the object as `refresh`
        # (pull-side; a `push --yes` never clobbers the kept remote, and
        # `hassle pull` reconciles the bundle). A locally-DELETED object
        # resolved to keep-remote instead drops its manifest entry entirely:
        # nothing local claims it anymore, so it re-plans as `adopt`.
        new_manifest = result.manifest
        accepted_remote = [
            entry
            for entry in the_plan.entries
            if entry.action is PlanAction.CONFLICT and entry.object_key in accept_remote
        ]
        if accepted_remote:
            from hassle.ir.canonical import sha256_hash, storage_canonical
            from hassle.sync.models import ManifestEntry

            new_objects = dict(new_manifest.objects)
            for entry in accepted_remote:
                if entry.local is None:
                    new_objects.pop(entry.object_key, None)
                    continue
                existing = new_objects.get(entry.object_key)
                new_objects[entry.object_key] = ManifestEntry(
                    source=existing.source if existing is not None else None,
                    compiled_hash=sha256_hash(storage_canonical(entry.kind, entry.local)),
                    kind=existing.kind if existing is not None else "dsl",
                    entry_id=existing.entry_id if existing is not None else None,
                    category=existing.category if existing is not None else None,
                )
            new_manifest = new_manifest.model_copy(update={"objects": new_objects})
        manifest_io.save_manifest(root, new_manifest)

    # Category write-back warnings are metadata-only (no local or UI edit is
    # ever silently lost) -- the push already succeeded (checked above);
    # these are printed, never fatal.
    for warning in result.category_warnings:
        console.print(f"[yellow]{_esc(warning)}[/yellow]")

    # Category-on-move conflicts (never silently resolved in either
    # direction) are printed too, never fatal for a push that otherwise
    # succeeded -- the object's own content update already applied; only its
    # category grouping is left exactly as it was pending the user resolving
    # which side should win.
    for conflict_message in result.category_conflicts:
        console.print(f"[bold red]{_esc(conflict_message)}[/bold red]")

    summary = plan_summary(resolved_plan)
    console.print(f"[green]hassle push: applied {sum(summary.values())} change(s)[/green]")
    console.print(f"[dim]{git_support.commit_message_for_plan(summary)}[/dim]")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit findings as JSON (the VS Code extension's Problems-pane contract).",
)
def validate(as_json: bool) -> None:
    """Compile + validate the bundle offline (DESIGN §9 tiers 1-3).

    ``--json`` prints exactly one JSON object on stdout --
    ``{"findings": [{code, severity, file, line, message, fix}, ...]}`` --
    regardless of exit code, and never any rich/plain-text banner lines
    (an editor extension parses this stdout directly). This is the schema
    `hassle_cli.tests.test_cli_commands::test_validate_json_reports_findings_with_stable_schema`
    and the VS Code extension's `findingsSchema.ts` both snapshot-test --
    field-for-field, it mirrors `hassle.registry.finding.Finding`.
    """
    from hassle.compiler.bundle import compile_bundle
    from hassle.compiler.errors import CompileError
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    console = get_console()
    root = _bundle_root_or_fail()
    registry_path = root / ".hassle" / "registry.json"
    try:
        result = compile_bundle(root)
    except CompileError as exc:
        # A compile-time error (e.g. a template_number/template_select
        # missing its required set_value=/select_option=) must be reported
        # the same clean way a tier-2/3 Finding is -- not let the exception
        # escape as a raw traceback. `compile_bundle` runs before any
        # Finding-producing check even starts, so this is the earliest
        # possible exit point. Shared with `plan`/`status`/`push` via
        # `_build_plan`.
        _report_compile_error(exc, root, as_json=as_json)
    skip_notice: str | None = None
    if registry_path.is_file():
        snapshot = RegistrySnapshot.load(registry_path)
        manifest = manifest_io.load_manifest(root)
        adopted = frozenset(manifest.objects) if manifest else frozenset()
        findings = validate_bundle(result, snapshot, adopted_helper_keys=adopted)
    else:
        findings = []
        skip_notice = (
            "hassle validate: no .hassle/registry.json found -- skipping tier-2/3 "
            "checks (entity/service/purpose-vocabulary references). Fix: run `hassle pull` "
            "or `hassle stubs --refresh` once you have HA credentials."
        )
        if not as_json:
            console.print(f"[yellow]{skip_notice}[/yellow]")

    if as_json:
        import json as _json

        payload = {
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "file": _relative_finding_path(f.file, root),
                    "line": f.line,
                    "message": f.message,
                    "fix": f.fix,
                }
                for f in findings
            ]
        }
        click.echo(_json.dumps(payload))
        if findings:
            raise SystemExit(1)
        return

    if not findings:
        console.print("[green]hassle validate: no findings[/green]")
        return

    for finding in findings:
        console.print(f"[red]{_esc(finding.code)}[/red]: {_esc(finding)}")
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------


@main.command(name="test")
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
def test_cmd(pytest_args: tuple[str, ...]) -> None:
    """Run pytest with the Hassle simulator plugin preloaded.

    Runs pytest as a **subprocess** (`python -m pytest`), not in-process via
    `pytest.main()`: bundles commonly reuse the same test-file basenames
    (`test_hallway.py`, ...) across separate directories, and repeated
    in-process `pytest.main()` calls within one long-lived interpreter (as a
    test suite driving this CLI many times would do) collide in
    `sys.modules`/pytest's own import cache ("import file mismatch") --
    exactly the isolation a real terminal invocation of `hassle test` gets
    for free from being its own process.

    Invoked with cwd set to the bundle's `tests/` directory: the `sim`
    fixture's bundle-discovery default (`hassle.testing.plugin._bundle_dir_for`)
    is "one level above pytest's rootdir", which only resolves correctly when
    pytest's rootdir *is* `tests/` (its own convention, predating this CLI) --
    passing `tests/` as a path argument instead makes pytest root at the
    bundle itself, one level too high.
    """
    root = _bundle_root_or_fail()
    tests_dir = root / "tests"
    cwd = tests_dir if tests_dir.is_dir() and not pytest_args else root
    result = subprocess.run([sys.executable, "-m", "pytest", *pytest_args], cwd=cwd)
    raise SystemExit(result.returncode)


# ---------------------------------------------------------------------------
# fmt
# ---------------------------------------------------------------------------


@main.command()
def fmt() -> None:
    """Run `ruff format` over the bundle's Python sources."""
    root = _bundle_root_or_fail()
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "format", str(root)], capture_output=True, text=True
    )
    console = get_console()
    console.print(result.stdout or result.stderr or "[dim]nothing to format[/dim]")
    if result.returncode not in (0,):
        raise SystemExit(result.returncode)


# ---------------------------------------------------------------------------
# stubs
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--refresh",
    is_flag=True,
    default=False,
    help="Refresh the registry snapshot first (needs a connection).",
)
def stubs(refresh: bool) -> None:
    """Generate `typings/hassle/registry/__init__.pyi` AND
    `typings/hassle/services.pyi` from the registry snapshot (DESIGN §11).

    See docs/internals/cli.md for why there are three generated stub files
    and the path history behind where they live; and docs/internals/ha-api-notes.md.
    """
    from hassle.registry.snapshot import RegistrySnapshot

    console = get_console()
    root = _bundle_root_or_fail()
    registry_path = root / ".hassle" / "registry.json"

    if refresh:
        _refresh_registry_snapshot(root, registry_path)

    if not registry_path.is_file():
        console.print(
            "[red]hassle stubs: no .hassle/registry.json found. "
            "Fix: run `hassle pull` first, or `hassle stubs --refresh`.[/red]"
        )
        raise SystemExit(1)

    snapshot = RegistrySnapshot.load(registry_path)
    out_path = _write_stub_if_changed(snapshot, root)
    # Root-relative (matches `scaffold_pyproject_file`'s "wrote
    # pyproject.toml" convention) -- see the matching comment on the `pull`
    # print site.
    console.print(f"[green]hassle stubs: wrote {_esc(out_path.relative_to(root))}[/green]")


def _write_if_changed(path: Path, content: str) -> bool:
    """Write `content` to `path` only if it differs (write-if-changed, the
    same convention `_write_registry_snapshot` uses) -- returns whether the
    file was actually written (changed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def _write_stub_if_changed(snapshot: object, root: Path) -> Path:
    """Generate `typings/hassle/registry/__init__.pyi` (entity stub),
    `typings/hassle/services.pyi` (typed service namespaces), AND
    `typings/hassle/__init__.pyi` (a re-export of every `hassle.__all__` name
    from its true defining module -- guards against pyright treating
    `hassle` as a namespace/partial stub package once submodule stubs exist
    for it, which would otherwise hide the real package's own top-level
    surface) from `snapshot`, each write-if-changed (the same convention
    `_write_registry_snapshot` uses for `.hassle/registry.json`, so an
    unchanged registry never dirties the tree / rewrites any of the files).

    Shared by both `hassle stubs` (manual refresh) and `hassle pull`
    (automatic, every pull) so the two commands can never disagree on what
    "the stubs for this snapshot" look like. Returns the entities stub's
    path (the caller's printed "wrote ..." message anchor) -- the other two
    are written alongside it as a side effect. See docs/internals/cli.md.
    """
    from hassle.registry.stubs import (
        generate_entities_stub,
        generate_hassle_reexport_stub,
        generate_services_stub,
    )

    entities_text = generate_entities_stub(snapshot)  # type: ignore[arg-type]
    entities_dir = root / "typings" / "hassle" / "registry"
    out_path = entities_dir / "__init__.pyi"
    _write_if_changed(out_path, entities_text)

    services_text = generate_services_stub(snapshot)  # type: ignore[arg-type]
    services_path = root / "typings" / "hassle" / "services.pyi"
    _write_if_changed(services_path, services_text)

    # The re-export stub is a pure function of `hassle.__all__` (no snapshot
    # input at all) -- but still write-if-changed, keyed to whatever this
    # installed `hassle-core` version's surface currently is, so it stays in
    # lockstep with the running toolchain across an upgrade.
    reexport_text = generate_hassle_reexport_stub()
    reexport_path = root / "typings" / "hassle" / "__init__.pyi"
    _write_if_changed(reexport_path, reexport_text)

    return out_path


def _stub_changed(snapshot: object, root: Path) -> bool:
    """Whether writing any of the three stubs (entities, services, or the
    top-level re-export) for `snapshot` would change a file on disk (checked
    BEFORE writing, so `pull` can print its step line only when something
    actually changed -- matching `_write_registry_snapshot`'s write-if-changed
    convention)."""
    from hassle.registry.stubs import (
        generate_entities_stub,
        generate_hassle_reexport_stub,
        generate_services_stub,
    )

    entities_text = generate_entities_stub(snapshot)  # type: ignore[arg-type]
    entities_path = root / "typings" / "hassle" / "registry" / "__init__.pyi"
    entities_changed = not (
        entities_path.is_file() and entities_path.read_text(encoding="utf-8") == entities_text
    )

    services_text = generate_services_stub(snapshot)  # type: ignore[arg-type]
    services_path = root / "typings" / "hassle" / "services.pyi"
    services_changed = not (
        services_path.is_file() and services_path.read_text(encoding="utf-8") == services_text
    )

    reexport_text = generate_hassle_reexport_stub()
    reexport_path = root / "typings" / "hassle" / "__init__.pyi"
    reexport_changed = not (
        reexport_path.is_file() and reexport_path.read_text(encoding="utf-8") == reexport_text
    )
    return entities_changed or services_changed or reexport_changed


def _write_registry_snapshot(backend: object, root: Path):
    if not hasattr(backend, "fetch_registry_snapshot"):
        return None
    snapshot = backend.fetch_registry_snapshot()  # type: ignore[attr-defined]
    registry_path = root / ".hassle" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    content = snapshot.model_dump_json(indent=2)
    # Write-if-changed: an unchanged registry must not dirty the tree (the
    # daily loop ends with a no-op pull on a clean tree, DESIGN §8.4).
    if not (registry_path.is_file() and registry_path.read_text(encoding="utf-8") == content):
        registry_path.write_text(content, encoding="utf-8")
    return snapshot


def _refresh_registry_snapshot(root: Path, registry_path: Path) -> None:
    from hassle_cli import backend_factory

    ha_url, token = _require_backend_config(root)
    with backend_factory.connect(ha_url, token) as backend:
        _write_registry_snapshot(backend, root)


# ---------------------------------------------------------------------------
# explain / render
# ---------------------------------------------------------------------------


@main.command()
@click.argument("object_key")
@click.option("--yaml", "as_yaml_flag", is_flag=True, default=True)
def explain(object_key: str, as_yaml_flag: bool) -> None:
    """Show the compiled config for `object_key` (e.g. automation:hall_light_on_motion)."""
    from hassle_cli.explain import as_yaml, compiled_config_for

    console = get_console()
    root = _bundle_root_or_fail()
    try:
        config = compiled_config_for(root, object_key)
    except KeyError as exc:
        console.print(f"[red]hassle explain: {_esc(exc)}[/red]")
        raise SystemExit(1) from exc
    # The compiled YAML/repr is the exact product output `explain` promises
    # (a compiled config can legitimately contain `[...]` -- a flow-style
    # YAML list, a Jinja template using list indexing, ...) -- never parsed
    # as rich markup.
    console.print(as_yaml(config) if as_yaml_flag else str(config), markup=False)


@main.command()
@click.argument("template")
def render(template: str) -> None:
    """Render a Jinja template through the simulator's template engine subset."""
    from hassle_cli.explain import render_template_offline

    console = get_console()
    # A rendered Jinja template is arbitrary text (`{{ ... }}`, list
    # literals, ...) -- never parsed as rich markup.
    console.print(render_template_offline(template), markup=False)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@main.command()
@click.argument("target")
@click.option("--live", is_flag=True, default=False)
@click.option("--yes", is_flag=True, default=False)
@click.option("--skip-conditions", is_flag=True, default=False)
def run(target: str, live: bool, yes: bool, skip_conditions: bool) -> None:
    """Run one automation: on the simulator, or (--live) against real HA."""
    console = get_console()
    root = _bundle_root_or_fail()

    if not live:
        from hassle_cli.run_sim import (
            InvalidRunTargetError,
            UnknownRunTargetError,
            run_on_simulator,
        )

        try:
            object_key, sim = run_on_simulator(root, target)
        except (InvalidRunTargetError, UnknownRunTargetError) as exc:
            console.print(f"[red]hassle run: {_esc(exc)}[/red]")
            raise SystemExit(1) from exc
        console.print(f"[green]ran {_esc(object_key)} on the simulator[/green]")
        for call in sim.all_calls():
            console.print(f"  called {_esc(call.action)} {_esc(call.data)}")
        return

    if not yes and _interactive():
        if not click.confirm(
            f"Run {target} against the LIVE Home Assistant (real devices)?",
            default=True,
        ):
            raise SystemExit(1)
    elif not yes:
        console.print(
            "[bold red]hassle run --live executes real service calls on real devices. "
            "Fix: re-run with --yes to confirm.[/bold red]"
        )
        raise SystemExit(1)

    from hassle_cli.commands.run_live_command import execute_live_run

    execute_live_run(root, target, skip_conditions=skip_conditions, console=console)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


@main.command()
@click.option("--sweep-shadows", is_flag=True, default=False)
def doctor(sweep_shadows: bool) -> None:
    """Diagnostics: committed-secret scan, webhook-ID census, orphaned shadow
    sweep, HA version check."""
    from hassle.backend.version import TESTED_HA_MAX, TESTED_HA_MIN, version_warning
    from hassle.compiler.errors import CompileError
    from hassle_cli.doctor import find_committed_tokens, find_webhook_ids, sweep_orphaned_shadows
    from hassle_cli.uv_project import doctor_report_lines

    console = get_console()
    root = _bundle_root_or_fail()
    problems = 0

    committed = find_committed_tokens(root)
    if committed:
        problems += 1
        for path, reason in committed:
            console.print(
                f"[red]doctor: found a possible committed secret in {_esc(path.name)} "
                f"({_esc(reason)}). Fix: remove it, run `hassle login` to store the token in "
                "the system keyring, and rotate the exposed token in HA.[/red]"
            )

    # Webhook-ID census (DESIGN §14; SECURITY.md "What ends up in your
    # repository"): purely informational, so a compile failure here must
    # never turn into a doctor "problem" -- `hassle validate` is the command
    # that surfaces compile errors; this best-effort census just stays quiet
    # about the count if the bundle doesn't currently compile.
    try:
        local_objects, _compile_result = bundle_ops.compile_local_objects(root)
    except CompileError:
        console.print(
            "[dim]doctor: skipped the webhook-ID census -- this bundle doesn't currently "
            "compile (see `hassle validate`).[/dim]"
        )
    else:
        webhook_ids = find_webhook_ids(local_objects)
        if webhook_ids:
            console.print(
                f"[yellow]doctor: this bundle contains {len(webhook_ids)} webhook "
                f"{'id' if len(webhook_ids) == 1 else 'ids'}. A webhook_id is a bearer "
                "secret -- anyone who knows it can trigger that automation with no "
                "authentication. Fix: do not publish this bundle's repository publicly "
                "without removing/rotating them first.[/yellow]"
            )
        else:
            console.print("[dim]doctor: 0 webhook ids in this bundle.[/dim]")

    # "HA tested-version range surfaced in hassle doctor" -- the range itself
    # is always shown (offline, a static constant, safe under the "unit tests
    # never touch the network" rule). The LIVE instance's version is only
    # ever checked when the caller explicitly opts into a connection
    # (`--sweep-shadows`, the pre-existing connection gate) -- `doctor` must
    # never make network I/O just because `ha_url` happens to be configured
    # (a bare `hassle doctor` is an offline diagnostic).
    console.print(
        f"[dim]doctor: Hassle is tested against Home Assistant "
        f"{TESTED_HA_MIN}-{TESTED_HA_MAX}[/dim]"
    )

    # Bundle-as-uv-project status -- filesystem-only, no `uv` subprocess ever
    # spawned by this check (see `uv_project.doctor_report_lines` docstring).
    for line in doctor_report_lines(root):
        console.print(f"[dim]{line}[/dim]")

    if sweep_shadows:
        config = load_config(root)
        if config.ha_url:
            from hassle_cli import backend_factory
            from hassle_cli.token import resolve_token

            _warn_if_plaintext_http(config.ha_url)
            token = resolve_token(config.ha_url) or ""
            with backend_factory.connect(config.ha_url, token) as backend:
                ha_version = getattr(backend, "ha_version", None)
                swept = sweep_orphaned_shadows(backend)
            if swept:
                console.print(
                    f"[yellow]doctor: swept {len(swept)} orphaned shadow automation(s)[/yellow]"
                )
            if ha_version:
                # `ha_version` is remote-supplied (GET /api/config); `warning`
                # (from `version_warning`) embeds it verbatim too -- both
                # routed through `_esc` (control-code stripping + markup
                # escaping), never interpolated raw.
                warning = version_warning(ha_version)
                if warning is not None:
                    console.print(f"[yellow]doctor: {_esc(warning)}[/yellow]")
                else:
                    console.print(
                        f"[dim]doctor: connected Home Assistant {_esc(ha_version)} (in range)[/dim]"
                    )

    if problems:
        raise SystemExit(1)
    console.print("[green]doctor: no problems found[/green]")
