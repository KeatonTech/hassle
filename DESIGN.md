# Hassle — Design Document

**Hassle** (HASS + hassle): a round-trip toolchain for Home Assistant automations, scripts,
and helpers. Pull everything down as clean Python, edit and unit-test locally, push back up —
while everything stays fully editable in the Home Assistant UI.

Status: **DRAFT v2 — CLI-only architecture (owner-approved direction, 2026-07-03).**
Companion documents: [CONTRIBUTING.md](CONTRIBUTING.md) (the engineering rules and gates) and
[docs/history/milestones.md](docs/history/milestones.md) (the original implementation plan this
project was built against — historical record, with a vocabulary legend).

> **v2 change (decision record):** v1 of this design included a Home Assistant add-on that
> proxied all API traffic and persisted bundle files server-side. It was cut. Every HA API
> Hassle needs is directly reachable by a CLI holding a long-lived access token, and **git is
> the source of truth for sources and tests** (the Terraform model: the platform stores the
> live objects, your repo stores the code). This works on every HA install type (OS,
> Supervised, Container, Core), adds no listening service to the network, and removes an entire
> Docker/server codebase. (A best-effort in-HA "mirror" of the bundle
> ZIP was designed here and later removed — §8.5.) The `Backend` protocol keeps the door open for a
> future add-on if a server-side feature ever earns one (§13).

---

## 1. Goals and non-goals

### Goals

| # | Requirement | How Hassle addresses it |
|---|---|---|
| G1 | Pull automations, scripts, helpers to a ZIP of clean text | `hassle pull` merges live HA state into a Python **bundle** directory (§6); `--zip` emits/consumes ZIP as a transport format |
| G2 | Edit locally, push back, including adds/deletes | Full-state sync with a Terraform-style plan/apply flow (§8) |
| G3 | Everything remains UI-editable | Hassle only writes through HA's native config APIs — the same ones the UI uses. No custom YAML packages, ever. (§4, invariant I1) |
| G4 | Python-based syntax, not YAML | Embedded Python DSL compiled to HA-native JSON (§5) |
| G5 | Unit tests persist across the edit cycle | pytest + a local HA simulator; tests live in the bundle, whose source of truth is **git** (§8.4). ~~Optional: mirror the bundle ZIP into HA's media storage (best-effort)~~ *(mirror removed — §8.5)*. *Revised from "persisted inside HA" — see the v2 decision record above.* |
| G6 | Entity/reference validation | Four-tier validation: pyright → compile → registry → server-side check (§9) |
| G7 | Macros / reusable logic | `@macro` (compile-time inlining) and `@shared_script` (compiles to a real HA script) (§5.6) |
| G8 | Conflict detection on push | Per-object three-way merge against a `manifest.lock` baseline, hashes re-verified at apply time (§8) |
| G9 | Live test-run against the real instance | Shadow-deploy + trigger + trace streaming (§10.4) |
| G10 | VS Code autocompletion/highlighting | Generated type stubs make pyright/Pylance do the heavy lifting; thin extension on top (§11) |
| G11 | AI-agent-optimized docs | Generated `AGENTS.md` + stable DSL reference shipped inside every bundle (§12) |
| G12 | Extensible to scenes, more helpers, dashboards | Everything is an `ObjectType` plugin; transport is behind a `Backend` protocol (§13) |

### Non-goals (v1)

- Managing YAML-only configuration (packages, `configuration.yaml` integrations, Lovelace YAML mode).
- ~~Managing config-entry helpers~~ **Revised (owner decision, 2026-07-05):** template-domain
  config-entry helpers are now in scope as M10 (the first §13 plugin); other config-entry
  domains (threshold, derivative, group, …) remain follow-ons.
- Replacing HA's execution engine. Hassle compiles **to** native HA automations; nothing runs
  through Hassle at runtime. If Hassle is deleted, everything keeps working.
- Multi-user concurrent editing beyond conflict *detection* (no CRDT/merge editor).
- A Home Assistant add-on (see the v2 decision record).

---

## 2. The core idea in one page

```
┌────────────────────── laptop ──────────────────────┐      ┌───── Home Assistant ─────┐
│  bundle/  — a git repo (source of truth for        │      │                          │
│  sources + tests); ZIP is just a transport format  │      │  HA Core APIs (the same  │
│   ├── <category>.py, misc.py  (see §6 for the      │ pull │  ones the UI uses):      │
│   │    current, category-first layout — MILESTONES │──────┼─ config REST API         │
│   │    M15 retired the old automations/scripts/    │      │  (automations, scripts)  │
│   │    helpers/ per-kind trees this diagram once    │      │                          │
│   │    showed here)                                │      │                          │
│   ├── lib/*.py      (macros)  ─────────────────────┼──────┼─►WebSocket API (helpers, │
│   ├── tests/test_*.py                       push   │      │  registry, validation,   │
│   ├── stubs/  (generated .pyi)         (plan/apply)│      │  traces, templates)      │
│   ├── .hassle/ (manifest.lock, registry snapshot)  │      │                          │
│   └── AGENTS.md, docs/                             │      │  → automations.yaml,     │
│                                                    │      │    scripts.yaml,         │
│  hassle CLI: pull · plan · push · validate · test  │      │    .storage/* — the SAME │
│  · run --live · fmt · stubs · explain              │      │    storage the UI edits  │
│  pytest: runs tests on the local simulator         │      │                          │
│  git: history, sync between machines, backup       │      │                          │
└────────────────────────────────────────────────────┘      │                          │
                     auth: one long-lived HA token          └──────────────────────────┘
```

- **HA is the source of truth for live objects** (automations, scripts, helpers). **Git is the
  source of truth for source text, tests, macros, and docs.** `manifest.lock` (committed to
  git) is the merge base tying the two together.
- Bundle files are **real Python**. The CLI *compiles* them to the exact JSON HA stores
  natively, and *decompiles* HA's JSON back into DSL Python. Compilation is deterministic;
  decompilation is deterministic and stable.
- **The edit loop is a merge loop** (§8.4): `hassle pull` three-way-merges UI-side changes into
  your working tree (like `git pull` from the house), you edit and test, `hassle push`
  plan/applies your changes to HA, and you commit the result. UI edits and your edits both
  survive; overlaps surface as explicit conflicts.
- **Source preservation is local:** pull only touches files for objects whose live HA config
  drifted from the manifest baseline — everything else keeps your hand-written formatting and
  comments untouched. A fresh machine gets the sources from `git clone`, not from HA.

### Invariants (implementing agents: never violate these)

- **I1 — UI editability.** Every write goes through the same HA APIs the UI uses
  (`/api/config/...` REST, helper WebSocket collections). Never write YAML files directly.
- **I2 — Stable identity.** An object's HA `id` is its identity. The toolchain never changes an
  existing `id`; entity registry data (entity_id, areas, labels, categories) survives because of this.
- **I3 — Lossless round-trip.** `compile(decompile(x)) == x` (semantic JSON equality) for *any*
  HA config, via the `raw` escape hatch (§5.8) when the DSL can't model a construct. Precisely:
  equality is modulo HA's *own* storage normalization (HA ≥ 2024.10 rewrites legacy singular
  `trigger/condition/action` + `service:` to the plural schema before storing — see
  docs/ha-api-notes.md §10.1), so `compile(decompile(x)) == normalize_ha(x)`; for configs as HA
  actually stores and returns them — the only ones the sync engine ever sees — that is exact
  equality.
- **I4 — No runtime dependency.** HA never depends on Hassle to execute anything.
- **I5 — Tests test the artifact.** The simulator executes the *compiled JSON*, not the Python,
  so tests validate exactly what will be uploaded.
- **I6 — Never clobber silently.** Any sequence of local edits, UI edits, and syncs either
  preserves both sides or stops with an explicit conflict (§8.2). This is fuzz-tested.

---

## 3. Components

