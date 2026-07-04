"""M4 test 7 (I5): the simulator consumes compiled IR/HA-JSON only.

Proof: run a corpus JSON automation that never existed as DSL Python at all --
loaded straight from `fixtures/configs/`, parsed through the M0 IR
(`hassle.ir.parse` + `normalize_ha`), and handed to the simulator as a
`CompileResult`-shaped bundle built by hand (never touching `compile_bundle`,
never importing a bundle directory, no DSL Python anywhere in this file).
If the simulator secretly needed DSL source to run, this test would have
nothing to give it and would fail to even construct a `Simulator`.
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle.compiler.bundle import CompileResult
from hassle.ir import normalize_ha, parse
from hassle.testing import Simulator

_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "configs"
    / "automation_state_trigger_basic.json"
)


def _corpus_result() -> CompileResult:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    normalized = normalize_ha(raw, kind="automation")
    obj = parse(normalized, kind="automation", key_hint="corpus_only")
    result = CompileResult()
    result.add(obj, spans={}, decl_span=None, duplicate_of=None)
    return result


def test_sim_runs_corpus_json_that_never_existed_as_dsl() -> None:
    result = _corpus_result()
    sim = Simulator(result)
    sim.state_change("binary_sensor.motion_detector", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway")


def test_sim_input_is_ir_objects_not_dsl_source() -> None:
    """The `Simulator` constructor never receives a bundle directory, a
    module, or any Python source -- only the `CompileResult` produced from
    parsed IR. This is the structural half of the I5 proof (the behavioral
    half is the test above actually firing the automation)."""
    result = _corpus_result()
    assert result.objects["automation:corpus_only"].to_ha()["triggers"][0]["trigger"] == "state"
    # Constructing the simulator from this hand-built result (no bundle dir,
    # no compile_bundle call) must succeed identically to the DSL path.
    sim = Simulator(result)
    assert sim is not None
