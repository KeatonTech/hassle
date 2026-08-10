"""Blueprint sources: parsing, ``!input`` substitution, expansion.

**Core, not testing** (docs/internals/blueprints-design.md §1). This module
started life as ``hassle.testing.blueprints``, serving only the simulator;
stage 1 of the blueprints design makes a blueprint *file* a managed object, so
three more callers need the very same parse/expand logic and none of them may
import a testing module (`tests/test_package_layering.py` pins the direction):

- the **validator** (:mod:`hassle.registry.validate`, §6) checks each
  ``@blueprint_automation``'s inputs against the blueprint's declared
  ``blueprint.input`` block;
- the **compiler** (:mod:`hassle.compiler.bundle`) discovers blueprint files
  and registers one ``BlueprintConfig`` IR object per file (§1);
- **``FakeBackend.blueprint_substitute``** (§2/§7) answers HA's
  ``blueprint/substitute`` command by expanding its own stored YAML — ONE
  expansion implementation everywhere, which is what makes the
  substitute-compare drift oracle (§2.2) a real comparison of two independently
  stored copies rather than a circular one.

``hassle.testing.blueprints`` remains as a pure re-export of everything here,
so every existing importer (bundles' own tests included) keeps working — the
frozen surfaces are additive-only (CONTRIBUTING R5).

A ``@blueprint_automation`` (DESIGN §5.8) compiles to only
``{"use_blueprint": {"path": ..., "input": {...}}}`` — no triggers, no
conditions, no actions — because HA applies the blueprint at runtime. That
makes the object *inert* to the simulator (DESIGN §10.1 executes
triggers/actions), so nothing a bundle routes through a blueprint could be
tested. This module supplies the missing half: it turns the stored
``use_blueprint`` reference back into the concrete automation config HA would
run, which :class:`~hassle.testing.Simulator` then simulates like any other
automation.

**Where blueprints live.** A blueprint source is a *bundle-local file* at
``<bundle>/blueprints/automation/<use_blueprint path>`` — so
``use_blueprint="local/room-switch-controls.yaml"`` reads
``<bundle>/blueprints/automation/local/room-switch-controls.yaml``. That
mirrors HA's own ``config/blueprints/automation/`` layout, so a bundle-authored
blueprint sits in the same relative place on both sides.

**Why local and offline.** Unit tests never touch the network (CONTRIBUTING
R2), and a bundle's tests must be deterministic: fetching a community
blueprint from GitHub at test time would be neither. A blueprint whose file is
NOT in the bundle (an imported community blueprint that only exists inside HA)
is therefore not expanded at all — the automation stays exactly as inert as it
was before this module existed, which is a behavior-preserving default rather
than a guess at what the remote blueprint does.

**Semantics** mirror ``homeassistant/components/blueprint``: parse the YAML
including the ``!input`` custom tag, validate the instance's supplied inputs
against the blueprint's ``blueprint.input`` metadata (a missing *required*
input is an error; an absent *optional* one takes its declared ``default``),
substitute every ``!input`` node by a straight recursive tree-walk, and emit
the blueprint's own body (triggers/conditions/actions/mode/…) with the
instance's own top-level fields carried over.

Nothing here touches the IR: expansion reads ``to_ha()`` output and returns a
fresh dict, so the payload sync/push builds is byte-identical with or without
a blueprint file present.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from hassle.ir import normalize_ha

#: The bundle-relative root holding every blueprint source, mirroring HA's own
#: ``config/blueprints/``.
BLUEPRINT_ROOT: str = "blueprints"

#: HA's blueprint domains — the ``<domain>`` segment of a
#: ``blueprint:<domain>/<path>`` object key (blueprints-design §1). HA itself
#: ships exactly these two blueprint domains; a bundle directory under
#: ``blueprints/`` naming anything else is not a blueprint tree and is ignored
#: by discovery rather than guessed at.
BLUEPRINT_DOMAINS: tuple[str, ...] = ("automation", "script")

#: The default domain, and the only one ``@blueprint_automation`` can produce
#: an instance of. Every per-domain entry point below defaults to it, which is
#: what keeps this module's pre-promotion surface byte-identical.
DEFAULT_BLUEPRINT_DOMAIN: str = "automation"


def blueprint_subdir(domain: str = DEFAULT_BLUEPRINT_DOMAIN) -> tuple[str, ...]:
    """Bundle-relative directory holding ``domain``'s blueprint sources, as
    path segments — ``("blueprints", "automation")``.

    Mirrors HA's ``config/blueprints/<domain>/``; a ``use_blueprint`` path is
    appended verbatim underneath it. Generalizing the old ``BLUEPRINT_SUBDIR``
    constant (which pinned ``automation``) to a per-domain function is
    blueprints-design §1's "additive" generalization: the constant keeps its
    exact old value and every caller that doesn't pass a domain behaves
    identically.
    """
    return (BLUEPRINT_ROOT, domain)


#: Bundle-relative directory holding AUTOMATION blueprint sources, as path
#: segments. Retained at its exact pre-promotion value; prefer
#: :func:`blueprint_subdir` in new code, which takes the domain.
BLUEPRINT_SUBDIR: tuple[str, ...] = blueprint_subdir(DEFAULT_BLUEPRINT_DOMAIN)

#: Instance top-level fields that survive expansion, overriding anything the
#: blueprint body declares under the same name. HA keeps the automation's own
#: identity/labelling rather than the blueprint's.
_CARRIED_FIELDS: tuple[str, ...] = ("id", "alias", "description")


class BlueprintError(Exception):
    """Base class for every blueprint-expansion failure (all snapshot-tested)."""


class InvalidBlueprintError(BlueprintError):
    """A blueprint file exists but is not a usable automation blueprint."""

    def __init__(self, display_path: str, reason: str, *, where: str | None = None) -> None:
        self.display_path = display_path
        self.reason = reason
        location = f" (used by the automation declared at {where})" if where else ""
        super().__init__(
            f"The blueprint `{display_path}`{location} could not be read: {reason}. The "
            f"simulator expands a `use_blueprint` automation against that file, so it must "
            f"be a valid automation blueprint -- a YAML mapping with a top-level "
            f"`blueprint:` block (holding `name:` and an `input:` map) alongside the "
            f"automation body (`triggers:`/`actions:`/...). Fix: correct the file, or "
            f"remove it from the bundle to leave the automation unsimulated (an "
            f"automation whose blueprint file is absent is simply not expanded)."
        )


class MissingBlueprintInputError(BlueprintError):
    """A blueprint instance omitted an input the blueprint requires."""

    def __init__(
        self,
        display_path: str,
        input_name: str,
        *,
        supplied: list[str],
        where: str | None = None,
    ) -> None:
        self.display_path = display_path
        self.input_name = input_name
        self.supplied = supplied
        location = where or "this bundle"
        supplied_text = ", ".join(f"`{name}`" for name in supplied) if supplied else "none"
        super().__init__(
            f"The blueprint automation declared at {location} does not supply the input "
            f"`{input_name}`, which `{display_path}` declares with no `default:` and "
            f"therefore requires (inputs supplied: {supplied_text}). Real Home Assistant "
            f"rejects the automation the same way, so the simulator will not guess a "
            f'value. Fix: add `"{input_name}": ...` to that automation\'s `inputs=` dict, '
            f"or give `{input_name}` a `default:` in the blueprint's `blueprint.input` "
            f"block."
        )


@dataclass(frozen=True)
class BlueprintInput:
    """One declared ``blueprint.input`` entry: its name and optional default."""

    name: str
    has_default: bool
    default: Any = None


@dataclass(frozen=True)
class Blueprint:
    """A parsed automation blueprint: its declared inputs plus its body."""

    #: Bundle-relative display path (POSIX), for error messages.
    display_path: str
    #: Declared inputs, in declaration order.
    inputs: dict[str, BlueprintInput]
    #: The automation body, `blueprint:` block removed, `!input` nodes intact.
    body: dict[str, Any]
    #: The ``blueprint.input`` block exactly as written — every entry's full
    #: metadata mapping, or ``None`` for a bare ``room_key:`` with none at all.
    #: This is what rides in the IR body (`BlueprintConfig.inputs`) and what
    #: §6's rules read: `inputs` above answers "required or defaulted", while
    #: this answers "and what selector was it declared with".
    raw_inputs: dict[str, Any] = field(default_factory=lambda: cast("dict[str, Any]", {}))

    def resolve_inputs(
        self, supplied: dict[str, Any], *, where: str | None = None
    ) -> dict[str, Any]:
        """Every declared input's effective value (supplied, else its ``default``).

        Raises :class:`MissingBlueprintInputError` for a declared input that
        has no ``default:`` and was not supplied. Inputs the blueprint does
        not declare are ignored rather than rejected — HA's own validation is
        stricter, but the simulator's job here is to run what the bundle
        stored, not to re-validate it.
        """
        resolved: dict[str, Any] = {}
        for name, spec in self.inputs.items():
            if name in supplied:
                resolved[name] = supplied[name]
            elif spec.has_default:
                resolved[name] = spec.default
            else:
                raise MissingBlueprintInputError(
                    self.display_path, name, supplied=sorted(supplied), where=where
                )
        return resolved

    def expand(self, supplied: dict[str, Any], *, where: str | None = None) -> dict[str, Any]:
        """Substitute ``supplied`` (plus defaults) into the body, canonicalized.

        The result runs through ``normalize_ha`` so a blueprint authored in
        HA's legacy singular shape (``trigger:``/``action:`` blocks,
        ``service:`` verbs) reaches the simulator engine in the same canonical
        plural schema every other compiled automation uses.
        """
        values = self.resolve_inputs(supplied, where=where)
        substituted = cast(
            "dict[str, Any]", _substitute(self.body, values, self.display_path, where)
        )
        return normalize_ha(substituted, kind="automation")


class _InputRef:
    """A parsed ``!input <name>`` node, replaced during substitution."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"!input {self.name}"


