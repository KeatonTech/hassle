# DSL public API surface

This is the frozen contract every bundle — and the decompiler, stubs/validation,
simulator, CLI, and generated docs — builds against. Changing anything
frozen here requires updating this document in the same PR
(CONTRIBUTING.md, "compatibility contracts"). **Additions are allowed;
changes and removals are not.**

The public surface is exactly `hassle.__all__` (module
`packages/hassle-core/src/hassle/__init__.py`). Bundle files write
`from hassle import automation, when, ...`; nothing outside this list is public.

Three dedicated entry points are deliberately *not* folded into `hassle.__all__`:
`hassle.registry` (below; DESIGN §5.3 imports it under its own alias, `from
hassle.registry import entities as e`), `hassle.services` (its own section
below), and `hassle.cards` (its own section below). The first two are
domain/instance-dynamic (their real shape depends on the bundle's own registry
snapshot), which is exactly why neither is part of the star surface:
`hassle.__all__` is a fixed, frozen contract, but which domains/services exist
is a property of a specific HA install, not the DSL itself. `hassle.cards` is
separate for a different reason — namespace hygiene, see its section.

### Entity indexing form — `hassle.registry.entities` (DESIGN §5.2/§5.3)

```python
from hassle.registry import entities as e

when(state(e.sensor.hall_motion).to("on"))     # attribute form
when(state(e.sensor["hall_motion"]).to("on"))   # index form — identical EntityRef
when(state(e.sensor._3d_printer).to("on"))      # digit-leading id: strip one leading `_`
when(state(e.sensor["3d_printer"]).to("on"))    # index form never needs the prefix
```

