"""The permanent pull -> plan-noop invariant gate (docs/ha-api-notes.md §23).

Seeds every `fixtures/configs/*.json` corpus object into a fresh `FakeBackend`
(keyed exactly like the M0 IR corpus loader does -- `hassle-core/tests/_corpus.py`'s
filename convention, reimplemented here since cross-package test imports aren't
wired up in this repo), runs the REAL CLI's `hassle pull` then `hassle plan`
against it, and asserts every resulting entry is `noop` or an `update` that
`is_modernization_only_diff` accepts (DESIGN §8.2's one-time legacy-schema
exception, MILESTONES M7 test 4b) -- **zero** `conflict`, **zero** plain
(non-modernization) `update`, **zero** `delete`/`create`/`adopt`/`refresh`
survives past the first pull's manifest write.

Plus two focused variants named in the task: a mode-less automation, and the
legacy `platform:` fixture (must be modernization-labeled, not noop -- it's a
whole-object `raw_automation` fallback whose stored form pre-dates HA's
`action:`/`actions:` normalization, DESIGN §7.3/§8.2, MILESTONES M2 test 1).
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from hassle.ir.keys import HELPER_DOMAINS
from hassle_cli.cli import _build_plan
from hassle_cli.diffing import is_modernization_only_diff

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIGS_DIR = REPO_ROOT / "fixtures" / "configs"


def _kind_for(name: str) -> tuple[str, str | None]:
    """Same filename convention as `hassle-core/tests/_corpus.py::_kind_for`."""
    if name.startswith("automation"):
        return "automation", None
    if name.startswith("script"):
        return "script", name
    if name.startswith("helper_"):
        rest = name[len("helper_") :]
        for dom in sorted(HELPER_DOMAINS, key=len, reverse=True):
            if rest == dom or rest.startswith(dom + "_"):
                return dom, None
        raise ValueError(f"cannot determine helper domain from fixture name {name!r}")
    raise ValueError(f"cannot determine object kind from fixture name {name!r}")


def _load_corpus() -> list[tuple[str, str, str | None, dict[str, Any]]]:
    """[(name, kind, key_hint, config), ...] for every fixtures/configs/*.json."""
    out: list[tuple[str, str, str | None, dict[str, Any]]] = []
    for path in sorted(CONFIGS_DIR.glob("*.json")):
        name = path.stem
        kind, key_hint = _kind_for(name)
        config = json.loads(path.read_text(encoding="utf-8"))
        out.append((name, kind, key_hint, config))
    return out


def _seed_backend(
    backend: Any, fixtures: list[tuple[str, str, str | None, dict[str, Any]]]
) -> None:
    """Seed every fixture into `backend` at its intended identity.

    Scripts are keyed by an EXTRINSIC object_id (the filename stem) --
    `backend.update(kind, identity, config)` sets the identity directly,
    the correct way to seed one (never passing `id` inside `config`, which
    would be the FACT 2 leak this whole test module guards against, even
    though `FakeBackend` no longer lets it stick). Automations/helpers carry
    their id INSIDE the body already (intrinsic identity), so a plain
    `create` (which normalizes + derives identity from that body) is right
    for them.
    """
    for _name, kind, key_hint, config in fixtures:
        if kind == "script":
            assert key_hint is not None
            backend.update(kind, key_hint, config)
        else:
            backend.create(kind, config)


def _run_pull_then_plan(git_repo: Path, cli: Any, fake_backend: Any, toml_writer: Any) -> Any:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    # `git_repo`/`bundle_dir` pre-seed a `hallway.py` with `hall_light_on_motion`
    # that has no corresponding remote object yet -- push it first (like
    # `test_modernization_labeling.py` does) so it becomes part of the base and
    # never shows up as noise (a `create`) in the corpus-only assertions below.
    push_result = cli(["push", "--yes"], cwd=git_repo)
    assert push_result.exit_code == 0, push_result.output
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "push hallway"], cwd=git_repo, check=True, capture_output=True
    )

    fixtures = _load_corpus()
    _seed_backend(backend, fixtures)
    backend.reset_write_tracking()

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "pull corpus"], cwd=git_repo, check=True, capture_output=True
    )

    return _build_plan(git_repo)


def test_full_corpus_pull_then_plan_is_noop_or_modernization(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """THE permanent gate: fresh pull of the whole fixture corpus, zero
    edits, re-plan -> every entry noop or modernization-labeled update; zero
    conflicts, zero plain updates, zero delete/create/adopt/refresh."""
    from hassle.sync.models import PlanAction

    plan = _run_pull_then_plan(git_repo, cli, fake_backend, toml_writer)

    counts = Counter(e.action.value for e in plan.entries)
    non_modernization_updates: list[str] = []
    conflicts: list[str] = []
    other_bad: list[str] = []
    for entry in plan.entries:
        if entry.action is PlanAction.CONFLICT:
            conflicts.append(entry.object_key)
        elif entry.action is PlanAction.UPDATE:
            if not is_modernization_only_diff(
                entry.object_key, entry.kind, entry.local, entry.remote
            ):
                non_modernization_updates.append(entry.object_key)
        elif entry.action not in (PlanAction.NOOP,):
            other_bad.append(f"{entry.object_key}:{entry.action.value}")

    assert conflicts == [], f"phantom conflicts from an untouched pull: {conflicts}"
    assert non_modernization_updates == [], (
        f"non-modernization updates: {non_modernization_updates}"
    )
    assert other_bad == [], f"unexpected non-noop actions: {other_bad}"
    assert counts.get("noop", 0) > 0, "expected at least some noop entries"


def test_mode_less_automation_pull_plan_noop(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """A mode-less automation (no `mode` key in the stored/remote body at
    all) must plan as `noop` after a pull with no edits -- `mode` must never
    be materialized as a default that then hash-mismatches against the
    mode-less remote."""
    from hassle.sync.models import PlanAction

    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    backend.create(
        "automation",
        {
            "id": "mode_less_pull_test",
            "alias": "Mode Less Pull Test",
            "triggers": [{"trigger": "state", "entity_id": "binary_sensor.x", "to": "on"}],
            "conditions": [],
            "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.y"}}],
            # deliberately no "mode" key
        },
    )
    backend.reset_write_tracking()

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "pull"], cwd=git_repo, check=True, capture_output=True
    )

    plan = _build_plan(git_repo)
    entry = next(e for e in plan.entries if e.object_key == "automation:mode_less_pull_test")
    assert entry.action is PlanAction.NOOP, (entry.action, entry.local, entry.remote)


def test_legacy_platform_automation_is_modernization_labeled(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """`automation_legacy_platform_naming` (whole-object `raw_automation`
    fallback, ancient inline `platform:`/`entity_id:`/`to:` top-level form)
    must plan as a modernization-labeled `update` on re-plan, not `noop` (the
    stored fixture predates HA's `actions:` pluralization so a one-time
    schema diff is expected) and never `conflict`."""
    from hassle.sync.models import PlanAction

    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    fixture_path = CONFIGS_DIR / "automation_legacy_platform_naming.json"
    config = json.loads(fixture_path.read_text(encoding="utf-8"))
    # Seed directly into the store (bypassing `create()`'s own `normalize_ha`
    # call) -- this fixture models config that predates HA's `action:` ->
    # `actions:` pluralization and is already stored exactly as-is; real HA
    # never re-normalizes stored config on its own (docs/ha-api-notes.md
    # §17.1), it only normalizes what's freshly POSTed. Matches
    # `test_modernization_labeling.py`'s own seeding approach.
    backend._store["automation"]["legacy_platform_naming"] = {
        **config,
        "id": "legacy_platform_naming",
    }
    backend.reset_write_tracking()

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "pull"], cwd=git_repo, check=True, capture_output=True
    )

    plan = _build_plan(git_repo)
    entry = next(e for e in plan.entries if e.object_key == "automation:legacy_platform_naming")
    assert entry.action is PlanAction.UPDATE, (entry.action, entry.local, entry.remote)
    assert is_modernization_only_diff(entry.object_key, entry.kind, entry.local, entry.remote)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "script_basic",
        "script_call_to_action_notification",
        "script_dismiss_notification",
        "script_with_fields",
        "script_mode_queued",
    ],
)
def test_each_script_fixture_pull_plan_noop_or_modernization(
    git_repo: Path, cli, fake_backend, toml_writer, fixture_name: str
) -> None:
    """Narrower per-fixture check isolating FACT 2 (script id-in-body leak):
    every script fixture, seeded at its correct extrinsic object_id (no `id`
    leaked into the body), must plan as noop or modernization-only after an
    untouched pull -- never conflict, never a plain update."""
    from hassle.sync.models import PlanAction

    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    config = json.loads((CONFIGS_DIR / f"{fixture_name}.json").read_text(encoding="utf-8"))
    backend.update("script", fixture_name, config)
    backend.reset_write_tracking()

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "pull"], cwd=git_repo, check=True, capture_output=True
    )

    plan = _build_plan(git_repo)
    entry = next(e for e in plan.entries if e.object_key == f"script:{fixture_name}")
    assert entry.action in (PlanAction.NOOP, PlanAction.UPDATE), (entry.action,)
    if entry.action is PlanAction.UPDATE:
        assert is_modernization_only_diff(entry.object_key, entry.kind, entry.local, entry.remote)


def test_script_seeded_with_id_in_body_still_plans_noop(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """FACT 2's exact end-to-end regression: seeding a script via `create()`
    with a caller-supplied `id` key in the config (the natural mistake --
    automations/helpers both legitimately take one, so a test/seeding helper
    reaches for the same shape for a script) must NOT leak that `id` into
    the stored remote body (docs/ha-api-notes.md §23.2) -- if it did, every
    subsequent `hassle plan` on this untouched script would show a permanent
    `update` (local has no `id`, `ScriptConfig` has no such field; remote
    would keep it forever), never settling into `noop`."""
    from hassle.sync.models import PlanAction

    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    identity = backend.create(
        "script",
        {
            "id": "leak_check_script",
            "alias": "Leak Check Script",
            "mode": "single",
            "sequence": [{"action": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
        },
    )
    backend.reset_write_tracking()

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "pull"], cwd=git_repo, check=True, capture_output=True
    )

    plan = _build_plan(git_repo)
    entry = next(e for e in plan.entries if e.object_key == f"script:{identity}")
    assert entry.action is PlanAction.NOOP, (entry.action, entry.local, entry.remote)
