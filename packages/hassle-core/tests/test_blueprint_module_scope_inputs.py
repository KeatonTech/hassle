"""Module-scope `bp_input` (docs/internals/blueprints-design.md §8.2, revised).

`bp_input` used to raise outside a `@blueprint` body, on the reasoning that an
input "only means something to the blueprint that declares it". That constraint
fell: it also meant a trigger built at decoration time could never name an
input, which is the one thing standing between `@blueprint` and the
`triggers=` every other object decorator has (§8.11).

The replacement model has two halves, and they are deliberately different
questions:

- **Use determines MEMBERSHIP.** A blueprint's input schema is the set of
  declarations whose refs appear anywhere in its compiled triggers or actions,
  found by the same sentinel tree-walk §8.3's template check already runs.
  Declaring inside a body still counts as using, so in-body `bp_input` keeps
  working unchanged. Sharing one declaration across several blueprints is legal
  and intended -- HA's `!input` namespace is per-document, so each emitted
  document simply gets its own entry carrying the shared metadata.
- **Declaration determines ORDER.** Each document's `input:` block is its used
  declarations in global declaration-sequence order -- NOT first-use order,
  which would let a body refactor scramble the form a user sees in the HA UI.

The honest costs (§8.2's note, accepted): membership-by-use means deleting the
last branch that referenced an input silently drops it from the schema, and
editing a shared declaration moves every user's form at once.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.blueprints import parse_blueprint
from hassle.compiler.blueprint_dsl import DuplicateBlueprintInputError
from hassle.compiler.bundle import compile_bundle
from hassle.ir.models import BlueprintConfig
from hassle.registry.finding import Finding
from hassle.registry.validate import validate_bundle
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR_ERRORS = Path(__file__).resolve().parent / "snapshots" / "errors"
SNAP_DIR_FINDINGS = Path(__file__).resolve().parent / "snapshots" / "findings"

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "registry" / "home.json"


def _bundle(tmp_path: Path, source: str, *, name: str = "b") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "shared.py").write_text(source, encoding="utf-8")
    return root


def _sources(tmp_path: Path, source: str, *, name: str = "b") -> dict[str, str]:
    result = compile_bundle(_bundle(tmp_path, source, name=name))
    out: dict[str, str] = {}
    for key, obj in result.objects.items():
        assert isinstance(obj, BlueprintConfig)
        assert obj.source is not None
        out[key] = obj.source
    return out


def _inputs(tmp_path: Path, source: str, key: str, *, name: str = "b") -> list[str]:
    text = _sources(tmp_path, source, name=name)[key]
    return list(parse_blueprint(text, display_path=key).inputs)


ONE = "blueprint:automation/local/one.yaml"
TWO = "blueprint:automation/local/two.yaml"


# --- a module-scope declaration is legal ------------------------------------


FREE_FLOATING = """\
from hassle import blueprint, bp_input, service, state, when

BUTTON = bp_input("button", selector={"entity": {"domain": "event"}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state(BUTTON).to("on"))
    service("light.turn_on", target={"entity_id": "light.hall"})
"""


def test_a_bp_input_outside_a_blueprint_body_no_longer_raises(tmp_path: Path) -> None:
    compile_bundle(_bundle(tmp_path, FREE_FLOATING))


def test_a_module_scope_declaration_joins_the_schema_of_the_blueprint_that_uses_it(
    tmp_path: Path,
) -> None:
    assert _inputs(tmp_path, FREE_FLOATING, ONE) == ["button"]


def test_a_module_scope_ref_still_compiles_to_an_input_node(tmp_path: Path) -> None:
    assert "entity_id: !input button" in _sources(tmp_path, FREE_FLOATING)[ONE]


# --- sharing: one declaration, two documents --------------------------------


SHARED = """\
from hassle import blueprint, bp_input, service, state, when

LIGHT = bp_input(
    "light",
    selector={"entity": {"domain": "light"}},
    description="The light this room drives.",
)


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state("binary_sensor.a").to("on"))
    service("light.turn_on", target={"entity_id": LIGHT})


@blueprint(domain="automation", path="local/two.yaml", name="Two")
def two():
    when(state("binary_sensor.b").to("on"))
    service("light.turn_off", target={"entity_id": LIGHT})