`entities.<domain>` returns a domain accessor; both attribute access and
indexing resolve to the same `EntityRef` (a `str` subclass, identical to what
the helper-declaration builders return — accepted anywhere the DSL expects an
entity id). The digit-leading rule (DESIGN §5.2: object_ids match
`(?!_)[\da-z_]+(?<!_)`, so they may start with a digit but a Python identifier
can't) strips exactly one leading underscore when the next character is a
digit; any other name passes through unchanged. This module (`hassle.registry`)
is domain-open (no registry snapshot backs it at runtime); the registry module
also generates typed `.pyi` stub classes with the identical attribute/index
shape on top, so a bad attribute name becomes a pyright error in the editor
without changing how bundles are written.

### Typed service namespaces — `hassle.services`, and entity-method sugar

```python
from hassle.services import cover, light
from hassle.registry import entities as e

light.turn_on(target=e.light.hallway, brightness_pct=60)   # namespace form
cover.close_cover(target={"entity_id": "cover.blind"})
e.cover.blind.close_cover()                                 # entity-method sugar
```

`hassle.services` is a non-star module (not part of `hassle.__all__`, for the
same domain-instance-dynamic reason `hassle.registry` isn't): a module-level
PEP 562 `__getattr__` accepts ANY domain name and returns a namespace object
whose own `__getattr__` accepts ANY service name and returns a callable —
`light.turn_on(**fields)` records the identical action a
`service("light.turn_on", **fields)` call would. Offline compile never fails
on an unknown domain/service (that is `hassle validate`'s job — an
`unknown-service` Finding with a did-you-mean suggestion, gated on real
edit-distance evidence rather than "not in this snapshot", since HA's service
catalog is per-installed-integration, never a complete, stable enumeration the
way entities are).

**Entity-method sugar:** `e.<domain>.<id>.<method>(**fields)` (any
`EntityRef`, whether from `hassle.registry.entities` or a helper
declaration) records the same action with `target={"entity_id": "<domain>.
<id>"}` implicit. Only a CALL records anything — bare attribute access
(`e.cover.x.close_cover`, no parens) stays inert, so it can never be mistaken
for the pre-existing `.attr(name)` sugar (a real `EntityRef` method, found by
normal attribute lookup before `__getattr__` is ever consulted) or plain
`EntityRef`/`str` usage elsewhere.

Both forms delegate to the exact same `hassle.compiler.actions.service()`
verb internally, so IR and span capture (`hassle validate`'s file:line) are
byte-identical to `service(...)` by construction — proven by a golden pair
fixture (`fixtures/dsl/service_namespace_sugar/`) compiling all three forms
to the identical IR.

**Decompiler canonical form** (DESIGN §7.3): a plain service-call action
whose literal `"domain.service"` exists in the registry snapshot AND whose
`data` keys are all kwarg-expressible Python identifiers (not a reserved
word) decompiles to the namespace form, with a per-file
`from hassle.services import <domains>` import (sorted, deduplicated —
aliased to `svc_<domain>` whenever the domain name collides with a
star-imported DSL name, e.g. `automation`/`script`/`zone`/`schedule`/`time`
are simultaneously real HA service domains and frozen DSL names). Everything
else (a templated service name, a service/domain absent from the snapshot,
no snapshot supplied at all, or a non-kwarg-safe data key) falls back to
`service(...)` — round-trips byte-exact through both branches. The
entity-method form is author-only sugar and is never emitted by the
decompiler (one canonical output form, independent of how the DSL source
happened to be written).

### Card builders and Lovelace conditions — `hassle.cards`, `hassle.cards.cond`

```python
from hassle import *                  # dashboard, view, section, badge, raw_* …
from hassle import cards as c         # c.tile(...), with c.vertical_stack(): …
from hassle.cards import cond         # cond.state(...), cond.screen(...)
from hassle.registry import entities as e
```

`hassle.cards` is a non-star module for a reason unlike the other two: **name
collisions**, not instance-dynamism. Card type names collide head-on with the
frozen DSL surface — `area`, `calendar`, `button`, `light`, `sensor` are
already `hassle.__all__` names and `map` is a Python builtin — so folding ~35
card builders into the star surface would mean renaming every one of them away
from its own HA name (`map_card`, `area_card`, …). A dedicated namespace costs
one import line and keeps every builder named exactly what HA calls it
(docs/internals/dashboards-design.md §5.1).

The card vocabulary is a **closed, versioned set** (it ships in HA frontend
releases rather than being enumerable from an instance), so — unlike
`hassle.services` — this module has **no** `__getattr__` dynamism: every
builder is a real typed function and pyright checks every keyword. Its
`__all__` is frozen under the same additive-only rule as `hassle.__all__`. A
card type Hassle does not model is never an error: it round-trips through
`raw_card` and surfaces in the decompile-coverage metric.

- `hassle.cards.cond` — the **Lovelace** condition vocabulary (a different
  schema from automation conditions, dashboards-design §5.4):
  `cond.state(entity, value=None, *, not_=None)` →
  `{condition: state, entity, state|state_not}`;
  `cond.numeric(entity, above=, below=)` → `{condition: numeric_state, …}`;
  `cond.screen(media_query)` and `cond.user(*user_ids)` (the two UI-only
  kinds); `cond.any(...)` / `cond.all(...)` / `cond.not_(...)` →
  `{condition: or|and|not, conditions: [...]}`. A verbatim `dict` is accepted
  anywhere a condition is, so an unmodelled future condition kind round-trips
  raw.

### Dashboard builder conventions

Every structural builder above and every `hassle.cards` builder shares two
keyword conventions, implemented once
(`hassle.compiler.dashboards.builders`) so they cannot drift apart:

- **`extra: dict | None = None`, keyword-only, on every builder** — verbatim
  passthrough merged into the built body. The forward-compatibility valve: when
  HA adds an option Hassle doesn't model yet, the decompiler emits the *typed
  builder call plus `extra={...}`* instead of collapsing the node to `raw_card`,
  and an author can use a new option the day HA ships it. A typo'd kwarg is
  still a loud `TypeError` (builders have no `**kwargs`). An `extra` key may not
  shadow a **declared** kwarg of that builder — even one that was omitted —
  so every option has exactly one spelling (`ExtraShadowsKwargError`).
- **`visibility=`** — one condition or a list of them, each a `cond.*` object
  or a verbatim dict; normalized to HA's stored list-of-conditions. An
  automation condition builder here raises `DashboardConditionTypeError`.

### Dashboard trap table (both directions)

| You wrote | Where | What happens |
|---|---|---|
| `raw_card(...)`/`view(...)`/`section()`/`badge(...)` | outside a `@dashboard` body | `NoDashboardContextError` (message sharpens if an `@automation` body is active) |
| `service(...)`/`when(...)`/any action verb | inside a `@dashboard` body | `NoRecordingContextError`, with dashboard-specific teaching text (put the call on the card's `tap_action`) |
| a card | straight in the `@dashboard` body, or a `badge()` outside a view, or a nested `view()` | `DashboardNestingError` |
| a card | directly under a `sections` view | `SectionRequiredError` |
| `section()`/`raw_section()` | under a masonry/panel/sidebar view, or nested | `SectionOutsideSectionsViewError` |
| 0 or ≥2 cards | in a `panel` view | `PanelViewArityError` |
| no `url_path=`+no `default=True`, both, a hyphen-less `url_path`, a raw `meta` without `url_path`, or a `meta` `url_path` contradicting the decorator's | `@dashboard`/`@raw_dashboard` | `DashboardUrlPathError` |
| `title=`/`icon=`/`show_in_sidebar=`/`require_admin=` | with `default=True` | `DefaultDashboardMetadataError` |
| an automation `ConditionBuilder` | `visibility=` / a conditional card | `DashboardConditionTypeError` (names the `cond.*` equivalent) |
| a `cond.*` object | `only_if`/`if_then`/`all_of`/… | `DashboardConditionInAutomationError` |
| an `extra=` key that is a declared kwarg | any builder | `ExtraShadowsKwargError` |

## The frozen surface, grouped by role

### Object decorators / declarations (top-level objects)
- `automation` — `@automation(**ha_options)` registers an automation.
  `triggers=` is a list of `TriggerBuilder` objects — the same objects
  `when()` accepts — evaluated at decoration time (built when the
  `@automation(...)` line itself runs, before the compiler invokes the
  function body). This is the CANONICAL decompiled form (DESIGN §5.3/§7.3):
  the decompiler emits `triggers=[...]` in the decorator instead of a
  `when(...)` call at the top of the body, multi-line (one trigger per line)
  when there's more than one. `when()` itself remains fully supported — still
  the right tool when the trigger list must be built dynamically (a
  compile-time loop, a shared helper function, …), since `triggers=`'s list is
  one Python expression evaluated once, at decoration time, and so can only
  ever be a single static list literal. `triggers=` and `when()` COMPOSE: the
  decorator's list is recorded first, then any `when()` calls inside the body
  append after it, in call order (DESIGN §5.3's position-independence note).
  Compile parity is exact: `@automation(triggers=[state(x).to("on")])`
  produces byte-identical IR to the equivalent `when(state(x).to("on"))` form.
- `script` — `@script(**ha_options)` registers a plain script.
- `shared_script` — `@shared_script(...)` registers a script **and** returns a
  call-site verb (invoking it elsewhere records a `script.<id>` call, DESIGN
  §5.6). See "`@shared_script` parameters" below for the body-side binding
  rules. The call-site wrapper accepts every declared field as a kwarg, plus
  three optional keyword-only step options mirroring every other action
  shape's step options: `metadata=`/`alias=`/`enabled=` (e.g.
  `flash_lights(times=5, metadata={...}, alias="...", enabled=False)`) — used
  to round-trip a UI-saved action's `metadata: {}` / step `alias`/`enabled`
  through the call site. `fields=` on the decorator itself carries full HA
  field metadata (`name`/`description`/`selector`/`example`/...) VERBATIM;
  when supplied it wins over the signature-derived `fields` dict (byte
  stability by construction), since real HA-UI-authored scripts always carry
  this richer shape. The signature stays the ergonomic call-site layer —
  every declared field is still a real Python parameter, `None`-defaulted
  when the metadata carries no `"default"` key (HA-side requiredness lives in
  the metadata, not in whether the compiler can invoke the body with zero
  arguments to build its sequence). A call-site kwarg not among `fields=`'s
  keys (the superset source of truth when `fields=` is explicit) is rejected
  with `UnknownFieldError` even if it would otherwise bind against the
  signature — catches an author who added a Python parameter but forgot to
  also declare it as a field.
- `macro` — `@macro` marks a compile-time-inlined function (DESIGN §5.6).
- `raw_automation` — `@raw_automation(id=...)` over a zero-arg function returning
  a verbatim automation dict (DESIGN §5.8; `normalize_ha` is applied).
- `blueprint_automation` — `blueprint_automation(id=, use_blueprint=, inputs=,
  alias=, description=)`; maps `inputs=` → stored `use_blueprint.input` with an
  author-qualified path (docs/internals/ha-api-notes.md §10.5). `alias=`/`description=`
  are real blueprint-automation top-level fields alongside `use_blueprint`
  (docs/internals/ha-api-notes.md §10.5).
- Helper declarations (DESIGN §5.7), one per storage-collection domain, each
  returning an `EntityRef` usable as an entity id elsewhere:
  `input_boolean`, `input_number`, `input_select`, `input_text`,
  `input_datetime`, `input_button`, `counter`, `timer`, `schedule`.
- Template-helper declarations (config-entry domain, DESIGN §13's config-entry
  plugin, docs/internals/ha-api-notes.md §26): `template_number(name=,
  state=, set_value=, min=, max=, step=, unit_of_measurement=, icon=)`,
  `template_sensor(name=, state=, unit_of_measurement=, device_class=, icon=)`,
  `template_binary_sensor(name=, state=, device_class=, icon=)`,
  `template_select(name=, state=, options=, select_option=, icon=)`. Same
  import-and-reference pattern as the storage-collection helpers above
  (returns an `EntityRef`).
  **No `id=`/`unique_id=` kwarg** (real HA's config-flow form schema rejects
  an unrecognized `unique_id` key outright — a flow-created entry has no
  caller-settable unique id at all; docs/internals/ha-api-notes.md §26.6).
  `name=` is the sole identity-bearing kwarg: the object key is
  `"<domain>:<slugify(name)>"`, mirroring the storage helpers' "id is a slug
  of name" rule. `set_value=` on `template_number` and `select_option=` on
  `template_select` are REQUIRED (HA's own form schema rejects the submission
  without them — a number/select needs a write-target action sequence;
  `template_sensor`/`template_binary_sensor` are read-only and need neither).
  The HA-assigned `entry_id` is manifest-only (docs/internals/backend-protocol.md),
  never in the DSL body.
- Group-helper declarations (config-entry domain, DESIGN §13's config-entry
  plugin; docs/internals/ha-api-notes.md §38): one builder per flavor, all
  taking `name=`/`entities=`/`hide_members=` (default `False`, always
  materialized explicitly): `group_button`, `group_cover`, `group_event`,
  `group_fan`, `group_lock`, `group_media_player`, `group_notify`,
  `group_valve`. Three flavors additionally take `all=` (default `False`,
  always materialized explicitly): `group_binary_sensor`, `group_light`,
  `group_switch`. One flavor additionally takes a REQUIRED `type=` (the
  aggregation kind: min/max/mean/median/last/range/product/sum/stdev):
  `group_sensor`. Same import-and-reference pattern as every other helper
  builder (returns an `EntityRef`); no decorator form (no Jinja `state=` field
  to defer, unlike template).
  **No `id=`/`unique_id=` kwarg**, same rule as template helpers (real HA's
  `group` config-flow form schema also rejects an unrecognized `unique_id`
  key outright; docs/internals/ha-api-notes.md §38.1). `name=` is the sole
  identity-bearing kwarg: the object key is `"group_<flavor>:<slugify(name)>"`
  (e.g. `group_cover:entryway_top`). The HA-assigned `entry_id` is
  manifest-only (docs/internals/backend-protocol.md), never in the DSL body.
  `entities=` (a list of member entity ids, possibly another group's own
  produced entity id — groups may nest) preserves order verbatim.

### `@shared_script` parameters

Every `@shared_script` signature parameter is annotated `TemplateExpr` — body-true:
inside the body it is ALWAYS a runtime template marker, never its declared
Python default's type. (A plain-type annotation like `times: int` would let
`sun_angle / 2`-style body composition type-check as real arithmetic when it's
actually building Jinja text.) The decorated function's own signature is
irrelevant to a caller's typing: `@shared_script`'s returned CALLER wrapper
signature is `(*args: Any, **kwargs: Any) -> None`, completely decoupled from
the body's annotations — the real validation net is `UnknownFieldError` /
Python's own `TypeError` from `bind_partial`, at compile time.

- `param(name)` — inside the body, a runtime reference to a declared field
  (returns `TemplateExpr`, specifically a `_BoundParamMarker` subclass,
  module-internal). Compiling a `@shared_script` body binds EVERY signature
  parameter whose name is a declared field to its `param(name)` marker BEFORE
  the body runs, regardless of its declared Python default — so `tag=tag`
  inside the body is exactly equivalent to `tag=param("tag")`; an unbound bare
  parameter never silently holds its literal Python default.
- `field_default(value)` — the typed-default helper for a parameter annotated
  `TemplateExpr`: the identity function AT RUNTIME (returns `value`
  unchanged, so the compiler's `inspect.signature` introspection sees the
  real declared default), typed as returning `TemplateExpr` so a field's
  default expression (`tag: TemplateExpr = field_default("")`) type-checks
  against its own annotation. Named in `pyproject.toml`'s
  `[tool.ruff.lint.flake8-bugbear] extend-immutable-calls` so ruff's B008
  doesn't flag it as a mutable-default-style anti-pattern.
- `SharedScriptParamMisuseError` — raised on `range()`/`bool()`/`int()`/
  `float()`/`round()`/`math.trunc()` misuse, and on `for`/`in`/`len`/indexing
  container misuse, applied to a bound shared-script parameter. Its message
  teaches the runtime/compile-time alternatives directly (`with
  repeat_count(name):` / `with repeat_for_each(name):` / a runtime
  condition-template for a genuinely runtime value; a module constant or
  `@macro` argument for a genuinely compile-time one).
- Decompiler emission (`hassle.decompiler.codegen._shared_script_signature`):
  every parameter is keyword-only (a leading `*,` — a required field with no
  declared default, bare `TemplateExpr` with no `=...`, can otherwise follow a
  defaulted one in the stored `fields` dict's own order, which is a plain
  Python parameter-ordering `SyntaxError` unless keyword-only). A required
  field gets bare `name: TemplateExpr`, a defaulted one gets `name:
  TemplateExpr = field_default(<default>)`. Inside a `@shared_script` body's
  own decompile, a `"{{ <field> }}"` data value whose name is exactly one of
  the script's own fields inverts to the bare parameter read (`tag`) instead
  of the raw string; a larger invertible expression containing a field read
  decompiles through the same bounded inverter with fields bound as
  parameters; the same field-aware rewrite also applies to
  `repeat.count`/`repeat.for_each`, so `repeat_count(times)`/
  `repeat_for_each(items)` round-trip with the bare parameter too. Scoped
  strictly to an actual shared-script body's decompile (a module-level
  context, reset immediately after) — never affects automation/plain-`@script`
  decompilation; anything the inverter can't accept keeps the unchanged
  raw-string fallback.

### Recording verbs
- `when(*triggers)` — append triggers to the active automation. Fully
  supported alongside `@automation(triggers=...)` (composes, decorator list
  first) — the right tool for a dynamically-built trigger list; not the
  decompiler's canonical output form (see `triggers=` above), but never
  removed.
- `only_if(*conditions)` — append conditions. Dual-form: the bare call is a
  plain function call; the SAME call is also usable as `with only_if(...):`,
  which additionally requires every action the automation records to be
  inside that one block (an action recorded before/after it raises
  `OnlyIfBlockCoverageError`). The decompiler emits the block form as
  canonical whenever an automation has any conditions at all, wrapping every
  action — compiled IR is byte-identical either form.
- `capture_actions()` → `with capture_actions() as bodies:` — capture a
  block's actions as plain action-body dicts WITHOUT appending them to the
  enclosing sequence. `emit_actions(bodies, *, span=)` — splice previously
  captured bodies into the CURRENT recording context (respecting nested
  containers), each re-wrapped with a span captured at the
  `emit_actions(...)` call site by default (or the given `span`) — so an
  error later raised against an emitted action points at the splice site,
  never some unrelated earlier line. `bodies` is read-only to
  `emit_actions`: emitting the same captured list more than once (e.g. into
  two different branches, see `fixtures/dsl/capture_emit_actions/`) is
  supported and produces independent, equal-but-distinct entries. Both raise
  `NoRecordingContextError` outside an active recording context, same message
  shape as `when`/`only_if`/every other recording verb. This is the public
  seam a `lib/` recipe builder uses in place of the internal
  `push_actions`/`RecordedNode` machinery `if_then`/`choose` are built on
  (e.g. the cookbook's actionable-mobile-notification recipe,
  `fixtures/cookbook/bundle/lib/notify_actions.py`).

### Core action verbs
- `service(action, *, target=, data=, data_template=, response_variable=,
  continue_on_error=, metadata=, alias=, enabled=, **fields)` — the **single**
  service-call verb (bare kwargs → `data`; `response_variable`/
  `continue_on_error`/`metadata`/`data_template`/`alias`/`enabled` emit as
  top-level HA action fields). `metadata=` round-trips the `"metadata": {}`
  the HA UI stamps on every action it saves (docs/internals/ha-api-notes.md
  §19.1); omitted by default. `data_template=` is the legacy templated-data
  key, a sibling of `data` never folded into it; `alias=`/`enabled=`
  name/toggle the individual step, the same way the HA UI does on every step
  (docs/internals/ha-api-notes.md §20). All three omitted by default.
- `delay(*, alias=, enabled=, **units)` — dict-form delay. `alias=`/`enabled=`
  are keyword-only so they never collide with a duration unit.
- `variables(**kwargs)` — a `variables` action.
- `stop(message=None, *, error=None, response_variable=None)` — a `stop`
  action. `response_variable=` names a run variable whose value becomes
  the script's response (HA script responses): pair with the call side's
  `service("script.<id>", response_variable=...)` to receive it, e.g.
  behavior scripts returning `{position, priority}` bid dicts.
- `fire_event(event_type, **event_data)` — the fire-event **action** (distinct
  from the `event` **trigger** builder below).

### Classic trigger / condition builders (DESIGN §5.4)
`state`, `numeric_state`, `time`, `time_pattern`, `sun`, `event`, `zone`,
`template`, `webhook`, `mqtt`, `calendar`, `persistent_notification`, `tag`,
`geo_location`, `homeassistant_start`, `homeassistant_shutdown`, `device`,
`trigger_condition`.

- Dual-purpose builders (`state`, `numeric_state`, `time`, `sun`, `zone`,
  `template`) serialize as a trigger inside `when(...)` and as a condition
  inside `only_if(...)`.
- `template(raw)` is **one** builder: as a bare value it *is* the `{{ … }}`
  Jinja string (a `str` subclass with operator overloading); inside
  `when`/`only_if` it serializes to a `template` trigger/condition.
- Common trigger options are set on the builder — for `state` via
  `.to(v, id=, enabled=, variables=, for_=)` / `.is_(...)` / `.with_options(...)`;
  for the classic-builder family via `.with_options(...)`.
- `state(entity_id)`'s `entity_id` (and `.to()`/`.is_()`'s `value`) and
  `numeric_state(entity_id, ...)`'s `entity_id` accept `str | Sequence[str]`
  (`Sequence` rather than `list` so a decompiled bundle's
  `state(e.<domain>.<id>)` — an entity STUB CLASS, a `str` subclass but not
  literally `str` — type-checks correctly under pyright strict; a bare `str`
  is itself a `Sequence[str]`, so the single-entity form is unaffected): the
  HA UI always stores these fields as a list, even for a single entity/value,
  and a singleton list decompiles back to a list, never a scalar. This
  applies on both the trigger and the `state` **condition** path
  (`hassle.decompiler.exprs._cond_state`), since `state()` is the same
  dual-purpose builder either way.
- `time(at=, after=, before=, weekday=)`: `weekday=` is emitted on both the
  **trigger** and condition side (HA's `time` trigger schema accepts it,
  docs/internals/ha-api-notes.md §19.3). `at=` accepts an entity reference
  (`input_datetime.x`) as a plain `str`.

### Entity-state conditions
- `EntityRef.state` — a `@property` on any `EntityRef` (both `e.<domain>.<id>`
  registry refs and helper-declaration handles, since both share the one
  implementation). Property lookup is a data descriptor and is always checked
  before the entity-method `__getattr__` sugar (above), so no HA domain name
  can shadow it. Returns a comparison accessor
  (`hassle.compiler.builders._StateAccessor`, non-public) bound to that one
  entity id:
  - `==`/`!=` → a native `state` condition (`state(x).is_(v)` /
    `state(x).is_not(v)`, byte-identical IR either spelling);
  - `>`/`<` → `numeric_state(x, above=v)` / `(x, below=v)`;
  - `>=`/`<=` → `InclusiveNumericBoundError`: HA's `numeric_state` has no
    inclusive bound, so silently mapping these onto `above`/`below` would
    compile a condition that is subtly wrong right at the boundary value.
    Raised instead of a wrong compile, naming the honest exclusive-operator
    rewrite;
  - `.in_([...])` → `state(x).is_(["a", "b"])` (HA's `state` condition already
    accepts a list value as OR-membership, verified against a real
    UI-authored config).

  The **`in`-operator trap** (Python semantics, non-negotiable): `x.state in
  [...]` dispatches to `list.__contains__`, which calls `bool()` on each
  element comparison to decide membership — no `__eq__` override can
  intercept this. The comparison-RESULT object (what `==`/`!=` return) refuses
  `__bool__` with `InOperatorTrapError`, naming `.in_([...])` as the fix — the
  natural-but-impossible spelling fails loudly, never silently.

  `StateExpr.is_not(v)` (mirroring `.is_()` exactly, including its
  list-valued `entity_id`/`value` handling) compiles to `{"condition": "not",
  "conditions": [<state-condition>]}`, byte-identical to `not_(state(x).is_(v))`.
  The `.state` accessor's `==`/`!=` are real `__eq__`/`__ne__` overloads;
  `StateExpr` is not a `str` subclass and deliberately keeps plain object
  equality — one blessed operator surface (the accessor) beats two parallel
  spellings, and `ConditionArgumentTypeError` (below) catches a
  `state(x) != ...` mistake loudly, naming both `.is_not()` and the `.state`
  accessor.

  The accessor's comparison result has `to_condition()` only, no
  `to_trigger()` — passing it to `when(...)` fails with a plain
  `AttributeError` on the missing method, never silently compiling as some
  other trigger shape. Distinct from `state_of(entity)` (below, the Jinja
  TEMPLATE-STRING read, `states('x')`, for template/expression composition):
  `.state` is the NATIVE-CONDITION read (a real `state`/`numeric_state`
  condition dict for `only_if(...)`/`if_then(...)`/etc.) — the two never
  produce the same IR shape.

- `ConditionArgumentTypeError` — every condition-accepting entry point
  (`only_if`, `if_then`, `else_if`, `choose().when_`, `repeat_while`,
  `repeat_until`, `any_of`/`all_of`/`not_`) rejects a plain Python `bool`
  argument with this error instead of a bare
  `AttributeError: 'bool' object has no attribute 'to_condition'` deep inside
  the compiler — the classic `==`/`!=`-on-a-plain-value typo.

Stubs: generated entity classes type the `.state` accessor
(`hassle.registry.stubs`'s `generate_entities_stub`). Decompiler canonical
output never emits the `.state` accessor form — it is authoring sugar only;
the decompiler still emits `state(...)`/`numeric_state(...)` builder calls.

### Condition combinators
- `all_of(*conditions)`, `any_of(*conditions)`, `not_(condition)`.

### Purpose-specific builders (DESIGN §5.4)
- `on(type, *, target=, behavior=, for_=, **options)` — purpose **trigger**.
- `met(type, *, target=, **options)` — purpose **condition**.
- Target constructors: `area`, `floor`, `label`, `device_id` (plus a plain
  entity-id string or an entity ref).

### Duration helpers
- `hours`, `minutes`, `seconds` — build the `for_=` / duration values.

### Template expression builder
- `expr(entity)` — numeric-context template read (`states('x') | float`).
- `state_of(entity)` — string-context template read (`states('x')`, no
  `| float`); accepts the same argument shapes as `expr()` (plain entity id
  string, `e.`-registry ref, or `state(...)` builder). Compose string
  comparisons via the same `.eq()`/`.ne()` methods (`states('x') == 'y'` /
  `!=`), and membership via `.in_(["a", "b"])` → `states('x') in ['a', 'b']`
  (a method on `TemplateExpr`, not a module-level name, same convention as
  `.eq()`/`.ne()` themselves).
- `template(raw)` — raw Jinja passthrough (see the trigger/condition note above).
- `param(name)` — inside a `@shared_script` body, a runtime reference to a field
  (see "`@shared_script` parameters" above).
- Operators `>`, `<`, `+`, `-`, `&`, `|`, `~`, `.eq`, `.ne`, `.in_`, … on the
  returned expression build up the Jinja string; a native Python `if` on one
  raises `CompileTimeBranchError`. `.eq()`/`.ne()` against something that
  isn't a `TemplateExpr` or a bare int/float/str/bool literal (e.g. a
  list/dict) raises `TemplateComparisonOperandError` (module-internal,
  `hassle.compiler.templates` — not part of `hassle.__all__`) instead of
  silently `repr()`-ing the value into nonsense Jinja.
- Inverter coverage (`hassle.decompiler.template_invert`, non-public
  tooling): bare `states('x')` (no `| float`) plus `==`/`!=`/`in [...]`
  against a string inverts to `state_of(...)` forms; `is_state('x', 'y')` is
  NOT accepted by the parser at all — it re-renders as `states('x') == 'y'`,
  which differs textually from an `is_state(...)`-authored template, so the
  byte-exact acceptance gate correctly rejects it and the caller falls back
  to the unchanged string form. This is a one-time canonicalization: only
  after the user's own edit (or Hassle's compiled re-render) replaces the
  stored template with the canonical `states(...) == ...` spelling does it
  invert cleanly forever after.

