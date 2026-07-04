"""M0 test 1 — `serialize(parse(x)) ≈ x` for every fixture (I3, key-order-insensitive)."""

from __future__ import annotations

import pytest
from _corpus import Fixture, load_corpus

from hassle.ir import parse, serialize

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


def test_ir_roundtrips_non_string_id() -> None:
    # Regression (reviewer nit, I3 "for ANY config"): a non-string id must
    # round-trip verbatim, not raise. HA stores ids as strings, but the IR
    # boundary must never mutate or reject data.
    config = {"id": 1687201958261, "alias": "numeric id", "trigger": [], "action": []}
    obj = parse(config, kind="automation")
    assert serialize(obj) == config
    assert obj.object_key() == "automation:1687201958261"
