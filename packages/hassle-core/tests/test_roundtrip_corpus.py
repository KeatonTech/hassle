"""M2 test 1 — the round-trip invariant (I3): ``compile(decompile(x)) ~ normalize_ha(x)``.

For every fixture in ``fixtures/configs/``: parse it to IR, decompile the IR to a
DSL bundle, recompile that bundle, and assert the recompiled IR's canonical hash
equals the canonical hash of ``normalize_ha(x)`` (which is ``x`` itself for every
fixture already in HA's stored plural form -- only the two legacy-form fixtures,
``automation_legacy_platform_naming`` and ``automation_service_call_longhand``,
exercise actual normalization).

No exceptions: fixtures the decompiler doesn't yet model in the typed DSL still
round-trip because the decompiler falls back to ``raw_automation``/``raw_trigger``/
``raw_condition``/``raw_action`` rather than dropping data (DESIGN §5.8, I3).

Automations in the corpus have no ``id`` field (the fixtures are hand-authored
docs examples; real HA always assigns one) -- exactly like the M0 corpus loader,
a per-fixture ``key_hint`` (the filename stem) supplies the identity needed to
name the decompiled object and round-trip through ``object_key()``.
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

    expected = normalize_ha(fx.config, kind=fx.kind)
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(expected), (
        f"{fx.name}: compile(decompile(x)) != normalize_ha(x)\n"
        f"decompiled source:\n{source}"
    )


def test_normalize_ha_is_identity_for_plural_fixtures() -> None:
    # Sanity check for the invariant statement itself: every fixture already in
    # HA's stored plural form must be its own normalization (only the two named
    # legacy-form fixtures are expected to differ).
    legacy_names = {"automation_legacy_platform_naming", "automation_service_call_longhand"}
    for fx in CORPUS:
        expected = normalize_ha(fx.config, kind=fx.kind)
        if fx.name in legacy_names:
            assert expected != fx.config, f"{fx.name} was expected to need normalization"
        else:
            assert expected == fx.config, f"{fx.name}: normalize_ha(x) != x for a plural fixture"