### Runtime-math expression surface (DESIGN §5.4 extension)
Symbolic-expression extension of the template builder (docs/internals/ha-api-notes.md
records no deviation; every builder mirrors HA's Jinja math set 1:1).
- Trig/algebra (bare Jinja function calls): `sin`, `cos`, `tan`, `asin`,
  `acos`, `atan`, `atan2`, `sqrt`, `log`.
- Jinja2-filter mirrors: `round_(x, precision=None)` → `| round` /
  `| round(n)`; `abs_(x)` → `| abs`; `min_(*args)` / `max_(*args)` →
  `[a, b, ...] | min` / `| max` (Jinja2's `min`/`max` filters take an
  iterable, not varargs).
- Constants: `PI`, `E_`, `TAU` — bare `TemplateExpr` leaves rendering to
  Jinja's own global names (`pi`/`e`/`tau`), never folded to a Python float.
- Datetime helpers: `as_datetime(x)`, `as_timestamp(x)`, `today_at(time_str)`,
  `timedelta_(**units)` (trailing underscore so it never collides with
  stdlib `datetime.timedelta`).
- `var(name)` — a runtime reference to an action-level `variables:` key
  (`{{ name }}`); unlike `param()`, freeform (no signature-bound validation).
- `param(name)` always returns a composable `Expr` (`param("x") / 360 * 2 * PI`
  works).
- `.attr(name)` on any entity reference (`EntityRef`, returned by helper
  declarations and by `hassle.registry.entities`) → `state_attr('domain.id',
  'name')`, e.g. `e.sun.sun.attr("elevation")`.
- `concat(*parts)` — explicit string join via Jinja's `~` operator. `+` on a
  `TemplateExpr` is **always arithmetic**, never string concatenation;
  `concat(...)` is the explicit spelling for joining text.
- Full reflected-operator set: `//`, `%`, `**` (with reflected forms) and
  unary `-`, alongside `+ - * /`, comparisons, `& | ~`.
- `PythonMathMisuseError` — Python's stdlib `math.*` (or a bare `float()`/
  `int()`) called on a runtime `TemplateExpr` raises this what/where/fix error
  instead of a bare `TypeError`; `math.pi` etc. as a **plain Python constant**
  is not a trap — it is just a literal, and composes fine.
