"""``modernize_for_comparison`` — the bounded, deterministic transform a
decompile+recompile cycle is EXPECTED to apply, promoted to production
(``fix/self-check-value-compare``, coordinator field-failure fix).

This is the exact transform `packages/hassle-core/tests/test_roundtrip_corpus.py`'s
`_modernized` test helper already applied to its *expectation* before comparing —
moved here so production code (the pull-side self-checks, `hassle.sync.pull_apply`/
`hassle_cli.cli`) can perform the identical, context-free comparison a raw canonical-
hash equality check cannot: `compile(decompile(x))` is expected to modernize two
cosmetic shapes relative to `normalize_ha(x)`, never anything else --

- **Inner trigger discriminator:** `platform:` -> `trigger:` (every TYPED trigger
  builder always emits the modern spelling; `device` triggers are excluded -- DESIGN
  §5.4, no stable cross-integration schema, always `raw_trigger`, which preserves
  `platform:` verbatim).
- **`delay:` format:** a string (`"HH:MM:SS"`) or bare number of seconds becomes the
  dict-of-units form (the typed `delay()` builder only emits that form).

Nothing else. In particular this is NOT a general "are these semantically
equivalent" comparator -- it is the narrow, bounded set of rewrites the decompiler
is documented to perform, applied once to `original` before a canonical-hash
comparison against the recompiled value. This is what makes the comparison
**context-free and deterministic**: unlike decompiling the recompiled IR back to DSL
source (which varies with whatever `used_names`/`resolver` happen to be in scope for
a *batch* compile -- name-collision `_2` suffixes, same-batch script-call rewriting --
the exact false-positive mechanism this fix replaces), this transform only ever looks
at the JSON value itself, so the same input always modernizes to the same output
regardless of what else is being compiled alongside it.
"""

from __future__ import annotations

import copy
from typing import Any, cast

from hassle.ir.normalize import normalize_ha

_DELAY_DURATION_UNITS: tuple[str, ...] = ("hours", "minutes", "seconds", "milliseconds")


def _modernize_one_trigger(trig: Any) -> Any:
    # `device` triggers never decompile to a typed builder (DESIGN §5.4: no stable
    # cross-integration schema -- always `raw_trigger`, which preserves `platform:`
    # verbatim), so they're excluded from this modernization.
    if isinstance(trig, dict):
        trig_dict = cast("dict[str, Any]", trig)
        if (
            "platform" in trig_dict
            and "trigger" not in trig_dict
            and trig_dict.get("platform") != "device"
        ):
            out = dict(trig_dict)
            out["trigger"] = out.pop("platform")
            return out
    return cast("Any", trig)


def _modernize_trigger_list(value: Any) -> Any:
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return [_modernize_one_trigger(t) for t in items]
    return _modernize_one_trigger(value)


def _modernize_wait_for_trigger(node: Any) -> None:
    """Modernize ``wait_for_trigger`` blocks in place, wherever nested."""
    if isinstance(node, dict):
        node_dict = cast("dict[str, Any]", node)
        if "wait_for_trigger" in node_dict:
            node_dict["wait_for_trigger"] = _modernize_trigger_list(node_dict["wait_for_trigger"])
        for v in node_dict.values():
            _modernize_wait_for_trigger(v)
    elif isinstance(node, list):
        for v in cast("list[Any]", node):
            _modernize_wait_for_trigger(v)


def _modernize_delay(node: Any) -> None:
    """Rewrite a string/numeric ``delay:`` value to the dict-of-units form, in
    place, wherever a ``{"delay": ...}`` action appears -- the typed ``delay()``
    builder only emits the dict form. Matches
    ``hassle.decompiler.actions._delay_source`` exactly: only nonzero unit fields
    are included, falling back to ``{"seconds": 0}`` for an all-zero duration.
    """
    if isinstance(node, dict):
        node_dict = cast("dict[str, Any]", node)
        if "delay" in node_dict and set(node_dict) == {"delay"}:
            value = node_dict["delay"]
            if isinstance(value, bool):
                pass
            elif isinstance(value, int | float):
                node_dict["delay"] = {"seconds": value} if value else {"seconds": 0}
            elif isinstance(value, str):
                pieces = value.split(":")
                if len(pieces) == 3 and all(p.isdigit() for p in pieces):
                    h, m, s = (int(p) for p in pieces)
                    units = {k: v for k, v in (("hours", h), ("minutes", m), ("seconds", s)) if v}
                    node_dict["delay"] = units or {"seconds": 0}
        for v in node_dict.values():
            _modernize_delay(v)
    elif isinstance(node, list):
        for v in cast("list[Any]", node):
            _modernize_delay(v)


def modernize_for_comparison(config: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Apply the bounded, deterministic decompile+recompile modernization to
    ``config`` (already ``normalize_ha``'d or not -- ``normalize_ha`` is applied
    here too, so callers never need to pre-normalize): inner ``platform:`` ->
    ``trigger:`` at every trigger position (including nested
    ``wait_for_trigger`` blocks), and a string/numeric ``delay:`` -> the
    dict-of-units form, wherever either occurs. Nothing else. Never mutates
    ``config``; safe to call on the same dict repeatedly (idempotent, matching
    ``normalize_ha``'s own contract).
    """
    normalized = normalize_ha(config, kind=kind)
    out = copy.deepcopy(normalized)
    for key in ("trigger", "triggers"):
        if key in out:
            out[key] = _modernize_trigger_list(out[key])
    _modernize_wait_for_trigger(out)
    _modernize_delay(out)
    return out
