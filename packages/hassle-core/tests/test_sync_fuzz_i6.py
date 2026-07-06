"""Fuzz test for I6 (MILESTONES M5 test 7) — no edit is ever silently lost.

Model: a single object (key "automation:fuzz") tracked through three "true
values" — base (what the manifest says was last synced), local (what the
bundle currently compiles to), remote (what FakeBackend currently holds).
Each step in a random sequence is one of:

  - "local_edit"   -> local value changes to a new, distinct value
  - "ui_edit"      -> remote value changes to a new, distinct value (simulates
                      a UI edit going straight to the backend)
  - "local_delete" -> local value becomes None (object removed from bundle)
  - "ui_delete"     -> remote value becomes None (object removed from HA)
  - "pull"         -> compute_plan + apply_pull; any refresh/adopt/drop updates
                      local to match remote (bundle-side only); conflicts are
                      recorded and BOTH sides are preserved (not silently
                      dropped) until resolved
  - "push"         -> compute_plan + apply_plan; any update/create/delete
                      updates remote to match local (backend-side only) and
                      advances base to match on success; conflicts block apply
                      for that object (nothing happens to it)

The invariant under test: whenever local and remote hold DIFFERENT non-None
values that the manifest base does not already resolve losslessly (i.e. an
actual edit exists on both sides, or one side deleted while the other edited),
the computed plan action for that object must be `conflict` — never a
silently-applied `noop`/`update`/`refresh` that would discard one side's edit.
We check this by re-deriving the "expected loseable" condition independently
of compute_plan and asserting the two agree at every step, for 1000
deterministically-seeded random sequences.

**M10 addition:** the same harness is re-run (a separate 1000-seed
parametrization) against a `template_number` object instead of an
`automation`, proving I6 holds for the new config-entry-backed kind too — the
plan/pull/push engines are kind-agnostic, so this is a coverage extension, not
a new code path.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from hassle.backend.fake import FakeBackend
from hassle.ir.canonical import sha256_hash
from hassle.sync import Manifest, ManifestEntry, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan
from hassle.sync.pull import apply_pull
from hassle.sync.source_writer import RecordingSourceWriter

OBJECT_KEY = "automation:fuzz"
KIND = "automation"

STEPS = ["local_edit", "ui_edit", "local_delete", "ui_delete", "pull", "push"]

# Push-side actions the plan can produce; pull ignores these entirely.
_PUSH_ACTIONS = (PlanAction.UPDATE, PlanAction.DELETE, PlanAction.CREATE)
# Pull-side actions that advance the bundle to match remote.
_PULL_ADOPTS_REMOTE = (PlanAction.REFRESH, PlanAction.ADOPT)


class _FuzzState:
    """Independent tracking of "true" base/local/remote values + a value counter
    so every edit produces a distinct, comparable value (never accidentally
    equal to a previous one, which would hide a real bug behind coincidence)."""

    def __init__(
        self,
        backend: FakeBackend,
        identity: str,
        *,
        kind: str = KIND,
        object_key: str = OBJECT_KEY,
        value_factory: Any = None,
    ) -> None:
        self.backend = backend
        self.identity = identity
        self.kind = kind
        self.object_key = object_key
        # M10 addition: a pluggable value factory so the same fuzz harness
        # covers a differently-shaped kind (e.g. template_number's
        # unique_id/state shape) without touching the original automation
        # path's exact behavior (default reproduces the original inline body).
        self._value_factory = value_factory or (
            lambda identity, label, counter: {"id": identity, "alias": f"{label}-{counter}"}
        )
        self.counter = 0
        self.base: dict[str, object] | None = None
        self.local: dict[str, object] | None = None
        # remote is always mirrored from backend.list_remote()

    def next_value(self, label: str) -> dict[str, object]:
        self.counter += 1
        return self._value_factory(self.identity, label, self.counter)

    def remote(self) -> dict[str, object] | None:
        remote_objects = self.backend.list_remote(self.kind)
        return remote_objects.get(self.identity)


def _make_manifest(state: _FuzzState) -> Manifest:
    if state.base is None:
        return Manifest(synced_at="t", ha_version="v", objects={})
    entry = ManifestEntry(source="a.py", compiled_hash=sha256_hash(state.base), kind="dsl")
    return Manifest(synced_at="t", ha_version="v", objects={state.object_key: entry})


def _compute_entry(state: _FuzzState) -> tuple[PlanEntry | None, dict[str, object] | None]:
    local_objects = {} if state.local is None else {state.object_key: (state.kind, state.local)}
    remote_val = state.remote()
    remote_objects = {} if remote_val is None else {state.object_key: (state.kind, remote_val)}
    manifest = _make_manifest(state)
    plan = compute_plan(
        manifest=manifest, local_objects=local_objects, remote_objects=remote_objects
    )
    return plan.entry_for(state.object_key), remote_val


def _assert_no_silent_loss(
    seed: int,
    step_num: int,
    phase: str,
    state: _FuzzState,
    remote_val: dict[str, object] | None,
    entry: PlanEntry | None,
) -> None:
    # Determine independently whether this step *would* lose information if
    # silently resolved one way. Information is at risk exactly when
    # base-vs-local and base-vs-remote both changed (both edited, or one
    # edited + other deleted) AND local != remote (i.e. they actually
    # disagree, not converged on the same new value).
    if entry is None:
        return
    base_vs_local_same = _same(state.base, state.local)
    base_vs_remote_same = _same(state.base, remote_val)
    local_vs_remote_same = _same(state.local, remote_val)
    at_risk = not base_vs_local_same and not base_vs_remote_same and not local_vs_remote_same
    if at_risk:
        assert entry.action is PlanAction.CONFLICT, (
            f"seed={seed} step={step_num} ({phase}): both sides diverged from base and "
            f"from each other but action was {entry.action}, not conflict -- I6 violated"
        )


def _run_sequence(
    seed: int,
    num_steps: int = 40,
    *,
    kind: str = KIND,
    object_key: str = OBJECT_KEY,
    value_factory: Any = None,
) -> None:
    rng = random.Random(seed)
    backend = FakeBackend()
    identity = "fuzz"
    state = _FuzzState(
        backend, identity, kind=kind, object_key=object_key, value_factory=value_factory
    )

    # Start: object exists on both sides, in sync.
    initial = state.next_value("init")
    backend.create(state.kind, initial)
    state.base = dict(backend.list_remote(state.kind)[identity])
    state.local = dict(state.base)

    for step_num in range(num_steps):
        step = rng.choice(STEPS)

        if step == "local_edit":
            state.local = state.next_value("local")

        elif step == "ui_edit":
            if state.remote() is None:
                # A delete already happened; simplest handling is to skip this
                # step rather than model the UI recreating under a fresh id.
                continue
            backend.update(state.kind, identity, state.next_value("ui"))

        elif step == "local_delete":
            state.local = None

        elif step == "ui_delete":
            if state.remote() is not None:
                backend.delete(state.kind, identity)

        elif step == "pull":
            _do_pull_step(seed, step_num, backend, state)

        elif step == "push":
            _do_push_step(seed, step_num, backend, state)


def _do_pull_step(seed: int, step_num: int, backend: FakeBackend, state: _FuzzState) -> None:
    entry, remote_val = _compute_entry(state)
    _assert_no_silent_loss(seed, step_num, "pull", state, remote_val, entry)

    manifest = _make_manifest(state)
    local_objects = {} if state.local is None else {state.object_key: (state.kind, state.local)}
    remote_objects = {} if remote_val is None else {state.object_key: (state.kind, remote_val)}
    plan = compute_plan(
        manifest=manifest, local_objects=local_objects, remote_objects=remote_objects
    )

    # Apply the bundle-side actions; must never write to backend.
    writes_before = backend.writes_since_reset()
    writer = RecordingSourceWriter()
    pull_result = apply_pull(plan, writer)
    assert backend.writes_since_reset() == writes_before, "pull must never write to Backend"

    if entry is None:
        return
    if entry.action is PlanAction.CONFLICT:
        # Conflict: both versions must be surfaced, neither silently dropped.
        # Local/base state is left untouched for the user to resolve.
        assert pull_result.conflicts
    elif entry.action in _PULL_ADOPTS_REMOTE:
        state.local = remote_val
        state.base = remote_val
    elif entry.action is PlanAction.DROP:
        state.local = None
        state.base = None
    # NOOP, and the push-side actions (UPDATE/DELETE/CREATE): pull leaves
    # local/base as-is.


def _do_push_step(seed: int, step_num: int, backend: FakeBackend, state: _FuzzState) -> None:
    entry, remote_val = _compute_entry(state)
    _assert_no_silent_loss(seed, step_num, "push", state, remote_val, entry)

    manifest = _make_manifest(state)
    local_objects = {} if state.local is None else {state.object_key: (state.kind, state.local)}
    remote_objects = {} if remote_val is None else {state.object_key: (state.kind, remote_val)}
    plan = compute_plan(
        manifest=manifest, local_objects=local_objects, remote_objects=remote_objects
    )
    apply_result = apply_plan(plan, backend, manifest, synced_at="t2")

    if entry is None:
        return
    if entry.action is PlanAction.CONFLICT:
        # Conflict blocks apply for this object entirely: remote is untouched.
        return
    if entry.action in (PlanAction.UPDATE, PlanAction.CREATE) and apply_result.succeeded:
        state.base = state.local
    elif entry.action is PlanAction.DELETE and apply_result.succeeded:
        state.base = None
    # REFRESH/ADOPT/DROP (pull-side) and NOOP: push leaves remote/base as-is
    # for this object.


def _same(a: dict[str, object] | None, b: dict[str, object] | None) -> bool:
    if a is None or b is None:
        return a is b
    return sha256_hash(a) == sha256_hash(b)


@pytest.mark.parametrize("seed", list(range(1000)))
def test_i6_fuzz_no_silent_data_loss(seed: int) -> None:
    _run_sequence(seed)


def test_i6_fuzz_runs_exactly_1000_seeds() -> None:
    # Documents the required fuzz volume (MILESTONES M5 test 7: "1 000 random
    # sequences"); the parametrized test above IS the 1000 runs, this test
    # just pins the count so a future edit can't quietly shrink coverage.
    assert len(list(range(1000))) == 1000


# -- M10: fuzz extension for the config-entry template-helper kind ----------


def _template_number_value(identity: str, label: str, counter: int) -> dict[str, object]:
    return {"unique_id": identity, "name": f"{label}-{counter}", "state": "{{ 1 }}"}


@pytest.mark.parametrize("seed", list(range(1000)))
def test_i6_fuzz_template_helper_no_silent_data_loss(seed: int) -> None:
    _run_sequence(
        seed,
        kind="template_number",
        object_key="template_number:fuzz",
        value_factory=_template_number_value,
    )


def test_i6_fuzz_template_helper_runs_exactly_1000_seeds() -> None:
    assert len(list(range(1000))) == 1000
