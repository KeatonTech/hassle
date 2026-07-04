"""M2 test 2 — decompiler stability (R8 determinism) and the fixed-point property.

- ``decompile(x)`` twice -> byte-identical output (no wall-clock, no randomness,
  no dict-iteration-order dependence).
- ``decompile(compile(decompile(x)))`` -> byte-identical to the *first* decompile:
  decompiling a bundle, recompiling it, and decompiling again reproduces the same
  source (a fixed point), even though the DSL bundle is the compiler's input and
  the corpus JSON is not directly comparable to it.
"""

from __future__ import annotations

import pytest
from _corpus import Fixture, load_corpus

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import parse

CORPUS: list[Fixture] = load_corpus()


def _ir_object(fx: Fixture) -> object:
    key_hint = fx.key_hint
    if fx.kind == "automation" and "id" not in fx.config:
        key_hint = fx.name
    return parse(fx.config, kind=fx.kind, key_hint=key_hint)


@pytest.mark.parametrize("fx", CORPUS, ids=[f.name for f in CORPUS])
def test_decompile_stable_across_runs(fx: Fixture) -> None:
    obj = _ir_object(fx)
    objects = {obj.object_key(): obj}  # type: ignore[attr-defined]
    first = decompile_bundle(objects)
    second = decompile_bundle(objects)
    assert first == second, f"{fx.name}: decompile(x) is not byte-stable across runs"


@pytest.mark.parametrize("fx", CORPUS, ids=[f.name for f in CORPUS])
def test_decompile_is_a_fixed_point(
    fx: Fixture, tmp_path_factory: pytest.TempPathFactory
) -> None:
    obj = _ir_object(fx)
    objects = {obj.object_key(): obj}  # type: ignore[attr-defined]
    first = decompile_bundle(objects)

    bundle_dir = tmp_path_factory.mktemp("bundle")
    (bundle_dir / "objects.py").write_text(first, encoding="utf-8")
    result = compile_bundle(str(bundle_dir))
    second = decompile_bundle(result.objects)

    assert first == second, (
        f"{fx.name}: decompile(compile(decompile(x))) != decompile(x)\n"
        f"first:\n{first}\nsecond:\n{second}"
    )
