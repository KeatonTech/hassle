"""``@blueprint`` / ``bp_input`` -- blueprints AUTHORED IN THE DSL
(docs/internals/blueprints-design.md §8).

The blueprint object kind made a blueprint FILE a managed object. This module
makes the file itself a compiled artifact: the body is recorded by the same recorder ``@automation``
uses, declared inputs become ``!input`` nodes, and the emitted YAML is
deterministic (§8.6) so the object layer's sync machinery can push it unchanged. No
file is written into ``blueprints/`` -- the compiled object IS the source of
truth.

**Why ``InputRef`` subclasses ``str``.** An input must be usable wherever the
DSL accepts an entity id or a scalar (§8.2), and this codebase has no central
coercion chokepoint -- values pass verbatim into dicts at ``state()``,
``service(target=...)``, ``normalize_target``, ``variables()`` and a dozen more.
``EntityRef`` (helpers.py) and ``TemplateExpr`` (templates.py) already solve
exactly this by subclassing ``str``, so every one of those sites tolerates them
with no change. ``InputRef`` follows that precedent.

Its *string value* is a sentinel marker rather than the input name, which is
what makes §8.3 enforceable. A ref that reaches the emitter still wrapped in
its own object emits ``!input <name>``; a ref that was interpolated into a
Jinja template (or concatenated, or ``.format``-ed) survives only as marker
text inside a longer plain ``str``, and the emitter raises a located error
naming the fix. One mechanism catches every embedding path, instead of
overriding ``__str__``/``__format__`` to raise and hoping no path escapes.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator, Iterator, Sequence
from typing import Any, Final, cast

import yaml

from hassle.compiler.errors import CompileError
from hassle.compiler.protocols import TriggerBuilder
from hassle.compiler.spans import SourceSpan, capture_span

# A marker no real config string can contain (NUL is illegal in YAML plain
# scalars and in HA entity ids alike), carrying the input name so an embedded
# ref can still be NAMED in the error it causes.
_MARK: Final = "\x00hassle-blueprint-input\x00"


class UnsetType:
    """The 'no default declared' sentinel.

    Not ``None``: ``None`` is a legitimate YAML default, and the object layer already
    depends on telling the two apart -- ``BlueprintConfig.inputs`` keeps a bare
    ``room_key:`` entry as ``None`` precisely so "declared with no ``default:``"
    stays distinguishable (blueprints-design §1).
    """

    _instance: UnsetType | None = None

    def __new__(cls) -> UnsetType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Final = UnsetType()


class InputRef(str):
    """A declared blueprint input, usable anywhere the DSL takes a scalar."""

    __slots__ = (
        "_bp_name",
        "_default",
        "_description",
        "_in_body",
        "_selector",
        "_sequence",
        "_span",
    )

    _bp_name: str
    _selector: dict[str, Any]
    _default: Any
    _description: str | None
    _span: SourceSpan | None
    _sequence: int
    _in_body: bool

    def __new__(
        cls,
        name: str,
        *,
        selector: dict[str, Any],
        default: Any = UNSET,
        description: str | None = None,
        span: SourceSpan | None = None,
        sequence: int = 0,
        in_body: bool = True,
    ) -> InputRef:
        self = super().__new__(cls, f"{_MARK}{name}{_MARK}")
        self._bp_name = name
        self._selector = selector
        self._default = default
        self._description = description
        self._span = span
        self._sequence = sequence
        self._in_body = in_body
        return self

    # `EntityRef` does the same: a deep-copied option dict would otherwise die
    # on the keyword-only __new__ signature.
    def __copy__(self) -> InputRef:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> InputRef:
        return self

    def __repr__(self) -> str:
        return f"!input {self._bp_name}"

    @property
    def input_name(self) -> str:
        return self._bp_name

    @property
    def declaration_span(self) -> SourceSpan | None:
        """The ``bp_input(...)`` call site (public accessor for diagnostics)."""
        return self._span

    @property
    def sequence(self) -> int:
        """This declaration's global sequence number (§8.2).

        Assigned at ``bp_input`` call time, monotonically, from a counter reset
        at the start of every compile. It is the *only* thing that orders a
        blueprint's emitted ``input:`` block, which is why it must not depend on
        where a ref is later used: a body refactor that moves a reference must
        not reorder the form the HA UI renders for a user.
        """
        return self._sequence

    @property
    def declared_in_body(self) -> bool:
        """True when the ``bp_input`` call ran inside a ``@blueprint`` body.

        A body-scoped declaration is a member of that body's blueprint by the
        act of declaring (§8.2), so it can never be dead; only a module-scope
        declaration can end up referenced by nothing.
        """
        return self._in_body

    @property
    def is_required(self) -> bool:
        return isinstance(self._default, UnsetType)

    @property
    def is_entity_selector(self) -> bool:
        return "entity" in self._selector

    def spec(self) -> dict[str, Any]:
        """This input's ``blueprint.input`` entry, in fixed key order (§8.6)."""
        spec: dict[str, Any] = {}
        if self._description is not None:
            spec["description"] = self._description
        spec["selector"] = self._selector
        if not self.is_required:
            spec["default"] = self._default
        return spec


