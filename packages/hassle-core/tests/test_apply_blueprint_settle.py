"""ha-api-notes §40.8's second implication — the post-update reload race.

§40.8 records that `blueprint/save`'s cache write races its own WS response:
for several seconds `blueprint/substitute` still serves the PRIOR document.
The drift oracle already settles across that window. What it left open is
that the `automation.reload` issued after a blueprint UPDATE
(blueprints-design §4.3) races the SAME window — HA would re-expand every
live instance against the OLD blueprint and leave them stale until some
future unrelated reload, a silently wrong house under a push that reported
success. §4.3's reload was, until this, "reload and hope".

The contract under test: **settle, then reload.** After a blueprint UPDATE
with declared instances, `apply_plan` probes `blueprint/substitute` (bounded,
the drift oracle's exact settle shape and knobs) until HA's answer matches
the just-saved content, and only then reloads. On settle timeout it still
reloads — the pre-existing behaviour is the fallback, never a hang — and
surfaces a warning naming the file and the operator remediation.

The fake never sleeps: `FakeBackend.blueprint_settle_sleep` RECORDS each
requested wait instead of taking it (R2's "no network in unit tests" applied
to the clock), so these tests assert the exact wait sequence, and the
agreeing-first-answer path provably costs nothing.
"""

from __future__ import annotations

from typing import Any

from hassle.backend.fake import FakeBackend
from hassle.blueprints import blueprint_body
from hassle.ir import BLUEPRINT_KIND, sha256_hash
from hassle.sync.apply import apply_plan
from hassle.sync.models import Manifest, ManifestEntry, Plan, PlanAction, PlanEntry

PATH = "local/room-switch-controls.yaml"
BLUEPRINT_KEY = f"blueprint:automation/{PATH}"
IDENTITY = f"automation/{PATH}"

