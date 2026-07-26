"""Live proof, against real HA: a new script is created under the object_id
its bundle declares, not under a slug of its ``alias``.

The offline contract lives in
`packages/hassle-core/tests/test_script_create_object_id.py` (FakeBackend);
this is the same field-evidence case (BrandtCamp 2026-07-25:
``@script(id="dining_bid_manual", alias="Dining Bid: Manual Hold")`` landing
as ``script.dining_bid_manual_hold``) driven through the real compile → plan
→ push path against a live instance, on both the ``stable`` and ``dev``
images CI runs.

It also pins the HA-side half of docs/internals/ha-api-notes.md §17.5's
2026-07-26 amendment: **scripts have no id-from-alias-slug rule.** HA stores
a script under the object_id in the REST path
(``/api/config/script/config/{object_id}``) and its entity is
``script.<object_id>``; ``alias`` is only the friendly name. If some future
HA version ever did start deriving script ids from ``alias``, this test is
where that shows up first -- and `_awrite_script`'s read-back would disagree
with the declared id, exactly the divergence `CreatedIdentityDivergedError`
now covers for scripts.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from hassle.backend import DirectBackend
from hassle.compiler.bundle import compile_bundle
from hassle.ir.keys import object_key, slugify
from hassle.sync import Manifest, PlanAction
from hassle.sync.apply import apply_plan
from hassle.sync.plan import compute_plan

ObjMap = dict[str, tuple[str, dict[str, Any]]]

DECLARED_ID = "dining_bid_manual"
ALIAS = "Dining Bid: Manual Hold"

BUNDLE = f'''
from hassle import script, service


@script(id="{DECLARED_ID}", alias="{ALIAS}")
def {DECLARED_ID}():
    service("homeassistant.turn_on", target={{"entity_id": "light.nonexistent"}})
'''


def _remote_scripts(ha: DirectBackend) -> ObjMap:
    return {
        object_key("script", identity): ("script", config)
        for identity, config in ha.list_remote("script").items()
    }


def test_push_creates_script_under_declared_object_id(ha: DirectBackend, tmp_path: Path) -> None:
    # The alias slug is a DIFFERENT identity -- the whole point of the case.
    assert slugify(ALIAS) != DECLARED_ID

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "scripts.py").write_text(BUNDLE, encoding="utf-8")
    result = compile_bundle(bundle)
    local: ObjMap = {key: (obj.kind(), obj.to_ha()) for key, obj in result.objects.items()}
    assert set(local) == {f"script:{DECLARED_ID}"}

    manifest = Manifest(synced_at="base", ha_version="test", objects={})
    plan = compute_plan(manifest=manifest, local_objects=local, remote_objects=_remote_scripts(ha))
    assert [(e.object_key, e.action) for e in plan.entries] == [
        (f"script:{DECLARED_ID}", PlanAction.CREATE)
    ]

    try:
        apply_result = apply_plan(plan, ha, manifest, synced_at="t1")
        assert apply_result.succeeded is True, apply_result.outcomes

        # `list_remote("script")` keys off the live `script.<object_id>`
        # entity ids in `/api/states`, so this IS the entity-id assertion.
        remote = ha.list_remote("script")
        assert DECLARED_ID in remote, remote
        assert slugify(ALIAS) not in remote, remote
        # HA keeps `alias` as the friendly name and no `id` in the body.
        assert remote[DECLARED_ID]["alias"] == ALIAS
        assert "id" not in remote[DECLARED_ID]

        # And the push links up: an immediate re-plan is a NOOP, not another
        # create under an identity that matches nothing remote.
        assert apply_result.manifest is not None
        replan = compute_plan(
            manifest=apply_result.manifest,
            local_objects=local,
            remote_objects=_remote_scripts(ha),
        )
        assert [(e.object_key, e.action) for e in replan.entries] == [
            (f"script:{DECLARED_ID}", PlanAction.NOOP)
        ]
    finally:
        with contextlib.suppress(Exception):
            ha.delete("script", DECLARED_ID)
        with contextlib.suppress(Exception):
            ha.delete("script", slugify(ALIAS))
