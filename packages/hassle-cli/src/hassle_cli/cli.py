"""`hassle` -- the daily-driver CLI (MILESTONES M7; DESIGN §8.4, §10.4, §14).

**Framework choice: `click`, not `typer`** (documented per the milestone's
"pick click or typer, document why in the package docstring" instruction --
see the package docstring in `hassle_cli/__init__.py` for the full rationale;
summary: click is the more minimal, more testable-via-`CliRunner` dependency,
and this CLI's option surface is irregular enough across 14 subcommands
--yes/--plain/--accept-local KEY/--allow-dirty/--live -- that click's
explicit `@click.option` declarations read clearer than typer's
function-signature-as-CLI-surface convention).

Command surface (DESIGN §8.4 loop + §10.4 + §14):
  init, login, pull, status, plan, push, validate, test, run, fmt, stubs,
  explain, render, mirror, doctor
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

from hassle_cli import bundle_ops, git_support, init_cmd, manifest_io
from hassle_cli.config import CURRENT_BUNDLE_FORMAT, find_bundle_root, load_config
from hassle_cli.render import get_console


def _bundle_root_or_fail(explicit: Path | None = None) -> Path:
    root = explicit or find_bundle_root()
    if root is None:
        click.echo(
            "hassle: no hassle.toml found in this directory or any parent. "
            "Fix: run `hassle init` here, or `cd` into your bundle directory.",
            err=True,
        )
        raise SystemExit(2)
    # MILESTONES M9 test 4: refuse a NEWER major bundle_format before doing ANY
    # work (no partial operation) -- checked here, the single choke point every
    # subcommand except `init`/`login` routes through, so there is no way to
    # reach compile/validate/plan/push logic on an unrecognized format.
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


def _require_backend_config(root: Path) -> tuple[str, str]:
    import os

    from hassle_cli.token import resolve_token

    # HASSLE_HA_URL + HASSLE_TOKEN env override (same convention as the M6
    # integration suite's HASSLE_TEST_HA_URL/_TOKEN): lets `run --live`'s one
    # integration test point at a Dockerized HA without needing a hassle.toml
    # ha_url or a keyring entry.
    env_url = os.environ.get("HASSLE_HA_URL")
    if env_url:
        env_token = os.environ.get("HASSLE_TOKEN", "")
        return env_url, env_token

    config = load_config(root)
    if not config.ha_url:
        click.echo(
            "hassle: no ha_url configured in hassle.toml. "
            "Fix: run `hassle login --url <your-ha-url>` first.",
            err=True,
        )
        raise SystemExit(2)
    token = resolve_token(config.ha_url)
    if token is None and not config.ha_url.startswith("fake://"):
        click.echo(
            "hassle: no token found for this HA instance (checked HASSLE_TOKEN and the "
            "system keyring). Fix: run `hassle login --url "
            f"{config.ha_url}` to store one.",
            err=True,
        )
        raise SystemExit(2)
    return config.ha_url, token or ""


@click.group()
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
@click.option("--token", required=True, help="A long-lived access token.")
def login(url: str, token: str) -> None:
    """Validate a token against HA and store it in the system keyring."""
    from hassle.backend.errors import HaAuthError, HaConnectionError
    from hassle_cli.commands.login import DirectBackend
    from hassle_cli.token import store_token

    console = get_console()
    try:
        with DirectBackend(url, token):
            pass
    except HaAuthError as exc:
        console.print(
            f"[red]hassle login: authentication failed (401) against {url}: {exc}[/red]\n"
            "Fix: double-check the long-lived access token (Profile -> Security -> "
            "Long-Lived Access Tokens in HA) and re-run `hassle login`."
        )
        raise SystemExit(1) from exc
    except HaConnectionError as exc:
        console.print(
            f"[red]hassle login: could not connect to {url}: {exc}[/red]\n"
            "Fix: check the URL is reachable from this machine."
        )
        raise SystemExit(1) from exc

    store_token(url, token)
    from hassle_cli.config import find_bundle_root, persist_ha_url

    root = find_bundle_root(Path.cwd()) or Path.cwd()
    persist_ha_url(root, url)
    console.print(
        f"[green]hassle login: token verified and stored for {url}[/green]\n"
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
    from hassle.sync.source_writer import WholeFileSourceWriter
    from hassle_cli import backend_factory
    from hassle_cli.doctor import find_committed_tokens
    from hassle_cli.git_support import commit_message_for_pull
    from hassle_cli.pull_apply import DecompiledBatchDoesNotCompileError, apply_pull_with_decompiler

    console = get_console()
    root = _bundle_root_or_fail()

    committed = find_committed_tokens(root)
    if committed:
        console.print(
            f"[red]hassle pull: a token was found committed in {committed[0][0].name}. "
            "Fix: remove the `token = ...` line, run `hassle login` to store it in the "
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
        scaffold_vscode_settings,
    )

    scaffold_lib_and_tests_readmes(root)
    scaffold_vscode_settings(root)
    scaffold_agent_docs(root)

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

    local_objects, compile_result = bundle_ops.compile_local_objects(root)

    with backend_factory.connect(ha_url, token) as backend:
        remote_objects = bundle_ops.remote_objects_from_backend(backend, list(OBJECT_KINDS))
        # DESIGN §9.2: the registry snapshot is refreshed on every pull (tier-2/3
        # validation and stubs depend on it). Best-effort: skipped when the
        # backend lacks the registry surface. Also drives DESIGN §7.3's
        # category-based placement for newly-adopted objects (below).
        registry_snapshot = _write_registry_snapshot(backend, root)

    ignore_result = apply_ignore_globs(
        local_objects=local_objects, remote_objects=remote_objects, ignore_globs=config.ignore
    )
    for finding in ignore_result.findings:
        console.print(f"[yellow]hassle pull: {finding}[/yellow]")

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

    writer = WholeFileSourceWriter()
    # `apply_pull_with_decompiler` self-checks every ADOPT destination
    # together BEFORE writing any of them (`hassle_cli.pull_apply` module
    # docstring, coordinator task 4) -- a decompiler coordination bug here is
    # caught pre-write, so nothing from this pull's adopt set has touched
    # disk yet. Distinct from the post-write backstop below (which also
    # covers REFRESH's single-object splice, the one path the pre-write
    # self-check can't cover -- see that module's docstring).
    try:
        result = apply_pull_with_decompiler(plan, writer)
    except DecompiledBatchDoesNotCompileError as exc:
        console.print(
            f"[bold red]hassle pull: {exc}[/bold red]\n"
            "[bold red]This is a bug in Hassle's decompiler, not a mistake in your HA "
            "configuration. Fix: please report this, then re-run `hassle pull` (or "
            "`--allow-dirty` if needed) once a fix lands -- nothing was written for the "
            "affected file(s), so there is nothing to clean up.[/bold red]"
        )
        raise SystemExit(1) from exc

    # Safety backstop (``ux/shared-script-calls-fix``): pull just wrote real
    # DSL source from the decompiler -- recompile the bundle it produced
    # before trusting it (manifest bookkeeping below establishes the new
    # three-way-merge baseline, so it must not run against a bundle that
    # doesn't even compile). A coordination bug in the decompiler (the field
    # failure this fix addresses: a caller rewritten to call a script whose
    # own emitted signature can't accept it) raises here instead of silently
    # leaving the user with a broken bundle discovered only on their next
    # `hassle test`/`hassle push`. Files are left in place (never rolled
    # back) -- the user needs them to file a useful bug report, and the fix
    # is always just a `hassle pull --allow-dirty` once it lands.
    try:
        bundle_ops.compile_local_objects(root)
    except Exception as exc:
        console.print(
            f"[bold red]hassle pull: the bundle just written to {root} does not compile "
            f"({type(exc).__name__}: {exc}). This is a bug in Hassle's decompiler, not a "
            "mistake in your HA configuration -- the files just written are left in place "
            "for you to inspect. Fix: please report this (include the error above and, if "
            "possible, the object(s) involved) at "
            "https://github.com/hassle-project/hassle/issues; once a fix lands, "
            "`hassle pull --allow-dirty` is safe to re-run and will overwrite the broken "
            "file(s).[/bold red]"
        )
        raise SystemExit(1) from exc

    from hassle.sync.models import ManifestEntry, PlanAction

    pull_actions = (PlanAction.REFRESH, PlanAction.ADOPT, PlanAction.DROP)
    for entry in plan.entries:
        if entry.action in pull_actions:
            console.print(f"[cyan]{entry.action.value:>10}[/cyan]  {entry.object_key}")
    if result.conflicts:
        for conflict in result.conflicts:
            console.print(
                f"[bold red]conflict[/bold red]  {conflict.object_key} (see written markers)"
            )

    # Pull mutates only the working tree (apply_pull never touches HA or the
    # manifest, DESIGN §8.3) -- but a `refresh`/`adopt`/`drop` DOES establish
    # (or remove) this object's three-way-merge baseline, or the very next
    # `plan` would see "no base" and perpetually re-propose the same
    # adopt/create. Advancing the manifest for pull-side actions is this
    # CLI's own bookkeeping (no core-layer test covers it: `apply_pull`
    # deliberately never accepts a manifest, MILESTONES M5 test 2).
    new_objects = dict(manifest.objects)
    for entry in plan.entries:
        if entry.action in (PlanAction.REFRESH, PlanAction.ADOPT):
            assert entry.remote is not None
            existing = manifest.objects.get(entry.object_key)
            from hassle.ir.canonical import sha256_hash

            new_objects[entry.object_key] = ManifestEntry(
                source=source_paths.get(entry.object_key),
                compiled_hash=sha256_hash(entry.remote),
                kind=existing.kind if existing is not None else "dsl",
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


def _build_plan(root: Path):
    from hassle.ir.keys import OBJECT_KINDS
    from hassle.sync.plan import compute_plan
    from hassle_cli import backend_factory
    from hassle_cli.ignore_filter import apply_ignore_globs, migrate_manifest_for_ignores

    ha_url, token = _require_backend_config(root)
    config = load_config(root)
    manifest = migrate_manifest_for_ignores(
        manifest_io.load_manifest(root), ignore_globs=config.ignore
    ).manifest
    local_objects, _compile_result = bundle_ops.compile_local_objects(root)
    with backend_factory.connect(ha_url, token) as backend:
        remote_objects = bundle_ops.remote_objects_from_backend(backend, list(OBJECT_KINDS))
    ignore_result = apply_ignore_globs(
        local_objects=local_objects, remote_objects=remote_objects, ignore_globs=config.ignore
    )
    return compute_plan(
        manifest=manifest,
        local_objects=ignore_result.local_objects,
        remote_objects=ignore_result.remote_objects,
    )


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
    from hassle.sync.models import PlanAction
    from hassle_cli import backend_factory
    from hassle_cli.plan_render import plan_summary, render_plan

    console = get_console(force_plain=ctx.obj.get("plain", False))
    root = _bundle_root_or_fail()
    the_plan = _build_plan(root)

    unresolved_conflicts = [
        e
        for e in the_plan.entries_with_action(PlanAction.CONFLICT)
        if e.object_key not in accept_local and e.object_key not in accept_remote
    ]
    if unresolved_conflicts:
        render_plan(console, the_plan)
        console.print(
            "[bold red]hassle push: unresolved conflict(s). Fix: re-run with "
            "--accept-local KEY or --accept-remote KEY for each conflicting object "
            "key above (or pull-and-merge in the editor, then push again).[/bold red]"
        )
        raise SystemExit(1)

    has_deletions = bool(the_plan.entries_with_action(PlanAction.DELETE))
    if has_deletions and not yes:
        render_plan(console, the_plan)
        console.print(
            "[bold red]hassle push: this plan includes deletion(s), which require "
            "explicit confirmation. Fix: re-run with --yes to apply.[/bold red]"
        )
        raise SystemExit(1)

    resolved_entries = []
    for entry in the_plan.entries:
        if entry.action is PlanAction.CONFLICT:
            if entry.object_key in accept_local:
                entry = entry.model_copy(update={"action": PlanAction.UPDATE})
            elif entry.object_key in accept_remote:
                continue  # keep remote as-is: nothing to push for this key
        resolved_entries.append(entry)
    from hassle.sync.models import Plan

    resolved_plan = Plan(entries=resolved_entries)

    ha_url, token = _require_backend_config(root)
    manifest = manifest_io.load_manifest(root)
    with backend_factory.connect(ha_url, token) as backend:
        result = apply_plan(resolved_plan, backend, manifest, synced_at=manifest_io.now_iso())

    if not result.succeeded:
        console.print(f"[bold red]hassle push: apply failed/aborted: {result.outcomes}[/bold red]")
        raise SystemExit(1)

    if result.manifest is not None:
        manifest_io.save_manifest(root, result.manifest)

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
    help="Emit findings as JSON (the VS Code extension's Problems-pane contract, MILESTONES M8).",
)
def validate(as_json: bool) -> None:
    """Compile + validate the bundle offline (DESIGN §9 tiers 1-3).

    ``--json`` prints exactly one JSON object on stdout --
    ``{"findings": [{code, severity, file, line, message, fix}, ...]}`` --
    regardless of exit code, and never any rich/plain-text banner lines
    (an editor extension parses this stdout directly). This is the schema
    `hassle_cli.tests.test_cli_commands::test_validate_json_reports_findings_with_stable_schema`
    and the VS Code extension's `findingsSchema.ts` both snapshot-test
    (MILESTONES M8 test 3) -- field-for-field, it mirrors
    `hassle.registry.finding.Finding`.
    """
    from hassle.compiler.bundle import compile_bundle
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.validate import validate_bundle

    console = get_console()
    root = _bundle_root_or_fail()
    registry_path = root / ".hassle" / "registry.json"
    result = compile_bundle(root)
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
        console.print(f"[red]{finding.code}[/red]: {finding}")
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
    """Generate `typings/hassle/registry/__init__.pyi` from the registry
    snapshot (DESIGN §11).

    **M8 layer-1 fix:** this used to write `.hassle/entities.pyi` -- a path no
    pyright/Pylance configuration (including `hassle init`'s own
    `.vscode/settings.json`) ever pointed at, so the generated types were
    silently never picked up by a real editor. `typings/hassle/registry/__init__.pyi`
    (with `.vscode/settings.json`'s `python.analysis.stubPath: "typings"`) is
    the placement pyright actually prefers over the real runtime
    `hassle.registry` module for that dotted path -- verified end-to-end in
    `packages/hassle-core/tests/test_registry_stubs_pyright*.py`. See
    docs/ha-api-notes.md.
    """
    from hassle.registry.snapshot import RegistrySnapshot
    from hassle.registry.stubs import generate_entities_stub

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
    stub_text = generate_entities_stub(snapshot)
    stub_dir = root / "typings" / "hassle" / "registry"
    stub_dir.mkdir(parents=True, exist_ok=True)
    out_path = stub_dir / "__init__.pyi"
    out_path.write_text(stub_text, encoding="utf-8")
    # Package marker so pyright treats the synthetic `hassle` stub package as
    # a regular package (matches the real runtime `hassle` package shape).
    package_marker = root / "typings" / "hassle" / "__init__.pyi"
    if not package_marker.is_file():
        package_marker.write_text("", encoding="utf-8")
    console.print(f"[green]hassle stubs: wrote {out_path}[/green]")


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
        console.print(f"[red]hassle explain: {exc}[/red]")
        raise SystemExit(1) from exc
    console.print(as_yaml(config) if as_yaml_flag else str(config))


@main.command()
@click.argument("template")
def render(template: str) -> None:
    """Render a Jinja template through the simulator's template engine subset."""
    from hassle_cli.explain import render_template_offline

    console = get_console()
    console.print(render_template_offline(template))


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
        from hassle_cli.run_sim import run_on_simulator

        object_key, sim = run_on_simulator(root, target)
        console.print(f"[green]ran {object_key} on the simulator[/green]")
        for call in sim.all_calls():
            console.print(f"  called {call.action} {call.data}")
        return

    if not yes:
        console.print(
            "[bold red]hassle run --live executes real service calls on real devices. "
            "Fix: re-run with --yes to confirm.[/bold red]"
        )
        raise SystemExit(1)

    from hassle_cli.commands.run_live_command import execute_live_run

    execute_live_run(root, target, skip_conditions=skip_conditions, console=console)


# ---------------------------------------------------------------------------
# mirror
# ---------------------------------------------------------------------------


@main.group()
def mirror() -> None:
    """DESIGN §8.5: optional in-HA mirror of the bundle."""


@mirror.command(name="status")
def mirror_status() -> None:
    root = _bundle_root_or_fail()
    config = load_config(root)
    console = get_console()
    if config.mirror:
        console.print("[green]mirror: enabled[/green]")
    else:
        console.print(
            "[dim]mirror: disabled (off by default; set mirror = true in hassle.toml)[/dim]"
        )


@mirror.command(name="push")
def mirror_push() -> None:
    root = _bundle_root_or_fail()
    config = load_config(root)
    console = get_console()
    if not config.mirror:
        console.print("[yellow]mirror is disabled; enable it in hassle.toml first[/yellow]")
        raise SystemExit(1)
    console.print("[dim]mirror push: not yet connected in this environment[/dim]")


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


@main.command()
@click.option("--sweep-shadows", is_flag=True, default=False)
def doctor(sweep_shadows: bool) -> None:
    """Diagnostics: committed-secret scan, orphaned shadow sweep, HA version check."""
    from hassle.backend.version import TESTED_HA_MAX, TESTED_HA_MIN, version_warning
    from hassle_cli.doctor import find_committed_tokens, sweep_orphaned_shadows

    console = get_console()
    root = _bundle_root_or_fail()
    problems = 0

    committed = find_committed_tokens(root)
    if committed:
        problems += 1
        for path, _value in committed:
            console.print(
                f"[red]doctor: found a committed token in {path.name}. "
                "Fix: remove the `token = ...` line, run `hassle login` to store it in the "
                "system keyring, and rotate the exposed token in HA.[/red]"
            )

    # MILESTONES M9 deliverable 4: "HA tested-version range surfaced in
    # hassle doctor" -- the range itself is always shown (offline, a static
    # constant, R2-safe). The LIVE instance's version is only ever checked
    # when the caller explicitly opts into a connection (`--sweep-shadows`,
    # the pre-existing connection gate) -- `doctor` must never make network
    # I/O just because `ha_url` happens to be configured (R2; a bare
    # `hassle doctor` is an offline diagnostic).
    console.print(
        f"[dim]doctor: Hassle is tested against Home Assistant "
        f"{TESTED_HA_MIN}-{TESTED_HA_MAX}[/dim]"
    )

    if sweep_shadows:
        config = load_config(root)
        if config.ha_url:
            from hassle_cli import backend_factory
            from hassle_cli.token import resolve_token

            token = resolve_token(config.ha_url) or ""
            with backend_factory.connect(config.ha_url, token) as backend:
                ha_version = getattr(backend, "ha_version", None)
                swept = sweep_orphaned_shadows(backend)
            if swept:
                console.print(
                    f"[yellow]doctor: swept {len(swept)} orphaned shadow automation(s)[/yellow]"
                )
            if ha_version:
                warning = version_warning(ha_version)
                if warning is not None:
                    console.print(f"[yellow]doctor: {warning}[/yellow]")
                else:
                    console.print(
                        f"[dim]doctor: connected Home Assistant {ha_version} (in range)[/dim]"
                    )

    if problems:
        raise SystemExit(1)
    console.print("[green]doctor: no problems found[/green]")
