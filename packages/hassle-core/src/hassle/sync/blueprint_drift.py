"""The substitute-compare drift oracle — blueprints-design §2.2 / §3.

HA cannot serve a blueprint's source back, so the obvious "did the remote copy
change?" question has no textual answer. It has a **behavioural** one:

1. pick one of the blueprint's own instances in the bundle and take its inputs;
2. ask HA to expand ITS copy with them (``blueprint/substitute``);
3. expand the bundle's copy with the same inputs — ``Blueprint.expand``, the
   blueprint-BODY-only expansion, **never**
   `hassle.blueprints.expand_blueprint`, which is the simulator's entry point
   and deliberately merges the instance's own ``id``/``alias``/``description``
   on top (see the key-intersection note below);
4. normalize both and compare, **on the keys both sides express**.

Equal expansions mean the two documents agree in every way that can matter to
an instance — which is the only kind of agreement worth having, since an
instance is all a blueprint ever produces.

Three deliberate conservatisms, each pinned by a test in
`test_blueprint_drift_oracle`:

- **No instances → skip.** §3: nothing can be affected by the drift, and there
  would be no input set to substitute with anyway.
- **Normalize before comparing.** A blueprint authored in HA's legacy singular
  schema (`trigger:`/`service:`) expands to the same automation as its plural
  twin. Comparing raw expansions would report permanent, unfixable drift for
  every legacy blueprint in existence.
- **A post-save stale read is not drift** (ha-api-notes §40.8, a field
  false-positive from the first live run). `blueprint/substitute` serves the
  PRIOR document for several seconds after a `blueprint/save`, so a plan run
  straight after a push reported drift that healed a minute later, prescribing
  an `--accept-local` the user should never run. On a mismatch the oracle waits
  and asks again, bounded, and believes the later answer -- a real remote edit
  stays a mismatch on every retry.

- **A failure is not drift.** This oracle *corroborates*; it must never
  manufacture a conflict out of a transport hiccup, a backend that doesn't
  implement `blueprint_substitute`, or an input set HA rejects. "Unknown" falls
  back to the manifest hash, which is what §3 makes authoritative for content.
- **Compare the key INTERSECTION, not the whole config** (ha-api-notes §40.7 —
  a field false-positive from the first live run, where a provably in-sync
  blueprint reported drift on every plan). ``blueprint/substitute`` is handed
  ``{domain, path, input}`` and **no instance**, so its output is the config
  block only: it can never carry ``id``/``alias``/``description``, not even
  when the blueprint *document* declares an ``alias:``/``description:`` of its
  own — which community blueprints commonly do as a default label. The local
  expansion keeps whatever the document declared, so the two sides legitimately
  express different key SETS.

  Intersection rather than stripping a fixed list of instance-identity keys,
  because the intersection follows from *how HA builds the substituted config*
  rather than from a list someone has to keep in sync: with no instance in
  hand, any key only the local side has is by construction something HA could
  not have expressed, so its presence says nothing about whether HA's copy
  drifted. A strip-list would have to be extended by hand every time HA's
  substitute output gained or lost a wrapper key, and each omission would be
  another permanent false positive — the failure mode this fix exists to end.

  The accepted cost: if HA *omits* a key the blueprint does define, a local
  edit confined to that key is invisible to the oracle. That is a weakening of
  a deliberately corroborative check whose authoritative half is the manifest
  hash (§3) — and vastly preferable to a false conflict on every correctly
  synced blueprint, which makes the feature unusable and trains users to click
  through conflict prompts (the failure I6 exists to prevent).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, cast

from hassle.blueprints import (
    instance_inputs,
    instances_by_blueprint,
    parse_blueprint,
    split_blueprint_identity,
)
from hassle.ir.keys import BLUEPRINT_KIND
from hassle.ir.modernize import modernize_for_comparison

#: Bounded settle for a substitute MISMATCH (ha-api-notes §40.8), shaped after
#: `DirectBackend`'s `reload_timeout`/`reload_interval` pair -- the repo's
#: existing precedent for "the write landed, the read hasn't caught up yet".
#: Only ever paid when a mismatch is seen, which is rare and is exactly the
#: moment before telling a user their blueprint conflicts.
SETTLE_TIMEOUT: float = 5.0
SETTLE_INTERVAL: float = 1.0


def detect_blueprint_drift(
    backend: object,
    local_objects: dict[str, tuple[str, dict[str, Any]]],
    *,
    settle_timeout: float = SETTLE_TIMEOUT,
    settle_interval: float = SETTLE_INTERVAL,
    sleep: Callable[[float], None] = time.sleep,
) -> frozenset[str]:
    """Blueprint object keys whose remote copy expands differently.

    ``local_objects`` is the sync engine's usual ``object_key -> (kind, body)``
    map. ``backend`` is probed with `getattr` for `blueprint_substitute` — the
    same defensive pattern `entry_id_for` and `fetch_registry_snapshot` use, so
    a `Backend` implementer without it degrades to "no corroboration" rather
    than an AttributeError.

    ``settle_timeout``/``settle_interval`` bound the post-save re-check (see
    the module docstring's staleness bullet); ``settle_timeout=0`` disables it.
    ``sleep`` is injectable purely so the unit tests exercise the retry without
    actually waiting — nothing else should pass it.

    Returns a frozenset so it can be handed straight to `compute_plan`'s
    ``blueprint_drift`` argument.
    """
    substitute = getattr(backend, "blueprint_substitute", None)
    if substitute is None:
        return frozenset()

    remote_keys = _remote_blueprint_keys(backend)
    if not remote_keys:
        return frozenset()

    bodies = {key: body for key, (_kind, body) in local_objects.items()}
    instances = instances_by_blueprint(bodies)

    drifted: set[str] = set()
    for key, (kind, local_body) in sorted(local_objects.items()):
        if kind != BLUEPRINT_KIND or key not in remote_keys:
            continue
        instance_keys = instances.get(key)
        if not instance_keys:
            continue  # §3: no instances, nothing drift could affect.
        inputs = instance_inputs(bodies[instance_keys[0]])
        if _differs_after_settle(
            substitute,
            key,
            local_body,
            inputs,
            settle_timeout=settle_timeout,
            settle_interval=settle_interval,
            sleep=sleep,
        ):
            drifted.add(key)
    return frozenset(drifted)


def await_blueprint_settled(
    backend: object,
    object_key: str,
    local_body: dict[str, Any],
    inputs: dict[str, Any],
    *,
    settle_timeout: float = SETTLE_TIMEOUT,
    settle_interval: float = SETTLE_INTERVAL,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Wait until HA's substitute reflects the just-saved blueprint.

    The exact complement of the drift check, sharing its loop, its knobs and
    its comparison — one settle shape, two callers (ha-api-notes §40.8).

    This exists because of the implication §40.8 opened up: if
    ``blueprint/save``'s cache write races the WS response, then the
    ``automation.reload`` `apply_plan` issues right after a blueprint UPDATE
    (blueprints-design §4.3) races **the same window**. HA would then re-expand
    the live instances against the **OLD** blueprint and leave them stale until
    some future, unrelated reload — a silently wrong house, with the plan
    reporting success. §4.3's reload was, until this, "reload and hope".

    So: settle first, reload second. Returns ``True`` once HA's copy matches
    (or immediately, if the backend cannot be probed — that is the
    pre-existing behaviour and must not become a hang), ``False`` on timeout,
    which the caller turns into a reload-anyway plus a warning.
    """
    substitute = getattr(backend, "blueprint_substitute", None)
    if substitute is None:
        # Nothing to probe with. Reload immediately, exactly as before.
        return True
    return not _differs_after_settle(
        substitute,
        object_key,
        local_body,
        inputs,
        settle_timeout=settle_timeout,
        settle_interval=settle_interval,
        sleep=sleep,
    )


def _differs_after_settle(
    substitute: Any,
    object_key: str,
    local_body: dict[str, Any],
    inputs: dict[str, Any],
    *,
    settle_timeout: float,
    settle_interval: float,
    sleep: Callable[[float], None],
) -> bool:
    """A mismatch, re-checked once the post-save stale window has passed.

    docs/internals/ha-api-notes.md §40.8: `blueprint/substitute` serves the
    PRIOR document for several seconds after a `blueprint/save`, so a plan run
    straight after a push saw drift that healed itself a minute later — and
    prescribed an `--accept-local` the user should never run. (The
    `automation.reload` §4.3 issues after the save does NOT prevent it; the
    blueprint cache and automation expansion are separate.)

    So: on a mismatch, wait and ask again, and believe the later answer. A real
    remote edit stays a mismatch on every retry; the stale window heals
    invisibly. Bounded, and best-effort in the same sense as
    `DirectBackend._await_config_entity` — this is an I/O settle in the
    backend/drift seam, not core-logic wall-clock (R8 is about compiler and
    simulator determinism), and it never runs at all unless the first answer
    already said "conflict".

    Retry COUNT is derived from the two knobs rather than read off a clock, so
    the loop is deterministic and the tests need no fake time source.
    """
    if not _expansions_differ(substitute, object_key, local_body, inputs):
        return False
    retries = 0 if settle_interval <= 0 else max(0, int(settle_timeout // settle_interval))
    for _ in range(retries):
        sleep(settle_interval)
        if not _expansions_differ(substitute, object_key, local_body, inputs):
            return False
    return True


def _remote_blueprint_keys(backend: object) -> frozenset[str]:
    lister = getattr(backend, "list_remote", None)
    if lister is None:  # pragma: no cover - defensive
        return frozenset()
    try:
        listed = cast("dict[str, Any]", lister(BLUEPRINT_KIND))
    except Exception:  # pragma: no cover - defensive
        return frozenset()
    return frozenset(f"{BLUEPRINT_KIND}:{identity}" for identity in listed)


def _expansions_differ(
    substitute: Any,
    object_key: str,
    local_body: dict[str, Any],
    inputs: dict[str, Any],
) -> bool:
    identity = object_key.partition(":")[2]
    domain, path = split_blueprint_identity(identity)
    source = local_body.get("source")
    if not isinstance(source, str):  # pragma: no cover - defensive
        return False
    try:
        remote_expansion = substitute(domain, path, dict(inputs))
        local_expansion = parse_blueprint(source, display_path=identity).expand(dict(inputs))
    except Exception:
        # Unknown is not drift. A blueprint whose inputs HA rejects, or a
        # dropped connection, must not turn into a conflict the user cannot
        # act on -- and if the local copy really is broken, §6's validation
        # says so with a message that names the actual problem.
        return False
    if not isinstance(remote_expansion, dict):  # pragma: no cover - defensive
        return False
    remote_comparable = _comparable(cast("dict[str, Any]", remote_expansion))
    local_comparable = _comparable(local_expansion)
    shared = remote_comparable.keys() & local_comparable.keys()
    return {key: remote_comparable[key] for key in shared} != {
        key: local_comparable[key] for key in shared
    }


def _comparable(config: dict[str, Any]) -> dict[str, Any]:
    """Both expansions in one schema, so only real differences survive."""
    return modernize_for_comparison(config, kind="automation")
