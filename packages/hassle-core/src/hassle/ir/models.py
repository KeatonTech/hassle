"""IR pydantic models + parse/serialize -- part of the frozen IR schema.

The IR mirrors Home Assistant's stored config for each managed object kind. Two
hard requirements (DESIGN §7.1) drive the design:

- **Unknown-field preservation** (compile(decompile(x)) must equal x for any
  config): every model allows and preserves extra
  fields at every nesting level (``extra="allow"``), and serialization emits
  exactly the keys that were parsed (``exclude_unset=True``) — no defaults are
  ever materialized into the output, so ``serialize(parse(x)) == x``.
- **Canonical serialization + hashing:** see :mod:`hassle.ir.canonical`.

Structural blocks (``trigger``/``condition``/``action``/``sequence``/``fields``/…)
pass through verbatim as native JSON; the typed compiler that interprets
them is a separate layer. What is frozen here is the object-level model schema,
the identity/key derivation, and the serialization contract.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict, PrivateAttr

from hassle.ir.canonical import canonical_json, sha256_hash
from hassle.ir.keys import (
    BLUEPRINT_KIND,
    DASHBOARD_KIND,
    GROUP_DOMAINS,
    HELPER_DOMAINS,
    TEMPLATE_DOMAINS,
    object_key,
)


class IRObject(BaseModel):
    """Base class for every managed HA object (automation, script, helper)."""

    model_config = ConfigDict(extra="allow")

    # Extrinsic identity: an object_id/id supplied at parse time when it is not
    # part of the config body (e.g. a script's object_id). Never serialized.
    _key_id: str | None = PrivateAttr(default=None)

    def kind(self) -> str:
        """The object kind (``"automation"``, ``"script"``, a helper domain)."""
        raise NotImplementedError

    def attach_key(self, key_id: str) -> None:
        """Attach an extrinsic identity (used by :func:`parse`)."""
        self._key_id = key_id

    @property
    def identity(self) -> str | None:
        """The identity used in the object key (id / object_id)."""
        return self._key_id

    def object_key(self) -> str:
        """``"<kind>:<identity>"`` — the stable manifest/plan key."""
        ident = self.identity
        if ident is None:
            raise ValueError(f"{type(self).__name__} has no identity; pass key_hint= at parse time")
        return object_key(self.kind(), ident)

    def to_ha(self) -> dict[str, Any]:
        """Serialize back to the exact HA config body (lossless)."""
        return self.model_dump(mode="json", exclude_unset=True)

    def canonical_json(self) -> str:
        return canonical_json(self.to_ha())

    def sha256(self) -> str:
        return sha256_hash(self.to_ha())


class AutomationConfig(IRObject):
    """A single automation config (``automations.yaml`` entry, keyed by ``id``)."""

    # `id` is typed Any (not str) so that a non-string id round-trips verbatim
    # rather than raising — compile(decompile(x)) must hold for ANY config.
    # HA stores ids as strings.
    id: Any = None
    alias: Any = None
    description: Any = None
    mode: Any = None
    max: Any = None
    max_exceeded: Any = None
    initial_state: Any = None

    def kind(self) -> str:
        return "automation"

    @property
    def identity(self) -> str | None:
        return self.id if self.id is not None else self._key_id


class ScriptConfig(IRObject):
    """A single script config (``scripts.yaml`` entry, keyed by extrinsic object_id)."""

    alias: Any = None
    mode: Any = None
    icon: Any = None
    fields: Any = None

    def kind(self) -> str:
        return "script"


class HelperConfig(IRObject):
    """A storage-collection helper item (one of the nine domains, keyed by ``id``)."""

    # See AutomationConfig.id — typed Any to preserve any id value verbatim.
    id: Any = None
    name: Any = None
    icon: Any = None

    _domain: str = PrivateAttr(default="")

    def attach_domain(self, domain: str) -> None:
        """Attach the helper domain (used by :func:`parse`)."""
        self._domain = domain

    def kind(self) -> str:
        if not self._domain:
            raise ValueError("HelperConfig has no domain; parse it with kind=<helper domain>")
        return self._domain

    @property
    def identity(self) -> str | None:
        return self.id if self.id is not None else self._key_id


class TemplateHelperConfig(IRObject):
    """A template-helper config-entry subentry body (one of the four
    ``TEMPLATE_DOMAINS``) — the "options" a template number/sensor/
    binary_sensor/select config entry holds (DESIGN §13's config-entry helper
    plugin).

    **Identity: there is no ``unique_id`` field** (docs/internals/ha-api-notes.md
    §26.6). The `template` config flow's
    form schema rejects an unrecognized ``unique_id`` key outright (real HA
    returned ``400 {"errors": {"base": ["extra keys not allowed @
    data['unique_id']"]}}``) — a flow-created entry has no caller-settable
    unique id at all. Identity is instead **derived from ``name``**, exactly
    mirroring the nine storage helpers' "id is a slug of name" rule
    (``hassle.ir.keys.slugify``, docs/internals/ha-api-notes.md §4/§17.5) — except here
    it's the ONLY identity source (no override), since the flow gives us
    nothing else stable to key on locally; on the wire, HA's own correlator
    is the entry's ``title`` (which the flow sets from the submitted
    ``name``). The HA-assigned config ``entry_id`` remains HA-side transport
    identity only, tracked in the manifest entry, never in this body or the
    object key (an existing object's HA id is never changed: an update never
    changes the entry_id).

    ``name``/``state`` (the Jinja template string) are the two fields every
    template domain shares; domain-specific fields (``min``/``max``/``step``/
    ``unit_of_measurement``/``set_value`` for number, ``options``/
    ``select_option`` for select) pass through via ``extra="allow"`` like
    every other IR model.
    """

    name: Any = None

    _domain: str = PrivateAttr(default="")

    def attach_domain(self, domain: str) -> None:
        """Attach the template domain (used by :func:`parse`)."""
        self._domain = domain

    def kind(self) -> str:
        if not self._domain:
            raise ValueError(
                "TemplateHelperConfig has no domain; parse it with kind=<template domain>"
            )
        return self._domain

    @property
    def identity(self) -> str | None:
        if self._key_id is not None:
            return self._key_id
        if self.name is not None:
            from hassle.ir.keys import slugify

            return slugify(str(self.name))
        return None


class GroupHelperConfig(IRObject):
    """A group-helper config-entry subentry body (one of the twelve
    ``GROUP_DOMAINS``) -- the "options" a group config entry holds
    (DESIGN §13's config-entry helper plugin, a mechanical follow-on to the
    template-helper config-entry domains).

    **Identity: there is no ``unique_id`` field**, exactly mirroring
    ``TemplateHelperConfig`` (docs/internals/ha-api-notes.md §26.6): the `group`
    config flow's form schema rejects an unrecognized ``unique_id`` key
    outright (docs/internals/ha-api-notes.md §38.1) -- a flow-created entry has no
    caller-settable unique id at all. Identity is derived from ``name``
    (``hassle.ir.keys.slugify``), the ONLY identity source, same as template
    helpers; on the wire, HA's own correlator is the entry's ``title`` (set
    from the submitted ``name``). The HA-assigned config ``entry_id`` remains
    HA-side transport identity only, tracked in the manifest entry, never in
    this body or the object key (an existing object's HA id is never changed).

    ``name``/``entities`` (a list of member entity ids, order preserved
    verbatim) are common to every flavor; ``hide_members`` (bool,
    always materialized) is common to every flavor too. ``all`` (bool, the
    three flavors that have it: binary_sensor/light/switch) and ``type`` (the
    aggregation kind, required for sensor) pass through via ``extra="allow"``
    like every other IR model field, exactly the way ``TemplateHelperConfig``
    passes through ``state``/``min``/``max``/etc.
    """

    name: Any = None

    _domain: str = PrivateAttr(default="")

    def attach_domain(self, domain: str) -> None:
        """Attach the group flavor domain (used by :func:`parse`)."""
        self._domain = domain

    def kind(self) -> str:
        if not self._domain:
            raise ValueError("GroupHelperConfig has no domain; parse it with kind=<group domain>")
        return self._domain

    @property
    def identity(self) -> str | None:
        if self._key_id is not None:
            return self._key_id
        if self.name is not None:
            from hassle.ir.keys import slugify

            return slugify(str(self.name))
        return None


class DashboardConfig(IRObject):
    """A Lovelace storage-mode dashboard -- the two-store envelope
    (docs/internals/dashboards-design.md §3.2).

    A dashboard is **two HA-side objects** (a `lovelace_dashboards` registry
    item and a `lovelace[.<url_path>]` config blob) but **one Hassle object**:
    one decorator declares both, one plan row diffs both, one conflict covers
    both. The IR body is therefore a Hassle-composed envelope -- the one
    deliberate departure from "the body mirrors exactly one HA store"::

        {"meta": {"url_path": ..., "title": ..., "icon": ...,
                  "show_in_sidebar": ..., "require_admin": ...},
         "config": {"views": [...]}}

    - ``meta`` is the registry item **minus** ``id`` (HA-assigned,
      transport-only, never in the body -- same rule as a config entry's
      ``entry_id``) and minus ``mode`` (always ``"storage"``; a YAML-mode
      dashboard is filtered out of ``list_remote`` entirely, it is not ours to
      manage -- I1). ``meta`` is ``None`` for the DEFAULT dashboard, which has
      no registry item at all.
    - ``config`` is the view config **verbatim** -- native-JSON passthrough
      (``Any``), exactly like ``triggers``/``actions`` on
      :class:`AutomationConfig`. The typed card layer lives in the compiler/
      decompiler, not here (ir-format.md's "structural blocks pass through
      verbatim" rule), so ``serialize(parse(x)) == x`` holds by construction
      for both halves.

    Rejected alternative: flattening ``meta`` into the config top level. The
    Lovelace config historically allows its own top-level ``title`` key, so
    flattening risks a silent collision between "sidebar title" and "config
    title"; the envelope keeps the two stores' keyspaces disjoint by
    construction, at the cost of one documented wrapper.

    Because ``compiled_hash`` is the canonical hash of the whole envelope, a UI
    edit to *either* the sidebar metadata or the cards shows up as one drifted
    object -- refresh/conflict at dashboard granularity, which is the sync
    behavior the design wants (§4.4).

    Identity (§3.1): the ``url_path`` from ``meta``, used verbatim; else the
    extrinsic ``_key_id``; else the sentinel ``"default"``. The sentinel is
    collision-free only by convention: HA's hyphen rule is bypassable via
    ``allow_single_word`` (docs/internals/ha-api-notes.md §39.3), and on HA
    2026.x the default dashboard usually has its own registry item at
    ``url_path: "lovelace"`` instead (§39.2).
    """

    # Both halves are passthrough `Any` -- see the class docstring. `None`
    # defaults (rather than required fields) keep a partial/hand-written body
    # parseable; `exclude_unset=True` means an explicitly-set `meta: null`
    # still round-trips as `null` while an absent `meta` stays absent.
    meta: Any = None
    config: Any = None

    def kind(self) -> str:
        return DASHBOARD_KIND

    @property
    def identity(self) -> str | None:
        meta = self.meta
        if isinstance(meta, dict):
            url_path = cast("dict[str, Any]", meta).get("url_path")
            if url_path is not None:
                # Verbatim -- never slugified. A `url_path` IS HA's slug.
                return str(url_path)
        if self._key_id is not None:
            return self._key_id
        # The default dashboard (no registry item, no `url_path`). Returning
        # the sentinel rather than `None` means `object_key()` never raises for
        # this kind: a dashboard body is always self-describing enough to key.
        return "default"


class BlueprintConfig(IRObject):
    """A blueprint SOURCE FILE (docs/internals/blueprints-design.md §1).

    The body is a Hassle-composed envelope, like :class:`DashboardConfig`'s and
    for a related reason: what HA's ``blueprint/save`` takes is
    ``{domain, path, yaml}`` — three things at once — and the ``yaml`` half is
    an opaque document rather than a config mapping::

        {"domain": "automation",
         "path": "local/room-switch-controls.yaml",
         "source": "blueprint:\\n  name: ...\\n",
         "inputs": {"button_up": {...}, "room_key": None}}

    - ``source`` is the file's text, **byte-preserved**. A file-authored blueprint
      is AUTHORED, not generated (a DSL-authored one, §8, is a compiled artifact),
      so a push that reflowed it would lose the author's comments, block
      scalars and blank lines — and HA stores the document verbatim anyway.
      :func:`hassle.blueprints.blueprint_body` reads it via
      ``bytes.decode("utf-8")`` rather than text mode, so even CRLF survives.
    - ``inputs`` is the parsed ``blueprint.input`` block, **verbatim** (a bare
      ``room_key:`` entry stays ``None``, which is how "declared with no
      ``default:``" — i.e. required — stays distinguishable from ``{}``). It is
      derived from ``source``, and stored anyway on purpose: it is what the
      validator (§6) reads, so nothing downstream has to re-parse YAML to
      answer "which inputs does this blueprint declare".

    Identity is ``"<domain>/<path>"``, verbatim (see ``BLUEPRINT_KIND`` in
    :mod:`hassle.ir.keys`): ``<path>`` is exactly the string instances put in
    ``use_blueprint``, so an instance's own reference derives its blueprint's
    object key with no transformation at all.
    """

    # `inputs` is passthrough `Any` for the same reason `DashboardConfig.config`
    # is: it is third-party-shaped data (HA selector schemas), and the IR's job
    # is to carry it losslessly, not to model it. `None` defaults keep a
    # partial/hand-written body parseable, and `exclude_unset=True` means an
    # absent key stays absent.
    domain: str | None = None
    path: str | None = None
    source: str | None = None
    inputs: Any = None

    def kind(self) -> str:
        return BLUEPRINT_KIND

    @property
    def identity(self) -> str | None:
        if self.domain and self.path:
            return f"{self.domain}/{self.path}"
        return self._key_id


def parse(config: dict[str, Any], *, kind: str, key_hint: str | None = None) -> IRObject:
    """Parse an HA config body into the IR model for ``kind``.

    ``key_hint`` supplies an extrinsic identity (a script's object_id, or a
    helper/automation id absent from the body) used for the object key.
    """
    obj: IRObject
    if kind == "automation":
        obj = AutomationConfig.model_validate(config)
    elif kind == "script":
        obj = ScriptConfig.model_validate(config)
    elif kind in HELPER_DOMAINS:
        helper = HelperConfig.model_validate(config)
        helper.attach_domain(kind)
        obj = helper
    elif kind in TEMPLATE_DOMAINS:
        template_helper = TemplateHelperConfig.model_validate(config)
        template_helper.attach_domain(kind)
        obj = template_helper
    elif kind in GROUP_DOMAINS:
        group_helper = GroupHelperConfig.model_validate(config)
        group_helper.attach_domain(kind)
        obj = group_helper
    elif kind == DASHBOARD_KIND:
        obj = DashboardConfig.model_validate(config)
    elif kind == BLUEPRINT_KIND:
        obj = BlueprintConfig.model_validate(config)
    else:
        raise ValueError(f"unknown object kind {kind!r}")
    if key_hint is not None:
        obj.attach_key(key_hint)
    return obj


def serialize(obj: IRObject) -> dict[str, Any]:
    """Serialize an IR object back to its exact HA config body (lossless)."""
    return obj.to_ha()