"""


def test_one_declaration_shared_by_two_blueprints_is_legal(tmp_path: Path) -> None:
    sources = _sources(tmp_path, SHARED)
    assert set(sources) == {ONE, TWO}


def test_each_document_gets_its_own_entry_with_the_shared_metadata(tmp_path: Path) -> None:
    """HA's `!input` namespace is per-document, so sharing is a source-level
    convenience, not a cross-document reference."""
    sources = _sources(tmp_path, SHARED)
    for text in sources.values():
        parsed = parse_blueprint(text, display_path="x")
        assert parsed.inputs["light"]["description"] == "The light this room drives."


# --- membership by use ------------------------------------------------------


A_B_C = """\
from hassle import blueprint, bp_input, service, state, when

A = bp_input("a", selector={"entity": {"domain": "light"}})
B = bp_input("b", selector={"entity": {"domain": "light"}})
C = bp_input("c", selector={"number": {"min": 1, "max": 100}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state("binary_sensor.x").to("on"))
    service("light.turn_on", target={"entity_id": A}, brightness_pct=C)


@blueprint(domain="automation", path="local/two.yaml", name="Two")
def two():
    when(state("binary_sensor.y").to("on"))
    service("light.turn_on", target={"entity_id": B}, brightness_pct=C)
"""


def test_a_blueprint_declares_exactly_the_inputs_it_uses(tmp_path: Path) -> None:
    assert _inputs(tmp_path, A_B_C, ONE) == ["a", "c"]
    assert _inputs(tmp_path, A_B_C, TWO) == ["b", "c"]


def test_an_input_used_only_in_a_trigger_is_a_member(tmp_path: Path) -> None:
    """The walk covers triggers, not just actions -- a blueprint whose only
    reference to an input is the thing it triggers on still declares it."""
    assert _inputs(
        tmp_path,
        """\
from hassle import blueprint, bp_input, service, state, when

BUTTON = bp_input("button", selector={"entity": {"domain": "event"}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state(BUTTON).to("on"))
    service("light.turn_on", target={"entity_id": "light.hall"})
""",
        ONE,
    ) == ["button"]


def test_an_input_used_only_in_a_condition_is_a_member(tmp_path: Path) -> None:
    assert _inputs(
        tmp_path,
        """\
from hassle import blueprint, bp_input, only_if, service, state, when

GATE = bp_input("gate", selector={"entity": {"domain": "input_boolean"}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state("binary_sensor.x").to("on"))
    with only_if(state(GATE).is_("on")):
        service("light.turn_on", target={"entity_id": "light.hall"})
""",
        ONE,
    ) == ["gate"]


def test_an_input_used_only_inside_a_nested_action_container_is_a_member(
    tmp_path: Path,
) -> None:
    """The sentinel walk is recursive, so a ref three containers deep counts
    exactly like one at the top level."""
    assert _inputs(
        tmp_path,
        """\
from hassle import blueprint, bp_input, choose, service, state, when

DEEP = bp_input("deep", selector={"entity": {"domain": "light"}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state("binary_sensor.x").to("on"))
    with choose() as c:
        with c.when_(state("binary_sensor.y").is_("on")):
            service("light.turn_on", target={"entity_id": DEEP})
""",
        ONE,
    ) == ["deep"]


# --- declaration order, not first-use order ---------------------------------


ORDER = """\
from hassle import blueprint, bp_input, service, state, when

C = bp_input("c", selector={"number": {"min": 1, "max": 100}})
A = bp_input("a", selector={"entity": {"domain": "light"}})
B = bp_input("b", selector={"entity": {"domain": "light"}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state("binary_sensor.x").to("on"))
    service("light.turn_on", target={"entity_id": A}, brightness_pct=C)
    service("light.turn_off", target={"entity_id": B})
"""


def test_the_input_block_follows_declaration_sequence_not_first_use(tmp_path: Path) -> None:
    """`a` is used first but declared second. Sorting by use would let a body
    refactor reorder the form the HA UI renders."""
    assert _inputs(tmp_path, ORDER, ONE) == ["c", "a", "b"]


# --- in-body declarations keep working --------------------------------------


IN_BODY = """\
from hassle import blueprint, bp_input, service, state, when


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    switch = bp_input("switch", selector={"entity": {"domain": "event"}})
    light = bp_input("light", selector={"entity": {"domain": "light"}})
    when(state(switch).to("on"))
    service("light.turn_on", target={"entity_id": light})
"""


def test_in_body_declarations_are_unchanged(tmp_path: Path) -> None:
    assert _inputs(tmp_path, IN_BODY, ONE) == ["switch", "light"]


DECLARED_UNUSED_IN_BODY = """\
from hassle import blueprint, bp_input, service, state, when


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    bp_input("spare", selector={"text": {}})
    when(state("binary_sensor.x").to("on"))
    service("light.turn_on", target={"entity_id": "light.hall"})
"""


def test_declaring_in_a_body_is_also_using(tmp_path: Path) -> None:
    """The one asymmetry between the two declaration sites, and it is what
    keeps every pre-existing bundle compiling byte-identically."""
    assert _inputs(tmp_path, DECLARED_UNUSED_IN_BODY, ONE) == ["spare"]


MIXED = """\
from hassle import blueprint, bp_input, service, state, when

SHARED_LIGHT = bp_input("shared_light", selector={"entity": {"domain": "light"}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    local = bp_input("local", selector={"number": {"min": 1, "max": 100}})
    when(state("binary_sensor.x").to("on"))
    service("light.turn_on", target={"entity_id": SHARED_LIGHT}, brightness_pct=local)
"""


def test_module_scope_declarations_precede_in_body_ones(tmp_path: Path) -> None:
    """Sequence order, applied across both sites: module scope runs at import,
    a body runs during compilation, so a module-scope declaration is always
    the earlier one."""
    assert _inputs(tmp_path, MIXED, ONE) == ["shared_light", "local"]


# --- decorator triggers may name inputs -------------------------------------


DECORATOR_TRIGGER = """\
from hassle import blueprint, bp_input, service, state

BUTTON = bp_input("button", selector={"entity": {"domain": "event"}})
LIGHT = bp_input("light", selector={"entity": {"domain": "light"}})


@blueprint(
    domain="automation",
    path="local/one.yaml",
    name="One",
    triggers=[
        state(BUTTON).with_options(
            id="press", not_from=["unavailable"], not_to=["unknown", "unavailable"]
        )
    ],
)
def one():
    service("light.turn_on", target={"entity_id": LIGHT})
"""


def test_a_decorator_trigger_may_reference_an_input(tmp_path: Path) -> None:
    """§8.11's payoff: the whole subscription lives in the decorator and the
    body is a pure action sequence."""
    src = _sources(tmp_path, DECORATOR_TRIGGER)[ONE]
    assert "entity_id: !input button" in src


def test_a_decorator_trigger_makes_its_input_a_member(tmp_path: Path) -> None:
    assert _inputs(tmp_path, DECORATOR_TRIGGER, ONE) == ["button", "light"]


def test_the_decorator_triggers_negations_survive_into_the_document(tmp_path: Path) -> None:
    body = parse_blueprint(_sources(tmp_path, DECORATOR_TRIGGER)[ONE], display_path=ONE).body
    trigger = body["triggers"][0]
    assert trigger["not_from"] == ["unavailable"]
    assert trigger["not_to"] == ["unknown", "unavailable"]


# --- determinism ------------------------------------------------------------


def test_the_sequence_is_stable_across_compiles(tmp_path: Path) -> None:
    """R8: the counter is reset per compile and assigned at call time, and
    both import order and compile order are deterministic."""
    assert _sources(tmp_path, A_B_C, name="first") == _sources(tmp_path, A_B_C, name="second")


# --- diagnostics: two declarations, one name, one blueprint -----------------


COLLIDING = """\
from hassle import blueprint, bp_input, service, state, when

FIRST = bp_input("light", selector={"entity": {"domain": "light"}})
SECOND = bp_input("light", selector={"entity": {"domain": "switch"}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state("binary_sensor.x").to("on"))
    service("light.turn_on", target={"entity_id": FIRST})
    service("light.turn_off", target={"entity_id": SECOND})
"""


def test_two_declarations_of_one_name_in_one_blueprint_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(DuplicateBlueprintInputError):
        compile_bundle(_bundle(tmp_path, COLLIDING))


def test_the_collision_message_names_both_declaration_sites(tmp_path: Path) -> None:
    with pytest.raises(DuplicateBlueprintInputError) as excinfo:
        compile_bundle(_bundle(tmp_path, COLLIDING))
    message = str(excinfo.value)
    assert "shared.py:3" in message
    assert "shared.py:4" in message


def test_duplicate_input_message_snapshot(tmp_path: Path) -> None:
    with pytest.raises(DuplicateBlueprintInputError) as excinfo:
        compile_bundle(_bundle(tmp_path, COLLIDING))
    check_snapshot(
        SNAP_DIR_ERRORS, "blueprint_duplicate_input", normalize_error(str(excinfo.value))
    )


IN_BODY_COLLIDING = """\
from hassle import blueprint, bp_input, service, state, when


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    first = bp_input("light", selector={"entity": {"domain": "light"}})
    second = bp_input("light", selector={"entity": {"domain": "switch"}})
    when(state("binary_sensor.x").to("on"))
    service("light.turn_on", target={"entity_id": first})
    service("light.turn_off", target={"entity_id": second})
"""


def test_two_in_body_declarations_of_one_name_are_still_an_error(tmp_path: Path) -> None:
    with pytest.raises(DuplicateBlueprintInputError):
        compile_bundle(_bundle(tmp_path, IN_BODY_COLLIDING))


DISJOINT_SAME_NAME = """\
from hassle import blueprint, bp_input, service, state, when

FIRST = bp_input("light", selector={"entity": {"domain": "light"}})
SECOND = bp_input("light", selector={"entity": {"domain": "switch"}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state("binary_sensor.x").to("on"))
    service("light.turn_on", target={"entity_id": FIRST})


@blueprint(domain="automation", path="local/two.yaml", name="Two")
def two():
    when(state("binary_sensor.y").to("on"))
    service("switch.turn_on", target={"entity_id": SECOND})
"""


def test_the_same_name_in_two_different_blueprints_is_fine(tmp_path: Path) -> None:
    """The rule is per-document, because HA's input namespace is. Two
    blueprints each declaring their own `light` collide with nothing."""
    sources = _sources(tmp_path, DISJOINT_SAME_NAME)
    assert "domain: light" in sources[ONE]
    assert "domain: switch" in sources[TWO]


# --- diagnostics: a declaration nothing uses --------------------------------


DEAD = """\
from hassle import blueprint, bp_input, service, state, when

USED = bp_input("used", selector={"entity": {"domain": "light"}})
ORPHAN = bp_input("orphan", selector={"entity": {"domain": "light"}})


@blueprint(domain="automation", path="local/one.yaml", name="One")
def one():
    when(state("binary_sensor.x").to("on"))
    service("light.turn_on", target={"entity_id": USED})
"""


def _findings(tmp_path: Path, source: str, *, name: str = "b") -> list[Finding]:
    from hassle.registry.snapshot import RegistrySnapshot

    return validate_bundle(
        compile_bundle(_bundle(tmp_path, source, name=name)), RegistrySnapshot.load(FIXTURE)
    )


def _of(findings: list[Finding], code: str) -> list[Finding]:
    return [f for f in findings if f.code == code]


def test_a_declaration_no_blueprint_uses_is_a_warning_not_an_error(tmp_path: Path) -> None:
    """It reaches no Home Assistant document at all, so it is dead code --
    but it is also exactly what a half-finished refactor looks like, and
    failing the compile would block the intermediate state."""
    findings = _of(_findings(tmp_path, DEAD), "blueprint-input-never-used")
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "orphan" in findings[0].message


def test_the_dead_declaration_warning_points_at_the_declaration(tmp_path: Path) -> None:
    finding = _of(_findings(tmp_path, DEAD), "blueprint-input-never-used")[0]
    assert finding.file is not None and finding.file.endswith("shared.py")
    assert finding.line == 4


def test_a_used_declaration_is_not_flagged(tmp_path: Path) -> None:
    codes = [f.code for f in _findings(tmp_path, DEAD)]
    assert codes.count("blueprint-input-never-used") == 1


def test_an_in_body_declaration_is_never_dead(tmp_path: Path) -> None:
    """Declaring in a body is using, so the warning cannot fire there."""
    assert _of(_findings(tmp_path, DECLARED_UNUSED_IN_BODY), "blueprint-input-never-used") == []


def test_dead_declaration_finding_snapshot(tmp_path: Path) -> None:
    finding = _of(_findings(tmp_path, DEAD), "blueprint-input-never-used")[0]
    check_snapshot(SNAP_DIR_FINDINGS, "blueprint_input_never_used", normalize_error(str(finding)))


def test_the_dead_declaration_warning_does_not_survive_into_the_next_compile(
    tmp_path: Path,
) -> None:
    """Declarations are per-compile state; a stale one would report a warning
    against a file the second bundle does not contain."""
    _findings(tmp_path, DEAD, name="first")
    assert (
        _of(_findings(tmp_path, FREE_FLOATING, name="second"), "blueprint-input-never-used") == []
    )