- **One-way sugar:** the decompiler always reconstructs a compiled Jinja
  string as a raw `template("...")` string; it never re-derives the operator/
  builder call chain (`cos(...)`, `.attr(...)`, …) that produced it.

### Control flow (DESIGN §5.5) — context managers
- `if_then(condition, *, alias=, enabled=)` / `else_then()` / `else_if(condition)`.
- `choose(*, alias=, enabled=)` → use `as c:` then `c.when_(condition, *,
  alias=, enabled=)` / `c.default()`. `c.when_()`'s `alias=`/`enabled=`
  name/toggle *that branch specifically* — a distinct layer from `choose()`'s
  own `alias=`/`enabled=` (the whole block) and from any step's own inside
  the branch's body.
- `repeat_count(n, *, alias=, enabled=)` / `repeat_while(condition, *, alias=,
  enabled=)` / `repeat_until(condition, *, alias=, enabled=)` /
  `repeat_for_each(items, *, alias=, enabled=)`. `repeat_for_each` also
  accepts a bare Jinja template `str` (HA's `repeat.for_each` may be stored
  as a template that renders to a list at runtime, not just a literal list) —
  passed through verbatim, never exploded into a list of characters.
- `parallel(*, alias=, enabled=)` → optionally bind `as p:` and use `with
  p.branch(alias=, enabled=): ...` to group one or more steps into one
  explicit branch, optionally naming/toggling it. A bare `with parallel():
  action(); action()` with **no** `as p:` binding still puts each top-level
  action into its own single-action branch. `p.branch()` is how a branch with
  more than one step is authored.