| Component | Language / stack | Purpose |
|---|---|---|
| `hassle-core` (import package: `hassle`) | Python 3.12, pydantic v2, jinja2, LibCST | IR, compiler, decompiler, validator, simulator, sync engine, `Backend` protocol + `DirectBackend` (REST/WS client for HA Core) |
| `hassle-cli` | Python (click or typer), rich, keyring | `pull/plan/push/validate/test/run/fmt/stubs/explain/doctor` |
| VS Code extension | TypeScript (thin) + pyright | Commands, diagnostics from `hassle validate`, entity hovers (stretch) |
| Docs generator | part of `hassle-core` | Emits `AGENTS.md`, entity inventory, DSL reference into every bundle |

Repository layout (monorepo):

```
hassle/
├── packages/
│   ├── hassle-core/          # the shared library (most of the code lives here)
│   └── hassle-cli/
├── vscode-extension/
├── fixtures/                 # corpus of real HA JSON configs + registry snapshots
├── docs/                     # DSL reference, cookbook, agent docs templates, ha-api-notes.md
├── DESIGN.md  CONTRIBUTING.md   # milestone plan preserved in docs/history/
└── pyproject.toml            # uv workspace; ruff + pyright strict on hassle-core
```

---

## 4. How Home Assistant stores these objects (verified API surface)

This is the substrate everything sits on. All facts below were verified against HA core source
and official docs in July 2026 (config REST handlers in `homeassistant/components/config/view.py`,
storage collections in `helpers/collection.py`, media source in
`components/media_source/local_source.py`, etc.). Implementing agents: **still re-verify
behaviorally against a live HA instance** (docs/history/milestones.md, M0.V); HA
versions drift.

| Object | Native storage | Read | Write/Delete |
|---|---|---|---|
| Automations | `automations.yaml`, keyed by `id` | Enumerate: list states for domain `automation`, read `attributes.id`; fetch: `GET /api/config/automation/config/{id}` | `POST/DELETE /api/config/automation/config/{id}` (auto-reloads) |
| Scripts | `scripts.yaml`, keyed by object_id | object_id from `entity_id`; `GET /api/config/script/config/{object_id}` | `POST/DELETE` same path |
| Helpers (storage-collection): `input_boolean`, `input_number`, `input_select`, `input_text`, `input_datetime`, `input_button`, `counter`, `timer`, `schedule` | `.storage/{domain}` | WS `{domain}/list` (also `{domain}/subscribe`) | WS `{domain}/create`, `{domain}/update`, `{domain}/delete` — update/delete take the item id as `{domain}_id` (e.g. `input_boolean_id`). Storage items are `editable: true`; YAML-defined helpers coexist as `editable: false` and are out of scope (I1) |
| Entity/device/area/floor/label registries | `.storage/*` | WS `config/entity_registry/list`, `config/device_registry/list`, `config/area_registry/list`, `config/floor_registry/list`, `config/label_registry/list` | (read-only for Hassle v1) |
| Services + schemas | — | WS `get_services` | — |
| Validation | — | WS `validate_config` (trigger/condition/action blocks); `POST /api/config/core/check_config` | — |
| Traces | — | WS `trace/list` (domain [+ item_id]); `trace/get` requires domain + item_id + **run_id**; admin-only | — |
| Template render | — | `POST /api/template`; WS `render_template` (subscription; `strict`, `report_errors` flags) | — |
| Media (~~optional mirror~~ — removed, §8.5) | `/media` dir | WS `media_source/browse_media`, `media_source/resolve_media`; authenticated `GET /media/{source}/{path}` | `POST /api/media_source/local_source/upload` (admin, multipart `media_content_id` + `file`); WS `media_source/local_source/remove` |

API quirks the implementation must respect (source-verified July 2026, then behaviorally
verified against a live instance in M0.V — details and raw captures in
[docs/ha-api-notes.md](docs/ha-api-notes.md), corrections in its §10):

- **Plural schema normalization (HA ≥ 2024.10).** The config API accepts legacy singular keys
  (`trigger/condition/action`, `service:`) but **stores and returns the plural form**
  (`triggers/conditions/actions`, `action:`). WS `validate_config` rejects singular outer keys
  outright. Hassle's compiled and canonical-hashed form is therefore always plural (§7.1).
- **Automation `entity_id` derives from the alias, not the id** (`slug(alias)`). Never construct
  `automation.<id>`; resolve entity_ids by matching `attributes.id` from `/api/states`.
- **Purpose-specific triggers/conditions (HA 2026.7+, web-verified July 2026).** HA 2026.7 made
  a new trigger/condition vocabulary the UI default: 200+ namespaced types stored as
  `trigger: <domain>.<event>` (e.g. `motion.detected`, `battery.became_low`,
  `vacuum.returned_to_dock`) with a `target:` block (`entity_id`/`device_id`/`area_id`/
  `floor_id`/`label_id`), a `behavior:` key (`first`/`each`/`all` multi-target semantics), and
  an `options:` block (e.g. `for:`). Same plural storage schema, same config API — the UI will
  generate these constantly from 2026.7 on, so Hassle must treat them as first-class (§5.4),
  not `raw`. Caution: HA renamed several of these keys between their Labs debut and 2026.7
  (e.g. `battery.low` → `battery.became_low`, `schedule.turned_on` → `schedule.block_started`)
  **without migration — old keys simply stop working** — so the vocabulary must be treated as
  data (enumerated from the instance, validated with rename hints), never hard-coded. M6 must
  find and capture the WS API the UI uses to enumerate available purpose types (M0.V ran on
  2026.2.3 and could not).
- `automation.trigger`'s `skip_condition` **defaults to `true`** — live runs must pass
  `skip_condition: false` explicitly unless the user asked for `--skip-conditions` (§10.4).
- The automation `id` attribute has moved into `capability_attributes` in recent HA — it still
  surfaces in `/api/states` attribute payloads, but don't assume its position in internals.
- The media endpoints have **two independent incidental gates** the (since-removed) mirror (§8.5) had to pass:
  upload checks only the client-supplied multipart `Content-Type` (must start with `image/`,
  `video/`, or `audio/`; bytes/extension never inspected), while **download** (`GET /media/…`)
  404s unless the file *extension* maps to an image/video/audio MIME type. So the mirrored ZIP
  must be stored under a media extension (e.g. `bundle.mp3`; bytes unchanged). Also: never
  upload to the media root (its signed URLs are broken — notes §10.4), and the target subfolder
  must already exist (upload does not mkdir; M6 determines the folder-creation story). Treat the
  whole mirror as fragile by design.
- On HAOS/Supervised, `/media` is a **separate opt-in toggle in backups** (recommended off by
  HA). Do not claim mirrored files are in backups unless the user enables that toggle.
- Long-lived access tokens have no introspection endpoint; validity is checked by making any
  API call (401 ⇒ invalid). CLI validates on `hassle login` via `GET /api/config`.

---

## 5. The DSL

### 5.1 Why embedded Python (decision record)

Alternatives considered:

1. **Custom language + custom parser + custom LSP** — full control over syntax, but we'd hand
   a swarm of models a compiler-and-LSP project. Highest risk, worst tooling on day one.
2. **Structured Python-ish YAML alternative (e.g. Pkl, CUE)** — still "a config language", user
   asked for Python-like scripting; no pytest story.
3. **Embedded Python DSL** (chosen) — bundle files are real Python. We get for free:
   the parser (CPython), formatting (ruff), syntax highlighting (every editor), **autocompletion
   and typo-catching via generated type stubs + pyright**, unit tests via pytest, and macros as
   plain functions. The compiler is "trace a function call and build JSON", which is a small,
   very testable program.

The trade-off: Python executes at *compile time*, so runtime control flow needs explicit
constructs (§5.5). This is a real sharp edge; it is mitigated by trap-catching (§5.5) and is a
headline item in the agent docs (§12).

### 5.2 Entities and services — generated, typed

`hassle stubs` generates from the registry snapshot (§9.2):

