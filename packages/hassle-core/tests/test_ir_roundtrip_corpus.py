"""M0 test 1 — `serialize(parse(x)) ≈ x` for every fixture (I3, key-order-insensitive)."""

from __future__ import annotations

import pytest
from _corpus import Fixture, load_corpus

from hassle_core.ir import parse, serialize

CORPUS: list[Fixture] = load_corpus()


def test_corpus_is_present() -> None:
    # The corpus is the acceptance substrate; an empty one is a failure, not a skip.
    assert CORPUS, "no fixtures found under fixtures/configs/"


@pytest.mark.parametrize("fx", CORPUS, ids=[f.name for f in CORPUS])
def test_ir_roundtrip_corpus(fx: Fixture) -> None:
    obj = parse(fx.config, kind=fx.kind, key_hint=fx.key_hint)
    result = serialize(obj)
    # dict `==` is key-order-insensitive and recurses; list order is significant.
    assert result == fx.config
