"""`normalize_ha` — reproduce HA's 2024.10+ storage normalization.

Home Assistant's config API accepts the legacy singular schema
(``trigger``/``condition``/``action`` outer keys, ``service:`` inner discriminator)
but **stores and returns** the plural schema (``triggers``/``conditions``/``actions``,
``action:``). See DESIGN §7.1 / docs/ha-api-notes.md §10.1. Hassle's canonical form
— what the compiler emits and what the sync engine hashes — is therefore the plural
form; without applying the same normalization locally, every object would hash
differently from HA's stored copy and the plan would show perpetual spurious diffs.

The rules, verified against the real POST->GET capture pair
(docs/ha-api-captures/normalize-post-get-pair.json):

- **Outer block keys** on an automation body: ``trigger`` -> ``triggers``,
  ``condition`` -> ``conditions``, ``action`` -> ``actions``. Scripts use
  ``sequence`` (unchanged).
- **``service:`` -> ``action:``** on any action mapping, recursively through every
  nested action container (``sequence``, ``choose``/``default``, ``if``/``then``/
  ``else``, ``repeat``, ``parallel``, ``choose[].sequence``, …).
- **Inner ``platform:`` is preserved** — HA pluralizes only the outer block key, it
  does not rewrite the trigger discriminator on read-back.

This is compatible with the frozen IR schema: it adds a new public function to
``hassle.ir`` and touches no existing frozen surface. It never mutates its input.
"""

from __future__ import annotations

from typing import Any

# Outer automation block keys: singular -> plural.
_OUTER_BLOCK_RENAMES: dict[str, str] = {
    "trigger": "triggers",
    "condition": "conditions",
    "action": "actions",
}

# Keys whose values are action lists (or a single action) that must be recursed
# into so nested ``service:`` discriminators are normalized. Covers HA's control
# flow containers plus the top-level plural ``actions`` and script ``sequence``.
_ACTION_LIST_KEYS: frozenset[str] = frozenset({"actions", "sequence", "default", "then", "else"})


def normalize_ha(config: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Return ``config`` normalized to HA's stored plural schema.

    ``kind`` is ``"automation"`` (outer-key pluralization applies) or ``"script"``
    / any other kind (only the recursive ``service:`` -> ``action:`` rewrite
    applies; scripts carry a ``sequence``, not ``triggers``/``actions``).

    The input is never mutated; a new dict is returned.
    """
    out: dict[str, Any] = {}
    for key, value in config.items():
        if kind == "automation" and key in _OUTER_BLOCK_RENAMES:
            new_key = _OUTER_BLOCK_RENAMES[key]
            out[new_key] = _normalize_block(new_key, value)
        else:
            out[key] = _normalize_block(key, value)
    return out


def _normalize_block(key: str, value: Any) -> Any:
    # At the object top level the action containers are ``actions`` (automations)
    # and ``sequence`` (scripts); everything else (triggers/conditions/scalars)
    # passes through with a deep copy so the input is never aliased into the output.
    if key in ("actions", "sequence"):
        return _normalize_action_container(value)
    return _deep_copy(value)


def _normalize_action_container(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_action(item) for item in value]  # type: ignore[misc]
    if isinstance(value, dict):
        # HA also accepts a single action mapping (not wrapped in a list).
        return _normalize_action(value)  # type: ignore[arg-type]
    return _deep_copy(value)


def _normalize_action(action: Any) -> Any:
    if not isinstance(action, dict):
        return _deep_copy(action)
    out: dict[str, Any] = {}
    for key, value in action.items():  # type: ignore[misc]
        if key == "service":
            # service: -> action:, unconditionally - mirrors HA's storage rewrite
            # (a body with both keys is malformed; last-write-wins like HA).
            out["action"] = _deep_copy(value)
            continue
        if key in _ACTION_LIST_KEYS:
            out[key] = _normalize_action_container(value)
        elif key == "choose":
            out[key] = _normalize_choose(value)
        elif key == "parallel":
            out[key] = _normalize_action_container(value)
        elif key == "repeat":
            out[key] = _normalize_repeat(value)
        else:
            out[key] = _deep_copy(value)
    return out


def _normalize_choose(value: Any) -> Any:
    if not isinstance(value, list):
        return _deep_copy(value)
    branches: list[Any] = []
    for branch in value:  # type: ignore[misc]
        if isinstance(branch, dict):
            new_branch: dict[str, Any] = {}
            for k, v in branch.items():  # type: ignore[misc]
                new_branch[k] = _normalize_action_container(v) if k == "sequence" else _deep_copy(v)
            branches.append(new_branch)
        else:
            branches.append(_deep_copy(branch))
    return branches


def _normalize_repeat(value: Any) -> Any:
    if not isinstance(value, dict):
        return _deep_copy(value)
    out: dict[str, Any] = {}
    for k, v in value.items():  # type: ignore[misc]
        out[k] = _normalize_action_container(v) if k == "sequence" else _deep_copy(v)
    return out


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}  # type: ignore[misc]
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]  # type: ignore[misc]
    return value
