"""``@blueprint`` / ``bp_input`` -- blueprints AUTHORED IN THE DSL
(docs/internals/blueprints-design.md §8).

Stage 1 made a blueprint FILE a managed object. Stage 2 makes the file itself a
compiled artifact: the body is recorded by the same recorder ``@automation``
uses, declared inputs become ``!input`` nodes, and the emitted YAML is
deterministic (§8.6) so stage 1's object machinery can push it unchanged. No
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
from collections.abc import Callable, Generator, Iterator
from typing import Any, Final, cast

import yaml

from hassle.compiler.errors import CompileError
from hassle.compiler.spans import SourceSpan, capture_span

# A marker no real config string can contain (NUL is illegal in YAML plain
# scalars and in HA entity ids alike), carrying the input name so an embedded
# ref can still be NAMED in the error it causes.
_MARK: Final = "\x00hassle-blueprint-input\x00"


class UnsetType:
    """The 'no default declared' sentinel.

    Not ``None``: ``None`` is a legitimate YAML default, and stage 1 already
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

    __slots__ = ("_bp_name", "_default", "_description", "_selector", "_span")

    _bp_name: str
    _selector: dict[str, Any]
    _default: Any
    _description: str | None
    _span: SourceSpan | None

    def __new__(
        cls,
        name: str,
        *,
        selector: dict[str, Any],
        default: Any = UNSET,
        description: str | None = None,
        span: SourceSpan | None = None,
    ) -> InputRef:
        self = super().__new__(cls, f"{_MARK}{name}{_MARK}")
        self._bp_name = name
        self._selector = selector
        self._default = default
        self._description = description
        self._span = span
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


class BlueprintInputOutsideBodyError(CompileError):
    """``bp_input`` was called outside a ``@blueprint`` body."""

    def __init__(self, name: str, span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"`bp_input({name!r})`{where} was called outside a `@blueprint` body. An "
            f"input only means something to the blueprint that declares it, so there is "
            f"nowhere to record this one. Fix: move the call inside a function decorated "
            f"with `@blueprint(...)`, or use a plain Python value if you meant a constant "
            f"shared by the bundle."
        )


class DuplicateBlueprintInputError(CompileError):
    """Two ``bp_input`` calls in one blueprint declared the same name."""

    def __init__(self, name: str, span: SourceSpan | None) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"The blueprint input `{name}` is declared twice{where}. HA's "
            f"`blueprint.input` block is a mapping, so the second declaration would "
            f"silently replace the first along with its selector and default. Fix: give "
            f"this input a different name, or reuse the `InputRef` the first "
            f"`bp_input({name!r})` call returned."
        )


# --- declaration context ----------------------------------------------------


class _InputCollector:
    """Collects one blueprint body's inputs, in declaration order (§8.6 rule 3)."""

    def __init__(self) -> None:
        self.declared: dict[str, InputRef] = {}

    def declare(self, ref: InputRef, span: SourceSpan | None) -> None:
        if ref.input_name in self.declared:
            raise DuplicateBlueprintInputError(ref.input_name, span)
        self.declared[ref.input_name] = ref


_COLLECTOR: list[_InputCollector] = []


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
    """Declare a blueprint input and return its placeholder (§8.2)."""
    span = capture_span(depth=0)
    if not _COLLECTOR:
        raise BlueprintInputOutsideBodyError(name, span)
    ref = InputRef(name, selector=selector, default=default, description=description, span=span)
    _COLLECTOR[-1].declare(ref, span)
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
        replaces is a bad first impression for stage 2. Cosmetic only, and
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
    **options: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare a blueprint whose body is the recorder DSL (§8.1).

    ``domain``/``path`` are stage 1's identity, verbatim: ``path`` is exactly
    the string instances put in ``use_blueprint``, so the object key this
    compiles to (``blueprint:<domain>/<path>``) is the one every stage-1
    consumer already looks up. Remaining ``**options`` are the automation
    options the blueprint body carries (``mode``, ``max``).

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
        )
        return func

    return decorate