class _BlueprintLoader(yaml.SafeLoader):
    """``SafeLoader`` plus HA's ``!input`` tag. Safe-by-construction: no other
    custom tag is registered, so a blueprint file can never construct an
    arbitrary Python object."""


def _construct_input(loader: yaml.SafeLoader, node: yaml.Node) -> _InputRef:
    return _InputRef(str(loader.construct_scalar(node)))  # type: ignore[arg-type]


_BlueprintLoader.add_constructor("!input", _construct_input)


def _substitute(node: Any, values: dict[str, Any], display_path: str, where: str | None) -> Any:
    """Replace every :class:`_InputRef` in ``node`` with its resolved value.

    A straight recursive tree-walk, exactly like HA's own
    ``homeassistant/util/yaml/input.py::substitute`` — no templating, no
    string interpolation, no type coercion. Each substituted value is
    deep-copied so two instances of the same blueprint never share mutable
    structure. An ``!input`` naming something the ``blueprint.input`` block
    never declared is a bug in the blueprint file, not a missing instance
    input, so it surfaces as :class:`InvalidBlueprintError`.
    """
    if isinstance(node, _InputRef):
        if node.name not in values:
            raise InvalidBlueprintError(
                display_path,
                f"its body references `!input {node.name}`, which its `blueprint.input` "
                f"block does not declare",
                where=where,
            )
        return copy.deepcopy(values[node.name])
    if isinstance(node, dict):
        typed_dict = cast("dict[Any, Any]", node)
        return {
            key: _substitute(value, values, display_path, where)
            for key, value in typed_dict.items()
        }
    if isinstance(node, list):
        typed_list = cast("list[Any]", node)
        return [_substitute(item, values, display_path, where) for item in typed_list]
    return node


