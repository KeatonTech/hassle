"""The blueprint plan table — docs/internals/blueprints-design.md §3.

`compute_plan` routes ``kind == "blueprint"`` here instead of through the
generic base/local/remote hash comparison, because the generic comparison
cannot apply: HA has no command that serves a blueprint's source back (§2.1,
ha-api-notes §40.2), so a remote blueprint body is metadata and a local one is
the authored document. Comparing their hashes would report a conflict on every
plan, forever.

What replaces it (§3): **existence** from ``blueprint/list``, **content** from
the manifest's stored hash of the local file at last push, optionally
corroborated by the **substitute-compare oracle** (`hassle.sync.blueprint_drift`).

| Local file | In manifest | Remote (list) | Plan row |
|---|---|---|---|
| yes | no  | no  | `create` |
| yes | no  | yes | `conflict` — remote has a same-path blueprint Hassle didn't put there |
| yes | yes | yes, hash differs from manifest | `update` |
| yes | yes | mismatch, local unchanged | `conflict` — the remote copy was edited in place |
| no  | yes | yes | `delete` (ordered, §4) |
| no  | no  | yes | `adopt (unmanageable)` — warning row only |

One qualification to row 4, forced by what the oracle can observe (see the
DEVIATION comment at the check itself): the substitute-compare conflict fires
only when the LOCAL file is unchanged since base. `blueprint/substitute`
compares HA's copy against the bundle's copy as it is now, and the base version
cannot be expanded, so a mismatch on an edited local file is fully explained by
that edit and says nothing about the remote side.

Two combinations the table leaves implicit, decided here and pinned by
`test_blueprint_plan_table`:

- **local yes / remote no, whatever the manifest says → `create`.** The bundle
  has the file and HA does not, so pushing it is the only non-destructive
  answer. The generic table's `drop` would delete an authored source file
  because somebody removed the blueprint in HA, which I6 forbids.
- **local no / remote no, manifest yes → `drop`**, matching the generic
  table's "both sides gone" row: nothing to push either way, and the stale
  manifest entry should not survive.

The `adopt (unmanageable)` row is an ordinary `PlanAction.ADOPT` carrying
`warning=True` and a message, **not** a new action: DESIGN §8.2's action set is
frozen at eight, and this row is never executed by anything (apply only runs
create/update/delete; pull excludes the kind from writes entirely, §5). Making
it a ninth action would have widened a frozen contract to express "we printed
a sentence".
"""

from __future__ import annotations

from typing import Any

from hassle.ir.canonical import sha256_hash
from hassle.sync.models import Conflict, ConflictKind, PlanAction, PlanEntry


def plan_blueprint(
    object_key: str,
    *,
    base_hash: str | None,
    local_config: dict[str, Any] | None,
    remote_config: dict[str, Any] | None,
    source_path: str | None = None,
    drifted: bool = False,
) -> PlanEntry:
    """One blueprint's plan row (the §3 table above).

    ``base_hash`` is the manifest's `compiled_hash` — the hash of the LOCAL
    body at last push, never of anything remote. ``drifted`` is the
    substitute-compare verdict; `False` when the check is disabled or was
    skipped, which reproduces the pre-oracle behaviour exactly.
    """
    remote_hash = None if remote_config is None else sha256_hash(remote_config)

    def entry(action: PlanAction, **extra: Any) -> PlanEntry:
        return PlanEntry(
            object_key=object_key,
            kind="blueprint",
            action=action,
            source_path=source_path,
            **extra,
        )

    if local_config is None and remote_config is None:
        # Gone from both sides. `drop` even though pull will not act on it
        # (§5) -- the row exists so the stale manifest entry is visible and
        # accounted for rather than silently immortal.
        return entry(PlanAction.DROP if base_hash is not None else PlanAction.NOOP)

    if local_config is None:
        assert remote_config is not None
        if base_hash is not None:
            # Row 5. Ordered after every automation row, and refused outright
            # while the bundle still declares an instance (§4.2, enforced in
            # `hassle.sync.apply`).
            return entry(PlanAction.DELETE, remote=remote_config, remote_hash_at_plan=remote_hash)
        # Row 6: `adopt (unmanageable)`.
        return entry(
            PlanAction.ADOPT,
            remote=remote_config,
            remote_hash_at_plan=remote_hash,
            warning=True,
            message=_unmanageable_adopt_message(remote_config),
        )

    if remote_config is None:
        # Row 1, and the implicit "remotely deleted" case: push it.
        return entry(PlanAction.CREATE, local=local_config)

    local_hash = sha256_hash(local_config)

    if base_hash is None:
        # Row 2: a same-path blueprint Hassle didn't put there.
        return entry(
            PlanAction.CONFLICT,
            local=local_config,
            remote=remote_config,
            remote_hash_at_plan=remote_hash,
            conflict=_conflict(object_key, local_config, remote_config),
            message=_unexpected_remote_message(remote_config),
        )

    if drifted and base_hash == local_hash:
        # Row 4, gated on the local file being UNCHANGED since base.
        #
        # DEVIATION from a literal reading of §3's row 4, forced by what the
        # oracle can actually observe and caught by the golden bundle
        # (`test_blueprint_golden_bundle`). `blueprint/substitute` compares
        # HA's copy against the bundle's copy AS IT IS NOW -- there is no way
        # to expand the BASE version, because the manifest stores only its
        # hash and HA will not serve a source back. So a mismatch has two
        # possible causes and the oracle cannot tell them apart:
        #
        #   - the local file is unchanged since base -> the difference can
        #     only come from the remote side. Unambiguous: CONFLICT.
        #   - the local file was edited -> the difference is fully explained
        #     by that edit. Escalating here would make EVERY ordinary
        #     blueprint edit a conflict, which is unusable and would train
        #     users to click through conflict prompts (the failure mode I6
        #     exists to prevent).
        #
        # So the drift row applies only to the first case, and an edited local
        # file falls through to row 3's `update` -- the same exposure every
        # other kind already carries, no worse. §3's table agrees when read
        # top-down: its "hash differs from manifest -> update" row precedes
        # the drift row.
        return entry(
            PlanAction.CONFLICT,
            local=local_config,
            remote=remote_config,
            remote_hash_at_plan=remote_hash,
            conflict=_conflict(object_key, local_config, remote_config),
            message=_drift_message(remote_config),
        )

    if base_hash != local_hash:
        # Row 3.
        return entry(
            PlanAction.UPDATE,
            local=local_config,
            remote=remote_config,
            remote_hash_at_plan=remote_hash,
        )

    return entry(
        PlanAction.NOOP,
        local=local_config,
        remote=remote_config,
        remote_hash_at_plan=remote_hash,
    )


