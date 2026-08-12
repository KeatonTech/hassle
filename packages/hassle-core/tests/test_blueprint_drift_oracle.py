"""The substitute-compare drift oracle (blueprints-design §2.2 / §3).

HA cannot serve a blueprint's source back, so text comparison is impossible.
What IS possible: ask HA to expand its own copy with a known input set
(``blueprint/substitute``), expand the bundle's copy locally with the same
inputs, normalize, compare. Equal expansions mean the two copies agree in
every way that can matter to an instance.

§3 pins where the inputs come from: **one of the blueprint's own instances in
the bundle** — any instance covers all required inputs, or validate would have
failed (§6) — and a blueprint with **no** instances skips the check entirely,
because nothing can be affected by its drift.
"""

from __future__ import annotations

from typing import Any

from hassle.backend.fake import FakeBackend
from hassle.blueprints import blueprint_body, instances_by_blueprint
from hassle.ir import BLUEPRINT_KIND
from hassle.sync.blueprint_drift import detect_blueprint_drift


def _NO_WAIT(_seconds: float) -> None:
    """A no-op settle for tests that are not about the settle itself
    (ha-api-notes §40.8). The retry only fires on a MISMATCH, so without this
    every real-drift assertion would spend the full SETTLE_TIMEOUT sleeping."""


SOURCE = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    switch_entity:
    room_light:
mode: restart
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions:
  - action: light.turn_on
    target:
      entity_id: !input room_light
"""

PATH = "local/room-switch-controls.yaml"
KEY = f"blueprint:automation/{PATH}"

INSTANCE = {
    "id": "office_switch",
    "use_blueprint": {
        "path": PATH,
        "input": {"switch_entity": "event.office", "room_light": "light.office"},
    },
}


def _local(source: str = SOURCE) -> dict[str, Any]:
    return blueprint_body(domain="automation", path=PATH, source=source)


def _objects(*, source: str = SOURCE, with_instance: bool = True) -> dict[str, Any]:
    objects: dict[str, Any] = {KEY: (BLUEPRINT_KIND, _local(source))}
    if with_instance:
        objects["automation:office_switch"] = ("automation", INSTANCE)
    return objects


def _backend(source: str = SOURCE) -> FakeBackend:
    backend = FakeBackend()
    backend.create(BLUEPRINT_KIND, _local(source))
    return backend


# --- instances_by_blueprint ------------------------------------------------


def test_instances_are_found_by_their_use_blueprint_path() -> None:
    bodies = {"automation:office_switch": INSTANCE}
    assert instances_by_blueprint(bodies) == {KEY: ["automation:office_switch"]}


def test_instances_are_grouped_and_ordered_deterministically() -> None:
    bodies = {
        "automation:b": INSTANCE,
        "automation:a": INSTANCE,
    }
    assert instances_by_blueprint(bodies) == {KEY: ["automation:a", "automation:b"]}


def test_an_automation_with_no_use_blueprint_is_ignored() -> None:
    assert instances_by_blueprint({"automation:plain": {"id": "plain", "triggers": []}}) == {}


def test_a_community_blueprint_path_still_maps_to_its_would_be_key() -> None:
    """An instance of a blueprint that lives only in HA has no bundle file --
    but its key is still derivable, which is what lets §6's rule 2 name the
    file that WOULD make it managed."""
    body = {"id": "x", "use_blueprint": {"path": "jay-kub/taps.yaml", "input": {}}}
    assert instances_by_blueprint({"automation:x": body}) == {
        "blueprint:automation/jay-kub/taps.yaml": ["automation:x"]
    }


# --- detect_blueprint_drift ------------------------------------------------


def test_agreeing_copies_report_no_drift() -> None:
    assert detect_blueprint_drift(_backend(), _objects()) == frozenset()


def test_a_remotely_edited_blueprint_is_detected() -> None:
    """The whole point: the two documents' TEXT can't be compared, but their
    behaviour can."""
    backend = _backend()
    backend.update(
        BLUEPRINT_KIND,
        f"automation/{PATH}",
        _local(SOURCE.replace("light.turn_on", "light.toggle")),
    )
    assert detect_blueprint_drift(backend, _objects(), sleep=_NO_WAIT) == frozenset({KEY})


def test_a_blueprint_with_no_instances_is_skipped() -> None:
    """§3: "a blueprint with no instances skips the check (nothing can be
    affected by drift)" -- and there would be no input set to substitute
    with anyway."""
    backend = _backend()
    backend.update(
        BLUEPRINT_KIND,
        f"automation/{PATH}",
        _local(SOURCE.replace("light.turn_on", "light.toggle")),
    )
    assert detect_blueprint_drift(backend, _objects(with_instance=False)) == frozenset()


def test_a_blueprint_that_is_not_remote_yet_is_skipped() -> None:
    """Nothing to compare against: a `create` row has no remote copy."""
    assert detect_blueprint_drift(FakeBackend(), _objects()) == frozenset()


def test_normalization_differences_are_not_drift() -> None:
    """A blueprint authored in HA's legacy singular schema expands to the same
    automation as its plural twin. Comparing raw expansions would report
    permanent, unfixable drift for every legacy blueprint."""
    legacy = SOURCE.replace("triggers:", "trigger:").replace("actions:", "action:")
    legacy = legacy.replace("  - action: light.turn_on", "  - service: light.turn_on")
    backend = _backend(legacy)
    assert detect_blueprint_drift(backend, _objects(source=legacy)) == frozenset()


def test_a_backend_without_substitute_reports_nothing() -> None:
    """Additive, `getattr`-probed surface: a Backend implementer that doesn't
    expose `blueprint_substitute` simply skips the corroboration, exactly as
    one without `entry_id_for` gets `entry_id=None` forever."""

    class _Bare:
        def list_remote(self, kind: str) -> dict[str, dict[str, Any]]:
            return {}

    assert detect_blueprint_drift(_Bare(), _objects()) == frozenset()


def test_a_failing_substitute_is_not_reported_as_drift() -> None:
    """The oracle CORROBORATES; it must never invent a conflict out of a
    transport hiccup or an input set HA rejects. A failure means "unknown",
    and unknown is not drift (the manifest hash still governs)."""

    class _Exploding(FakeBackend):
        def blueprint_substitute(
            self, domain: str, path: str, inputs: dict[str, Any]
        ) -> dict[str, Any]:
            raise RuntimeError("boom")

    backend = _Exploding()
    backend.create(BLUEPRINT_KIND, _local())
    assert detect_blueprint_drift(backend, _objects()) == frozenset()


# --- the field false-positive (ha-api-notes §40.7) --------------------------
#
# First live run of the blueprint object kind against the owner's HA: the oracle reported "edited
# in place in Home Assistant" for a blueprint pushed seconds earlier and
# provably in sync. Root cause: `blueprint/substitute` is handed
# `{domain, path, input}` and NO INSTANCE, so it returns the CONFIG BLOCK ONLY
# and can never carry `id`/`alias`/`description` -- not even when the blueprint
# DOCUMENT declares an `alias:`/`description:` of its own, which community
# blueprints commonly do as a default label. The local expansion keeps whatever
# the document declared, so the two sides expressed different KEY SETS and the
# comparison read a superset-vs-subset difference as drift, permanently, for
# every correctly-synced blueprint of that shape.

LABELLED_SOURCE = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    switch_entity:
    room_light:
alias: Room switch controls
description: The blueprint's own default label.
mode: restart
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions:
  - action: light.turn_on
    target:
      entity_id: !input room_light
"""


