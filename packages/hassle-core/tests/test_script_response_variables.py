"""Script response variables (owner request 2026-07-24, `ux/script-responses`).

HA script responses (2023.7+): a script ends with ``stop`` carrying
``response_variable: <name>`` -- the named RUN VARIABLE's value becomes the
script's response -- and a caller passing ``response_variable=`` on the
service call receives it. The owner's blind-auction architecture depends on
this: behavior scripts return ``{position, peek, priority}`` bid dicts and a
coordinator picks the highest-priority bid.

Coverage:
- ``stop()`` gains ``response_variable=`` (F3-additive widening; emitting
  ``{"stop": ..., "response_variable": ...}``);
- the decompiler round-trips it (I3);
- the simulator delivers the callee's response into the caller's variables
  under the CALLER's ``response_variable`` name (I5, end to end);
- a callee that never stops with a response yields ``None`` (no crash).
"""

from __future__ import annotations

from pathlib import Path

from _sim_helpers import build_sim, compile_source

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler import decompile_bundle
from hassle.ir import parse, sha256_hash

_BIDDER = """
    from hassle import automation, service, shared_script, state, stop, variables, when

    @shared_script(id="bidder", alias="Bidder")
    def bidder():
        variables(bid={"position": "peek_bottom", "peek": 54, "priority": 70})
        stop("bid placed", response_variable="bid")

    @automation(id="a", alias="a")
    def a():
        when(state("button.go").to("on"))
        service("script.bidder", response_variable="result")
        service(
            "notify.phone",
            message="{{ result.position }}",
            priority="{{ result.priority }}",
        )
"""


def test_stop_compiles_the_response_variable(tmp_path: Path) -> None:
    result = compile_source(tmp_path, _BIDDER)
    script = result.objects["script:bidder"].to_ha()
    assert script["sequence"][-1] == {
        "stop": "bid placed",
        "response_variable": "bid",
    }


def test_sim_delivers_the_response_to_the_caller(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _BIDDER)
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.phone", message="peek_bottom", priority="70")


_NO_RESPONSE = """
    from hassle import automation, service, shared_script, state, when

    @shared_script(id="quiet", alias="Quiet")
    def quiet():
        service("light.turn_on", entity_id="light.x")

    @automation(id="a", alias="a")
    def a():
        when(state("button.go").to("on"))
        service("script.quiet", response_variable="result")
        service("notify.phone", message="{{ 'empty' if result is none else 'set' }}")
"""


def test_missing_response_yields_none(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _NO_RESPONSE)
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.phone", message="empty")


_NESTED = """
    from hassle import automation, service, shared_script, state, stop, variables, when

    @shared_script(id="bidder", alias="Bidder")
    def bidder():
        variables(bid={"position": "open", "priority": 40})
        stop("bid", response_variable="bid")

    @shared_script(id="coordinator", alias="Coordinator")
    def coordinator():
        service("script.bidder", response_variable="inner")
        variables(best=[{"position": "{{ inner.position }}"}])
        stop("done", response_variable="best")

    @automation(id="a", alias="a")
    def a():
        when(state("button.go").to("on"))
        service("script.coordinator", response_variable="outer")
        service("notify.phone", message="{{ outer[0].position }}")
"""


def test_nested_script_responses_compose(tmp_path: Path) -> None:
    """The blind-auction shape: a coordinator script calls a bidder with
    response_variable and returns a value derived from it -- the outer
    automation reads the chained result (reviewer suggestion #2)."""
    sim = build_sim(tmp_path, _NESTED)
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.phone", message="open")


_ERROR_RESPONDER = """
    from hassle import automation, service, shared_script, state, stop, variables, when

    @shared_script(id="failer", alias="Failer")
    def failer():
        variables(bid={"position": "open"})
        stop("bad", error=True, response_variable="bid")

    @automation(id="a", alias="a")
    def a():
        when(state("button.go").to("on"))
        service("script.failer", response_variable="result")
        service("switch.turn_on", entity_id="switch.after")
"""


def test_error_stop_with_response_still_halts_the_caller(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _ERROR_RESPONDER)
    sim.state_change("button.go", "off", "on")
    sim.assert_not_called("switch.turn_on")


_UNMODELED_RESPONSE = """
    from hassle import automation, service, state, when

    @automation(id="a", alias="a")
    def a():
        when(state("button.go").to("on"))
        service("weather.get_forecasts", type="daily", response_variable="fc")
        service("notify.phone", message="{{ 'empty' if fc is none else 'set' }}")
"""


def test_unmodeled_service_response_yields_none_not_undefined(tmp_path: Path) -> None:
    """Reviewer suggestion #1: the permissive no-response contract must be
    uniform. A response_variable on a service the simulator doesn't model
    (weather.get_forecasts) seeds `none` instead of leaving the name
    Jinja-undefined, which killed the simulation at the first read."""
    sim = build_sim(tmp_path, _UNMODELED_RESPONSE)
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.phone", message="empty")


def test_stop_with_response_decompile_recompiles_to_identical_ir() -> None:
    config = {
        "alias": "Bidder",
        "sequence": [
            {"variables": {"bid": {"position": "open", "priority": 40}}},
            {"stop": "bid placed", "response_variable": "bid"},
        ],
    }
    obj = parse(config, kind="script", key_hint="bidder")
    source = decompile_bundle({obj.object_key(): obj})
    assert 'response_variable="bid"' in source

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "scripts.py").write_text(source, encoding="utf-8")
        result = compile_bundle(tmp)

    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(obj.to_ha())
