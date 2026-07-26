"""Regression: a NEW script must be created under the object_id its bundle
declares -- never under a slug of its ``alias``.

**Field evidence (BrandtCamp bundle, 2026-07-25).**
``@script(id="dining_bid_manual", alias="Dining Bid: Manual Hold")`` was
pushed and landed in Home Assistant as ``script.dining_bid_manual_hold``,
silently breaking every caller that invoked ``script.dining_bid_manual``
(the owner had to rename by hand). ``hassle validate`` reported nothing,
and `hassle push` reported success.

**The cause is Hassle's own create path, not Home Assistant.** A script's
object_id is extrinsic -- `ScriptConfig` has no ``id`` field at all and
`hassle.compiler.bundle._build_script` deliberately keeps the declared id out
of the body (it belongs in the REST path, ``/api/config/script/config/
{object_id}``, docs/internals/ha-api-notes.md §3). But `Backend.create(kind,
config)` takes no identity argument, so the id has to ride *in* the config
dict -- exactly as `Backend.update` already forwards it
(``{**config, "id": identity}``). The CREATE branch of
`hassle.sync.apply._apply_one` never did that, so both backends fell through
to their "no id supplied" fallback and invented one by slugifying ``alias``
(`DirectBackend._awrite_script`, `FakeBackend._derive_identity`), then POSTed
to that URL -- and HA faithfully stored the script where it was told to.
`_apply_one`'s divergence guard (`CreatedIdentityDivergedError`) exempted
scripts as "caller-keyed ... so their create is always exact", which was
true of the protocol and false of the payload, so the divergence was silent.

Home Assistant honors the caller-supplied script object_id; it does NOT
derive one from ``alias`` (docs/internals/ha-api-notes.md §17.5's script-side
amendment, and the live-HA proof in
`tests/integration/test_live_category_writeback.py::
test_push_create_script_scope_assigns_category`, whose script's alias slug
differs from its object_id). Automations are likewise unaffected -- their
``id`` is a real stored body field that `_build_automation` always emits --
which `test_automation_create_is_unaffected` pins as the control case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hassle.backend.fake import FakeBackend
from hassle.compiler.bundle import compile_bundle
from hassle.ir.canonical import sha256_hash, storage_canonical
from hassle.ir.keys import object_key
from hassle.sync import ApplyOutcome, Manifest, ManifestEntry, Plan, PlanAction, PlanEntry
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan

ObjectMap = dict[str, tuple[str, dict[str, Any]]]

# The exact declaration from the field report: `slugify(alias)` is
# `dining_bid_manual_hold`, which is NOT the declared object_id.
FIELD_BUNDLE = """
from hassle import script, service

@script(id="dining_bid_manual", alias="Dining Bid: Manual Hold")
def dining_bid_manual():
    service("light.turn_on", target={"entity_id": "light.hallway"})
"""


def _write_bundle(tmp_path: Path, code: str, name: str = "scripts.py") -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir(exist_ok=True)
    (bundle / name).write_text(code, encoding="utf-8")
    return bundle


def _local_objects(bundle: Path) -> ObjectMap:
    result = compile_bundle(bundle)
    return {key: (obj.kind(), obj.to_ha()) for key, obj in result.objects.items()}


def _remote_objects(backend: FakeBackend, kinds: list[str]) -> ObjectMap:
    return {
        object_key(kind, identity): (kind, config)
        for kind in kinds
        for identity, config in backend.list_remote(kind).items()
    }


def _empty_manifest() -> Manifest:
    return Manifest(synced_at="t0", ha_version="2026.7", objects={})


def test_new_script_is_created_under_its_declared_object_id(tmp_path: Path) -> None:
    """The field-evidence reproduction: push a brand-new script whose alias
    does not slugify to its declared id, and it must land under the DECLARED
    id (`script.dining_bid_manual`), not the alias slug.
    """
    bundle = _write_bundle(tmp_path, FIELD_BUNDLE)
    local = _local_objects(bundle)
    assert set(local) == {"script:dining_bid_manual"}
    # The compiled body itself carries no `id` -- the object_id is extrinsic
    # (real HA's script read-back has no `id` either), so the apply layer is
    # the only place that can carry the declared id to the backend.
    assert "id" not in local["script:dining_bid_manual"][1]

    backend = FakeBackend()
    manifest = _empty_manifest()
    plan = compute_plan(
        manifest=manifest,
        local_objects=local,
        remote_objects=_remote_objects(backend, ["script"]),
    )
    assert [(e.object_key, e.action) for e in plan.entries] == [
        ("script:dining_bid_manual", PlanAction.CREATE)
    ]

    result = apply_plan(plan, backend, manifest, synced_at="t1")
    assert result.succeeded is True, result.outcomes
    assert list(backend.list_remote("script")) == ["dining_bid_manual"]
    # ...and the id never leaks into the stored body (docs/internals/
    # ha-api-notes.md: a script's stored/read-back body has no `id` key).
    assert "id" not in backend.list_remote("script")["dining_bid_manual"]


def test_pushed_script_replans_as_noop_not_a_duplicate(tmp_path: Path) -> None:
    """The downstream damage the wrong id caused: with the script live under
    the alias slug, the manifest key (`script:dining_bid_manual`) matched
    nothing remote, so every subsequent push planned ANOTHER create -- the
    duplicate-forever signature `CreatedIdentityDivergedError` exists to
    prevent. An immediate re-plan after a correct push is a full NOOP.
    """
    bundle = _write_bundle(tmp_path, FIELD_BUNDLE)
    backend = FakeBackend()
    manifest = _empty_manifest()
    local = _local_objects(bundle)

    plan = compute_plan(
        manifest=manifest,
        local_objects=local,
        remote_objects=_remote_objects(backend, ["script"]),
    )
    result = apply_plan(plan, backend, manifest, synced_at="t1")
    assert result.succeeded is True and result.manifest is not None

    replan = compute_plan(
        manifest=result.manifest,
        local_objects=local,
        remote_objects=_remote_objects(backend, ["script"]),
    )
    assert [(e.object_key, e.action) for e in replan.entries] == [
        ("script:dining_bid_manual", PlanAction.NOOP)
    ]


def test_automation_create_is_unaffected(tmp_path: Path) -> None:
    """Control case: an automation's `id` is a real stored body field (not
    slug-derived), so an alias that does not slugify to the id was never a
    problem for automations. Pinned so a future "generalize the rule to
    automations" change has to argue with a test.
    """
    bundle = _write_bundle(
        tmp_path,
        """