def _labelled_backend() -> FakeBackend:
    backend = FakeBackend()
    backend.create(BLUEPRINT_KIND, _local(LABELLED_SOURCE))
    return backend


def test_substitute_returns_the_config_block_only() -> None:
    """The observed API shape (§40.7): no instance means no instance identity.

    Pinned on the fake because it is what real HA does, not a special case --
    a fake that returned these keys would keep both sides' key sets
    artificially identical and could never catch this class of bug.
    """
    expanded = _labelled_backend().blueprint_substitute(
        "automation", PATH, {"switch_entity": "event.office", "room_light": "light.office"}
    )
    assert "alias" not in expanded
    assert "description" not in expanded
    assert "id" not in expanded
    assert set(expanded) == {"mode", "triggers", "actions"}


def test_an_in_sync_blueprint_with_its_own_alias_reports_no_drift() -> None:
    """The regression itself: identical documents, differing key sets."""
    backend = _labelled_backend()
    assert detect_blueprint_drift(backend, _objects(source=LABELLED_SOURCE)) == frozenset()


def test_real_drift_is_still_caught_on_a_labelled_blueprint() -> None:
    """The fix must not be a blanket "ignore differences": a genuine remote
    edit to a key BOTH sides express is still drift."""
    backend = _labelled_backend()
    backend.update(
        BLUEPRINT_KIND,
        f"automation/{PATH}",
        _local(LABELLED_SOURCE.replace("light.turn_on", "light.toggle")),
    )
    assert detect_blueprint_drift(
        backend, _objects(source=LABELLED_SOURCE), sleep=_NO_WAIT
    ) == frozenset({KEY})