def blueprint_file(
    bundle_root: Path,
    use_blueprint_path: str,
    *,
    domain: str = DEFAULT_BLUEPRINT_DOMAIN,
) -> Path:
    """The bundle-local file a ``use_blueprint`` path names.

    ``"local/room-switch-controls.yaml"`` ->
    ``<bundle_root>/blueprints/automation/local/room-switch-controls.yaml``.

    ``domain`` is additive and defaults to ``"automation"``, so every
    pre-promotion caller resolves the identical path.
    """
    return bundle_root.joinpath(*blueprint_subdir(domain), use_blueprint_path)


def blueprint_display_path(
    use_blueprint_path: str, *, domain: str = DEFAULT_BLUEPRINT_DOMAIN
) -> str:
    """The bundle-relative path shown in error messages (snapshot-stable —
    never an absolute checkout path)."""
    return "/".join((*blueprint_subdir(domain), use_blueprint_path))


def read_blueprint_source(path: Path) -> str:
    """One blueprint file's text, **byte-preserved**.

    Decoded from bytes rather than read in text mode on purpose: text mode
    applies universal-newline translation, so a CRLF-authored blueprint would
    silently become LF on the way to `blueprint/save` — and HA stores the
    document exactly as handed (blueprints-design §1, "byte-preserved").
    """
    return path.read_bytes().decode("utf-8")


