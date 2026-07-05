"""MILESTONES M6 tests 4 & 5 — transactional apply against real HA.

- test 4 (`test_apply_rollback_live`): a push batch whose 3rd object is crafted
  invalid (rejected by HA) → objects 1-2 are restored; HA state is hash-identical
  to pre-apply.
- test 5 (`test_apply_aborts_on_drift_live`): an object mutated via HA's API
  between plan and apply → apply aborts before writing anything. Includes the
  **CREATE-collision** case (M5 review finding): an object appearing under a
  planned-create identity between plan and apply is drift too.
- The M4 finding folded in here: does HA rewrite inner legacy `platform:` →
  `trigger:` on storage? (`normalize_ha` preserves inner `platform:`.) Verified
  directly against HA below.
"""

from __future__ import annotations

from hassle.backend import DirectBackend
from hassle.ir.canonical import sha256_hash
from hassle.ir.normalize import normalize_ha
from hassle.sync import ApplyOutcome, Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan


def _hash_state(ha: DirectBackend, kinds: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for kind in kinds:
        for identity, config in ha.list_remote(kind).items():
            out[f"{kind}:{identity}"] = sha256_hash(config)
    return out


def test_apply_rollback_live(ha: DirectBackend) -> None:
    kinds = ("automation", "input_boolean")
    ha.create("input_boolean", {"id": "roll_flag", "name": "Roll Flag"})
    ha.create(
        "automation",
        {"id": "roll_auto", "alias": "Roll Auto", "trigger": [], "condition": [], "action": []},
    )
    before = _hash_state(ha, kinds)

    helper_hash = sha256_hash(ha.list_remote("input_boolean")["roll_flag"])
    auto_hash = sha256_hash(ha.list_remote("automation")["roll_auto"])

    # 3rd object is invalid: an automation trigger referencing a bogus platform,
    # which HA's config API rejects on POST.
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="input_boolean:roll_flag",
                kind="input_boolean",
                action=PlanAction.UPDATE,
                local={"id": "roll_flag", "name": "Roll Flag v2"},
                remote_hash_at_plan=helper_hash,
            ),
            PlanEntry(
                object_key="automation:roll_auto",
                kind="automation",
                action=PlanAction.UPDATE,
                local={
                    "id": "roll_auto",
                    "alias": "Roll Auto v2",
                    "trigger": [],
                    "condition": [],
                    "action": [],
                },
                remote_hash_at_plan=auto_hash,
            ),
            PlanEntry(
                object_key="automation:roll_bad",
                kind="automation",
                action=PlanAction.CREATE,
                local={"id": "roll_bad", "triggers": "this-should-be-a-list-not-a-string"},
            ),
        ]
    )
    manifest = Manifest(synced_at="base", ha_version="test", objects={})
    result = apply_plan(plan, ha, manifest)

    assert result.succeeded is False
    assert result.outcomes["automation:roll_bad"] is ApplyOutcome.FAILED
    assert result.outcomes["input_boolean:roll_flag"] is ApplyOutcome.ROLLED_BACK
    assert result.outcomes["automation:roll_auto"] is ApplyOutcome.ROLLED_BACK
    # HA state hash-identical to pre-apply (rollback restored objects 1-2).
    assert _hash_state(ha, kinds) == before


def test_apply_aborts_on_drift_live(ha: DirectBackend) -> None:
    ha.create(
        "automation",
        {"id": "drift_me", "alias": "Original", "trigger": [], "condition": [], "action": []},
    )
    plan_hash = sha256_hash(ha.list_remote("automation")["drift_me"])

    # Mutate via HA's API between plan and apply.
    ha.update(
        "automation",
        "drift_me",
        {"id": "drift_me", "alias": "Drifted in UI", "trigger": [], "condition": [], "action": []},
    )
    drifted = ha.list_remote("automation")["drift_me"]

    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:drift_me",
                kind="automation",
                action=PlanAction.UPDATE,
                local={
                    "id": "drift_me",
                    "alias": "Local edit",
                    "trigger": [],
                    "condition": [],
                    "action": [],
                },
                remote_hash_at_plan=plan_hash,
            )
        ]
    )
    result = apply_plan(plan, ha, Manifest(synced_at="b", ha_version="t", objects={}))
    assert result.succeeded is False
    assert result.outcomes["automation:drift_me"] is ApplyOutcome.ABORTED
    # Nothing written: HA still shows the UI's drift, not the local edit.
    assert ha.list_remote("automation")["drift_me"] == drifted


def test_apply_aborts_on_create_collision_live(ha: DirectBackend) -> None:
    # Plan a CREATE for an id that is free at plan time.
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="automation:collide",
                kind="automation",
                action=PlanAction.CREATE,
                local={
                    "id": "collide",
                    "alias": "Mine",
                    "trigger": [],
                    "condition": [],
                    "action": [],
                },
            )
        ]
    )
    # Between plan and apply, the id is taken (UI creates it).
    ha.create(
        "automation",
        {"id": "collide", "alias": "Created in UI", "trigger": [], "condition": [], "action": []},
    )

    result = apply_plan(plan, ha, Manifest(synced_at="b", ha_version="t", objects={}))
    assert result.succeeded is False
    assert result.outcomes["automation:collide"] is ApplyOutcome.ABORTED
    # The UI's object is not overwritten.
    assert ha.list_remote("automation")["collide"]["alias"] == "Created in UI"


def test_ha_does_not_rewrite_inner_platform_to_trigger(ha: DirectBackend) -> None:
    """M4 finding: normalize_ha preserves inner `platform:`; verify HA agrees.

    If this ever fails on a future HA (inner `platform:` rewritten to `trigger:`
    on storage), `normalize_ha` needs the extra rule and this is the evidence.
    """
    posted = {
        "id": "platform_probe",
        "alias": "Platform Probe",
        "trigger": [{"platform": "state", "entity_id": "input_boolean.x", "to": "on"}],
        "condition": [],
        "action": [{"service": "input_boolean.toggle", "target": {"entity_id": "input_boolean.x"}}],
    }
    ha.create("automation", posted)
    stored = ha.list_remote("automation")["platform_probe"]

    trig = stored["triggers"][0]
    assert "platform" in trig and "trigger" not in trig, (
        "HA rewrote inner platform:->trigger: on storage; normalize_ha must be extended "
        f"(stored trigger was {trig!r})"
    )
    # And normalize_ha reproduces exactly what HA returns (round-trip base).
    assert sha256_hash(normalize_ha(posted, kind="automation")) == sha256_hash(stored)
