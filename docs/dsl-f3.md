# F3 — Frozen DSL public API surface (end of M1)

> **DECLARED 2026-07-03** (post final review + fixes, 338 tests green). This
> is the frozen contract every bundle and downstream milestone (M2 decompiler,
> M3 stubs/validation, M4 simulator, M7 CLI, M9 docs) builds against.
> Per R5, changing anything frozen here requires updating MILESTONES.md in the
> same PR. **Additions are allowed; changes and removals are not.**

> **Renamed 2026-07-03 (owner decision):** the `hassle-core` distribution now
> ships exactly one top-level import package, `hassle` (previously two:
> `hassle_core` + a thin `hassle` facade). `hassle_core.dsl_builtins` — a
> second re-export of this same surface, kept only so tools could import it
> without depending on the `hassle` package layout — is deleted along with
> `hassle_core` itself; there is now only one module to import this surface
> from, so the parity concern it existed to guard against (and its test,
> `test_dsl_builtins_parity_with_hassle_all`) is moot by construction. All
> module paths below (`hassle_core.compiler.*`, `hassle_core.ir`, …) are now
> `hassle.compiler.*` / `hassle.ir`; the frozen contract itself is unchanged.

> **Widened 2026-07-05 (`ux/shared-script-calls`, owner feedback, F3-additive):**
> the module-internal `ScriptCallAction` (`hassle.compiler.scripts` — already
> listed below as non-frozen tooling surface, not part of `hassle.__all__`)
> gained three optional keyword-only constructor args, `metadata=`/`alias=`/
> `enabled=`, mirroring every other action shape's step options. The
> `@shared_script`-decorated caller wrapper it backs widened the same way:
> `flash_lights(times=5, metadata={...}, alias="...", enabled=False)` is now
> accepted alongside the script's own declared field kwargs. Purely additive —
> no existing call site's signature changed, and `hassle.__all__` itself is
> untouched (`shared_script` was already frozen there; only its returned
> wrapper's accepted kwargs widened). Motivation: the decompiler's new
> function-call rewrite for a caller's `script.<id>` action (DESIGN §7.3) needs
> a way to round-trip a UI-saved action's `metadata: {}` / step `alias`/
> `enabled` through the call site instead of falling back to `service()`.

> **Widened 2026-07-05 (`ux/shared-script-rich-fields`, owner feedback,
> F3-additive):** `@shared_script` gained a `fields=` kwarg carrying full HA
> field metadata (`name`/`description`/`selector`/`example`/...) VERBATIM —
> when supplied it wins over the signature-derived `fields` dict (byte-
> stability by construction), since real HA-UI-authored scripts always carry
> this richer shape (the narrower signature-only rule made the decompiler's
> caller-rewrite feature inert on real bundles: every field forced the
> `@script` fallback). The signature stays the ergonomic call-site layer —
> every declared field is still a real Python parameter, `None`-defaulted
> when the metadata carries no `"default"` key (HA-side requiredness lives in
> the metadata, not in whether the compiler can invoke the body with zero
> arguments to build its sequence). New error `UnknownFieldError` (added to
> `hassle.__all__`, surface count 72 → 73): a call-site kwarg not among
> `fields=`'s keys (the superset source of truth when `fields=` is explicit)
> is rejected even if it would otherwise bind against the signature — catches
> an author who added a Python parameter but forgot to also declare it as a
> field. Purely additive; no existing name's meaning changed.

> **Widened 2026-07-05 (`ux/triggers-in-decorator`, owner-approved DSL
> evolution, task #10, F3-additive):** `@automation` gained a `triggers=`
> keyword-only kwarg: a list of `TriggerBuilder` objects — the same objects
> `when()` accepts — evaluated at decoration time (built when the
> `@automation(...)` line itself runs, before the compiler invokes the
> function body). This is now the CANONICAL decompiled form (DESIGN §5.3/§7.3):
> the decompiler emits `triggers=[...]` in the decorator instead of a
> `when(...)` call at the top of the body, multi-line (one trigger per line)
> when there's more than one. `when()` itself is UNCHANGED and remains fully
> supported (F3 forbids removing it) — still the right tool when the trigger
> list must be built dynamically (a compile-time loop, a shared helper
> function, …), since `triggers=`'s list is one Python expression evaluated
> once, at decoration time, and so can only ever be a single static list
> literal. `triggers=` and `when()` COMPOSE: the decorator's list is recorded
> first, then any `when()` calls inside the body append after it, in call
> order — see DESIGN §5.3's position-independence note. Compile parity is
> exact: `@automation(triggers=[state(x).to("on")])` produces byte-identical
> IR to the equivalent `when(state(x).to("on"))` form (golden pair
> `fixtures/dsl/triggers_in_decorator/`, proven against the `when()`-form
> golden `fixtures/dsl/state_delay_service/`'s identical `expected_ir.json`).
> Purely additive: no existing name's meaning changed, `hassle.__all__` itself
> is untouched (`automation` was already frozen there; only its accepted
> kwargs widened).

> **Widened 2026-07-05 (`ux/dsl-ergonomics`, owner feedback, F3-additive,
> surface count 98 → 101 — the doc's earlier "72"/"73" counts predate several
> unrelated widenings and were never kept current; this note states the
> actual delta this workstream makes, not a running total):** four DSL
> ergonomics changes, all additive.
> (1) `only_if(*conditions)` — already frozen — is now dual-form: the bare
> call is byte-for-byte unchanged (F3); the SAME call is also usable as
> `with only_if(...):`, which additionally requires every action the
> automation records to be inside that one block (an action recorded
> before/after it raises the new `OnlyIfBlockCoverageError`, added to
> `hassle.__all__`). The decompiler now emits the block form as canonical
> whenever an automation has any conditions at all, wrapping every action —
> compiled IR is byte-identical either form (golden pair
> `fixtures/dsl/only_if_block_form/` vs. `fixtures/dsl/only_if_bare_form_parity/`).
> (2) Two new `StrEnum` names, `Mode` and `MaxExceeded` (added to
> `hassle.__all__`), for HA's enumerated `mode:`/`max_exceeded:` automation/
> script options — a real `str` subclass, so `mode=Mode.RESTART` compiles
> byte-identical to `mode="restart"`; the decompiler emits the enum member
> for a recognized value and falls back to the raw string otherwise (never
> fails on an unrecognized future HA value). (3) `service(..., target=...)`
> (and every other `target=` accepting call) now also accepts a bare entity
> ref/`str`, a list of them, or an `area()`/`floor()`/`label()`/`device_id()`
> target helper object directly — normalized to HA's stored target dict shape
> by the new `hassle.compiler.purpose.normalize_target` (non-public tooling
> seam, not added to `hassle.__all__`); an already-built dict passes through
> unchanged. The decompiler emits the bare form whenever a stored `target`
> has exactly one key, keeping the dict literal for any multi-key target.
> (4) `repeat_for_each(items)` now also accepts a bare Jinja template `str`
> (HA's `repeat.for_each` may be stored as a template that renders to a list
> at runtime, not just a literal list) — passed through verbatim, never
> exploded into a list of characters (the bug this fixes, docs/ha-api-notes.md).
> None of these four changes alters the meaning of any existing name;
> `hassle.__all__` itself gains exactly three entries (`Mode`, `MaxExceeded`,
> `OnlyIfBlockCoverageError`) and `only_if`'s existing frozen entry is
> untouched (only its usage — bare vs. `with` — widened).

The public surface is exactly `hassle.__all__` (module
`packages/hassle-core/src/hassle/__init__.py`). Bundle files write
`from hassle import automation, when, ...`; nothing outside this list is public.

Current surface: **72 names**, plus one dedicated entry point (`hassle.registry`,
below) that is deliberately *not* folded into `hassle.__all__` because DESIGN
§5.3 imports it under its own alias (`from hassle.registry import entities as e`).

### Entity indexing form — `hassle.registry.entities` (DESIGN §5.2/§5.3, M1 test 8)

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
is the M1 *runtime* shape and is domain-open (no registry snapshot backs it);
M3 layers generated, typed `.pyi`
stub classes with the identical attribute/index shape on top, so a bad
attribute name becomes a pyright error in the editor without changing how
bundles are written.

## The frozen surface, grouped by role

### Object decorators / declarations (top-level objects)
- `automation` — `@automation(**ha_options)` registers an automation.
  `triggers=` (F3-additive, `ux/triggers-in-decorator`) is a list of
  `TriggerBuilder` objects recorded at decoration time — the canonical,
  decompiler-emitted way to attach triggers; composes with `when()` (below),
  which remains the tool for a dynamically-built trigger list.
- `script` — `@script(**ha_options)` registers a plain script.
- `shared_script` — `@shared_script(...)` registers a script **and** returns a
  call-site verb (invoking it elsewhere records a `script.<id>` call, DESIGN §5.6).
- `macro` — `@macro` marks a compile-time-inlined function (DESIGN §5.6).
- `raw_automation` — `@raw_automation(id=...)` over a zero-arg function returning
  a verbatim automation dict (DESIGN §5.8; `normalize_ha` is applied).
- `blueprint_automation` — `blueprint_automation(id=, use_blueprint=, inputs=,
  alias=, description=)`; maps `inputs=` → stored `use_blueprint.input` with an
  author-qualified path (docs/ha-api-notes.md §10.5). `alias=`/`description=`
  are an M2 addition (widening, not a break — real blueprint automations carry
  these top-level fields alongside `use_blueprint`, docs/ha-api-notes.md §10.5).
- Helper declarations (DESIGN §5.7), one per storage-collection domain, each
  returning an `EntityRef` usable as an entity id elsewhere:
  `input_boolean`, `input_number`, `input_select`, `input_text`,
  `input_datetime`, `input_button`, `counter`, `timer`, `schedule`.
- **M10 ADDITION** — template-helper declarations (config-entry domain, DESIGN
  §13's config-entry plugin, docs/ha-api-notes.md §26): `template_number(name=,
  state=, set_value=, min=, max=, step=, unit_of_measurement=, icon=)`,
  `template_sensor(name=, state=, unit_of_measurement=, device_class=, icon=)`,
  `template_binary_sensor(name=, state=, device_class=, icon=)`,
  `template_select(name=, state=, options=, select_option=, icon=)`. Same
  import-and-reference pattern as the storage-collection helpers above
  (returns an `EntityRef`).
  **No `id=`/`unique_id=` kwarg** (redesigned 2026-07-05, docs/ha-api-notes.md
  §26.6, CI evidence: real HA's config-flow form schema rejects an
  unrecognized `unique_id` key outright — a flow-created entry has no
  caller-settable unique id at all). `name=` is the sole identity-bearing
  kwarg: the object key is `"<domain>:<slugify(name)>"`, mirroring the
  storage helpers' "id is a slug of name" rule. `set_value=` on
  `template_number` and `select_option=` on `template_select` are REQUIRED
  (HA's own form schema rejects the submission without them — a number/select
  needs a write-target action sequence; `template_sensor`/
  `template_binary_sensor` are read-only and need neither). The HA-assigned
  `entry_id` is manifest-only (docs/backend.md), never in the DSL body.

### Recording verbs
- `when(*triggers)` — append triggers to the active automation. Fully
  supported alongside `@automation(triggers=...)` (composes, decorator list
  first) — the right tool for a dynamically-built trigger list; no longer the
  decompiler's canonical output form (`ux/triggers-in-decorator`), but never
  removed (F3).
- `only_if(*conditions)` — append conditions.

### Core action verbs
- `service(action, *, target=, data=, data_template=, response_variable=,
  continue_on_error=, metadata=, alias=, enabled=, **fields)` — the **single**
  service-call verb (bare kwargs → `data`; `response_variable`/
  `continue_on_error`/`metadata`/`data_template`/`alias`/`enabled` emit as
  top-level HA action fields). `metadata=` is a real-world smoke-test ADDITION
  (docs/ha-api-notes.md §19.1): the HA UI stamps `"metadata": {}` on every
  action it saves; passing it (even as `{}`) round-trips that byte-stable.
  Omitted by default. `data_template=`/`alias=`/`enabled=` are residue-coverage
  round-2 ADDITIONS (docs/ha-api-notes.md §20): `data_template=` is the legacy
  templated-data key, a sibling of `data` never folded into it; `alias=`/
  `enabled=` name/toggle the individual step (the HA UI does this on every
  step). All three omitted by default.
- `delay(*, alias=, enabled=, **units)` — dict-form delay. `alias=`/`enabled=`
  are the same residue-coverage round-2 ADDITION, keyword-only so they never
  collide with a duration unit.
- `variables(**kwargs)` — a `variables` action.
- `stop(message=None, *, error=None)` — a `stop` action.
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
  `numeric_state(entity_id, ...)`'s `entity_id` accept `str | list[str]`
  (real-world smoke-test ADDITION, docs/ha-api-notes.md §19.2): the HA UI
  always stores these fields as a list, even for a single entity/value, and a
  singleton list decompiles back to a list, never a scalar. Residue-coverage
  round 2 (docs/ha-api-notes.md §20) extended the **decompiler** side of this
  to the `state` **condition** path (`to_condition()`'s `entity_id`/`state`
  were already list-capable at the builder level since round 1; only
  `hassle.decompiler.exprs._cond_state` needed the matching widening) — no
  further DSL surface change, since `state()` is the same dual-purpose builder.
- `time(at=, after=, before=, weekday=)`: `weekday=` is now also emitted on the
  **trigger** side, not condition-only as originally documented (real-world
  smoke-test ADDITION, docs/ha-api-notes.md §19.3 — HA's `time` trigger schema
  accepts it). `at=` accepting an entity reference (`input_datetime.x`) needed
  no code change (`at` was always a plain `str`) but is noted there too.

### Condition combinators
- `all_of(*conditions)`, `any_of(*conditions)`, `not_(condition)`.

### Purpose-specific builders (2026.7+, DESIGN §5.4)
- `on(type, *, target=, behavior=, for_=, **options)` — purpose **trigger**.
- `met(type, *, target=, **options)` — purpose **condition**.
- Target constructors: `area`, `floor`, `label`, `device_id` (plus a plain
  entity-id string or an entity ref).

### Duration helpers
- `hours`, `minutes`, `seconds` — build the `for_=` / duration values.

### Template expression builder
- `expr(entity)` — numeric-context template read (`states('x') | float`).
- `template(raw)` — raw Jinja passthrough (see the trigger/condition note above).
- `param(name)` — inside a `@shared_script` body, a runtime reference to a field.
- (Operators `>`, `<`, `+`, `-`, `&`, `|`, `~`, `.eq`, `.ne`, … on the returned
  expression build up the Jinja string; a native Python `if` on one raises
  `CompileTimeBranchError`.)

### Runtime-math expression surface (M1.1 ADDITION, DESIGN §5.4 extension)
Symbolic-expression extension of the template builder (docs/ha-api-notes.md
records no deviation; every builder mirrors HA's Jinja math set 1:1). All of
this is additive to `hassle.__all__`; nothing above changed.
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
- `param(name)` is now documented as a composable `Expr`: it always returned
  a `TemplateExpr` (no behavior changed), this milestone just exercises and
  pins that composability (`param("x") / 360 * 2 * PI`).
- `.attr(name)` on any entity reference (`EntityRef`, returned by helper
  declarations and by `hassle.registry.entities`) → `state_attr('domain.id',
  'name')`, e.g. `e.sun.sun.attr("elevation")`.
- `concat(*parts)` — explicit string join via Jinja's `~` operator. Documented
  decision: `+` on a `TemplateExpr` is **always arithmetic**, never string
  concatenation; `concat(...)` is the explicit spelling for joining text.
- Full reflected-operator set: `//`, `%`, `**` (with reflected forms) and
  unary `-`, alongside the M1 set (`+ - * /`, comparisons, `& | ~`).
- `PythonMathMisuseError` — Python's stdlib `math.*` (or a bare `float()`/
  `int()`) called on a runtime `TemplateExpr` raises this what/where/fix error
  instead of a bare `TypeError`; `math.pi` etc. as a **plain Python constant**
  is not a trap — it is just a literal, and composes fine.
- **One-way sugar:** the M2 decompiler always reconstructs a compiled Jinja
  string as a raw `template("...")` string; it never re-derives the operator/
  builder call chain (`cos(...)`, `.attr(...)`, …) that produced it.

### Control flow (DESIGN §5.5) — context managers
- `if_then(condition, *, alias=, enabled=)` / `else_then()` / `else_if(condition)`.
- `choose(*, alias=, enabled=)` → use `as c:` then `c.when_(condition, *,
  alias=, enabled=)` / `c.default()`. `c.when_()`'s `alias=`/`enabled=` are a
  residue-coverage round-3 ADDITION (docs/ha-api-notes.md §21.1): they name/
  toggle *that branch specifically* — a third, distinct layer from `choose()`'s
  own `alias=`/`enabled=` (the whole block) and from any step's own inside the
  branch's body.
- `repeat_count(n, *, alias=, enabled=)` / `repeat_while(condition, *, alias=,
  enabled=)` / `repeat_until(condition, *, alias=, enabled=)` /
  `repeat_for_each(items, *, alias=, enabled=)`.
- `parallel(*, alias=, enabled=)` → optionally bind `as p:` and use `with
  p.branch(alias=, enabled=): ...` (residue-coverage round-3 ADDITION,
  docs/ha-api-notes.md §21.1/§21.2) to group one or more steps into one
  explicit branch, optionally naming/toggling it. A bare `with parallel():
  action(); action()` with **no** `as p:` binding is unchanged: each top-level
  action still becomes its own single-action branch, exactly as before this
  addition (fully backward compatible, no pre-existing caller's compiled
  output changes). `p.branch()` is also how a branch with more than one step
  is authored — round-2-and-earlier `parallel()` had no way to group multiple
  actions into a single branch at all.
- `wait_for(*triggers, ..., alias=, enabled=)` / `wait_template(raw, ...,
  alias=, enabled=)`.
- `alias=`/`enabled=` on every construct above (container-level) are
  residue-coverage round-2 ADDITIONS (docs/ha-api-notes.md §20): the HA UI
  names and toggles whole containers (`if`/`choose`/`repeat`/`parallel`/
  `wait_for_trigger`/`wait_template`) the same way it does leaf actions —
  `with if_then(cond, alias="..."):` compiles the `alias` onto the assembled
  `if`-block body, not onto a child step. Omitted by default (unchanged
  behavior for every pre-existing caller).

### Raw escape hatches (DESIGN §5.8, I3)
- `raw_trigger(dict)`, `raw_condition(dict)`, `raw_action(dict)` — verbatim
  passthrough of any HA block the DSL doesn't model (normalized by the compiler).

### Trap / error surface (assertable by bundles and tests)
- `CompileTimeBranchError` — raised when a runtime expression is used in a
  Python `if`/`bool()` (DESIGN §5.5).
- `ElseWithoutIfError` — `else_then()`/`else_if()` with no preceding `if`/`choose`.
- `NoParamContextError` — `param()` outside a `@shared_script` body.
- `UnknownParamError` — `param(name)` naming a field absent from the signature.
- `PythonMathMisuseError` (M1.1 ADDITION) — Python's stdlib `math.*`/`float()`/
  `int()` called on a runtime `TemplateExpr` (MILESTONES M1.1 test 3).

## Stability contract

- **Additions allowed.** Later milestones may add names to `hassle.__all__`
  (e.g. the M3 entity-sugar `e.<domain>.<object_id>` builders, which compile down
  to `service(...)`/`state(...)`). Adding a name is not a breaking change.
- **Changes / removals are breaking** and require a MILESTONES.md update in the
  same PR. This includes: renaming a public name, removing one, changing the
  meaning of a call, or narrowing an accepted keyword. Widening a signature
  with a new optional keyword is an addition, not a change.
- **Emitted IR shape is governed by F1** (the plural canonical HA schema); the
  DSL is byte-deterministic (R8) and every construct has a golden pair under
  `fixtures/dsl/`.

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
  `PrebuiltObject`, `current_registry`, `fresh`, `Registry.add_object` (the §12
  pre-built-object registration path).
- `hassle.compiler.bundle` — `CompileResult` (`.objects`, `.spans_for`),
  `compile_bundle`, `compile_registered`. The pipeline output the compiler,
  validator, and simulator consume.
- `hassle.ir` — the F1 IR surface (frozen separately).
- Module-internal helpers exposed only for the builder modules and their unit
  tests: `EntityRef`, `declared_helpers`, `declared_raw_automations`,
  `build_raw_automation`, `TemplateExpr`, `StateExpr`, `NumericStateExpr`, the
  other `*Trigger`/`*Expr` builder classes, `normalize_duration`,
  `ScriptCallAction`, `Raw{Trigger,Condition,Action}`, `capture_span`. These are
  importable from `hassle.compiler` for tooling but are **not** part of the
  frozen bundle-facing surface.
- `hassle.compiler.math_expr` (M1.1 ADDITION) — the sibling module the
  runtime-math builders live in; its module-internal `_call`/`_filter`/
  `_render_operand`/`_render_call_arg` are not part of the frozen surface
  (only the function/constant names re-exported through `hassle.__all__`
  are). `TemplateExpr.render_as_operand(min_prec=...)` (on the frozen-surface
  `TemplateExpr`) is the sanctioned public seam a sibling builder module uses
  to render one expression nested inside another without reaching into the
  private `_as_operand`/`_prec`/`_compound` fields — same convention as
  subclassing `builders._NoBool` for the `__bool__` trap.

## Acceptance

All M1 golden pairs green (`fixtures/dsl/`, checked by
`test_dsl_golden_pairs.py` and `hassle-dev goldens`); every fixture-corpus
construct expressible in the DSL with a backing golden (the M1 done-gate
expressibility checklist, in the integration report); `test_entity_attr_and_
index_equivalent` (MILESTONES M1 test 8, `test_entity_accessor.py`) green —
`e.sensor.hall_motion` and `e.sensor["hall_motion"]` compile to byte-identical
IR.
