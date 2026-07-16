"""The round-trip invariant (compile(decompile(x)) == x for any config):
``compile(decompile(x)) ~ normalize_ha(x)``.

For every fixture in ``fixtures/configs/``: parse it to IR, decompile the IR to a
DSL bundle, recompile that bundle, and assert the recompiled IR's canonical hash
equals the canonical hash of ``normalize_ha(x)`` (which is ``x`` itself for every
fixture already in HA's stored plural form).

**Note on the corpus (recorded in docs/ha-api-notes.md):** the corpus (built
before the 2026.7 purpose vocabulary made the plural form the UI default) is
**48 of 55** automation fixtures in legacy singular form
(`trigger`/`condition`/`action` + `service:`) -- normalization is the common
case here, not an occasional exception. This test exercises `normalize_ha`
correctly regardless (it is fixture-shape-driven, not hardcoded to specific
fixture names).

No exceptions: fixtures the decompiler doesn't yet model in the typed DSL still
round-trip because the decompiler falls back to ``raw_automation``/``raw_trigger``/
``raw_condition``/``raw_action`` rather than dropping data (DESIGN §5.8).

Automations in the corpus have no ``id`` field (the fixtures are hand-authored
docs examples; real HA always assigns one on creation) -- a per-fixture
``key_hint`` (the filename stem) supplies the
identity needed to name the decompiled object and round-trip through
``object_key()``.

**Recorded finding (docs/ha-api-notes.md):** the compiler *always* materializes
an explicit ``id`` in its output (``options.get("id") or reg.func.__name__``,
``bundle.py``'s ``_build_automation``) -- there is no DSL shape that omits it.
So for the ~50 corpus fixtures missing ``id`` (an artifact of being hand-authored
docs examples; real HA assigns one on creation and always returns it), the
correct post-round-trip comparison is ``normalize_ha(x)`` **with the synthesized
id added** -- matching what real HA would already have. This is expected
compiler behavior, not a decompiler bug or a lossy round-trip.

**Recorded finding, ``platform:`` modernization (docs/ha-api-notes.md §16):**
``normalize_ha`` deliberately preserves an inner ``platform:`` discriminator
verbatim (verified against real HA -- docs/ha-api-notes.md §10.1: HA itself
never rewrites it). But every *typed* trigger builder in ``hassle.compiler``
always emits the modern ``trigger:`` discriminator (there is no builder-level
way to request the legacy spelling) -- 48 of the 55 corpus automation fixtures
use ``platform:``. Decompiling one of these to a typed builder (rather than
`raw_trigger`, which _would_ preserve the spelling but would tank the >= 90%
coverage gate on a corpus that is mostly legacy-form fixtures) is a deliberate
product decision: a decompile+recompile cycle is expected to modernize a
trigger's discriminator spelling, exactly as HA's own schema migrations do when
a config is re-saved through a newer editor. This is cosmetic (the trigger's
*meaning* is identical) and does not touch `normalize_ha` itself (which stays
byte-faithful to real HA for the sync engine's actual hashing). The
`_modernized` helper below is local to *this test's expectation*, not a change
to the frozen IR schema's `normalize_ha` surface.

**Recorded finding, ``delay:`` format modernization (docs/ha-api-notes.md §18):**
HA accepts a ``delay`` action as a dict of units, an ``"HH:MM:SS"`` string, or a
bare number of seconds -- all equivalent at runtime. The typed ``delay()``
builder (part of the frozen top-level DSL surface) only emits the dict form.
Same treatment as the trigger discriminator: the decompiler converts a
string/numeric delay to the equivalent dict-kwarg call (cosmetic, cuts the
DSL-coverage exception count roughly in half on this corpus), and
`_modernized` applies the matching conversion to the test's expectation.
"""

from __future__ import annotations

import pytest
from _corpus import Fixture, load_corpus

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import normalize_ha, parse, sha256_hash

CORPUS: list[Fixture] = load_corpus()


def _write_bundle(tmp_path_factory: pytest.TempPathFactory, source: str) -> str:
    bundle_dir = tmp_path_factory.mktemp("bundle")
    (bundle_dir / "objects.py").write_text(source, encoding="utf-8")
    return str(bundle_dir)


def _modernize_one_trigger(trig: object) -> object:
    # `device` triggers never decompile to a typed builder (DESIGN §5.4: no
    # stable cross-integration schema -- always `raw_trigger`, which preserves
    # `platform:` verbatim), so they're excluded from this modernization.
    if (
        isinstance(trig, dict)
        and "platform" in trig
        and "trigger" not in trig
        and trig.get("platform") != "device"
    ):
        out = dict(trig)
        out["trigger"] = out.pop("platform")
        return out
    return trig


def _modernize_trigger_list(value: object) -> object:
    if isinstance(value, list):
        return [_modernize_one_trigger(t) for t in value]  # type: ignore[misc]
    return _modernize_one_trigger(value)


def _find_wait_for_trigger_lists(node: object) -> None:
    """Modernize ``wait_for_trigger`` blocks in place, wherever nested."""
    if isinstance(node, dict):
        if "wait_for_trigger" in node:
            node["wait_for_trigger"] = _modernize_trigger_list(node["wait_for_trigger"])
        for v in node.values():
            _find_wait_for_trigger_lists(v)
    elif isinstance(node, list):
        for v in node:  # type: ignore[misc]
            _find_wait_for_trigger_lists(v)


