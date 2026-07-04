"""M1 test 1 + test 7 — DSL bundle -> IR golden pairs, and byte-determinism (R8).

`compile_bundle` imports a bundle dir in isolation, runs each registered object's
function once inside a recording context, and emits ``{object_key: ha_json}`` in
the canonical plural schema (§7.1). Each golden case's ``expected_ir.json`` is the
exact HA JSON the compile must reproduce.
"""

from __future__ import annotations

import pytest
from _dsl_cases import DslCase, ir_cases

from hassle_core.compiler import compile_bundle
from hassle_core.ir import canonical_json

CASES: list[DslCase] = ir_cases()


def test_dsl_cases_present() -> None:
    # At least the five seeded M1-core cases must exist.
    names = {c.name for c in CASES}
    assert {"minimal", "state_delay_service", "loop_three_rooms", "kitchen_sink_lite"} <= names


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_dsl_golden_pair(case: DslCase) -> None:
    assert case.expected_ir is not None
    result = compile_bundle(case.bundle_dir)
    emitted = {key: obj.to_ha() for key, obj in result.objects.items()}
    assert emitted == case.expected_ir


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_compile_deterministic(case: DslCase) -> None:
    # R8: two independent compiles produce byte-identical canonical JSON.
    first = compile_bundle(case.bundle_dir)
    second = compile_bundle(case.bundle_dir)

    def dump(result: object) -> str:
        assert hasattr(result, "objects")
        objects = result.objects  # type: ignore[attr-defined]
        return canonical_json({key: obj.to_ha() for key, obj in objects.items()})

    assert dump(first) == dump(second)