# --- errors -----------------------------------------------------------------


class BlueprintInputInTemplateError(CompileError):
    """A blueprint input was interpolated into a template string (§8.3)."""

    def __init__(self, name: str, span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"The blueprint input `{name}`{where} was built into a template string. "
            f"Home Assistant substitutes `!input` into YAML nodes, not into the text "
            f"inside a template, so the reference would reach HA as literal characters "
            f"and never resolve. Fix: bind the input to a variable first with "
            f"`variables({name}={name})`, then reference the variable in the template as "
            f"`{{{{ {name} }}}}`."
        )


class OptionalEntityInputAsTriggerError(CompileError):
    """An optional entity input was used as a literal trigger ``entity_id`` (§8.5)."""

    def __init__(self, name: str, span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"The blueprint input `{name}`{where} is an OPTIONAL entity selector used as a "
            f"trigger's `entity_id`. Left empty it expands to an empty entity id, which "
            f"Home Assistant rejects when it validates the expanded automation -- and "
            f"unlike a service target there is no templated form to fall back on, because "
            f"HA does not template trigger entity ids. Fix: make the input required by "
            f"removing its `default=`, or trigger on something else and use `{name}` only "
            f"as a service target, where the compiler emits the templated form for you."
        )


class BlueprintDefinedTwiceError(CompileError):
    """One domain/path declared both in the DSL and as an on-disk file (§8.7)."""

    def __init__(self, identity: str, file: str, span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"The blueprint `{identity}` is declared twice: by a `@blueprint(...)` in the "
            f"DSL{where}, and by the bundle file `{file}`. Hassle will not pick a winner -- "
            f"preferring the file would discard whatever the Python says, and preferring the "
            f"DSL would make compiled output depend on a file's mere existence. Fix: delete "
            f"whichever one is no longer the source of truth. If you are migrating this "
            f"blueprint into the DSL, delete the file -- a DSL blueprint needs no file, "
            f"because the compiled object is what gets pushed."
        )


# `BlueprintInputOutsideBodyError` used to live here: a `bp_input(...)` call
# outside a `@blueprint` body was an error, because "an input only means
# something to the blueprint that declares it". §8.2's revision retired it --
# see that section's dated note. The short version: the constraint was never
# about inputs, it was about the DECLARATION SITE being the only place a
# blueprint's membership could be read from, and once membership is read from
# USE instead (the sentinel walk), a free-floating declaration is perfectly
# well-defined and is what lets a decoration-time trigger name an input at all.


def _at(span: SourceSpan | None) -> str:
    return f"{span.file}:{span.line}" if span is not None else "an unknown location"