def load_blueprint(path: Path, *, display_path: str, where: str | None = None) -> Blueprint:
    """Parse one automation blueprint file (``!input`` tag included).

    Raises :class:`InvalidBlueprintError` for unparseable YAML, a non-mapping
    document, or a document with no top-level ``blueprint:`` block.
    """
    try:
        source = read_blueprint_source(path)
    except OSError as exc:  # pragma: no cover - defensive
        raise InvalidBlueprintError(
            display_path, f"it could not be read ({exc})", where=where
        ) from exc
    return parse_blueprint(source, display_path=display_path, where=where)


def parse_blueprint(source: str, *, display_path: str, where: str | None = None) -> Blueprint:
    """Parse blueprint YAML **text** (``!input`` tag included).

    The text-shaped sibling of :func:`load_blueprint`, for the two callers that
    hold a document rather than a file: the IR body builder
    (:func:`blueprint_body`) and ``FakeBackend.blueprint_substitute``, which
    expands its own stored YAML (blueprints-design §7 — one expansion
    implementation everywhere).
    """
    try:
        raw: Any = yaml.load(source, Loader=_BlueprintLoader)
    except yaml.YAMLError as exc:
        detail = str(exc).strip().splitlines()[0] if str(exc).strip() else "invalid YAML"
        raise InvalidBlueprintError(
            display_path, f"its YAML is invalid ({detail})", where=where
        ) from exc
    if not isinstance(raw, dict):
        raise InvalidBlueprintError(
            display_path, "its top level is not a YAML mapping", where=where
        )
    document = cast("dict[str, Any]", raw)
    metadata = document.get("blueprint")
    if not isinstance(metadata, dict):
        raise InvalidBlueprintError(
            display_path, "it has no top-level `blueprint:` mapping", where=where
        )
    typed_metadata = cast("dict[str, Any]", metadata)
    raw_input_block = typed_metadata.get("input")
    inputs = _parse_inputs(raw_input_block)
    raw_inputs: dict[str, Any] = (
        {str(name): spec for name, spec in cast("dict[Any, Any]", raw_input_block).items()}
        if isinstance(raw_input_block, dict)
        else {}
    )
    body = {key: value for key, value in document.items() if key != "blueprint"}
    return Blueprint(display_path=display_path, inputs=inputs, body=body, raw_inputs=raw_inputs)


def blueprint_body(*, domain: str, path: str, source: str) -> dict[str, Any]:
    """The IR body for one blueprint source file (blueprints-design §1).

    ``{"domain", "path", "source", "inputs"}`` — see
    :class:`hassle.ir.models.BlueprintConfig` for what each half is and why.
    ``source`` rides through **verbatim**; ``inputs`` is the parsed
    ``blueprint.input`` block, also verbatim (a bare ``room_key:`` stays
    ``None``, which is what keeps "required" distinguishable from "declared
    with an empty metadata mapping").

    Raises :class:`InvalidBlueprintError` if the document is not a usable
    blueprint — a bundle cannot manage a file HA would reject.
    """
    parsed = parse_blueprint(source, display_path=blueprint_display_path(path, domain=domain))
    return {
        "domain": domain,
        "path": path,
        "source": source,
        "inputs": parsed.raw_inputs,
    }


def blueprint_metadata(source: str, *, display_path: str = "<blueprint>") -> dict[str, Any]:
    """A blueprint document's own top-level ``blueprint:`` block.

    This is exactly what HA's ``blueprint/list`` returns per entry
    (blueprints-design §2: "metadata only — name, inputs, source_url; no
    source text"), so both backends build their remote bodies from it and the
    two shapes cannot drift apart.
    """
    parsed: Any = yaml.load(source, Loader=_BlueprintLoader)
    if not isinstance(parsed, dict):  # pragma: no cover - defensive
        raise InvalidBlueprintError(display_path, "its top level is not a YAML mapping")
    metadata = cast("dict[str, Any]", parsed).get("blueprint")
    if not isinstance(metadata, dict):  # pragma: no cover - defensive
        raise InvalidBlueprintError(display_path, "it has no top-level `blueprint:` mapping")
    return cast("dict[str, Any]", metadata)