from hassle import automation, service

@automation(id="dining_bid_manual", alias="Dining Bid: Manual Hold")
def dining_bid_manual():
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        name="automations.py",
    )
    local = _local_objects(bundle)
    # Unlike a script, the automation body DOES carry its id.
    assert local["automation:dining_bid_manual"][1]["id"] == "dining_bid_manual"

    backend = FakeBackend()
    manifest = _empty_manifest()
    plan = compute_plan(
        manifest=manifest,
        local_objects=local,
        remote_objects=_remote_objects(backend, ["automation"]),
    )
    result = apply_plan(plan, backend, manifest, synced_at="t1")
    assert result.succeeded is True, result.outcomes
    assert list(backend.list_remote("automation")) == ["dining_bid_manual"]


class _DivergingScriptBackend(FakeBackend):
    """A backend that assigns a script some identity other than the one the
    caller asked for -- the failure mode this regression is about, forced.
    """

    def create(self, kind: str, config: dict[str, Any]) -> str:
        if kind == "script":
            config = {**config, "id": f"{config.get('id', 'script')}_elsewhere"}
        return super().create(kind, config)


def test_script_create_identity_divergence_is_never_silent(tmp_path: Path) -> None:
    """Belt and braces: if a backend ever again assigns a script an identity
    the bundle did not declare, apply must roll the created object back out
    and fail loudly (`CreatedIdentityDivergedError`) rather than report
    success -- the guard scripts were previously exempt from.
    """
    bundle = _write_bundle(tmp_path, FIELD_BUNDLE)
    backend = _DivergingScriptBackend()
    manifest = _empty_manifest()
    plan = compute_plan(
        manifest=manifest,
        local_objects=_local_objects(bundle),
        remote_objects=_remote_objects(backend, ["script"]),
    )

    result = apply_plan(plan, backend, manifest, synced_at="t1")

    assert result.succeeded is False
    assert result.outcomes["script:dining_bid_manual"] is ApplyOutcome.FAILED
    assert result.failure_message is not None
    assert "dining_bid_manual" in result.failure_message
    # The object created under the wrong identity was removed again.
    assert backend.list_remote("script") == {}


def test_rollback_restores_a_deleted_script_under_its_original_object_id() -> None:
    """The same missing-id defect in the rollback path: restoring a DELETEd
    script recreates it from its remote read-back body, which (correctly)
    has no `id` -- so without the object_id being supplied, a rolled-back
    delete resurrected the script at the alias slug instead of where it
    was, losing the original entity id.

    Setup: a script whose alias does not slugify to its object_id is deleted,
    then a later entry in the same plan fails, forcing a rollback.
    """
    backend = FakeBackend()
    backend.create(
        "script",
        {"id": "dining_bid_manual", "alias": "Dining Bid: Manual Hold", "sequence": []},
    )
    assert list(backend.list_remote("script")) == ["dining_bid_manual"]
    remote = backend.list_remote("script")["dining_bid_manual"]

    manifest = Manifest(
        synced_at="t0",
        ha_version="2026.7",
        objects={
            "script:dining_bid_manual": ManifestEntry(
                source="dining_bid_manual.py",
                compiled_hash=sha256_hash(storage_canonical("script", remote)),
                kind="dsl",
            )
        },
    )

    # Scripts apply before automations (`_kind_sort_key`), so the automation
    # CREATE below is the later entry -- and it collides with an object that
    # materialized between plan and apply, which aborts and rolls back.
    backend.create("automation", {"id": "collides", "alias": "Created in UI"})
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="script:dining_bid_manual",
                kind="script",
                action=PlanAction.DELETE,
                remote_hash_at_plan=sha256_hash(storage_canonical("script", remote)),
            ),
            PlanEntry(
                object_key="automation:collides",
                kind="automation",
                action=PlanAction.CREATE,
                local={"id": "collides", "alias": "Mine"},
            ),
        ]
    )

    result = apply_plan(plan, backend, manifest, synced_at="t1")

    assert result.succeeded is False
    # The rolled-back script is back under its ORIGINAL object_id, not the
    # alias slug -- `script.dining_bid_manual` still resolves for its callers.
    assert list(backend.list_remote("script")) == ["dining_bid_manual"]
    assert backend.list_remote("script")["dining_bid_manual"] == remote