class DuplicateBlueprintInputError(CompileError):
    """Two declarations of one input name are reachable from one blueprint (§8.2)."""

    def __init__(
        self,
        name: str,
        identity: str,
        first: SourceSpan | None,
        second: SourceSpan | None,
    ) -> None:
        super().__init__(
            f"Two different `bp_input({name!r})` declarations are both reachable from the "
            f"blueprint `{identity}` -- one at {_at(first)}, the other at {_at(second)}. "
            f"HA's `blueprint.input` block is a mapping, so one would silently replace the "
            f"other along with its selector and default, and which one survived would "
            f"depend on declaration order rather than on anything you wrote. Fix: delete "
            f"one of them and reference the surviving `InputRef` from both places, or give "
            f"one of them a different name. Two declarations sharing a name is only a "
            f"problem when a single blueprint can see both -- separate blueprints each get "
            f"their own `input:` namespace and may reuse the name freely."
        )


# --- declaration context ----------------------------------------------------


class _InputCollector:
    """Collects the declarations made INSIDE one blueprint body.

    Body-scoped declarations are the one case where declaring is also using
    (§8.2), so this list seeds the blueprint's membership set before the
    use-walk runs. It no longer checks for duplicates: with two declaration
    sites the question "are these two the same input?" is only answerable once
    a blueprint's whole reachable set is known, which is where
    :func:`resolve_inputs` asks it -- and where both spans are available to put
    in the error.
    """

    def __init__(self) -> None:
        self.declared: list[InputRef] = []

    def declare(self, ref: InputRef) -> None:
        self.declared.append(ref)


_COLLECTOR: list[_InputCollector] = []

#: Every ``bp_input`` call of the CURRENT compile, in call order. An entry's
#: index is its global declaration sequence number (§8.2): assignment is at call
#: time, and both halves of compile order are deterministic -- bundle modules
#: are imported in sorted path order, and blueprint bodies run in registration
#: order -- so the numbering is reproducible across runs and machines (R8).
#: Reset by :func:`reset_declared_blueprint_inputs`, exactly like the other
#: declarative builders' module-level lists, so one compile never sees another's.
_DECLARATIONS: list[InputRef] = []


def reset_declared_blueprint_inputs() -> None:
    """Clear the declaration list + sequence counter (called per compile)."""
    _DECLARATIONS.clear()


def drain_module_scope_declarations() -> list[InputRef]:
    """Declarations made OUTSIDE any blueprint body, in declaration order.

    The only ones that can turn out to be dead: a body-scoped declaration is a
    member of its own blueprint by construction.

    **Self-cleaning** -- the declaration list is emptied on the way out, in a
    ``finally``, exactly as
    ``template_helpers.check_no_dangling_template_helper_declarations`` empties
    its pending list, and for the same reason. ``compile_bundle`` resets at the
    START of every compile, so the CLI path was always safe; a DIRECT
    ``compile_registered`` caller has no such protection, and since a
    blueprint-less compile reaches none of a previous compile's declarations it
    would report every one of them as dead -- against a file its own bundle does
    not contain. Draining here means no future direct caller has to remember.
    """
    try:
        return [ref for ref in _DECLARATIONS if not ref.declared_in_body]
    finally:
        _DECLARATIONS.clear()


@contextlib.contextmanager
def collecting_inputs() -> Generator[_InputCollector]:
    collector = _InputCollector()
    _COLLECTOR.append(collector)
    try:
        yield collector
    finally:
        _COLLECTOR.pop()