```python
# stubs/entities.pyi  (generated — gives pyright full knowledge of YOUR instance)
class _Light:
    hallway: LightEntity          # light.hallway — "Hallway Ceiling", area: Hallway
    living_room: LightEntity
class _BinarySensor:
    hall_motion: BinarySensorEntity
...
```

Domain entity classes expose typed service methods generated from `get_services` schemas
(`LightEntity.turn_on(brightness_pct: int | Template = ..., transition: float = ...)`).
Entity object_ids match `(?!_)[\da-z_]+(?<!_)` — lowercase alphanumerics and underscores, but
they **may start with a digit** (`sensor.3d_printer` is legal). The stub generator therefore
prefixes digit-leading object_ids with an underscore (`e.sensor._3d_printer`, with the real
entity_id in the docstring), and every domain class also supports indexing
(`e.sensor["3d_printer"]`) as the universal escape hatch. The compiler resolves both to the same
entity reference.

Result: `e.light.halway` is a **pyright error in the editor**, before any tool runs.

### 5.3 Automations

```python
# automations/hallway.py
from hassle import automation, only_if, state, sun, delay, if_then
from hassle.registry import entities as e
from helpers.modes import guest_mode
from lib.notify import notify_adults

@automation(
    id="hall_light_on_motion",   # HA identity — NEVER change once deployed (tooling enforces)
    alias="Hallway: light on motion",
    mode="restart",
    triggers=[state(e.binary_sensor.hall_motion).to("on")],
)
def hall_light_on_motion():
    only_if(
        state(guest_mode).is_("off"),
        sun(after="sunset", after_offset="-00:30"),
    )
    e.light.hallway.turn_on(brightness_pct=60, transition=2)
    delay(minutes=5)
    e.light.hallway.turn_off()
```

Semantics: the decorator registers the function and, when `triggers=` is given, records those
triggers immediately (at decoration time — the list itself is built when the `@automation(...)`
line runs, same as every other decorator kwarg); the **compiler then calls the function once
inside a recording context**. `only_if()` sets conditions; entity service calls, `delay`, etc.
append actions. The body is a *description*, not runtime code (§5.5).

`triggers=` is the canonical, preferred spelling for an automation's triggers (Python idiom: the
decorator is where subscription/registration metadata lives, the same way a web framework's route
decorator carries its path — cf. `@app.route("/x")`). The classic form, `when(...)` called inside
the body, remains fully supported and is still the right tool when the trigger list itself needs
to be built dynamically (a compile-time Python loop, a helper function, a conditional trigger set)
— see the position-independence note in §7.3. The two **compose**: `triggers=`'s list is recorded
first, then any `when()` calls inside the body append after it, in call order.

`@automation` accepts every HA automation option (`mode`, `max`, `max_exceeded`,
`trigger_variables`, `variables`, `description`, `initial_state`, …). New automations default
`id` to the function name; ids must be unique bundle-wide (validated).

### 5.4 Triggers, conditions, templates

Every classic HA trigger/condition type has a typed builder: `state()`, `numeric_state()`,
`time()`, `time_pattern()`, `sun()`, `event()`, `zone()`, `template()`, `webhook()`, `device()`
(raw passthrough), `mqtt()`, `calendar()`, `persistent_notification()`, plus `for_=` durations,
trigger `id=`s, `not_(...)`, `any_of(...)`, `all_of(...)`.

**Purpose-specific triggers/conditions (2026.7+, §4)** get one *generic* typed builder rather
than 200+ hand-written ones — the vocabulary is instance data, not code:

```python
when(on("motion.detected", target=area("office"), behavior="first", for_=minutes(5)))
only_if(met("climate.is_target_temperature", target=e.climate.living))
# targets: e.<domain>.<object_id> | area("office") | floor("upstairs") | label("security") | device_id("…")
```

The type string is validated against the vocabulary enumerated from the instance (tier 2, §9),
with rename hints for HA's known Labs→2026.7 renames; target ids are validated against the
registries. Decompilation of UI-authored purpose triggers produces exactly this form — never
`raw`.

Templates are built with operator overloading and compile to Jinja:

```python
state(e.sensor.outdoor_temp).value > 25
# compiles to: {{ states('sensor.outdoor_temp') | float > 25 }}

e.climate.living.set_temperature(temperature=expr(e.input_number.target_temp) - 1)
# temperature: "{{ states('input_number.target_temp') | float - 1 }}"
```

Raw Jinja is always available: `template("{{ ... }}")` — validated by tier-3 lint (§9).

### 5.5 Compile-time vs runtime control flow — THE rule

- **Python `if`/`for`/functions run at compile time.** This is a feature: loop over rooms to
  generate per-room automations, share constants, compute schedules. Metaprogramming for free.
- **Runtime branching uses explicit context managers**, which compile to HA `choose` / `if` /
  `repeat` / `parallel` / `wait`:

```python
with if_then(state(e.person.kai).is_("home")):
    notify_adults("Welcome home")
with else_then():
    with repeat_count(3):
        e.light.porch.toggle()
        delay(seconds=1)

with parallel():
    ...
wait_for(state(e.binary_sensor.door).to("off"), timeout=minutes(2))
```

- **Trap-catching:** condition objects define `__bool__` to raise
  `CompileTimeBranchError("You wrote a Python `if` on a runtime state — use `with if_then(...)`. ")`.
  A native Python `if` on an entity comparison therefore *cannot silently compile wrong* — it
  fails loudly with a teaching error. This class of error message is a deliverable, not a nicety
  (agents and humans both depend on it).
- **`@automation(triggers=[...])` changes nothing about this rule.** The trigger builder objects
  in the list are ordinary compile-time-built Python objects — `state(...)`, `on(...)`, etc. —
  built when the decorator line itself runs, exactly like a `when(state(...))` call inside the
  body would build them. Putting them in the decorator is purely a placement/style choice (§5.3);
  it has no bearing on the compile-time/runtime split.

### 5.6 Macros and shared scripts (G7)

```python
# lib/notify.py
from hassle import macro, shared_script

@macro                                # compile-time inlining: expands into each caller's
def notify_adults(message: str):      # action list. Zero HA-side footprint.
    e.notify.mobile_app_kai(message=message)
    e.notify.mobile_app_spouse(message=message)

@shared_script(id="flash_lights", alias="Flash lights", icon="mdi:alarm-light")
def flash_lights(times: int = 3):     # becomes a real HA script entity with typed fields;
    with repeat_count(param("times")):  # callers compile to script.turn_on / script.flash_lights
        e.light.all_downstairs.toggle()
        delay(seconds=1)
```

Rule of thumb (documented in AGENTS.md): `@macro` for small glue; `@shared_script` when you want
it visible/runnable/editable in the HA UI or called from UI-authored automations.

### 5.7 Scripts and helpers

```python
# scripts/movie_time.py
@script(id="movie_time", alias="Movie time", mode="single")
def movie_time():
    e.light.living_room.turn_on(brightness_pct=10)
    e.media_player.tv.turn_on()

# helpers/modes.py — declarative; synced like any object; referenced by import elsewhere
guest_mode = input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account-group")
target_temp = input_number(id="target_temp", name="Target Temperature",
                           min=15, max=25, step=0.5, unit_of_measurement="°C")
```

Helpers declared in the bundle count as "existing" for validation even before first push, so a
new helper + the automation using it can be authored and validated in one edit.

### 5.8 The `raw` escape hatch (I3)

Any construct the DSL/decompiler doesn't model round-trips as verbatim JSON:

```python
@raw_automation(id="1687201958261")
def legacy_device_automation():          # decorator wraps a function RETURNING the dict
    return {
        "alias": "Weird device trigger thing",
        "trigger": [{"platform": "device", "device_id": "abc123", ...}],  # legacy keys fine:
        ...                                # normalized to the plural schema exactly as HA does
    }
```

Also granular: `raw_trigger({...})`, `raw_action({...})` inside normal DSL automations.
Blueprint-based automations decompile to a structured form, not raw:

