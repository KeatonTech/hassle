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
- `script` — `@script(**ha_options)` registers a plain script.
- `shared_script` — `@shared_script(...)` registers a script **and** returns a
  call-site verb (invoking it elsewhere records a `script.<id>` call, DESIGN §5.6).
- `macro` — `@macro` marks a compile-time-inlined function (DESIGN §5.6).
- `raw_automation` — `@raw_automation(id=...)` over a zero-arg function returning
  a verbatim automation dict (DESIGN §5.8; `normalize_ha` is applied).
- `blueprint_automation` — `blueprint_automation(id=, use_blueprint=, inputs=)`;
  maps `inputs=` → stored `use_blueprint.input` with an author-qualified path
  (docs/ha-api-notes.md §10.5).
- Helper declarations (DESIGN §5.7), one per storage-collection domain, each
  returning an `EntityRef` usable as an entity id elsewhere:
  `input_boolean`, `input_number`, `input_select`, `input_text`,
  `input_datetime`, `input_button`, `counter`, `timer`, `schedule`.

### Recording verbs
- `when(*triggers)` — append triggers to the active automation.
- `only_if(*conditions)` — append conditions.

### Core action verbs
- `service(action, *, target=, data=, response_variable=, continue_on_error=,
  **fields)` — the **single** service-call verb (bare kwargs → `data`;
  `response_variable`/`continue_on_error` emit as top-level HA action fields).
- `delay(**units)` — dict-form delay.
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

### Control flow (DESIGN §5.5) — context managers
- `if_then(condition)` / `else_then()` / `else_if(condition)`.
- `choose()` → use `as c:` then `c.when_(condition)` / `c.default()`.
- `repeat_count(n)` / `repeat_while(condition)` / `repeat_until(condition)` /
  `repeat_for_each(items)`.
- `parallel()`.
- `wait_for(*triggers, ...)` / `wait_template(raw)`.

### Raw escape hatches (DESIGN §5.8, I3)
- `raw_trigger(dict)`, `raw_condition(dict)`, `raw_action(dict)` — verbatim
  passthrough of any HA block the DSL doesn't model (normalized by the compiler).

### Trap / error surface (assertable by bundles and tests)
- `CompileTimeBranchError` — raised when a runtime expression is used in a
  Python `if`/`bool()` (DESIGN §5.5).
- `ElseWithoutIfError` — `else_then()`/`else_if()` with no preceding `if`/`choose`.
- `NoParamContextError` — `param()` outside a `@shared_script` body.
- `UnknownParamError` — `param(name)` naming a field absent from the signature.

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

## Acceptance

All M1 golden pairs green (`fixtures/dsl/`, checked by
`test_dsl_golden_pairs.py` and `hassle-dev goldens`); every fixture-corpus
construct expressible in the DSL with a backing golden (the M1 done-gate
expressibility checklist, in the integration report); `test_entity_attr_and_
index_equivalent` (MILESTONES M1 test 8, `test_entity_accessor.py`) green —
`e.sensor.hall_motion` and `e.sensor["hall_motion"]` compile to byte-identical
IR.