#: OLD and NEW differ inside the config block (`mode:`), so a stale
#: substitute answer genuinely mismatches the new local expansion and a
#: fresh one genuinely matches -- the settle has something real to detect.
OLD_SOURCE = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    switch_entity:
mode: restart
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions: []
"""

NEW_SOURCE = OLD_SOURCE.replace("mode: restart", "mode: single")

INSTANCE_INPUTS = {"switch_entity": "event.office"}


def _body(source: str) -> dict[str, Any]:
    return blueprint_body(domain="automation", path=PATH, source=source)


class _SettleRecordingBackend(FakeBackend):
    """FakeBackend plus an ordered log of updates, substitute probes (tagged
    stale/fresh) and reloads — the ORDER is what §40.8's fix is about."""

    def __init__(self) -> None:
        super().__init__()
        self.log: list[tuple[str, str]] = []

    def update(self, kind: str, identity: str, config: dict[str, Any]) -> None:
        super().update(kind, identity, config)
        self.log.append(("update", identity))

    def blueprint_substitute(
        self, domain: str, path: str, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        # Mirror the fake's own staleness condition BEFORE super() decrements.
        stale = self.blueprint_stale_reads > 0 and f"{domain}/{path}" in self._blueprint_previous
        result = super().blueprint_substitute(domain, path, inputs)
        self.log.append(("substitute", "stale" if stale else "fresh"))
        return result

    def reload_automations(self) -> None:
        super().reload_automations()
        self.log.append(("reload", "*"))


def _seeded_backend(*, stale_reads: int = 0) -> _SettleRecordingBackend:
    backend = _SettleRecordingBackend()
    backend.create(BLUEPRINT_KIND, _body(OLD_SOURCE))
    backend.blueprint_stale_reads = stale_reads
    return backend


def _update_plan(backend: FakeBackend) -> Plan:
    return Plan(
        entries=[
            PlanEntry(
                object_key=BLUEPRINT_KEY,
                kind=BLUEPRINT_KIND,
                action=PlanAction.UPDATE,
                local=_body(NEW_SOURCE),
                remote_hash_at_plan=backend.hash_of(BLUEPRINT_KIND, IDENTITY),
            )
        ]
    )


def _manifest() -> Manifest:
    return Manifest(
        synced_at="2026-08-10T00:00:00Z",
        ha_version="2026.8.0",
        objects={
            BLUEPRINT_KEY: ManifestEntry(
                source=None,
                compiled_hash=sha256_hash(_body(OLD_SOURCE)),
                kind="blueprint",
            )
        },
    )


def _instances() -> dict[str, list[str]]:
    return {BLUEPRINT_KEY: ["automation:office_switch"]}


def _inputs() -> dict[str, dict[str, Any]]:
    return {BLUEPRINT_KEY: INSTANCE_INPUTS}


def _apply(backend: _SettleRecordingBackend, **overrides: Any):
    kwargs: dict[str, Any] = {
        "blueprint_instances": _instances(),
        "blueprint_instance_inputs": _inputs(),
    }
    kwargs.update(overrides)
    return apply_plan(_update_plan(backend), backend, _manifest(), **kwargs)


def test_the_reload_waits_out_the_stale_window() -> None:
    """The core §40.8 fix: with HA still serving the prior document, the
    reload fires only after substitute has come back FRESH — never into the
    stale window where it would re-expand instances against the OLD copy."""
    backend = _seeded_backend(stale_reads=2)
    result = _apply(backend)
    assert result.succeeded
    assert result.blueprint_reloads == [BLUEPRINT_KEY]
    assert result.blueprint_warnings == []
    # Two stale answers, each followed by one settle interval, then fresh.
    assert backend.blueprint_settle_waits == [1.0, 1.0]
    substitutes = [tag for op, tag in backend.log if op == "substitute"]
    assert substitutes == ["stale", "stale", "fresh"]
    # The ordering assertion §40.8's fix exists for: the reload comes AFTER
    # the last (fresh) substitute, and nothing probes after the reload.
    ops = [op for op, _ in backend.log]
    assert ops.index("reload") > len(ops) - 1 - ops[::-1].index("substitute")


def test_an_agreeing_first_answer_never_sleeps() -> None:
    """Free on the common path: HA already fresh means zero waits — the
    settle must cost nothing when there is nothing to settle."""
    backend = _seeded_backend(stale_reads=0)
    result = _apply(backend)
    assert result.succeeded
    assert result.blueprint_reloads == [BLUEPRINT_KEY]
    assert result.blueprint_warnings == []
    assert backend.blueprint_settle_waits == []
    assert [tag for op, tag in backend.log if op == "substitute"] == ["fresh"]


def test_a_never_healing_window_still_reloads_and_warns() -> None:
    """Timeout is a fallback to the old behaviour plus a warning — never a
    hang, never a skipped reload. The warning names the §40.8 window and the
    operator remediation (one more manual reload)."""
    backend = _seeded_backend(stale_reads=99)
    result = _apply(backend)
    assert result.succeeded  # metadata-only, like category_warnings
    assert result.blueprint_reloads == [BLUEPRINT_KEY]
    # Initial probe plus SETTLE_TIMEOUT // SETTLE_INTERVAL re-asks, all stale.
    assert backend.blueprint_settle_waits == [1.0] * 5
    assert [tag for op, tag in backend.log if op == "substitute"] == ["stale"] * 6
    assert backend.log[-1] == ("reload", "*")
    (warning,) = result.blueprint_warnings
    assert "40.8" in warning
    assert IDENTITY in warning
    assert "reload" in warning.lower()


def test_no_declared_instances_skips_probe_and_reload() -> None:
    """Nothing to re-expand: neither the probe nor the reload has work. This
    skip predates the settle and must survive it."""
    backend = _seeded_backend(stale_reads=2)
    result = _apply(backend, blueprint_instances={})
    assert result.succeeded
    assert result.blueprint_reloads == []
    assert result.blueprint_warnings == []
    assert backend.blueprint_settle_waits == []
    assert [op for op, _ in backend.log if op in ("substitute", "reload")] == []


def test_omitting_instance_inputs_preserves_the_presettle_behaviour() -> None:
    """`blueprint_instance_inputs` is additive: a caller that does not pass
    it gets the pre-settle sequence byte for byte — immediate reload, no
    probe, no waits, no warning."""
    backend = _seeded_backend(stale_reads=2)
    result = _apply(backend, blueprint_instance_inputs=None)
    assert result.succeeded
    assert result.blueprint_reloads == [BLUEPRINT_KEY]
    assert result.blueprint_warnings == []
    assert backend.blueprint_settle_waits == []
    assert [op for op, _ in backend.log if op == "substitute"] == []
    assert backend.log[-1] == ("reload", "*")