```python
hall_motion = blueprint_automation(       # call form: it declares an object, no body to trace
    id="...", use_blueprint="hassle/motion_light.yaml",   # author-qualified path
    inputs={"motion_entity": e.binary_sensor.hall_motion},
)
```

(DSL keeps the ergonomic `inputs=`; the stored JSON key is `use_blueprint.input` — singular —
and the path includes the author directory. The compiler/decompiler map between the two; see
docs/ha-api-notes.md §10.5.)

The decompiler's "DSL coverage %" over the fixture corpus is a tracked metric (MILESTONES M2);
`raw` is the correctness backstop, not the plan.

---

## 6. Bundle format

~~Original (v1, superseded by MILESTONES M15):~~

```
my-home/                   # a git repository (hassle init/pull offers to `git init`)
├── hassle.toml            # bundle settings: HA URL (never the token), formatting opts, plugins
├── automations/           # one file per area/topic; multiple objects per file is fine
├── scripts/
├── helpers/
├── lib/                   # macros, shared scripts, constants — yours, never auto-regenerated
│                          # (README.md written once by `init`/`pull`, explaining the directory)
├── tests/                 # pytest files — yours; persist in git (G5)
├── stubs/                 # generated .pyi (checked in so pyright works immediately)
├── .vscode/settings.json  # points pyright at stubs/; generated once, then left alone
├── .hassle/
│   ├── manifest.lock      # machine-owned sync baseline (§8.1) — committed, never hand-edited
│   ├── registry.json      # snapshot: entities, services, areas, devices, labels, categories (§9.2)
│   └── plan.json          # last computed plan (transient, gitignored)
├── .gitignore             # generated: plan.json, caches
├── AGENTS.md              # generated agent instructions (§12)
└── docs/                  # generated DSL reference + cookbook (stable content, versioned)
```

**Revised (MILESTONES M15, "category-first bundle layout" — owner-commissioned,
evidence base docs/ha-api-notes.md §31): root-level, mixed-kind category files, not
a per-kind tree.** The `automations/`/`scripts/`/`helpers/` trees above are RETIRED —
every category (automation, script, or any of the 13 helper kinds sharing HA's
`"helpers"` category-registry scope) now gets ONE root-level file that can hold
objects of every kind at once:

```
my-home/                   # a git repository (hassle init/pull offers to `git init`)
├── hassle.toml            # bundle settings: HA URL (never the token), formatting opts, plugins
├── hvac.py                 # a category-shaped file: mixes automations/scripts/helpers
├── misc.py                 # every uncategorized object, of every kind
├── lib/                   # macros, shared scripts, constants — yours, never auto-regenerated
│                          # (README.md written once by `init`/`pull`, explaining the directory)
├── tests/                 # pytest files — yours; persist in git (G5)
├── stubs/                 # generated .pyi (checked in so pyright works immediately)
├── .vscode/settings.json  # points pyright at stubs/; generated once, then left alone
├── .hassle/
│   ├── manifest.lock      # machine-owned sync baseline (§8.1) — committed, never hand-edited
│   ├── registry.json      # snapshot: entities, services, areas, devices, labels, categories (§9.2)
│   └── plan.json          # last computed plan (transient, gitignored)
├── .gitignore             # generated: plan.json, caches
├── AGENTS.md              # generated agent instructions (§12)
└── docs/                  # generated DSL reference + cookbook (stable content, versioned)
```

`lib/`, `tests/`, `stubs/`, `docs/`, and `.hassle/` are unchanged by this revision.
An old-layout bundle (the retired per-kind trees, `bundle_format` 1) is migrated
in place by the next `hassle pull` — see the migration bullet below.

- The **directory (a git repo)** is the working format; **ZIP** is a transport/interchange
  format (`hassle pull --zip out.zip`, `hassle push --zip in.zip`) per G1 — useful for moving a
  bundle without git.
- ~~File organization is user-controlled: the decompiler only decides placement for objects it has
  never seen (defaults: one file per HA UI category if the object's entity-registry entry has one
  — `automations/<slug(category name)>.py` / `scripts/<slug(category name)>.py`, fetched via WS
  `config/category_registry/list` per scope; else `automations/misc.py` / `scripts/misc.py` /
  `helpers/misc.py` — helpers have no category-registry scope in HA, so they always use the domain
  default); after that, objects stay in whatever file the user puts them in (tracked by
  manifest).~~ **Revised (MILESTONES M15):** file organization is still user-controlled after
  first placement, but the DEFAULT for a never-seen object is now root-level and cross-kind:
  `<slug(category name)>.py` at the bundle root, derived from the object's OWN scope's category
  (automation → category-registry scope `"automation"`, script → `"script"`, every helper kind →
  the single shared scope `"helpers"`, all confirmed live, docs/ha-api-notes.md §31.2/§31.6) —
  same category name across scopes lands every object in the SAME file (a mixed-kind category
  file); else the single shared `misc.py`, replacing the old three-tree `automations/misc.py` /
  `scripts/misc.py` / `helpers/misc.py` fallback. **Local moves sync back:** moving an EXISTING
  object to a different category-shaped file is a category reassignment on the next push
  (`ManifestEntry.category`, three-way against the base recorded at last sync — F2 amendment) —
  extends the create-only write-back below to updates; a local move + a conflicting HA-side
  recategorization surfaces as a conflict (I6), never silently overwritten either way. A
  mixed-kind file maps to up to three real category ROWS (one per scope, sharing only a name) —
  created per scope on demand; if HA-side renames make the scopes' names diverge for what was one
  file, the next pull places each object by its own scope's category (the file may split) and
  emits a divergence warning, never guessing a winner.
  **`hassle init` and `hassle pull`** (when it scaffolds missing directories) also write
  `lib/README.md` (explaining `@macro`/`@shared_script`/plain constants, §5.6) and, when `tests/`
  is otherwise empty, a one-line `tests/README.md` — both idempotent, never overwriting an
  existing file.
- **Migration (MILESTONES M15):** an old-layout bundle is detected by `hassle pull` (populated
  `automations/`/`scripts/`/`helpers/` trees) and restructured in place: every managed object is
  spliced out of its old file and regenerated at its new root-level destination; an old file is
  deleted only when nothing but imports would remain in it (I6 — a user's own comment or a custom
  `def` keeps the file alive, with just the migrated object's statement removed). Every move is
  reported in `hassle pull`'s output. `hassle.toml`'s `bundle_format` bumps once migration
  completes (the M9 versioning surface: an OLDER CLI opening a NEWER bundle_format refuses with a
  clear upgrade error; an older bundle_format itself is never refused — it's exactly what
  triggers migration). Migration only moves DSL source, never changes an object's compiled
  config, so the very next plan is a NOOP and a second pull is byte-stable.
- **`ignore` (owner amendment, `ux/pull-organization`):** `hassle.toml` may declare
  `ignore = ["input_boolean:material_you_*", …]` — `fnmatch` globs matched against object keys.
  This REVISES §8.2's "first-ever pull adopts everything; nothing is ever unmanaged": an object
  key matching an `ignore` glob is filtered out of both the freshly-compiled local objects and the
  freshly-fetched remote objects **before** `compute_plan` runs, so it can never be adopted,
  refreshed, updated, or — the safety-critical case — deleted, no matter what either side looks
  like. A local declaration that itself matches an `ignore` glob is excluded from the plan too and
  raises a `declared-but-ignored` warning (almost always a mistake — the user probably meant to
  ignore something else). If a glob starts matching a `manifest.lock` entry that predates it, the
  next `hassle pull` drops that entry from the manifest (never touching HA) and prints a one-time
  notice. See `hassle_cli.ignore_filter` for the implementation and its test
  coverage (`packages/hassle-cli/tests/test_ignore_filtering.py`,
  `test_pull_ignore_globs.py`).

---

## 7. Compiler and decompiler

### 7.1 IR (intermediate representation)

Pydantic models mirroring HA's config schema exactly: `AutomationConfig`, `Trigger` (tagged
union), `Condition`, `Action` (tagged union incl. `choose/if/repeat/parallel/wait_*`),
`ScriptConfig`, `HelperConfig` per domain. Two hard requirements:

