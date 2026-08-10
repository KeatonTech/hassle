"""The substitute-compare drift oracle — blueprints-design §2.2 / §3.

HA cannot serve a blueprint's source back, so the obvious "did the remote copy
change?" question has no textual answer. It has a **behavioural** one:

1. pick one of the blueprint's own instances in the bundle and take its inputs;
2. ask HA to expand ITS copy with them (``blueprint/substitute``);
3. expand the bundle's copy with the same inputs
   (`hassle.blueprints.expand_blueprint`, the same implementation everywhere);
4. normalize both and compare.

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
- **A failure is not drift.** This oracle *corroborates*; it must never
  manufacture a conflict out of a transport hiccup, a backend that doesn't
  implement `blueprint_substitute`, or an input set HA rejects. "Unknown" falls
  back to the manifest hash, which is what §3 makes authoritative for content.
"""

from __future__ import annotations

from typing import Any, cast

from hassle.blueprints import (
    instance_inputs,
    instances_by_blueprint,
    parse_blueprint,
    split_blueprint_identity,
)
from hassle.ir.keys import BLUEPRINT_KIND
from hassle.ir.modernize import modernize_for_comparison


def detect_blueprint_drift(
    backend: object,
    local_objects: dict[str, tuple[str, dict[str, Any]]],
) -> frozenset[str]:
    """Blueprint object keys whose remote copy expands differently.

    ``local_objects`` is the sync engine's usual ``object_key -> (kind, body)``
    map. ``backend`` is probed with `getattr` for `blueprint_substitute` — the
    same defensive pattern `entry_id_for` and `fetch_registry_snapshot` use, so
    a `Backend` implementer without it degrades to "no corroboration" rather
    than an AttributeError.

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
        if _expansions_differ(substitute, key, local_body, inputs):
            drifted.add(key)
    return frozenset(drifted)


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
    return _comparable(cast("dict[str, Any]", remote_expansion)) != _comparable(local_expansion)


def _comparable(config: dict[str, Any]) -> dict[str, Any]:
    """Both expansions in one schema, so only real differences survive."""
    return modernize_for_comparison(config, kind="automation")