def bp_input(
    name: str,
    *,
    selector: dict[str, Any],
    default: Any = UNSET,
    description: str | None = None,
) -> InputRef:
    """Declare a blueprint input and return its placeholder (§8.2).

    Legal both inside a ``@blueprint`` body and at module scope. The two sites
    differ in exactly one way, and it is not the declaration: a body-scoped
    declaration is a member of that body's blueprint by the act of declaring,
    while a module-scope one joins the schema of every blueprint that
    REFERENCES it (and of no other). Either way the emitted ``input:`` block is
    ordered by declaration sequence, so where a ref is used never moves the
    form the HA UI shows.
    """
    span = capture_span(depth=0)
    ref = InputRef(
        name,
        selector=selector,
        default=default,
        description=description,
        span=span,
        sequence=len(_DECLARATIONS),
        in_body=bool(_COLLECTOR),
    )
    _DECLARATIONS.append(ref)
    if _COLLECTOR:
        _COLLECTOR[-1].declare(ref)
    return ref


# --- the emitter ------------------------------------------------------------


class _BlueprintDumper(yaml.SafeDumper):
    """SafeDumper plus HA's ``!input`` tag and a fixed block-scalar policy."""

    def choose_scalar_style(self) -> str:
        """Force PLAIN style for ``!input`` scalars.

        PyYAML only allows plain style when a scalar's tag is the one the
        resolver would have inferred. ``!input`` never is, so the stock emitter
        falls through to single quotes and writes ``!input 'room_light'`` —
        legal YAML, but not the form HA's own blueprints use, and a gratuitous
        diff against every hand-written blueprint. The style choice is the only
        thing overridden; the analysis super() performs is left intact.
        """
        style = super().choose_scalar_style()
        event = self.event
        if event is not None and getattr(event, "tag", None) == "!input":
            return ""
        return style

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        """Indent block sequences under their key.

        PyYAML writes a sequence flush with its parent key by default. HA reads
        both, but every hand-written blueprint (and HA's own docs) indents, and
        a compiled artifact that diffs noisily against the hand-written one it
        replaces is a bad first impression for a DSL-authored blueprint. Cosmetic only, and
        applied unconditionally, so it costs nothing in determinism.
        """
        super().increase_indent(flow, False)


def _scalar(
    dumper: yaml.SafeDumper, tag: str, value: str, style: str | None = None
) -> yaml.ScalarNode:
    """``represent_scalar`` with a typed seam (PyYAML ships no precise stubs)."""
    return dumper.represent_scalar(tag, value, style=style)  # pyright: ignore[reportUnknownMemberType]


def _represent_input(dumper: yaml.SafeDumper, data: InputRef) -> yaml.ScalarNode:
    # style="" forces PLAIN style. Without it PyYAML single-quotes the scalar,
    # because the value's implicit resolved tag differs from the explicit one --
    # and `!input 'room_light'` is not the form HA's own blueprints use.
    return _scalar(dumper, "!input", data.input_name, style="")


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    # §8.6 rule 7: multi-line strings (Jinja bodies, mostly) as block scalars,
    # so their bytes never depend on escape-quoting choices.
    if "\n" in data:
        return _scalar(dumper, "tag:yaml.org,2002:str", data, style="|")
    return _scalar(dumper, "tag:yaml.org,2002:str", data)


_BlueprintDumper.add_representer(InputRef, _represent_input)  # type: ignore[arg-type]
_BlueprintDumper.add_representer(str, _represent_str)  # type: ignore[arg-type]