- **Unknown-field preservation** (`model_config = ConfigDict(extra="allow")` + explicit tests):
  HA adds fields; the IR must never drop them.
- **Canonical JSON serialization** (sorted keys, stable list order) so object hashing (§8) is
  deterministic.
- **The canonical form is the plural schema** (§4 quirks): the compiler always emits
  `triggers/conditions/actions` and `action:` — including for `raw_*` bodies a user authored in
  legacy singular form, which are normalized exactly as HA itself would normalize them on
  storage (`normalize_ha`, an M1 deliverable). The decompiler accepts both forms as input.
  Without this, every locally-compiled object would hash differently from HA's stored copy and
  the plan would show perpetual spurious diffs.

Pipelines: `DSL —(trace)→ IR —(serialize)→ HA JSON` and `HA JSON —(parse)→ IR —(codegen)→ DSL`.
The IR is the frozen interface between the two pipelines (docs/ir-format.md).

### 7.2 Compiler

Imports the bundle as a package (isolated, `sys.path` sandboxed, no network), executes each
registered object's function inside a recording context, emits IR. Every emitted IR node carries
a source span (`file:line`) so *all* downstream errors — validation, plan conflicts, simulator
failures — point at the user's Python line.

### 7.3 Decompiler and source preservation

- Deterministic codegen from IR: stable ordering, ruff-formatted output, `snake_case` function
  names derived from alias with collision handling.
- **Source preservation on pull (local):** for each object, if `hash(live HA JSON) ==
  manifest.compiled_hash`, the working-tree file is left completely untouched (the user's own
  code, comments intact). Otherwise the object drifted in the UI: decompile just that object and
  **splice it into its existing file with LibCST** (replace the one top-level decorated def /
  assignment), leaving the rest of the file untouched. Spliced objects get a
  `# hassle: updated from UI on <date>` comment, and `hassle pull` lists them so the git diff
  is legible.
- A machine with no bundle (no git clone) can still `hassle pull` from scratch — it just gets a
  fully decompiled bundle (semantically identical, hand-written comments absent). The fix is
  "clone the repo", and the CLI says so.
- Objects that decompile to `raw_*` are flagged in `hassle pull` output as DSL-coverage gaps.

**Codegen readability (owner feedback after first real pull; style, not schema — I3 holds byte-
for-byte, verified over the whole round-trip corpus):**

- **Entity references through the registry accessor:** an entity id in an entity position
  (`state()`/`numeric_state()`'s entity arg, `target={"entity_id": ...}` — including nested
  inside the dict literal — a `wait_for_trigger` trigger's entity arg, a helper declaration used
  elsewhere) is emitted as `e.<domain>.<object_id>` (`e.<domain>["<object_id>"]` for a
  digit-leading object_id) rather than the quoted string, backed by
  `from hassle.registry import entities as e`. Only a bare string matching the `domain.object_id`
  shape qualifies — a state **value** (`.to()`/`.is_()`), a Jinja `template("...")` string, and a
  registry UUID never match, so they're untouched. `EntityRef` is a `str` subclass, so this is
  purely cosmetic: it compiles to the identical HA value.
- **Star import:** a freshly decompiled module emits `from hassle import *` (the DSL surface
  defines `__all__`, so pyright resolves this without configuration) instead of an enumerated
  builder-name list — owner preference, and it also means an F3 addition never needs a matching
  update to a generated-code import list. The `entities as e` import stays its own explicit line
  (DESIGN §5.3: a dedicated, non-`__all__` entry point). This is the **generated-code** style
  only; hand-written bundle files may use either form.
- **Section comments — introduced, then removed (dated note).** Originally: `# --- conditions ---`
  / `# --- actions ---` precede each non-empty section of an automation body (a script gets
  `# --- sequence ---` when its sequence is non-empty); an empty section gets no comment.
  Triggers never had a body section at all once `triggers=` moved them into the decorator
  (`ux/triggers-in-decorator`). **Removed 2026-07 (`ux/dsl-ergonomics`, owner amendment,
  supersedes this bullet's original "judge readability" latitude on item 1):** once conditions
  also moved out of the body — the `with only_if(...):` block form (below) is now the canonical
  decompiled shape whenever an automation has any conditions at all — the remaining section
  comments no longer disambiguated anything: the body's structure (decorator = when, `only_if`
  block = gate, plain statements = do) is self-describing on its own. A freshly decompiled
  automation/script body therefore carries no `# --- ... ---` comments at all.
- **Function names derive from `alias`, not `id`** (this section as originally written, now
  actually implemented): the name is `slugify(alias)`, with a deterministic `_2`/`_3` suffix on a
  collision — collisions include another decompiled object's alias-slug **and** any name the
  generated module's own imports bring into scope (`hassle.__all__`, `e`), so an automation
  aliased e.g. "Wait Template" never shadows the `wait_template()` builder inside its own function
  body. No `alias` falls back to `automation_<id>` / `script_<id>`. The `id=` kwarg is still
  emitted whenever it differs from the (now alias-derived) function name — I2 is untouched, only
  the *Python identifier* changed; a bundle's own `id=` values never do. One accepted UX
  consequence: since the name now tracks `alias`, a UI-only alias edit changes the function name
  on next pull/decompile, which shows up as a rename in the spliced diff (previously invisible,
  since the id-derived name never changed) — considered acceptable, since the alias visibly
  changed too and the diff is otherwise exactly the meaningful one-line edit.
