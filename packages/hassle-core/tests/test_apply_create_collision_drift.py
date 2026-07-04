"""CREATE-collision drift detection in the apply engine (M5 review finding).

DESIGN §8.2's "apply is transactional" paragraph says apply re-verifies remote
hashes immediately before writing and aborts on drift. M5's `apply_plan`
implemented that for UPDATE/DELETE (which carry a `remote_hash_at_plan`), but a
`CREATE` entry has no plan-time remote hash because, at plan time, nothing
existed under that identity. The M5 review (surfaced again in MILESTONES M6
test 5) flagged the gap: if some object appears under a planned-CREATE identity
*between* plan and apply — a UI-created object, or a racing second client —
blindly POSTing would silently overwrite it. That is drift too, and apply must
abort before writing, exactly like the UPDATE/DELETE case.

These are pure-logic tests against `FakeBackend`; the live-HA analogue is
MILESTONES M6 test 5 (`test_apply_aborts_on_drift_live`, CREATE-collision case).
"""

from __future__ import annotations

from hassle.backend.fake import FakeBackend
from hassle.sync import ApplyOutcome, Manifest, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan


def _create_entry(object_key: str, kind: str, local: dict[str, object]) -> PlanEntry:
    return PlanEntry(object_key=object_key, kind=kind, action=PlanAction.CREATE, local=local)


def test_create_aborts_when_identity_appears_between_plan_and_apply() -> None:
    backend = FakeBackend()
    # At plan time nothing exists under "automation:a_new".
    plan = Plan(
        entries=[_create_entry("automation:a_new", "automation", {"id": "a_new", "alias": "Mine"})]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})

    # Drift: a *different* object materializes under that identity before apply
    # (e.g. someone created it in the UI, or a racing client).
    backend.create("automation", {"id": "a_new", "alias": "Created in UI"})
    backend.reset_write_tracking()

    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    assert result.outcomes["automation:a_new"] is ApplyOutcome.ABORTED
    # Nothing written: the colliding object is left exactly as the UI left it.
    assert backend.writes_since_reset() == 0
    assert backend.list_remote("automation")["a_new"]["alias"] == "Created in UI"


def test_create_still_succeeds_when_identity_is_free_at_apply() -> None:
    backend = FakeBackend()
    plan = Plan(
        entries=[_create_entry("automation:a_new", "automation", {"id": "a_new", "alias": "Mine"})]
    )
    manifest = Manifest(synced_at="t", ha_version="v", objects={})

    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is True
    assert result.outcomes["automation:a_new"] is ApplyOutcome.SUCCEEDED
    assert backend.list_remote("automation")["a_new"]["alias"] == "Mine"


def test_create_collision_rolls_back_earlier_applied_objects() -> None:
    """A CREATE-collision mid-plan rolls back objects already applied this run."""
    backend = FakeBackend()
    manifest = Manifest(synced_at="t", ha_version="v", objects={})

    # Helper applies first (dependency order); then the automation CREATE collides.
    plan = Plan(
        entries=[
            _create_entry("input_boolean:hb", "input_boolean", {"id": "hb", "name": "HB"}),
            _create_entry("automation:a_new", "automation", {"id": "a_new", "alias": "Mine"}),
        ]
    )

    backend.create("automation", {"id": "a_new", "alias": "Created in UI"})
    backend.reset_write_tracking()

    result = apply_plan(plan, backend, manifest)

    assert result.succeeded is False
    assert result.outcomes["automation:a_new"] is ApplyOutcome.ABORTED
    # The helper we created earlier in this run is rolled back out.
    assert result.outcomes["input_boolean:hb"] is ApplyOutcome.ROLLED_BACK
    assert "hb" not in backend.list_remote("input_boolean")
    # The colliding automation is untouched.
    assert backend.list_remote("automation")["a_new"]["alias"] == "Created in UI"