def _iter_strings(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():  # type: ignore[misc]
            yield from _iter_strings(key)
            yield from _iter_strings(value)
    elif isinstance(node, list):
        for item in node:  # type: ignore[misc]
            yield from _iter_strings(item)


def check_no_embedded_refs(node: Any, span: SourceSpan | None) -> None:
    """Raise if any ref was interpolated into a longer string (§8.3)."""
    for text in _iter_strings(node):
        if isinstance(text, InputRef) or _MARK not in text:
            continue
        name = text.split(_MARK)[1] if text.count(_MARK) >= 2 else "?"
        raise BlueprintInputInTemplateError(name, span)


def resolve_inputs(
    *, declared_in_body: list[InputRef], body: Any, identity: str
) -> dict[str, InputRef]:
    """One blueprint's ``input:`` block: used declarations, in sequence order (§8.2).

    **Use determines membership.** A declaration belongs to this blueprint if a
    ref to it survives anywhere in the compiled body -- the same
    :func:`_iter_strings` walk §8.3's template check runs, asked a different
    question. There is deliberately no second traversal: whatever the recorder
    can put a ref into, both checks see, and they cannot drift apart.

    **Declaration determines order.** The result is sorted by global sequence
    number, not by where each ref first appears. First-use order would mean
    moving a service call reorders the form Home Assistant renders for every
    user of the blueprint -- a real, user-visible surface changing for a reason
    that is invisible in the diff.

    ``declared_in_body`` seeds the set because declaring inside a body is also
    using (§8.2): a body may legitimately declare an input it does not yet
    reference, and that is also what keeps every pre-existing bundle emitting
    byte-identical YAML (in-body declaration order IS sequence order).

    Must run BEFORE §8.5's optional-entity templating, which rewrites some refs
    out of the tree and into a variable binding -- they are used either way.
    """
    found: dict[int, InputRef] = {ref.sequence: ref for ref in declared_in_body}
    for text in _iter_strings(body):
        if isinstance(text, InputRef):
            found[text.sequence] = text

    resolved: dict[str, InputRef] = {}
    for sequence in sorted(found):
        ref = found[sequence]
        collision = resolved.get(ref.input_name)
        if collision is not None:
            raise DuplicateBlueprintInputError(
                ref.input_name, identity, collision.declaration_span, ref.declaration_span
            )
        resolved[ref.input_name] = ref
    return resolved


# --- §8.5: the structural guarantee -----------------------------------------
#
# The emitter distinguishes four cases, and between them they leave no code
# path that writes a literal empty entity id -- which is what "unwritable"
# means for the field 400 of §0.

#: The key an entity id lands under, in a trigger, a condition or a service
#: target alike (`target: {entity_id: ...}` and a bare `entity_id:` both).
_ENTITY_KEY: Final = "entity_id"


def _is_optional_entity(value: Any) -> bool:
    return isinstance(value, InputRef) and value.is_entity_selector and not value.is_required


def reject_optional_entity_triggers(node: Any, span: SourceSpan | None) -> None:
    """Raise if an optional entity input is a trigger's ``entity_id`` (§8.5).

    There is no templated escape here the way there is for a service target:
    HA does not template trigger entity ids, so the only fixes are the two the
    error names.
    """
    if isinstance(node, dict):
        typed = cast("dict[str, Any]", node)
        for key, value in typed.items():
            if key == _ENTITY_KEY:
                candidates: list[Any] = (
                    cast("list[Any]", value) if isinstance(value, list) else [value]
                )
                for candidate in candidates:
                    if _is_optional_entity(candidate):
                        raise OptionalEntityInputAsTriggerError(
                            cast("InputRef", candidate).input_name, span
                        )
            reject_optional_entity_triggers(value, span)
    elif isinstance(node, list):
        for item in cast("list[Any]", node):
            reject_optional_entity_triggers(item, span)


def _template_entity_value(value: Any, bindings: dict[str, InputRef]) -> Any:
    if _is_optional_entity(value):
        ref = cast("InputRef", value)
        bindings[ref.input_name] = ref
        return f"{{{{ {ref.input_name} }}}}"
    if isinstance(value, list):
        return [_template_entity_value(item, bindings) for item in cast("list[Any]", value)]
    return value


def template_optional_entity_targets(node: Any, bindings: dict[str, InputRef]) -> Any:
    """Rewrite optional entity inputs used as targets into the templated form.

    This IS §6.3's prescribed fix, applied automatically and unconditionally: a
    template is opaque to HA's static validation, so the empty case passes
    schema and resolves to "no targets" at run time.
    """
    if isinstance(node, dict):
        typed = cast("dict[str, Any]", node)
        return {
            key: (
                _template_entity_value(value, bindings)
                if key == _ENTITY_KEY
                else template_optional_entity_targets(value, bindings)
            )
            for key, value in typed.items()
        }
    if isinstance(node, list):
        return [
            template_optional_entity_targets(item, bindings) for item in cast("list[Any]", node)
        ]
    return node


#: §8.6 rule 5 -- body sections in canonical HA order.
_SECTION_ORDER: Final = ("variables", "triggers", "conditions", "actions", "mode", "max")

_HEADER: Final = (
    "# Compiled from Python by Hassle. Do not edit -- edit the source and recompile.\n"
    "# Source: {source_file}\n"
)


def emit_blueprint_yaml(
    *,
    name: str,
    description: str | None,
    domain: str,
    inputs: dict[str, InputRef],
    body: dict[str, Any],
    source_file: str,
) -> str:
    """Render a blueprint document deterministically (§8.6).

    Every degree of freedom a YAML emitter has is pinned here rather than left
    to PyYAML's defaults: key order is insertion order (``sort_keys=False``,
    with the orders built below), block style throughout, and an effectively
    infinite line width so a long template never soft-wraps -- wrapping is the
    subtlest byte-instability available, because it depends on content length
    and so changes under edits far away from the wrap.
    """
    metadata: dict[str, Any] = {"name": name}
    if description is not None:
        metadata["description"] = description
    metadata["domain"] = domain
    metadata["input"] = {n: ref.spec() for n, ref in inputs.items()}

    document: dict[str, Any] = {"blueprint": metadata}
    for section in _SECTION_ORDER:
        value = body.get(section)
        if value is None or (isinstance(value, (list, dict)) and not value):
            continue
        document[section] = value

    rendered = yaml.dump(
        document,
        Dumper=_BlueprintDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=1 << 30,
        indent=2,
    )
    text = _HEADER.format(source_file=source_file) + rendered
    # §8.6 rule 8: LF, no trailing whitespace, exactly one trailing newline.
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).rstrip("\n") + "\n"