- **Scripts decompile as `@shared_script`, not `@script`** (owner feedback, `ux/shared-script-calls`,
  widened by `ux/shared-script-rich-fields`): since `@shared_script` compiles to the exact same
  `ScriptConfig` `@script` does, every script decompiles to `@shared_script` by default. Fields whose
  every spec is *exactly* `{"default": ...}` get the terse form (no explicit `fields=` kwarg — the
  signature alone reproduces it, with a Python type annotation when one is inferable from the
  default's Python type, e.g. `times: int = 3`). Any richer shape — `name`/`description`/`selector`/
  `example`/... metadata, or a field declared with **no** `default` at all — ALSO decompiles to
  `@shared_script`, now emitting `fields=` **verbatim** (byte-stability by construction: the stored
  metadata a Python signature alone could never reconstruct) with every parameter `None`-defaulted
  (HA-side requiredness lives in the metadata, not in whether `@shared_script`'s underlying function
  — always invoked with zero arguments to build its sequence, DESIGN §5.6 — can be called). This
  widening matters in practice: real HA-UI-authored scripts always carry the richer shape, so the
  original signature-only rule made the `@script` fallback the common case, not the exception. The
  `@script` fallback is now rare — only a field name that isn't a valid Python identifier, or a
  malformed (non-dict) field spec, neither of which the HA UI ever produces.
- **Caller rewrite: a `script.<object_id>` call becomes a real function call** (owner feedback):
  a stored action `{"action": "script.<id>", "data": {...}, "metadata": {...}}` decompiles to
  `<fn_name>(<data as kwargs>, metadata={...})` when `<id>` is a MANAGED script in the same pull
  batch, every `data` key is one of the script's declared fields, the action is the direct
  `script.<id>` form (`script.turn_on` with `target`/`variables` is a different, generic-caller
  shape and is never rewritten), and there's no `target`/`data_template`/`response_variable`/
  `continue_on_error` beyond what the call reproduces — any of these falls back to today's
  `service()` form (never `raw`). `ScriptCallAction` (compiler-internal, `hassle.compiler.scripts`)
  widened additively to carry `metadata=`/`alias=`/`enabled=` so the rewritten call recompiles
  byte-identical (docs/dsl-extensions.md).
- **Cross-file imports for the caller rewrite:** when the callee script lives in a different
  destination file than its caller (category-based placement routinely splits them), the
  decompiler emits `from scripts.<module> import <fn_name>` — built from a cross-reference table
  (`{script_object_id: (module_path, function_name)}`) the pull layer supplies, since only it knows
  every managed script's placement across the whole pull batch. A script the table doesn't know
  about (not in this pull, or genuinely unmanaged) stays `service()`. Only whole-file writes
  (`hassle pull`'s multi-object adopt batches, and a fresh from-scratch decompile) can gain this
  rewrite: the LibCST single-object splice used for a drifted object's `refresh` replaces exactly
  one top-level statement and cannot also inject a new top-level import line, so a refreshed
  caller's CROSS-FILE script call stays `service()` on that path specifically (a same-file call
  never arises there, since a splice always targets exactly one object). A script-to-script call
  cycle across two files (A calls B, B calls A back) would require a circular import — one
  direction's edge is deterministically dropped back to `service()`, with a one-line
  `# hassle: ... cross-file script call cycle ...` comment, rather than ever emitting a mutually
  importing pair of generated files.
- **Triggers decompile into the decorator, not the body** (owner-approved DSL evolution,
  `ux/triggers-in-decorator`, task #10; DESIGN §5.3/§5.5): typed triggers are emitted as a
  `triggers=[...]` decorator kwarg (multi-line, one trigger per line, when there's more than
  one — the same formatting `when(...)` used to use for a multi-trigger body call), rather than
  a `when(...)` call at the top of the body. `when()` itself is unaffected and stays fully
  supported (F3 forbids removing it) — it's still the only option for a dynamically-built trigger
  list (built by a compile-time `for` loop, a shared helper function, etc. — the decorator's
  `triggers=` list, by contrast, is one Python expression evaluated once, at decoration time, so
  it can only hold a single static list literal). A `raw_trigger(...)` (an untyped/unmodeled
  trigger) still can't be nested inside a list-literal kwarg — it's a recording *verb*, not an
  expression — so it stays a body statement, emitted first (with no header comment, since there's
  no more triggers section at all).

  **Position-independence, explained:** before this change, `when()`/`only_if()` could be called
  anywhere in an automation's body (the recorder doesn't care about call order relative to
  actions — DESIGN §7.2's "trace a function call" model just appends to whichever list the call
  targets) — so a body's *physical* layout carried no meaning beyond decompiler convention (the
  `# --- triggers ---`/`# --- conditions ---`/`# --- actions ---` section comments existed purely
  to make that convention legible, not because the compiler required that order). Moving triggers
  into the decorator removes this ambiguity entirely for the common case: a trigger is now
  syntactically pinned to one place (the decorator argument list), not just conventionally placed
  first in the body — there is no longer a *question* of where in the body a trigger "belongs".
  `when()` keeps the old position-independence property for whatever it's used for (which now
  reads, correctly, as "an escape hatch for dynamic trigger construction", not "the normal way to
  write a trigger") — a `when()` call still composes with the decorator's list regardless of
  where in the body it appears, appending after the decorator's triggers in call order.
- **`only_if` gains a block form; it's the canonical decompiled shape whenever conditions
  exist** (owner feedback — "a bare `only_if(...)` call looks like an empty if" —
  `ux/dsl-ergonomics`, item 1). `only_if(*conditions)` is now dual-form: the bare call keeps
  its exact pre-existing behavior (F3), and the SAME call is also usable as
  `with only_if(cond1, cond2): ...`. HA has no notion of a conditional subset of an
  automation's actions — automation-level conditions gate every single action regardless of
  where in the body it's written — so the block form makes that true visually: using it
  requires every action the automation records to be inside the block (recorded before or
  after it raises `OnlyIfBlockCoverageError`, a what/where/fix error naming the fix — move the
  action inside the block, or drop back to the bare form). The decompiler always emits the
  block form when an automation has any conditions at all, wrapping every action; no
  conditions means no block, exactly as before. Compiled IR is byte-identical either form
  (golden-pair parity proof, matching the precedent `triggers=` set: `fixtures/dsl/
  only_if_block_form/` vs. the equivalent bare-`only_if` golden).
- **Enums for enumerated HA options** (`ux/dsl-ergonomics`, item 2): `Mode`
  (`SINGLE`/`RESTART`/`QUEUED`/`PARALLEL`) and `MaxExceeded` (`SILENT`/`WARNING`/`ERROR`) are
  `StrEnum` — a real `str` subclass, so `@automation(mode=Mode.RESTART)` compiles byte-identical
  to `@automation(mode="restart")`. The decompiler emits `Mode.RESTART`/`MaxExceeded.SILENT` for
  a recognized value and falls back to the raw string for anything else (an unrecognized future
  HA value is never a decompiler error).
- **Bare entity target sugar** (`ux/dsl-ergonomics`, item 3): `service(..., target=e.weather.
  forecast_home)` — an `EntityRef`/`str`, or a list of them — compiles to
  `target={"entity_id": ...}`, identical to writing the dict by hand; `area(...)`/`floor(...)`/
  `label(...)`/`device_id(...)` (the same target helpers `on()`/`met()` already accept, DESIGN
  §5.4) are also accepted directly as `target=`, compiling to `{"area_id": ...}` etc. The
  decompiler emits the bare form whenever a stored `target` dict has exactly one key —
  `entity_id` (single ref or list) or one of the four id-key forms — and keeps the plain dict
  literal for any multi-key target (e.g. `entity_id` + `device_id` together).

---

## 8. Sync: plan/apply, conflicts, and the git loop (G2, G8)

### 8.1 manifest.lock

```json
{
  "synced_at": "2026-07-03T18:20:00Z",
  "ha_version": "2026.6.3",
  "objects": {
    "automation:hall_light_on_motion": {
      "source": "hallway.py",           // root-level (MILESTONES M15 category-first layout, §6)
      "compiled_hash": "sha256:…",     // hash of canonical JSON at last successful sync
      "kind": "dsl",                    // dsl | raw | blueprint
      "category": null                  // base category slug at last sync (F2 amendment, MILESTONES M15)
    },
    "input_boolean:guest_mode": { … }
  }
}
```

`compiled_hash` is the **base** of a three-way merge between your working tree and live HA.
`manifest.lock` is committed to git, which is what lets a second machine (or a teammate/agent)
clone the repo and immediately have the correct merge base.

### 8.2 Plan semantics (table-driven; this table IS the test spec for MILESTONES M5)

For each object key, compare **base** (manifest), **local** (freshly compiled), **remote**
(live HA, canonical-hashed):

| base vs remote | base vs local | Plan action |
|---|---|---|
| same | same | `noop` |
| same | different | `update` (safe: remote untouched since last sync) |
| same | local deleted | `delete` |
| different (UI edit) | same | `refresh` — pull the UI edit into the bundle; never clobber a UI edit the user didn't touch locally |
| different | different | **`conflict`** — shown with a 3-way diff of the *decompiled DSL*, not JSON |
| different | local deleted | **`conflict`** (deleted locally, edited remotely) |
| remote deleted | same | `drop` from bundle |
| remote deleted | different | **`conflict`** |
| (new local id) | — | `create` (id-collision with a new remote object → `conflict`) |
| (new remote id) | — | `adopt` on next pull (UI-created objects are auto-managed) |

- `hassle plan` renders the table with colors + DSL-level diffs; `hassle push` = plan + confirm +
  apply. Any `conflict` **aborts apply** unless resolved per-object:
  `--accept-local KEY`, `--accept-remote KEY`, or pull-and-merge in the editor.
- Deletions always enumerate loudly and require the confirm step (or `--yes`).
- **Apply is transactional (best-effort), executed by the CLI:** it snapshots every to-be-touched
  object's current remote config first, **re-verifies remote hashes immediately before writing**
  (abort on drift between plan and apply — this shrinks the concurrent-edit race window to
  seconds), applies in dependency order (helpers → scripts → automations), and rolls back from
  the snapshot on any failure. On success it rewrites `manifest.lock`.