def blueprint_remote_body(domain: str, path: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """The body a backend's ``list_remote("blueprint")`` returns for one entry.

    **There is deliberately no ``source`` key**, in either backend
    (blueprints-design §2.1): HA has no command that serves a blueprint's
    source back, so a remote blueprint body physically cannot carry one. That
    absence is a contract, not an omission — it is what makes this kind
    push-authoritative, and what §3's plan table is built around. A consumer
    telling a local body from a remote one asks exactly this: does it have a
    ``source``?
    """
    return {"domain": domain, "path": path, "metadata": metadata}


def blueprint_key_for_use_path(
    use_blueprint_path: str, *, domain: str = DEFAULT_BLUEPRINT_DOMAIN
) -> str:
    """The object key of the blueprint an instance's ``use_blueprint`` names.

    No transformation at all — ``<path>`` IS the identity's second segment
    (blueprints-design §1), which is exactly why the key format was chosen that
    way. Works whether or not the bundle actually has the file: a community
    blueprint that lives only in HA still has a derivable key, which is what
    lets §6's rule 2 name the file that would make it managed.
    """
    return f"blueprint:{domain}/{use_blueprint_path}"


def instances_by_blueprint(bodies: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Blueprint object key -> the object keys instantiating it.

    ``bodies`` is ``object_key -> to_ha() body`` for the bundle's compiled
    objects; anything without a ``use_blueprint`` reference is ignored. The
    instance lists are sorted, so every consumer sees the same deterministic
    order (R8).

    Three callers need this exact map and it must be one function, because a
    disagreement between them would be a silent correctness bug rather than a
    visible one: apply refuses a plan deleting a blueprint that still has
    instances and gates its post-update ``automation.reload`` on the same map
    (§4), the drift oracle picks an instance to substitute with (§3), and the
    validator checks each instance's inputs (§6).
    """
    found: dict[str, list[str]] = {}
    for object_key, body in bodies.items():
        reference = body.get("use_blueprint")
        if not isinstance(reference, dict):
            continue
        path = cast("dict[str, Any]", reference).get("path")
        if not isinstance(path, str) or not path:
            continue
        found.setdefault(blueprint_key_for_use_path(path), []).append(object_key)
    return {key: sorted(instances) for key, instances in sorted(found.items())}


def instance_inputs(body: dict[str, Any]) -> dict[str, Any]:
    """One instance's supplied ``use_blueprint.input`` mapping (never ``None``)."""
    reference = body.get("use_blueprint")
    if not isinstance(reference, dict):
        return {}
    supplied = cast("dict[str, Any]", reference).get("input")
    return dict(cast("dict[str, Any]", supplied)) if isinstance(supplied, dict) else {}


def split_blueprint_identity(identity: str) -> tuple[str, str]:
    """``"automation/local/x.yaml"`` -> ``("automation", "local/x.yaml")``.

    Splits on the **first** slash only: ``<path>`` routinely contains more of
    them, and it must come back out exactly as the instance wrote it.
    """
    domain, _, path = identity.partition("/")
    return domain, path


#: File extensions discovery treats as blueprint documents. Anything else
#: under ``blueprints/<domain>/`` (a README, a LICENSE, an editor swapfile) is
#: somebody's own file, not a blueprint to try to parse.
BLUEPRINT_SUFFIXES: tuple[str, ...] = (".yaml", ".yml")


@dataclass(frozen=True)
class DiscoveredBlueprint:
    """One blueprint file found in a bundle (`discover_blueprints`)."""

    #: HA's blueprint domain — the object key's ``<domain>`` segment.
    domain: str
    #: Exactly the string an instance puts in ``use_blueprint`` — the object
    #: key's ``<path>`` segment. POSIX separators on every platform.
    path: str
    #: Bundle-relative POSIX path of the file itself, ``blueprints/<domain>/<path>``.
    source_path: str
    #: The IR body (:func:`blueprint_body`).
    body: dict[str, Any]


def discover_blueprints(bundle_root: Path) -> list[DiscoveredBlueprint]:
    """Every blueprint source file in ``bundle_root``, in deterministic order.

    Scans ``blueprints/<domain>/`` for each domain in
    :data:`BLUEPRINT_DOMAINS` — HA ships exactly those two, and a directory
    under ``blueprints/`` naming anything else is somebody's own directory, not
    a blueprint tree to guess at.

    **Symlinks are skipped**, files and directories alike: the same sandbox
    rule the bundle module walk and :func:`expand_blueprint` apply, so a
    compile can never be made to read outside the bundle (DESIGN §14).

    A discovered file that is not a usable blueprint raises
    :class:`InvalidBlueprintError` rather than being skipped. A file living
    under ``blueprints/<domain>/`` is one the bundle means to manage, and HA
    would reject it at push time with an opaque 400 — surfacing it at compile
    time is exactly blueprints-design §0's third failure mode being closed.
    """
    found: list[DiscoveredBlueprint] = []
    for domain in BLUEPRINT_DOMAINS:
        domain_root = bundle_root.joinpath(*blueprint_subdir(domain))
        if domain_root.is_symlink() or not domain_root.is_dir():
            continue
        for file in sorted(domain_root.rglob("*")):
            if file.suffix not in BLUEPRINT_SUFFIXES:
                continue
            # `is_file()` follows symlinks, so the explicit check has to come
            # first -- and any symlinked PARENT directory is excluded the same
            # way (a link cannot smuggle a tree in either).
            if not file.is_file() or _has_symlink_component(file, domain_root):
                continue
            relative = file.relative_to(domain_root).as_posix()
            found.append(
                DiscoveredBlueprint(
                    domain=domain,
                    path=relative,
                    source_path="/".join((*blueprint_subdir(domain), relative)),
                    body=blueprint_body(
                        domain=domain, path=relative, source=read_blueprint_source(file)
                    ),
                )
            )
    return found


def _has_symlink_component(file: Path, stop_at: Path) -> bool:
    """True if ``file`` or any directory between it and ``stop_at`` is a link."""
    current = file
    while current != stop_at:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:  # pragma: no cover - defensive
            return False
        current = parent
    return False


def _parse_inputs(raw: Any) -> dict[str, BlueprintInput]:
    """The ``blueprint.input`` block -> declared inputs, in declaration order.

    An entry may be a mapping of metadata (``default:`` makes it optional), or
    ``null`` — HA allows a bare ``switch_entity:`` with no metadata at all,
    which is a required input.
    """
    if not isinstance(raw, dict):
        return {}
    typed_raw = cast("dict[str, Any]", raw)
    out: dict[str, BlueprintInput] = {}
    for name, spec in typed_raw.items():
        key = str(name)
        if isinstance(spec, dict):
            typed_spec = cast("dict[str, Any]", spec)
            has_default = "default" in typed_spec
            out[key] = BlueprintInput(key, has_default, typed_spec.get("default"))
        else:
            out[key] = BlueprintInput(key, has_default=False)
    return out


def expand_blueprint(
    body: dict[str, Any],
    *,
    bundle_root: Path | None,
    where: str | None = None,
) -> dict[str, Any] | None:
    """The concrete automation config for ``body``, or ``None`` if there is none.

    ``body`` is an automation's ``to_ha()`` output (never mutated).
    ``None`` — meaning "simulate this automation exactly as before" — is
    returned when the automation carries no ``use_blueprint``, when no bundle
    root is known (a :class:`~hassle.compiler.bundle.CompileResult` built from
    raw IR rather than a bundle directory), or when the referenced blueprint
    file is not in the bundle.

    ``where`` is the instance's declaration site (``file:line``), used only in
    error messages.
    """
    reference = body.get("use_blueprint")
    if not isinstance(reference, dict) or bundle_root is None:
        return None
    typed_reference = cast("dict[str, Any]", reference)
    raw_path = typed_reference.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = blueprint_file(bundle_root, raw_path)
    root = bundle_root.resolve()
    # A `use_blueprint` path comes from the bundle's own source, but the
    # loader still refuses to read outside the bundle -- the same sandbox rule
    # the module importer applies (DESIGN §14 / bundle.py's symlink policy).
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        return None
    display_path = blueprint_display_path(raw_path)
    blueprint = load_blueprint(path, display_path=display_path, where=where)
    supplied_raw = typed_reference.get("input")
    supplied: dict[str, Any] = (
        dict(cast("dict[str, Any]", supplied_raw)) if isinstance(supplied_raw, dict) else {}
    )
    expanded = blueprint.expand(supplied, where=where)
    # The instance's own identity/labelling wins over the blueprint's, and
    # leads the emitted key order (deterministic output, R8).
    carried = {key: body[key] for key in _CARRIED_FIELDS if key in body}
    config: dict[str, Any] = dict(carried)
    for key, value in expanded.items():
        if key not in config:
            config[key] = value
    return config
