"""The STRICT zero-transformation round-trip on already-HA-canonical input.

``test_roundtrip_corpus.py`` proves compile(decompile(x)) == x holds over
the *whole* corpus, but most of that corpus is legacy-form (docs/ha-api-notes.md
§15) and its expectation applies documented, narrow modernizations (id
synthesis, `setdefault` for empty blocks, `platform:`->`trigger:`, scalar-delay
->dict-delay -- §14/§16/§17/§18). None of those transformations should ever be
needed for input that is *already* in the exact shape production sync relies
on: a real live `GET /api/config/automation/config/{id}` response (string
`id`, plural `triggers`/`conditions`/`actions`, modern `trigger:`/`action:`
discriminators, dict-form `delay`, no legacy `platform:`/`service:` anywhere).

This module defines that shape as a predicate (:func:`is_ha_canonical`) and
asserts ``compile(decompile(x)) == x`` by direct canonical-hash equality --
zero transformations, not even ``normalize_ha`` (which would be a no-op on
canonical input anyway, but asserting equality against the literal fixture
dict makes that explicit rather than assumed) -- for every fixture matching
it. Today that's exactly ``automation_ha_canonical_modern.json``; the
parametrization picks up any future fixture in this shape automatically.
"""

from __future__ import annotations

from typing import Any

import pytest
from _corpus import Fixture, load_corpus

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import parse, sha256_hash

CORPUS: list[Fixture] = load_corpus()


def _walk(node: Any) -> Any:
    """Yield every dict and list encountered anywhere in ``node`` (incl. itself)."""
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _has_platform_or_service_key(config: dict[str, Any]) -> bool:
    for node in _walk(config):
        if isinstance(node, dict) and ("platform" in node or "service" in node):
            return True
    return False


def _has_scalar_delay(config: dict[str, Any]) -> bool:
    """A ``delay`` value that isn't the canonical dict-of-units form (a bare
    number or an "HH:MM:SS" string) -- see docs/ha-api-notes.md §18."""
    for node in _walk(config):
        if isinstance(node, dict) and "delay" in node and not isinstance(node["delay"], dict):
            return True
    return False


def is_ha_canonical(config: dict[str, Any], *, kind: str) -> bool:
    """True iff ``config`` is already in HA's exact post-2024.10 stored shape:

    - has an explicit ``id`` (automations/helpers) -- scripts are keyed
      extrinsically and have no ``id`` field at all, so they're exempt from
      this leg of the check;
    - uses only plural block keys (``triggers``/``conditions``/``actions`` for
      automations; scripts already only ever have ``sequence``) -- no
      singular ``trigger``/``condition``/``action`` outer key anywhere;
    - no legacy ``platform:``/``service:`` discriminator anywhere in the tree;
    - no scalar/string-form ``delay`` anywhere (only the dict-of-units form).
    """
    if kind == "automation" and "id" not in config:
        return False
    if kind == "automation":
        if "trigger" in config or "condition" in config or "action" in config:
            return False
        if "platform" in config:  # the ancient inline single-trigger form
            return False
    if _has_platform_or_service_key(config):
        return False
    return not _has_scalar_delay(config)


CANONICAL_FIXTURES = [fx for fx in CORPUS if is_ha_canonical(fx.config, kind=fx.kind)]


def test_at_least_one_ha_canonical_fixture_exists() -> None:
    # The predicate itself must not be vacuous -- otherwise the parametrized
    # test below would silently assert nothing.
    assert CANONICAL_FIXTURES, "expected >= 1 fixture matching is_ha_canonical()"
    assert any(fx.name == "automation_ha_canonical_modern" for fx in CANONICAL_FIXTURES)


@pytest.mark.parametrize("fx", CANONICAL_FIXTURES, ids=[f.name for f in CANONICAL_FIXTURES])
def test_ha_canonical_zero_transformation_roundtrip(
    fx: Fixture, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """compile(decompile(x)) == x, verbatim -- no _modernized, no setdefault,
    no id synthesis. Any fixture matching is_ha_canonical() is already exactly
    what production sync hashes against; the decompiler must reproduce it with
    zero transformations."""
    obj = parse(fx.config, kind=fx.kind, key_hint=fx.key_hint)
    source = decompile_bundle({obj.object_key(): obj})

    bundle_dir = tmp_path_factory.mktemp("canonical_bundle")
    (bundle_dir / "objects.py").write_text(source, encoding="utf-8")
    result = compile_bundle(str(bundle_dir))

    assert len(result.objects) == 1, f"expected exactly one recompiled object for {fx.name}"
    (recompiled,) = result.objects.values()

    assert sha256_hash(recompiled.to_ha()) == sha256_hash(fx.config), (
        f"{fx.name}: compile(decompile(x)) != x (zero-transformation round-trip failed)\n"
        f"decompiled source:\n{source}"
    )