- `wait_for(*triggers, ..., alias=, enabled=)` / `wait_template(raw, ...,
  alias=, enabled=)`.
- `alias=`/`enabled=` on every construct above (container-level) name and
  toggle whole containers (`if`/`choose`/`repeat`/`parallel`/
  `wait_for_trigger`/`wait_template`) the same way the HA UI does — `with
  if_then(cond, alias="..."):` compiles the `alias` onto the assembled
  `if`-block body, not onto a child step. Omitted by default.

### Dashboards — the eight structural names (dashboards-design §5.2/§5.5)

Card builders live in `hassle.cards` (above); only these eight structural names
are in `hassle.__all__`.

- `dashboard` — `@dashboard(url_path=, default=, title=, icon=,
  show_in_sidebar=, require_admin=)` registers a Lovelace storage-mode
  dashboard. Exactly one of `url_path=` (HA requires the slug to contain a
  hyphen) or `default=True` (THE default dashboard, which has no
  dashboard-registry item and therefore forbids the four metadata keywords).
  Compiles to the two-store envelope `{"meta": {...} | null, "config":
  {"views": [...]}}` (ir-format.md).
- `raw_dashboard` — `@raw_dashboard(url_path=|default=)` over a zero-argument
  function returning either the whole envelope (a dict with a `config` key) or
  just the Lovelace config. A returned `meta` dict MUST carry `url_path`
  (`DashboardUrlPathError`), so a malformed dashboard can never silently key as
  the default one.