# --- the decorator ----------------------------------------------------------


def blueprint(
    *,
    domain: str,
    path: str,
    name: str,
    description: str | None = None,
    triggers: Sequence[TriggerBuilder] | None = None,
    **options: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare a blueprint whose body is the recorder DSL (§8.1).

    ``domain``/``path`` are the object kind's identity, verbatim: ``path`` is exactly
    the string instances put in ``use_blueprint``, so the object key this
    compiles to (``blueprint:<domain>/<path>``) is the one every object-layer
    consumer already looks up. Remaining ``**options`` are the automation
    options the blueprint body carries (``mode``, ``max``).

    ``triggers=`` (§8.11) is ``@automation``'s, with the same semantics and the
    same precedence: a sequence of ``TriggerBuilder`` objects -- the same objects
    ``when()`` accepts -- built at DECORATION time and recorded before the body
    runs, so they land first and any ``when()``/``raw_trigger`` calls inside the
    body append after them in call order. Compile parity with the ``when()``
    form is exact.

    A trigger declared by a call inside the body is metadata masquerading as
    step zero: an action call corresponds 1:1 to a runtime step, a trigger call
    corresponds to nothing in the sequence. ``@blueprint`` lacked ``triggers=``
    only because ``bp_input`` used to be body-scoped, which left a
    decoration-time trigger with no way to name an input. Module-scope
    declarations (§8.2) removed that constraint; a decorator trigger may now
    reference an ``InputRef`` freely, and the emitter's existing sentinel walk
    converts it to an ``!input`` node in trigger position exactly as it does in
    the body.

    The undecorated function is returned unchanged, exactly as ``@automation``
    does, so a bundle can still call it.
    """
    span = capture_span(depth=0)

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        from hassle.compiler.registry import register_blueprint

        register_blueprint(
            func=func,
            domain=domain,
            path=path,
            name=name,
            description=description,
            options=dict(options),
            span=span,
            triggers=triggers,
        )
        return func

    return decorate