- Known limitation (documented, accepted): with no server-side component there is no global
  lock, so two machines applying in the *same instant* can interleave. The pre-write hash
  re-check catches everything slower than that. For a single-household tool this is acceptable;
  a future add-on could add a lock if ever needed (§13).
- First-ever pull adopts everything; nothing is ever "unmanaged" (simplest mental model) —
  **except** an object key matching a `hassle.toml` `ignore` glob (§6 amendment, owner decision):
  those are filtered out before this table is even computed, deliberately staying unmanaged
  forever (never adopted, refreshed, or deleted) so a push can never touch them.

### 8.3 Pull is the same merge, driven the other way

`hassle pull` computes the identical three-way table and applies the *bundle-side* actions:
`refresh` splices UI edits into your files (§7.3), `adopt` creates files for UI-created objects,
`drop` deletes files for UI-deleted objects (listed, and recoverable via git), conflicts are
written as both versions with markers plus a summary — the working tree, not HA, is what pull
mutates. HA is never written to during pull.

### 8.4 The git workflow (the recommended daily loop)

Git is the source of truth for sources and tests; HA for live objects; `manifest.lock` ties them
together. The loop:

```
(other machine?)  git pull                     # get teammates'/your other laptop's work
                  hassle pull                  # merge any UI-side edits into the working tree
                  git commit -m "sync: UI changes"   # UI edits land as their own commit
                  <edit .py files, write tests>
                  hassle validate && hassle test
                  hassle push                  # plan → confirm → apply to HA (+ manifest update)
                  git commit -m "…"            # your change + updated manifest.lock
                  git push
```

CLI affordances that keep this honest:

- `hassle pull` **requires a clean working tree** by default (`--allow-dirty` to override) — so
  UI-originated changes always land as a separate, reviewable commit, never tangled into your
  half-finished edits.
- `hassle push` warns if the working tree has uncommitted changes it is about to make live, and
  prints a ready-made commit message summarizing the applied plan.
- `hassle status` = local plan preview + git status in one view.
- None of this *requires* git (the tool functions in a bare directory and warns once), but
  `hassle init`/first pull offers `git init` and writes the `.gitignore`.

### 8.5 ~~Optional: the in-HA mirror (best-effort)~~ — REMOVED

> **Removed (2026-07-17).** The mirror was designed to stash the bundle ZIP inside HA's local
> media storage so a copy of sources+tests lived inside HA (and its backups). The backend layer
> was built and tested, but the CLI wiring was never finished, and the mechanism depended on two
> incidental HA media-endpoint quirks (upload Content-Type prefix, download extension→MIME
> mapping) that HA could close in any release. Rather than ship a feature resting on
> unsupported behavior, it was deleted; **git is the sole store for sources and tests** (§8.4).
> The captured HA media-API findings remain in `docs/ha-api-notes.md` §9/§10/§17.

---

## 9. Validation (G6)

| Tier | Where | Catches | When |
|---|---|---|---|
| 0. pyright on stubs | editor / CI | entity typos, wrong service params, type errors | as you type |
| 1. Compile | CLI | DSL misuse (incl. `CompileTimeBranchError`), duplicate ids, bad options | `hassle validate`, pre-plan |
| 2. Registry | CLI, offline | references to nonexistent entities/services/areas/floors/devices/labels — including inside `raw_*` blocks and Jinja strings (entity-id extraction lint); unknown purpose-trigger/condition type strings (validated against the instance's enumerated vocabulary, with rename hints for HA's known Labs→2026.7 renames); "did you mean `light.hallway`?" suggestions; bundle-declared helpers count as existing | `hassle validate` |
| 3. Template lint | CLI, offline | Jinja syntax errors; unknown entities inside templates | `hassle validate` |
| 4. Server-side | CLI → HA, pre-apply | anything HA itself rejects: WS `validate_config` per object + `check_config` | automatic during plan/apply; `hassle validate --live` |

### 9.2 Registry snapshot

The CLI fetches the registries directly over WebSocket (entity/device/area/label registries,
`get_services`) and stores the snapshot at `.hassle/registry.json` (committed); refreshed on
every pull and by `hassle stubs --refresh`. It drives tier-2 validation, stub generation, and
simulator defaults. Offline-first: everything except tier 4 works with no connection.

---

## 10. Testing (G5, G9)

### 10.1 Simulator

A miniature HA runtime in `hassle-core`, executing **compiled IR** (I5): state machine +
fake clock + trigger evaluator + action executor.

- **Actions (full support required):** service calls (recorded, not executed), `delay`,
  `wait_template`/`wait_for_trigger` (with timeouts), `choose/if/repeat/parallel`, variables,
  `stop`, mode semantics (`single/restart/queued/parallel` — including the classic
  "restart cancels my delay" behaviors, which are exactly what people need tests for).
- **Triggers (v1 set):** state (incl. `for_`), numeric_state, time, time_pattern, sun
  (configurable sunrise/sunset), event, template (subset), zone. Anything else — including the
  2026.7 purpose-specific vocabulary (§4), which is semantically defined per-type by HA and too
  large to reimplement faithfully — the test fires the automation manually:
  `sim.fire(automation, trigger_ctx={...})`. So *no automation is untestable*, some just skip
  trigger evaluation. (Mapping the most common purpose triggers onto state-trigger semantics is
  a designed-for v2 simulator extension.)
- **Templates:** real jinja2 plus reimplementations of the most-used HA extensions (`states()`,
  `is_state()`, `state_attr()`, `now()`, `today_at()`, `as_timestamp`, `float/int/round`,
  timedelta arithmetic, `iif`) **and HA's math set** (sin/cos/tan/asin/acos/atan/atan2/sqrt/
  log, pi/e/tau, min/max/abs — stock jinja2 lacks these; without them every math-template
  automation would be untestable in the simulator). Unsupported constructs raise
  `UnsupportedTemplateError` with a pointer to `hassle render --live` (never silently wrong).
- **Clock:** `sim.advance(minutes=5)` deterministically fires due time triggers, expires delays
  and waits. No wall-clock, no sleeps, no flakes.

### 10.2 Writing tests

```python
# tests/test_hallway.py
from hassle.testing import simulate
from automations.hallway import hall_light_on_motion

def test_motion_turns_on_light_at_night(sim):           # `sim` pytest fixture
    sim.at("2026-07-03 22:30")                          # after sunset
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    sim.advance(minutes=5)
    sim.assert_called("light.turn_off", entity_id="light.hallway")

def test_no_trigger_during_day(sim):
    sim.at("2026-07-03 12:00")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_not_called("light.turn_on")
```

`hassle test` = pytest with the plugin preloaded; plain `pytest` works too. The `sim` fixture
auto-loads the compiled bundle, seeds states from the registry snapshot, and pins the clock (which
is why tests are reproducible). Tests live in `tests/` and persist in git with everything else
(G5); because the bundle is a normal repo, they also run in CI (GitHub Actions template ships
with `hassle init`: `hassle validate && hassle test` on every push).

### 10.4 Live test-run (G9)

`hassle run hallway.py::hall_light_on_motion --live` (root-level path, MILESTONES M15 §6):

1. Compile + validate the single object; push it as a **shadow automation**
   (`id="hassle_shadow_<hash>"`), **enabled**, with its own trigger list replaced by a single
   event trigger on a run-unique event type (`hassle_shadow_never_<uuid>`) that nothing on the
   real event bus will ever fire — the same "its triggers never fire on their own" guarantee,
   without disabling the automation. *(Revised post-M7: the original design used
   `initial_state: off` instead; live verification against real HA (docs/ha-api-notes.md §27
   addendum) found the integration test that would have caught problems with that mechanism was
   itself broken from the day it was written by an unrelated test bug, so the disabled-shadow
   path had never actually run against real HA. HA source confirms a disabled automation's forced
   `automation.trigger` call DOES execute and DOES record a trace — so `initial_state: off` was
   never actually broken either — but the never-fires-event-trigger design removes the dependency
   on that indirect property entirely and is simpler to reason about.)*
