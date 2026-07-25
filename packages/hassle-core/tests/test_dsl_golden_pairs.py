"""DSL bundle -> IR golden pairs, and byte-determinism.

`compile_bundle` imports a bundle dir in isolation, runs each registered object's
function once inside a recording context, and emits ``{object_key: ha_json}`` in
the canonical plural schema (§7.1). Each golden case's ``expected_ir.json`` is the
exact HA JSON the compile must reproduce.
"""

from __future__ import annotations

import pytest
from _dsl_cases import DslCase, error_cases, ir_cases

from hassle.compiler import compile_bundle
from hassle.ir import canonical_json

CASES: list[DslCase] = ir_cases()
ERROR_CASES: list[DslCase] = error_cases()


def test_dsl_cases_present() -> None:
    # At least the core seeded cases must exist.
    names = {c.name for c in CASES}
    assert {"minimal", "state_delay_service", "loop_three_rooms", "kitchen_sink_lite"} <= names


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_dsl_golden_pair(case: DslCase) -> None:
    assert case.expected_ir is not None
    result = compile_bundle(case.bundle_dir)
    emitted = {key: obj.to_ha() for key, obj in result.objects.items()}
    assert emitted == case.expected_ir


@pytest.mark.parametrize("case", ERROR_CASES, ids=[c.name for c in ERROR_CASES])
def test_dsl_error_case(case: DslCase) -> None:
    # Error cases declare {error_type, contains}; compile must raise that type
    # with a message containing every fragment.
    assert case.expected_error is not None
    with pytest.raises(Exception) as excinfo:
        compile_bundle(case.bundle_dir)
    assert type(excinfo.value).__name__ == case.expected_error["error_type"]
    message = str(excinfo.value)
    for fragment in case.expected_error["contains"]:
        assert fragment in message


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_compile_deterministic(case: DslCase) -> None:
    # Two independent compiles produce byte-identical canonical JSON.
    first = compile_bundle(case.bundle_dir)
    second = compile_bundle(case.bundle_dir)

    def dump(result: object) -> str:
        assert hasattr(result, "objects")
        objects = result.objects  # type: ignore[attr-defined]
        return canonical_json({key: obj.to_ha() for key, obj in objects.items()})

    assert dump(first) == dump(second)