def test_a_remote_that_drops_a_whole_key_is_not_drift() -> None:
    """Generalizing the same rule: any key only ONE side can express carries
    no information about whether HA's copy drifted, because substitute's
    output is built without an instance. Compared on the key intersection."""

    class _Truncating(FakeBackend):
        def blueprint_substitute(
            self, domain: str, path: str, inputs: dict[str, Any]
        ) -> dict[str, Any]:
            expanded = super().blueprint_substitute(domain, path, inputs)
            return {k: v for k, v in expanded.items() if k != "mode"}

    backend = _Truncating()
    backend.create(BLUEPRINT_KIND, _local(LABELLED_SOURCE))
    assert detect_blueprint_drift(backend, _objects(source=LABELLED_SOURCE)) == frozenset()


# --- post-save staleness (ha-api-notes §40.8) -------------------------------
#
# Second field false-positive, root-caused live: `blueprint/save`, then a plan
# within seconds reported drift; a hand comparison a minute later showed zero
# difference; a fresh plan now shows none. `blueprint/substitute` served a
# STALE copy of the blueprint briefly after the save -- so the oracle told the
# user their blueprint conflicted and prescribed an `--accept-local` they
# should never have run. The `automation.reload` §4.3 issues after the save did
# NOT prevent it.


def _stale_backend(stale_reads: int) -> FakeBackend:
    """In sync, but the next `stale_reads` substitutes serve the old document
    -- exactly the window a plan run right after a push falls into."""
    backend = FakeBackend()
    backend.create(BLUEPRINT_KIND, _local(SOURCE.replace("light.turn_on", "light.toggle")))
    backend.update(BLUEPRINT_KIND, f"automation/{PATH}", _local())
    backend.blueprint_stale_reads = stale_reads
    return backend


def _calls() -> tuple[list[float], Any]:
    waited: list[float] = []
    return waited, waited.append


def test_without_the_settle_a_stale_read_reads_as_drift() -> None:
    """The bug itself, reproduced offline: this is what shipped."""
    assert detect_blueprint_drift(_stale_backend(1), _objects(), settle_timeout=0) == frozenset(
        {KEY}
    )


def test_the_settle_absorbs_a_stale_read() -> None:
    waited, sleep = _calls()
    assert detect_blueprint_drift(_stale_backend(1), _objects(), sleep=sleep) == frozenset()
    # Exactly one re-ask: it agreed on the first retry, so the loop stopped.
    assert waited == [1.0]


def test_the_settle_absorbs_a_longer_stale_window() -> None:
    waited, sleep = _calls()
    assert detect_blueprint_drift(_stale_backend(3), _objects(), sleep=sleep) == frozenset()
    assert waited == [1.0, 1.0, 1.0]


def test_a_real_remote_edit_survives_every_retry() -> None:
    """The mitigation must not become a blanket "retry until it agrees": a
    genuinely edited remote never agrees, so it stays a conflict."""
    backend = _backend()
    backend.update(
        BLUEPRINT_KIND,
        f"automation/{PATH}",
        _local(SOURCE.replace("light.turn_on", "light.toggle")),
    )
    waited, sleep = _calls()
    assert detect_blueprint_drift(backend, _objects(), sleep=sleep) == frozenset({KEY})
    # Bounded: it gave up rather than retrying forever.
    assert len(waited) == 5


def test_a_never_healing_stale_read_is_still_reported() -> None:
    """Bounded, not infinite -- a plan must never hang on a stuck backend."""
    waited, sleep = _calls()
    assert detect_blueprint_drift(_stale_backend(99), _objects(), sleep=sleep) == frozenset({KEY})
    assert len(waited) == 5


def test_an_agreeing_first_answer_never_waits() -> None:
    """The settle costs nothing on the overwhelmingly common path."""
    waited, sleep = _calls()
    assert detect_blueprint_drift(_backend(), _objects(), sleep=sleep) == frozenset()
    assert waited == []


def test_the_settle_knobs_bound_the_retry_count() -> None:
    waited, sleep = _calls()
    detect_blueprint_drift(
        _stale_backend(99), _objects(), settle_timeout=2, settle_interval=0.5, sleep=sleep
    )
    assert waited == [0.5, 0.5, 0.5, 0.5]


def test_a_zero_interval_disables_the_retry() -> None:
    waited, sleep = _calls()
    assert detect_blueprint_drift(
        _stale_backend(1), _objects(), settle_interval=0, sleep=sleep
    ) == frozenset({KEY})
    assert waited == []