2. Fire it via `automation.trigger`, targeting the shadow's real `entity_id` (`slug(alias)`, NOT
   `slug(id)` — §4/§10.2's quirk; resolve it by matching `attributes.id` on `/api/states`, the same
   way the automation is enumerated elsewhere) (options: `--skip-conditions`, `--vars k=v`). Note
   HA's `skip_condition` defaults to **true**; Hassle passes `skip_condition: false` unless
   `--skip-conditions` is given, so the default live run behaves like the real trigger would.
3. Stream the execution trace (WS `trace/get`) and live state changes; render as a step-by-step
   timeline mapped back to DSL source lines.
4. Delete the shadow. On any error the shadow is cleaned up (and `hassle doctor` sweeps orphans).

⚠️ Live runs execute **real service calls on real devices** — the CLI says so and requires a
first-time confirmation. `hassle run` without `--live` runs the same thing on the simulator.

---

## 11. VS Code (G10)

- **Layer 1 (free):** generated stubs + shipped `.vscode/settings.json` → Pylance autocompletion
  of entities/services, go-to-definition into helper declarations, typo squiggles. This works in
  any pyright-capable editor (also: neovim, etc.).
- **Layer 2 (extension):** commands (Pull/Plan/Push/Test/Run live), `hassle validate` diagnostics
  surfaced via a Problems-pane task, status bar sync state, "show compiled YAML/JSON" side-panel
  for the object under the cursor (`hassle explain` output; YAML view because that's what HA
  forums/docs speak).
- **Layer 3 (stretch, pygls LSP):** hovers showing *live entity state* over a direct WS
  connection, inline Jinja template validation, code lens "▶ run on simulator" per automation.

---

## 12. Documentation for AI agents (G11)

Every bundle ships self-contained agent docs (no internet needed):

- **`AGENTS.md`** (generated, short, imperative): the workflow contract —
  edit → `hassle validate` → `hassle test` → `hassle plan` → show human. Hard rules
  (never change `id`; never edit `.hassle/`; Python `if` is compile-time, use `if_then` — with
  the error message they'll see if they forget; commit UI-sync pulls separately from edits);
  pointers into `docs/`.
- **`docs/DSL.md`**: the full reference, one section per construct, every section with a
  DSL ↔ compiled-YAML pair (agents pattern-match on pairs; so do humans).
- **`docs/COOKBOOK.md`**: ~20 canonical recipes (motion light, presence, thermostat schedule,
  notify-with-actions, washing machine done, …) each with automation + test.
- **`.hassle/registry.json`** doubles as the machine-readable entity inventory
  (agents grep it instead of guessing entity ids).
- Error messages are part of the docs surface: every Hassle error states *what*, *where*
  (file:line), and *the fix*, in one paragraph — enforced with error-message
  snapshot tests (CONTRIBUTING.md).
- Acceptance test for the docs themselves (M9): a fresh model session, given only a pulled
  bundle, must complete representative edit tasks correctly — docs iterate until it does.

---

## 13. Extensibility (G12)

Every synced kind is an `ObjectType` plugin; the sync engine, planner, bundle layout, decompiler
dispatch, and docs generator are all plugin-driven:

```python
class ObjectType(Protocol):
    kind: str                                      # "automation", "input_boolean", …
    async def list_remote(self, ha) -> dict[str, JSON]       # key → canonical config
    async def apply(self, ha, key, config | None)             # create/update/delete
    def compile(self, dsl_obj) -> IR
    def decompile(self, ir) -> DslSource
    def validate(self, ir, registry) -> list[Finding]
    def simulate(self, ir, sim) -> SimBinding | None           # optional
```

Transport sits behind a `Backend` protocol; v1 ships `DirectBackend` (long-lived token,
REST + WS straight to HA Core — works on every install type). Future backends slot in without
touching sync logic.

v1 ships: `automation`, `script`, 9 storage-collection helper domains (one shared base class —
they're near-identical). Designed-for future plugins, in rough order:

- **Scenes** — same config REST pattern as automations; nearly free.
- **Config-entry helpers** (template sensor, threshold, derivative, group…) — needs the config
  flow WS API; the plugin protocol already allows async multi-step applies.
- **Dashboards** — Lovelace storage-mode config via WS; decompiles to a card-builder DSL. The
  bundle layout reserves `dashboards/`.
- **Entity registry metadata** (friendly names, areas, labels as code) — read side already exists.
- **A thin add-on** — only if a genuinely server-side feature earns it (apply locking for
  multi-user households, scheduled snapshots, webhook-triggered CI pulls, a web UI). It would be
  an *optional* second `Backend`/service, not a requirement; v1 explicitly proves it unnecessary.

---

## 14. Security

- One credential: an HA **long-lived access token**, used directly against HA's APIs — the same
  trust model as any HA client. No new listening service, no second auth system, outbound
  connections only.
- Token storage on laptop: macOS Keychain / Secret Service via `keyring`, `HASSLE_TOKEN` env
  override for CI. Never written into the bundle (pull refuses if it finds one in `hassle.toml`;
  `hassle doctor` scans for accidentally committed secrets).
- TLS: whatever the user's HA URL provides (local HTTP on LAN, or their existing reverse-proxy /
  Nabu Casa setup). The CLI warns once when the configured URL is plain http to a non-private
  address.
- The compiler executes bundle Python **on the laptop only** (it's the user's own code). Nothing
  Hassle uploads to HA is executable by Hassle — only HA-native JSON configs (and, if the mirror
  is enabled, an inert ZIP in the media dir).

---

## 15. Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Decompiler can't model some real-world configs | High (core promise) | `raw` fallback guarantees round-trip (I3); coverage % tracked against fixture corpus from M0; user's own export becomes a fixture early |
| Jinja/HA template fidelity in simulator | High | Explicit supported subset; loud `UnsupportedTemplateError`; `--live` render escape hatch; never silently-wrong |
| Compile-time vs runtime `if` confusion | Medium | `__bool__` trap raises teaching error (§5.5); AGENTS.md headline; lint |
| HA API drift across versions | Medium | M0.V verification checklist; CLI checks HA version via `get_config` and warns outside the tested range; CI job against HA `dev` container |
| Concurrent edits (UI while pushing) | Medium | Hash re-check at apply time (§8.2); simultaneous-apply race documented as accepted limitation |
| User skips git and loses hand-written sources | Medium | `hassle init`/pull offers `git init`; one-time warning in bare directories; optional mirror (§8.5) as belt-and-suspenders |
| Media gates tightened by HA — upload Content-Type or download extension check (mirror breaks) | Low (feature is optional) | Mirror is best-effort by design; degrades to a warning; sync never depends on it |
| Bundle Python does something malicious/surprising at compile time | Low (user's own code) | Compile sandbox: no network, sys.path isolation; documented that the bundle is code you review like any repo |

## 16. Decisions log and open questions

**Decided (owner-approved 2026-07-03):**
- CLI-only architecture; no add-on in v1 (v2 decision record, top of file).
- Git is the source of truth for sources/tests; HA for live objects; `manifest.lock` is the base.
- Auth: single long-lived HA token, direct connection.
- In-HA mirror is optional and best-effort (§8.5), off by default.

**Still open for the owner:**
1. **Name**: "Hassle" (from the directory) — CLI `hassle`. OK?
2. **Embedded-Python DSL** with compile-time tracing (§5.1, §5.5) vs. a custom standalone
   language — confirm the trade-off is acceptable. This is the load-bearing decision.
3. **Helper scope v1**: storage-collection helpers only; template/threshold/etc. helpers are a
   v2 plugin (§1 non-goals) — acceptable?
4. **Live run** creates a temporary shadow automation inside HA and executes real service
   calls (§10.4) — comfortable with that?
5. **Simulator template subset** (§10.1) rather than embedding HA itself — acceptable? (The
   alternative — depending on the `homeassistant` package for template eval — is heavyweight
   but could be a later opt-in `hassle test --engine=ha` mode.)