- `view` — `with view(title=, path=, icon=, type="sections", max_columns=,
  subview=, visible=, theme=, background=, header=, visibility=, extra=):`.
  One builder for every view type. `type=` takes `"sections"` (the authoring
  default, materialized explicitly), `"masonry"`/`"sidebar"`/`"panel"`
  (verbatim), or **`None`** — which emits *no* `type` key, the legacy-masonry
  storage shape. A `sections` view holds `with section():` blocks; every other
  type holds cards directly, and `panel` holds exactly one.
- `section` — `with section(column_span=, visibility=, extra=):`, stored as
  `{"type": "grid", "cards": [...]}` in the enclosing `sections` view's own
  `sections` list.
- `badge` — `badge(entity_or_dict, *, visibility=, extra=, **options)` records
  into the enclosing view's `badges` list; an entity id builds the modern
  object form, a plain dict passes through verbatim (legacy/unknown badges).
- `raw_card(dict)` / `raw_section(dict)` / `raw_view(dict)` — the structural
  raw ladder (I3): an unmodelled card inside any container, an unmodelled
  section inside a `sections` view, an unmodelled view (e.g. a strategy view)
  inside a `@dashboard` body. Dicts, not YAML strings — the same currency every
  other `raw_*` verb speaks. Never raw a parent merely because a child rawed.