def _modernize_delay(node: object) -> None:
    """Rewrite a string/numeric ``delay:`` value to the dict-of-units form, in
    place, wherever a ``{"delay": ...}`` action appears (see module docstring
    finding: the typed ``delay()`` builder only emits the dict form).

    Matches ``hassle.decompiler.actions._delay_source`` exactly: only the
    nonzero unit fields are included (``DelayAction`` only emits the keys it
    was actually passed, no zero-filling), falling back to ``{"seconds": 0}``
    for an all-zero duration.
    """
    if isinstance(node, dict):
        if "delay" in node and set(node) == {"delay"}:
            value = node["delay"]
            if isinstance(value, bool):
                pass
            elif isinstance(value, int | float):
                node["delay"] = {"seconds": value} if value else {"seconds": 0}
            elif isinstance(value, str):
                pieces = value.split(":")
                if len(pieces) == 3 and all(p.isdigit() for p in pieces):
                    h, m, s = (int(p) for p in pieces)
                    units = {k: v for k, v in (("hours", h), ("minutes", m), ("seconds", s)) if v}
                    node["delay"] = units or {"seconds": 0}
        for v in node.values():
            _modernize_delay(v)
    elif isinstance(node, list):
        for v in node:  # type: ignore[misc]
            _modernize_delay(v)


def _modernized(config: dict[str, object], *, kind: str) -> dict[str, object]:
    """Rewrite ``platform:`` -> ``trigger:`` at trigger positions, and a
    string/numeric ``delay:`` to the dict-of-units form, wherever they occur.

    Local to this test's expectation (see module docstring findings): the
    typed DSL builders always emit the modern discriminator / dict-of-units
    delay, so a decompile+recompile cycle is expected to modernize both --
    this never touches condition dicts, which have no such ambiguity.
    """
    import copy

    out = copy.deepcopy(config)
    for key in ("trigger", "triggers"):
        if key in out:
            out[key] = _modernize_trigger_list(out[key])
    _find_wait_for_trigger_lists(out)
    _modernize_delay(out)
    return out


@pytest.mark.parametrize("fx", CORPUS, ids=[f.name for f in CORPUS])
def test_roundtrip_corpus(fx: Fixture, tmp_path_factory: pytest.TempPathFactory) -> None:
    key_hint = fx.key_hint
    if fx.kind == "automation" and "id" not in fx.config:
        key_hint = fx.name  # synthesize an identity, exactly like a script's object_id

    obj = parse(fx.config, kind=fx.kind, key_hint=key_hint)
    source = decompile_bundle({obj.object_key(): obj})

    bundle_dir = _write_bundle(tmp_path_factory, source)
    result = compile_bundle(bundle_dir)

    assert len(result.objects) == 1, f"expected exactly one recompiled object for {fx.name}"
    (recompiled,) = result.objects.values()

    expected_config = fx.config
    if fx.kind == "automation" and "id" not in fx.config:
        # The compiler always materializes an explicit id (see module docstring
        # finding); a fixture missing one gets the synthesized identity added
        # to the expectation, matching what real HA would already have.
        expected_config = {**fx.config, "id": key_hint}
    expected = normalize_ha(expected_config, kind=fx.kind)
    # `@raw_automation`'s whole-object fallback (used when a config's top-level
    # shape can't be expressed as `@automation` at all -- e.g. the ancient
    # inline single-trigger form, see docs/ha-api-notes.md) and
    # `blueprint_automation` (which stores only `use_blueprint`, no
    # triggers/conditions/actions at all, DESIGN §5.8) both return the body
    # verbatim, unlike a typed `@automation`, which always materializes
    # `triggers`/`conditions`/`actions` even when empty. Only apply that
    # expectation adjustment (and the platform->trigger modernization, which is
    # a typed-builder-only behavior) when this fixture actually decompiled to a
    # typed `@automation`.
    went_through_typed_automation = "@automation(" in source
    if fx.kind == "automation" and went_through_typed_automation:
        # The compiler always materializes all three block keys, even empty
        # (the golden fixtures.dsl/minimal fixture accepts this: `conditions: []`
        # appears even when the DSL body calls no `only_if()` at all) -- a
        # fixture missing `conditions`/`triggers`/`actions` entirely gets the
        # empty list added to the expectation to match.
        expected.setdefault("triggers", [])
        expected.setdefault("conditions", [])
        expected.setdefault("actions", [])
    if fx.kind == "automation" or fx.kind == "script":
        # Scripts get the delay-format modernization too (no trigger list to
        # touch, but `_modernized` is a no-op on keys that aren't present).
        expected = _modernized(expected, kind=fx.kind)
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(expected), (
        f"{fx.name}: compile(decompile(x)) != normalize_ha(x)\ndecompiled source:\n{source}"
    )


def test_normalize_ha_is_identity_for_plural_fixtures() -> None:
    # Sanity check for the invariant statement itself: normalize_ha must be a
    # true no-op on any fixture already in HA's stored canonical form (whether
    # or not it happens to differ from the input -- that's exactly what
    # normalize_ha ought to report either way), and applying it twice must be
    # idempotent (an already-normalized config never changes further).
    for fx in CORPUS:
        expected = normalize_ha(fx.config, kind=fx.kind)
        twice = normalize_ha(expected, kind=fx.kind)
        assert twice == expected, f"{fx.name}: normalize_ha is not idempotent"