def _conflict(
    object_key: str, local_config: dict[str, Any], remote_config: dict[str, Any]
) -> Conflict:
    """Both blueprint conflict rows are `both_edited`.

    `ConflictKind` is not widened for this kind. Its three members describe
    WHICH SIDES diverged, and for a blueprint the answer is always the same one
    ("the remote is not what we last pushed, and the local side is present");
    what differs between the two rows is the *explanation and the fix*, which
    is what `PlanEntry.message` carries.
    """
    return Conflict(
        object_key=object_key,
        kind=ConflictKind.BOTH_EDITED,
        base=None,
        local=local_config,
        remote=remote_config,
    )


def _display_path(remote_config: dict[str, Any]) -> str:
    domain = remote_config.get("domain", "automation")
    path = remote_config.get("path", "")
    return f"blueprints/{domain}/{path}"


def _no_source_read() -> str:
    return (
        "Home Assistant has no command that serves a blueprint's source back "
        "(docs/internals/blueprints-design.md §2.1), so Hassle cannot fetch the "
        "remote copy for you"
    )


def _unmanageable_adopt_message(remote_config: dict[str, Any]) -> str:
    file = _display_path(remote_config)
    return (
        f"Home Assistant has a blueprint at `{file.removeprefix('blueprints/')}` that "
        f"this bundle does not, so Hassle cannot manage it. {_no_source_read()} -- "
        f"adopting it has to be a human act. Fix: save the blueprint's YAML into the "
        f"bundle at `{file}` (copy it from Home Assistant's own "
        f"`config/{file}`, or re-download it from its source_url), then run "
        f"`hassle plan` again -- it will show as an `update` you can push. Until "
        f"then this row is a warning only: nothing is pushed, changed or deleted."
    )


def _unexpected_remote_message(remote_config: dict[str, Any]) -> str:
    file = _display_path(remote_config)
    return (
        f"Home Assistant already has a blueprint at "
        f"`{file.removeprefix('blueprints/')}`, but Hassle did not put it there "
        f"(it has no manifest entry), and the bundle has a file of its own at "
        f"`{file}` -- pushing would overwrite whatever is live. {_no_source_read()}, "
        f"so the two cannot be merged automatically. Fix: push the bundle's copy "
        f"over it with `hassle push --accept-local blueprint:"
        f"{remote_config.get('domain', 'automation')}/{remote_config.get('path', '')}`, "
        f"or first copy Home Assistant's semantics into the bundle file by hand and "
        f"then push."
    )


def _drift_message(remote_config: dict[str, Any]) -> str:
    file = _display_path(remote_config)
    return (
        f"The blueprint `{file.removeprefix('blueprints/')}` was edited in place in "
        f"Home Assistant: expanding one of its instances remotely gives a different "
        f"automation than expanding the bundle's `{file}` with the same inputs. "
        f"{_no_source_read()}, so the edit cannot be pulled back into the bundle "
        f"automatically. Fix: push the bundle's copy over it with `hassle push "
        f"--accept-local blueprint:{remote_config.get('domain', 'automation')}/"
        f"{remote_config.get('path', '')}` (discarding the Home Assistant edit), or "
        f"reproduce the edit in `{file}` by hand and push that."
    )