### Raw escape hatches (DESIGN §5.8)
- `raw_trigger(dict)`, `raw_condition(dict)`, `raw_action(dict)` — verbatim
  passthrough of any HA block the DSL doesn't model (normalized by the compiler).

### Trap / error surface (assertable by bundles and tests)
- `CompileTimeBranchError` — raised when a runtime expression is used in a
  Python `if`/`bool()` (DESIGN §5.5).
- `ElseWithoutIfError` — `else_then()`/`else_if()` with no preceding `if`/`choose`.
- `NoParamContextError` — `param()` outside a `@shared_script` body.
- `UnknownParamError` — `param(name)` naming a field absent from the signature.
- `UnknownFieldError` — a `@shared_script` call-site kwarg not among an
  explicit `fields=`'s keys.
- `OnlyIfBlockCoverageError` — an action recorded outside a `with
  only_if(...):` block that covers the whole automation.
- `SharedScriptParamMisuseError` — Python-only operations (`range()`,
  indexing, `len()`, …) applied to a bound shared-script parameter.
- `InclusiveNumericBoundError` — `.state >=`/`.state <=` on an `EntityRef`
  (no inclusive form of `numeric_state`).
- `InOperatorTrapError` — `x.state in [...]` (Python's `in` can't be
  overridden to raise usefully; use `.in_([...])`).
- `ConditionArgumentTypeError` — a plain Python `bool` passed where a
  condition builder is expected.
- `TemplateComparisonOperandError` — module-internal (not in `hassle.__all__`)
  — `.eq()`/`.ne()` against a non-`TemplateExpr`, non-literal value.
- `PythonMathMisuseError` — Python's stdlib `math.*`/`float()`/`int()` called
  on a runtime `TemplateExpr`.

## Stability contract

- **Additions allowed.** New names may be added to `hassle.__all__` at any
  time — e.g. the entity-sugar `e.<domain>.<object_id>` builders, which
  compile down to `service(...)`/`state(...)`. Adding a name is not a
  breaking change.
- **Changes / removals are breaking** and are not permitted without a
  compatibility-contract exception process (CONTRIBUTING.md). This includes:
  renaming a public name, removing one, changing the meaning of a call, or
  narrowing an accepted keyword. Widening a signature with a new optional
  keyword is an addition, not a change.
- **Emitted IR shape is governed by `docs/internals/ir-format.md`** (the
  plural canonical HA schema); the DSL is byte-deterministic and every
  construct has a golden pair under `fixtures/dsl/`.

## Internal extension seams that remain NON-public

These are how new builder families are added; they are **not** in
`hassle.__all__` and downstream bundles must not import them:

- `hassle.compiler.protocols` — `TriggerBuilder` / `ConditionBuilder` /
  `ActionBuilder` (`runtime_checkable` Protocols: `to_trigger`/`to_condition`/
  `to_action`). A new builder implements one of these.
- `hassle.compiler.recording` — `record_trigger`/`record_condition`/
  `record_action`, `recording(...)`, `push_actions`, `_require_active`,
  `RecordedNode`, `Recorder`. The recording machinery a control-flow construct
  drives.
- `hassle.compiler.spans` — `SourceSpan`, `capture_span` (span capture).
- `hassle.compiler.registry` — `Registry`, `RegisteredObject`,
  `PrebuiltObject`, `current_registry`, `fresh`, `Registry.add_object` (the
  pre-built-object registration path used by macro/lib-style bundle code that
  registers an object without going through a `@automation`/`@script`
  decorator).
- `hassle.compiler.bundle` — `CompileResult` (`.objects`, `.spans_for`),
  `compile_bundle`, `compile_registered`. The pipeline output the compiler,
  validator, and simulator consume.
- `hassle.ir` — the frozen IR surface (`docs/internals/ir-format.md`).
- Module-internal helpers exposed only for the builder modules and their unit
  tests: `EntityRef`, `declared_helpers`, `declared_raw_automations`,
  `build_raw_automation`, `TemplateExpr`, `StateExpr`, `NumericStateExpr`, the
  other `*Trigger`/`*Expr` builder classes, `normalize_duration`,
  `ScriptCallAction`, `Raw{Trigger,Condition,Action}`, `capture_span`. These are
  importable from `hassle.compiler` for tooling but are **not** part of the
  frozen bundle-facing surface.
- `hassle.compiler.math_expr` — the sibling module the runtime-math builders
  live in; its module-internal `_call`/`_filter`/`_render_operand`/
  `_render_call_arg` are not part of the frozen surface (only the
  function/constant names re-exported through `hassle.__all__` are).
  `TemplateExpr.render_as_operand(min_prec=...)` (on the frozen-surface
  `TemplateExpr`) is the sanctioned public seam a sibling builder module uses
  to render one expression nested inside another without reaching into the
  private `_as_operand`/`_prec`/`_compound` fields — same convention as
  subclassing `builders._NoBool` for the `__bool__` trap.
- `hassle.compiler.dashboards.recorder` — `DashboardRecorder`,
  `dashboard_recording(...)`, `active_dashboard()`, `RecordedNode`,
  `ContainerFrame`, `DashboardRecorder.push`, `_require_active`, `_CM_DEPTH`,
  and the two record seams **`record_card(body, *, span, what=)`** /
  **`record_badge(body, *, span)`** plus the container seam
  **`push_container(body, *, label, span, child_key="cards", assign=True)`**.
  The dashboard sibling of `record_action`/`Recorder.push_actions`: every
  `hassle.cards` builder is implemented on top of it, so a third-party builder
  pack needs no recorder access of its own. `record_card` takes OWNERSHIP of
  the dict it is given (container cards keep mutating it); the `raw_*` verbs
  copy the author's dict before handing it over.
- `hassle.compiler.dashboards.builders` — `merge_extra`,
  `normalize_visibility`, `put`: the one implementation of the `extra=` merge +
  shadow check and the `visibility=` normalizer every dashboard builder shares.
- `hassle.compiler.dashboards.conditions` — `DashboardCondition` (the
  `to_dashboard_condition()` Protocol, the dashboard sibling of
  `ConditionBuilder`) and `normalize_condition`, the single entry point every
  condition-accepting dashboard parameter uses.
- `hassle.compiler.dashboards.card_registry` — `CardSpec` / `CARD_REGISTRY` /
  `STRUCTURE_REGISTRY` / `register_card`: the frozen (F5) card-type table that
  the card builders register into and that the decompiler's emitter selection
  and the validator's card-tree entity extraction both read.
- `hassle.compiler.registry.register_dashboard` — the dashboard registration
  path (identity is the `url_path`/`default` sentinel, not the function name).
- `hassle.compiler.bundle` — `CompileResult.node_spans_for(obj)` /
  `CompileResult.node_span(obj, path)`, the span sidecar for tree-shaped
  bodies. Path grammar: dot-joined `<key>[<index>]` segments relative to a
  dashboard's `config`, e.g. `views[0].sections[0].cards[2]`.
- `hassle.compiler.recording.active_recorder` — read-only "is an
  automation/script recorder open?", used only so each recorder's
  wrong-context error can name the actual mix-up.
- `hassle.compiler.purpose.normalize_target` — normalizes a bare entity
  ref/`str`, a list of them, or an `area()`/`floor()`/`label()`/`device_id()`
  target helper object into HA's stored `target` dict shape. Every `target=`
  parameter in the frozen surface accepts these forms and normalizes through
  this internal helper; an already-built dict passes through unchanged.

## Acceptance

All golden pairs under `fixtures/dsl/` are green (`test_dsl_golden_pairs.py`
and `hassle-dev goldens`); every fixture-corpus construct is expressible in
the DSL with a backing golden; `test_entity_attr_and_index_equivalent`
(`test_entity_accessor.py`) is green — `e.sensor.hall_motion` and
`e.sensor["hall_motion"]` compile to byte-identical IR.
