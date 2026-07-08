# Hassle — Implementation Plan (for the implementing agents)

Read [DESIGN.md](DESIGN.md) first (v2, CLI-only — there is no add-on). This file tells you what
to build, in what order, and — most importantly — **which tests to write before writing the
code**. Every milestone is TDD: its "Write these tests first" list is the acceptance contract.
A milestone is done when those tests (plus everything previously green) pass in CI.

## Global engineering rules (apply to every milestone)

- **R1 — Tests first.** Each work item starts by committing failing tests from the milestone's
  test list. Reviewers reject code-first PRs.
- **R2 — No network in unit tests.** Anything touching HA runs against fixtures or the fake
  backend; only `integration/`-marked tests may talk to the Dockerized HA (M6+).
- **R3 — Golden files.** Compiler/decompiler correctness is expressed as golden pairs in
  `fixtures/`. Regenerating goldens requires a human-visible diff in the PR
  (`hassle-dev goldens --update` writes them; CI fails if goldens changed without the marker).
- **R4 — Every bug becomes a regression test** before it is fixed.
- **R5 — Frozen interfaces.** After each freeze point (F1–F3 below), changing that interface
  requires updating this document in the same PR. This is what lets workstreams run in parallel.
- **R6 — Error messages are tested.** User-facing errors have snapshot tests
  (what/where/fix, one paragraph — DESIGN §12).
- **R7 — Tooling:** Python 3.12, `uv` workspace, `ruff` (format+lint), `pyright --strict` on
  `hassle-core`, `pytest`. CI = GitHub Actions: lint, typecheck, unit, integration (M6+).
- **R8 — Determinism.** No wall-clock, no randomness in core logic. Compiler/decompiler output
  and canonical JSON hashing must be byte-stable across runs and platforms (tested).

## Dependency graph / parallelism

```
M0 ──► M1 ──► M2 ─────────┐
 │      ├──► M3           ├──► M6 ──► M7 ──► M9
 │      ├──► M4           │            │
 │      └──► M5 ──────────┘            └──► M8 (parallel with M9)
 └──► M0.V (API verification, parallel with M1)
```

After M1 lands, **M2, M3, M4, M5 can be built by four parallel workstreams** — they share only
the frozen IR (F1). M8 (VS Code) and M9 (docs) can start early in stub form but finish last.

**Freeze points:**
- **F1** (end of M0): IR model schema + canonical JSON serialization + object key format
  (`"automation:<id>"` etc.).
- **F2** (start of M5): the `Backend` protocol (Python `Protocol` in `hassle-core`, spec'd in
  `docs/backend.md`) + the plan/apply data model. M5 builds the sync engine against `FakeBackend`;
  M6 builds `DirectBackend` against the same protocol — independently.
- **F3** (end of M1): DSL public API surface (`hassle.__all__`, 72 names, plus the
  `hassle.registry.entities` entry point) — additions allowed, changes are not.
  Declared in [docs/dsl-f3.md](docs/dsl-f3.md).

---

## M0 — Foundations: repo, fixture corpus, IR

**Goal:** a monorepo where `HA JSON ⇄ IR` round-trips losslessly, plus the fixture corpus every
later milestone tests against.

**Deliverables**
- Monorepo per DESIGN §3, CI green on empty packages.
- `fixtures/configs/`: **≥ 40 real-shape HA configs** — automations covering every trigger type,
  every condition type, `choose`/`if`/`repeat` (all variants)/`parallel`/`wait_template`/
  `wait_for_trigger`/`stop`/`variables`, all four `mode`s, blueprint-based automations, scripts
  with `fields`, and every storage-collection helper domain. Source them from HA docs examples +
  community forum exports; ugly real-world ones are the most valuable. Each fixture is
  `{name}.json` + provenance note.
- `fixtures/registry/home.json`: a realistic registry snapshot (≈150 entities incl. at least one
  digit-leading object_id like `sensor.3d_printer`, 12 areas, labels, services with schemas)
  used by M3/M4/M7.
- IR models (DESIGN §7.1) with parse/serialize + canonical JSON + `sha256` object hashing.
- `hassle-dev` internal CLI: `goldens`, `corpus-stats`.

**Write these tests first**
1. `test_ir_roundtrip_corpus`: for every fixture, `serialize(parse(x))` is semantically equal to
   `x` (key-order-insensitive) — parametrized over the whole corpus.
2. `test_ir_preserves_unknown_fields`: fixture with invented fields at every nesting level
   survives round-trip.
3. `test_canonical_hash_stable`: same config, shuffled key order / equivalent YAML-ish variants →
   same hash; any semantic change → different hash.
4. `test_object_key_format`: key derivation for all object kinds.

**Done when:** corpus ≥ 40 with all constructs represented (checked by `corpus-stats` in CI),
tests 1–4 green, **F1 declared**.

### M0.1 — corpus addendum (post-2026.7 finding; small, do before M1 golden work)

HA 2026.7 made **purpose-specific triggers/conditions** the UI default (DESIGN §4 quirks) —
UI-authored automations will contain them immediately, so the corpus must cover them. Add ≥ 6
fixtures: purpose triggers with entity / area / label targets; `behavior:` `first`/`each`/`all`;
`options.for`; a purpose-specific *condition* (e.g. `climate.is_target_temperature`); and one
fixture using a **renamed pre-2026.7 key** (e.g. `battery.low`) to exercise M3's rename hint.
Extend `fixtures/registry/home.json` with floors (`config/floor_registry/list` shape) and a
`purpose_vocabulary` section (the enumerated trigger/condition type list M3 validates against;
shape provisional until M6 captures the real API). IR round-trip tests must pass unchanged —
these are ordinary plural-schema configs to the IR.

### M0.V — API verification spike (parallel task, small)

DESIGN §4 was source-verified against HA core in July 2026, but must be verified
**behaviorally**. Stand up HA in Docker (`ghcr.io/home-assistant/home-assistant:stable`) and
script-verify every row of DESIGN §4 against it with a long-lived token: endpoint paths, WS
command names, payload shapes (`{domain}_id` keys on helper update/delete), auto-reload
behavior, `id`↔unique_id relationship, `skip_condition` default, blueprint config shape, and the
media upload/resolve/remove flow (incl. the Content-Type gate behavior — DESIGN §8.5 depends on
it). Deliverable: `docs/ha-api-notes.md` with request/response captures, plus corrections to
DESIGN §4 if any. These captures become the `FakeBackend` fixtures for M5.

---

## M1 — DSL + compiler

**Goal:** `bundle Python → IR` for the full DSL of DESIGN §5.

**Deliverables:** recording-context compiler; all trigger/condition builders; action recording;
`if_then/else_then/choose/repeat_*/parallel/wait_for`; template expression builder
(operator overloading → Jinja); `@macro` inlining; `@shared_script`; `@script`; helper
declarations; `raw_*` passthrough; `@blueprint_automation`; source-span tracking on every IR
node; `CompileTimeBranchError` trap; bundle loader (imports bundle in isolation, collects
registered objects, rejects duplicate ids); entity indexing form (`e.sensor["3d_printer"]`);
**`normalize_ha`** — the singular→plural / `service:`→`action:` normalization HA itself applies
on storage (docs/ha-api-notes.md §10.1), applied by the compiler to everything it emits,
including legacy-form `raw_*` bodies (added to `hassle.ir` as an F1-compatible extension;
module renamed from `hassle_core.ir` 2026-07-03, owner decision — see docs/ir-f1.md).

**Write these tests first**
1. **Golden pairs** `fixtures/dsl/{case}/bundle/…py` → `expected_ir.json`: one case per DSL
   construct, minimum 30 cases, including a "kitchen sink" automation and a compile-time
   `for room in [...]` loop generating three automations.
2. `test_macro_inlining`: macro used by two automations → both action lists contain the expansion;
   nested macros; macro-with-args.
3. `test_shared_script_compiles_to_script_and_call`: caller emits `script.turn_on`-style action;
   the script object itself emits fields from the signature.
4. `test_template_expr_golden`: expression-builder → exact Jinja strings (goldens).
5. **Error snapshots (R6):** Python `if` on a state comparison → `CompileTimeBranchError` naming
   file:line and showing the `with if_then(...)` rewrite; duplicate id; unknown option;
   `raw_automation` with non-JSON value.
6. `test_source_spans`: every IR node from a golden case maps back to the correct file:line.
7. `test_compile_deterministic` (R8): two runs, byte-identical IR JSON.
8. `test_entity_attr_and_index_equivalent`: `e.sensor._3d_printer` and `e.sensor["3d_printer"]`
   compile to the same entity reference.
9. `test_compiler_emits_plural_schema`: all compiled output uses `triggers/conditions/actions` +
   `action:`; a `raw_automation` authored with legacy singular keys and `service:` compiles to
   the plural form, and `normalize_ha` output matches HA's real POST→GET normalization pair
   captured in `docs/ha-api-captures/` (golden).
10. `test_purpose_trigger_builder` (DESIGN §5.4): `on("motion.detected", target=area("office"),
    behavior="first", for_=minutes(5))` and `met("climate.is_target_temperature", target=…)`
    golden-compile to the stored 2026.7 shape (`trigger:`/`condition:` type string, `target:`,
    `behavior:`, `options:`); all five target forms (entity/area/floor/label/device) covered.

**Done when:** goldens green, F3 declared, and every fixture-corpus *construct* is expressible
in the DSL (checklist in PR description).

---

## M1.1 — Runtime-math expression surface (additive under F3; after M1 merges, parallel with M2–M5)

Symbolic-expression extension of the template builder (SymPy-style: leaves return Expr objects,
operators compose, render to Jinja at compile time — owner-confirmed direction). Everything here
is an F3 ADDITION; no existing name may change.

**Deliverables:** math builders mirroring HA's Jinja set 1:1 (sin/cos/tan/asin/acos/atan/atan2/
sqrt/log, round_/min_/max_/abs_); constants PI/E_/TAU rendering to Jinja names (`pi`, not
3.14159…); attribute access `e.sun.sun.attr("elevation")` → `state_attr(...)`; `var("name")`
references; `param()` upgraded to a composable Expr; datetime helpers (as_datetime, timedelta_,
as_timestamp, today_at); full reflected-operator set; documented `+`-is-not-concat decision
(explicit concat helper).

**Write these tests first**
1. Acceptance examples verbatim: `param("sun_angle") / 360 * 2 * PI` and
   `var("wakeup_time") + var("offset")` → exact Jinja goldens.
2. Reflected-operator/precedence torture test (literals on either side; nested mixed ops;
   wrong grouping = failure, extra parens acceptable).
3. Trap boundary: `math.cos(state(x).value)` raises the CompileTimeBranchError-family teaching
   error; `math.pi` as a plain constant folds into a literal and compiles fine.
4. Golden `shade_tracks_sun` matching the corpus fixture byte-for-byte (see M0 corpus addendum 2).
5. Docs: operator table extended; note that expression sugar is one-way (decompiler keeps Jinja
   as `template("...")` strings).

---

## M2 — Decompiler + round-trip

**Goal:** `IR → DSL Python`, lossless against the corpus, stable, spliceable.

**Deliverables:** codegen (ruff-formatted, deterministic); `raw_*` fallback; blueprint decompile;
LibCST-based single-object splice into an existing file; DSL-coverage metric.

**Write these tests first**
1. `test_roundtrip_corpus` (**the** invariant, I3): for every fixture:
   `compile(decompile(x)) ≈ normalize_ha(x)` (canonical-hash equality; `normalize_ha(x) == x`
   for every fixture already in HA's stored plural form). No exceptions — `raw` fallback makes
   this achievable by construction. The legacy-form fixtures
   (`automation_legacy_platform_naming`, `automation_service_call_longhand`) are the cases
   where normalization applies.
2. `test_decompile_stable`: `decompile(x)` twice → identical bytes; `decompile(compile(decompile(x)))`
   → identical to first decompile (fixed point).
3. `test_decompile_prefers_dsl`: corpus coverage report ≥ **90 % of fixture objects decompile
   with zero `raw_*` nodes**; the report lists the exceptions (CI artifact, tracked over time).
4. `test_splice_preserves_rest_of_file`: file with 3 automations + comments; splice a new body
   for the middle one; other two defs and all surrounding comments byte-identical; spliced def
   carries the `# hassle: updated from UI on <date>` marker.
5. Property test (hypothesis): random IR generated from the model schema round-trips.

**Done when:** 1–5 green; coverage report ≥ 90 %.

---

## M3 — Registry, validation, stubs

**Goal:** tiers 1–3 of DESIGN §9 + stub generation, all offline against `fixtures/registry/`.

**Deliverables:** registry snapshot model; entity/service/area/device/label reference extraction
from IR **including entity ids inside Jinja strings and `raw_*` blocks**; did-you-mean
suggestions (Levenshtein); bundle-declared helpers count as existing; service-call parameter
validation against `get_services` schemas; Jinja syntax lint; `.pyi` stub generator
(entities + typed service methods, underscore-prefix rule for digit-leading object_ids);
`Finding` model (severity, file:line, message, fix).

**Write these tests first**
1. `test_unknown_entity_flagged` / `test_known_entity_ok` — incl. inside templates, inside raw
   blocks, in `entity_id: [list]` forms, and in trigger/condition/action positions.
2. `test_did_you_mean`: `light.halway` → suggests `light.hallway`.
2b. `test_purpose_vocabulary_validation`: unknown purpose type string → Finding; a renamed
    pre-2026.7 key (`battery.low`) → Finding whose fix text names the new key
    (`battery.became_low`, from the known-renames table); target `area_id`/`floor_id`/
    `label_id` values validated against the registry snapshot (floors included).
3. `test_bundle_declared_helper_counts`: automation referencing a helper declared in the same
   bundle (not in registry) validates clean; referencing an undeclared one fails.
4. `test_service_param_validation`: unknown param, wrong type, missing required — each a distinct
   Finding with correct file:line (uses M1 spans).
5. `test_stub_golden`: `fixtures/registry/home.json` → golden `entities.pyi` / `services.pyi` —
   must cover the digit-leading object_id (underscore-prefix + indexing rules, DESIGN §5.2);
   then **pyright runs against a sample bundle + those stubs in CI**: a seeded typo file produces
   the expected pyright errors (this proves the editor story end-to-end without an editor).
6. Error snapshots for the top 10 finding types (R6).

**Done when:** validation catches every seeded error in a purpose-built "broken bundle" fixture
(≥ 25 distinct seeded mistakes) with zero false positives on the clean corpus.

---

## M4 — Simulator + pytest harness

**Goal:** DESIGN §10.1–10.2: deterministic execution of compiled IR with a fake clock.

**Deliverables:** state machine; trigger engine (v1 set per DESIGN §10.1); full action executor
(`choose/if/repeat/parallel/wait_*`, variables, `stop`), **mode semantics**
(`single/restart/queued/parallel`); Jinja subset engine with `UnsupportedTemplateError` — the environment MUST register HA's math globals/filters (sin/cos/tan/asin/acos/atan/atan2/sqrt/log, pi/e/tau, round/min/max/abs), which stock jinja2 lacks, and resolve `variables:` scope in templates;
`sim` pytest fixture + assertion API (`assert_called`, `assert_not_called`, `calls`, `fire`,
`advance`, `at`, `state_change`, `set_state`); `hassle test` entry point.

**Write these tests first** (this is a behavior spec — be exhaustive; ~100 small tests)
1. Trigger semantics per type, incl. `for_:` (state must hold; reset on flap), `to`/`from`
   filters, numeric_state crossing (only fires on cross, not while above), time_pattern, sun with
   configured times, template edge (fires on false→true only).
2. Mode semantics: `restart` cancels a pending `delay` (the canonical motion-light bug);
   `single` drops re-trigger; `queued` runs after; `parallel` interleaves.
3. `wait_for_trigger` timeout vs satisfied paths; `continue_on_timeout` both values.
4. `choose`/`if` branch selection incl. default; `repeat` while/until/count/for_each.
5. Clock: `advance()` fires due time triggers in order; delays expire exactly once; no test may
   take > 1 s wall-clock (CI-enforced marker).
6. Template subset goldens + `test_unsupported_template_raises` (never silently wrong).
7. `test_sim_runs_compiled_ir_only` (I5): fixture proving the simulator input is IR, by running
   a corpus JSON automation that never existed as DSL.
8. Meta-test: the example tests from DESIGN §10.2 run green against the example bundle.

**Done when:** spec suite green; example-bundle tests green; a seeded logic bug in the example
bundle (wrong condition) is caught by its test.

---

## M5 — Sync engine (pure logic, FakeBackend)

**Goal:** DESIGN §8 exactly: manifest, three-way plan, bidirectional apply (push mutates HA via
the backend; pull mutates the working tree), conflicts — all against an in-memory `FakeBackend`
built from the M0.V captures. **F2 (the `Backend` protocol + plan/apply data model) is declared
at the START of this milestone** so M6/M7 can proceed in parallel after it.

**Write these tests first**
1. **Table-driven plan tests: one test per row of the DESIGN §8.2 table** — the table is the
   spec; name tests after rows (`test_plan_remote_edited_local_untouched_is_refresh`, …).
2. `test_pull_applies_bundle_side_actions` (DESIGN §8.3): refresh splices, adopt creates files,
   drop deletes files, conflict writes both versions with markers; **HA is never written during
   pull** (FakeBackend asserts zero writes).
3. `test_apply_reverifies_hashes`: remote drifts between plan and apply → abort, nothing written.
4. `test_apply_order_and_rollback`: helpers→scripts→automations order; injected failure at each
   step → previously-applied objects restored from snapshot; FakeBackend asserts final state ==
   initial state.
5. `test_adopt_new_remote` / `test_first_pull_adopts_all`.
6. `test_manifest_updates_only_on_success`.
7. **Fuzz test for I6**: 1 000 random sequences of {local edit, UI edit, local delete, UI delete,
   pull, push} — invariant: no edit is ever silently lost; every loss path surfaces as a
   conflict or an explicit listed action.

**Done when:** every §8.2 row tested; pull-side tests green; fuzz green.

---

## M6 — DirectBackend + real-HA integration

**Goal:** the real transport (`DirectBackend`: long-lived token, REST + WS straight to HA Core),
proven end-to-end against real HA in Docker. *(This milestone shrank when the add-on was cut —
there is no server component, no Docker image of our own, no Supervisor mocking.)*

**Deliverables:** `HaClient` (aiohttp REST + WS with reconnect/retry, request timeouts);
`DirectBackend` implementing F2 (list/fetch/apply per object kind, registry snapshot fetch,
server-side validation calls, trace access, template render); transactional apply per DESIGN
§8.2 (client-side snapshot + pre-write hash re-verify + rollback); optional media mirror module
(upload/fetch/remove per DESIGN §8.5, isolated so its failure never affects sync); HA version
check via `get_config` with a tested-range warning.

**Write these tests first** (all `integration`-marked, against Dockerized HA `stable` and `dev`)
1. Seed HA with automations/scripts/helpers via its own API → `hassle pull` → bundle compiles,
   validates, decompiled sources match goldens.
2. **The core loop:** pull → edit one automation + add one helper + delete one script + add a
   test file → plan (shows exactly 3 changes) → push → HA state verified via HA's own API →
   pull again into the same working tree → **hand-written source and the test file are
   untouched** (source preservation is local; pull only rewrites drifted objects).
3. Conflict end-to-end: edit an automation via HA's API (simulating UI) after pull, edit the
   same object locally → plan says conflict → `--accept-local` and `--accept-remote` paths both
   verified against HA.
4. `test_apply_rollback_live`: push batch where object 3 of 3 is crafted invalid (rejected by
   HA) → objects 1–2 restored; HA state hash-identical to pre-apply.
5. `test_apply_aborts_on_drift_live`: mutate an object via HA's API between plan and apply →
   apply aborts before writing anything. Include the CREATE-collision case (M5 review
   finding): an object appearing under a planned-create identity between plan and apply is
   drift too — DirectBackend must detect it and abort rather than overwrite.
   Also verify (M4 finding): does HA rewrite inner legacy `platform:` → `trigger:` on
   storage? `normalize_ha` currently preserves inner `platform:` verbatim; if HA rewrites
   it, legacy-authored objects would hash-drift and normalize_ha needs the extra rule
   (frozen-interface-compatible extension + capture evidence in docs/ha-api-notes.md).
6. UI-editability check: after apply, `GET /api/config/automation/config/{id}` returns the
   config and the automation entity exists with correct unique_id (I2 proxy for "UI can edit it").
7. Auth: bad token → clean 401 error surfaced with fix hint; `hassle login` validation path.
8. Purpose-vocabulary enumeration (DESIGN §4): find and capture the WS API the 2026.7 UI uses
   to enumerate available purpose-specific trigger/condition types; wire it into the registry
   snapshot (replacing the provisional M0.1 `purpose_vocabulary` shape — update the fixture and
   MILESTONES in the same PR per R5 if the shape differs); verify a UI-authored purpose-trigger
   automation pulls, round-trips, and pushes byte-stable against real 2026.7.
9. Mirror round-trip: upload ZIP bytes under a media extension (both gates handled — upload
   Content-Type AND download extension, per DESIGN §4 quirks), resolve + download bytes
   identical, remove works; determine and document the target-folder creation story (upload
   does not mkdir); never target the media root; simulated tightened gate (403/400/404) →
   warning, sync unaffected. Re-confirm all docs/ha-api-notes.md §10 findings on HA `stable`
   (2026.7+) — M0.V ran on 2026.2.3 (see notes §0).

**Done when:** integration suite green in CI against HA `stable` **and** `dev` tags; a smoke
checklist against the owner's real instance (`docs/SMOKE.md`) executed once.

---

## M7 — CLI UX

**Goal:** the daily-driver tool. Everything exists in core by now; this milestone is wiring + UX.

**Deliverables:** `hassle init|login|pull|status|plan|push|validate|test|run|fmt|stubs|explain|
render|mirror|doctor`; config at `~/.config/hassle/` + per-bundle `hassle.toml`; keyring token
storage (`HASSLE_TOKEN` override); **git-aware flow (DESIGN §8.4)**: pull requires clean tree
(`--allow-dirty`), push prints a ready-made commit message, `status` = plan preview + git
status, `init` offers `git init` + writes `.gitignore` + a CI workflow template; rich diff
rendering (DSL-level 3-way for conflicts); ZIP transport (`--zip` on pull/push); `run --live`
shadow-automation flow with trace-to-source-line rendering (DESIGN §10.4) incl. confirmation
gate and orphan sweep in `doctor`.

**Write these tests first**
1. CLI-level tests with `FakeBackend` for every command: exit codes, output snapshots (rich
   rendering tested via captured plain-text mode).
2. `test_push_is_plan_plus_confirm`: refuses without confirmation when deletions present;
   `--yes` bypasses.
3. `test_pull_requires_clean_tree`: dirty repo → refusal with guidance; `--allow-dirty` works;
   non-git directory → one-time warning, still functions.
4. `test_conflict_ux_snapshot`: 3-way DSL diff output golden.
4b. `test_plan_labels_modernization_diffs` (M2 review finding): a legacy-form remote object
    (inner `platform:`/scalar `delay:`) adopted then re-pushed produces a ONE-TIME plan diff
    (Hassle compiles the modern form; HA stores it verbatim thereafter — capture-verified).
    The plan renderer must label this class of diff as "modernization (one-time)" so users
    aren't alarmed; snapshot-tested.
5. `run --live` integration test (Dockerized HA): shadow created **enabled**, with its trigger
   list replaced by a single never-fires event trigger (a run-unique event type — post-M7 revision,
   docs/ha-api-notes.md §27 addendum; superseded the original `initial_state: off` design after live
   verification), triggered with `skip_condition: false` by default (HA's own default is `true` —
   assert we override it) against the shadow's real `entity_id` (resolved via `attributes.id`
   matching, never assumed as `automation.<id>` — §10.2's quirk), trace rendered with correct
   source lines, the action's real side effect independently observed (a counter helper
   increments, M0.V pattern — proves the automation actually ran, not just that the service call
   was accepted), shadow deleted — **also on failure** (inject a trace-stream error; assert
   cleanup).
6. `test_no_token_in_bundle`: pull refuses/scrubs if a token appears in `hassle.toml`; doctor
   flags a committed token.
7. End-to-end smoke on mac + linux CI runners (the two target platforms).

**Done when:** the DESIGN §8.4 loop is demoable end-to-end from a fresh laptop in < 10 commands
(scripted as the final integration test).

---

## M8 — VS Code extension (parallel with M9)

**Goal:** DESIGN §11 layers 1–2 (layer 3 LSP is stretch, separate follow-on).

**Deliverables:** `.vscode/settings.json` + pyright config emitted by `hassle init/pull`
(layer 1 — verify, don't build); extension with commands (Pull/Plan/Push/Test/Run), Problems
integration running `hassle validate --json`, "Show compiled YAML" panel using `hassle explain
--yaml`, status bar sync state. Marketplace-ready packaging (`vsce`), but private install docs
first.

**Write these tests first**
1. Layer-1 proof (already in M3 CI, extend): fresh pulled bundle opened cold → pyright finds a
   seeded entity typo with zero configuration.
2. Extension integration tests (`@vscode/test-electron`): each command invokes the CLI with
   correct args (CLI mocked); validate findings appear as diagnostics with correct ranges;
   explain panel renders for automation under cursor.
3. `hassle validate --json` schema test (shared contract with the extension, snapshot-tested on
   both sides).

**Done when:** extension works against the M7 CLI on a sample bundle in CI; manual checklist on
macOS VS Code recorded.

---

## M9 — Agent docs + polish + release

**Goal:** DESIGN §12 as a tested artifact, plus release engineering.

**Deliverables:** generators for `AGENTS.md` (bundle-specific, including the git workflow rules
from DESIGN §8.4), `docs/DSL.md` (every construct with DSL ↔ YAML pair, generated from the M1
golden cases so it can never drift from reality), `docs/COOKBOOK.md` (≥ 20 recipes, each recipe
= automation + passing test, compiled in CI); error-message audit (every Finding/exception
passes the what/where/fix rubric); versioning + compatibility policy (bundle format version in
`hassle.toml`; HA tested-version range surfaced in `hassle doctor`); install docs
(`uv tool install hassle` / `pipx`, no add-on repository needed).

**Write these tests first / acceptance**
1. `test_dsl_docs_generated_from_goldens`: docs build fails if a DSL construct lacks a
   documented pair (coverage check against `hassle.__all__`).
2. Cookbook CI: every recipe compiles, validates against the fixture registry, and its test
   passes on the simulator.
3. **Agent acceptance run** (the real gate): a scripted harness gives a fresh model session the
   pulled sample bundle + AGENTS.md only, and 10 representative tasks ("make the hallway light
   also require the house to be occupied", "add a new helper and use it", "find why this test
   fails", …). ≥ 8/10 must produce changes that pass `hassle validate && hassle test` without
   human help. Iterate docs until green; keep the harness as a permanent regression suite.
4. Bundle-format version test: newer-major bundle opened by older CLI → clear upgrade error, no
   partial operation.

**Done when:** agent acceptance ≥ 8/10, cookbook green, release artifacts published (PyPI), and
the owner has run the `docs/SMOKE.md` checklist against the real house. 🎉

---

## M10 — Config-entry helpers: the template-helper plugin (owner-commissioned, revises the v1 non-goal)

Owner field need: template helpers (e.g. `number.active_hvac_zones`, platform `template`) are
config-entry objects, invisible to sync. This milestone builds the first config-entry
`ObjectType` plugin (DESIGN §13's protocol, finally exercised as designed), scoped to the
**template** domain first (number/sensor/binary_sensor/select at minimum); other config-entry
helper domains (threshold, derivative, group, …) become mechanical follow-ons.

**Write these tests first**
1. Capture-driven backend tests: WS `config_entries/get` (filter domain=template) list/read of
   entry options; create via `config_entries/flow` (handler=template: menu step → type step →
   form step) and update via `config_entries/options/flow` — FakeBackend models the multi-step
   flows; the REAL flow shapes are captured by extending the CI integration suite (M6 pattern,
   HA stable + dev) — integration test creates/updates/deletes a template number end-to-end.
2. DSL declarations: `template_number(id=..., name=..., state="{{ ... }}", min=..., max=...)`
   (+ template_sensor/binary_sensor/select), registered as prebuilt objects; golden pairs.
   **Amended by CI evidence (docs/ha-api-notes.md §26.6):** no `id=` kwarg exists in the
   implemented DSL — real HA's config-flow schema rejects a caller-supplied `unique_id` outright,
   so `name=` is the sole identity-bearing kwarg (`slugify(name)` derives the object key).
   `template_number`/`template_select` also gained required `set_value=`/`select_option=` kwargs
   (HA's own schema requires a write-target action sequence for a writable entity). See the
   identity-freeze note below for the full re-freeze.
3. Decompile/adopt into `helpers/` with the same category/misc placement rules; round-trip
   byte-stable against the entry-options shape (I3 applies to options bodies).
4. Plan/apply: create = full flow; update = options flow; delete = config entry removal;
   CREATE-collision drift + rollback semantics matching §8.2; fuzz extension covering the new
   kind. Identity: config entry_id is HA-side identity (I2 analog: never change it; object key
   uses the declared unique id — decide and freeze the key form in the same PR).
5. Ignore-glob + validation interplay (declared template helpers count as existing, §9).

DESIGN amendments in the same series: §1 non-goals (config-entry helpers move from v2 to M10),
§13 (plugin protocol gains the flow-based apply notes).

**Identity freeze, ORIGINAL (`m10/template-helpers`, CI round 1) — SUPERSEDED, see below:** object
key `"<template domain>:<unique_id>"`, `unique_id` a caller-declared DSL kwarg. **CI round 2 found
this un-implementable against real HA**: the `template` config flow's form schema rejects an
unrecognized `unique_id` key outright (`400 {"errors": {"base": ["extra keys not allowed @
data['unique_id']"]}}`, both HA `stable` and `dev` — docs/ha-api-notes.md §26.6) — a flow-created
entry has no caller-settable unique id at all. Per R5, un-freezing and re-freezing in the same
series with the evidence:

**Identity freeze, RE-FROZEN (`m10/template-helpers`, CI round 2 evidence, docs/ha-api-notes.md
§26.6):** object key is `"<template domain>:<slugify(name)>"` (e.g.
`"template_number:active_hvac_zones"` for `name="Active HVAC Zones"`) — identity is DERIVED from
the declared `name` (the DSL's `name=` kwarg, required), mirroring the nine storage helpers'
"id is a slug of name" rule (§4/§17.5) exactly, except here it is the ONLY identity source (no
override kwarg exists — there is nothing else HA lets a caller set). `TemplateHelperConfig`
(`hassle.ir.models`) has no `unique_id`/`id` field at all; `identity` is a computed property. The
object-key *format* itself is unchanged (`object_key(kind, identity)`, F1, additive:
`TEMPLATE_DOMAINS` widens `OBJECT_KINDS`). On the wire, the config flow sets the entry's `title`
from the submitted `name`; `list_remote` re-derives the identical identity by slugifying
`entry["title"]` on read-back. Sub-kind discrimination (which of the 4 template domains a listed
entry is) is resolved via the entity registry's `config_entry_id` cross-reference (a WS call,
`config/entity_registry/list`), not a client-side marker — the sub-kind data can't travel through
`options` either, for the same "no bookkeeping keys in the form schema" reason.

HA's config entry `entry_id` remains transport-side identity only (unaffected by the identity
redesign): tracked in `ManifestEntry.entry_id` (additive optional field, `hassle.sync.models`),
never in the IR body and never in the object key. An UPDATE never changes `entry_id` (I2 analog,
driven through the options flow); a DELETE followed by a re-CREATE under the same name-derived
identity gets a **fresh** `entry_id` from HA — documented, not hidden, as the rollback-by-recreate
caveat (docs/ha-api-notes.md §26.3). `template_number`/`template_select` additionally require a
write-target action sequence (`set_value=`/`select_option=`, §26.6) — HA's own form schema rejects
the submission without one. See docs/backend.md §3.1 and docs/ha-api-notes.md §26 (especially
§26.0 and §26.6) for the full mechanics; `Backend` (F2) itself required zero changes throughout
both rounds of correction.

---

## M11 — Category write-back on create (owner-commissioned)

New automations/scripts authored in a category-named bundle file get the matching HA category
assigned on push-create (entity registry write — first registry write; I1 holds: same WS APIs
the UI uses).

**Write these tests first**
1. Push-create of an automation whose source file is `automations/automatic_hvac.py` →
   after apply, the entity-registry entry carries the category whose name slugifies to
   `automatic_hvac` (FakeBackend models `config/entity_registry/update` + category registries;
   CI integration verifies live).
2. Missing category → created first via `config/category_registry/create` (scope-correct),
   then assigned; `misc.py` (or any non-category file) → no category action.
3. Failure isolation: category assignment failure NEVER fails or rolls back the object apply
   (it's metadata; warn and continue — test proves apply survives a category API error).
4. No retroactive changes: existing/adopted objects' categories are never touched (test).

---

## M12 — Category display names via `CATEGORY` module global (owner-commissioned)

**Goal:** M11 invents a display name (`humanize_slug("automatic_hvac")` → "Automatic Hvac")
when push-create has to CREATE a category — acronyms/punctuation are unrecoverable from a
slug. An optional module-level `CATEGORY: str = "Automatic HVAC"` in a category-shaped
bundle file (`automations/<slug>.py` / `scripts/<slug>.py`) supplies the exact name; pull
writes it so display names round-trip through source.

**Semantics (binding):**
- `slugify(CATEGORY)` MUST equal the file stem. Mismatch → validation Finding
  (what/where/fix, snapshot-tested); category write-back additionally ignores the global
  with a warning (never guesses which side is right).
- Used ONLY when creating a brand-new category. Matching stays slug-based; an existing HA
  category is NEVER renamed by push (no surprise renames — the HA UI owns renames).
- `hassle pull`, when it creates a NEW category file, emits the `CATEGORY = "…"` line from
  the HA category's real name. The splicer must leave the global intact on REFRESH/DROP
  (it is a top-level non-object statement).

**Write these tests first**
1. Push-create in a file with `CATEGORY = "Automatic HVAC"` → created category's name is
   exactly that string (FakeBackend; DirectBackend payload test).
2. `CATEGORY` that doesn't slugify to the stem → Finding (snapshot) + write-back warning
   path; object apply still succeeds (M11 test-3 isolation unchanged).
3. No `CATEGORY` → `humanize_slug` fallback byte-identical to M11 behavior.
4. Pull of a categorized bundle emits the global; re-pull is byte-stable; splice
   REFRESH/DROP of objects in that file preserves the line.
5. Existing-category match never consults or writes `CATEGORY` (no rename attempted).

---

## M13 — Template-helper expression DSL: decorator form + bounded Jinja inversion (owner-commissioned)

**Goal:** template helpers writable as decorated functions whose body returns a
`TemplateExpr` (the M1.1 python→Jinja surface, `hassle.compiler.math_expr`/`templates`)
instead of a raw Jinja string:

```python
@template_sensor(name="Average Temp", unit_of_measurement="°C", device_class="temperature")
def average_temp():
    return (states("sensor.a") | float_) / 2 + …   # exact spelling = existing M1.1 surface
```

The decorator form compiles to the IDENTICAL IR body as today's call form (`state=` becomes
the rendered Jinja). Existing call form stays (F3 additions only). Identity remains
`slug(name)` (§26.6) — the function name is cosmetic, like automations' function names.

**Decompiler direction (bounded inversion, owner-approved fallback):** implement an inverse
parser ONLY for the exact grammar the `TemplateExpr` renderer emits (literals, entity
reads, the emitted filters/functions, arithmetic with the renderer's precedence/parens).
Acceptance rule per template: `render(invert(jinja)) == jinja` BYTE-FOR-BYTE → decompile to
the decorator form; anything else → today's string-state call form (the raw fallback). I3
therefore holds trivially in both branches. Consequence (documented, deliberate): if a
template is edited on the HA side into something non-invertible, the next pull REFRESH
splices the user's decorator-form function away, replacing it with the call form — cleaner
Python is an offer, not a guarantee (I6: nothing is lost; the config is fully present in
the fallback).

**Write these tests first**
1. Golden DSL↔IR pair: decorator-form fixture for all four template domains compiles to
   the same IR as the equivalent call form (byte-identical bodies).
2. Inversion property test: for EVERY template the fixture corpus + renderer tests emit,
   `render(invert(t)) == t` byte-for-byte, and the decompiled decorator source recompiles
   to the identical IR (I3 through the nice branch).
3. Fallback: a hand-written gnarly Jinja template (loops/macros/whitespace tricks) decompiles
   to the string-state call form, never errors, and round-trips byte-stably (I3 through the
   fallback branch).
4. Refresh-overwrite: bundle has a decorator-form helper; remote template edited to
   something non-invertible; pull REFRESH replaces the function with the call form via the
   splicer (integration-level test with FakeBackend; no data loss).
5. Bad decorator body (returns a non-TemplateExpr/str, takes arguments, calls services) →
   R6 compile error, snapshot-tested.
6. Docs gate: new construct documented (goldens/docs regenerated via `hassle-dev … --update`
   with the diff shown, R3).

---

## M14 — Decorator form is the canonical template-helper output, both branches (owner-commissioned)

**Goal:** M13's decompiler emits the decorator form only when Jinja inversion is byte-exact;
non-invertible templates fall back to the call form. Owner feedback: the fallback should ALSO
be the decorator shape, with the raw Jinja as the string body — same IR, same I3 guarantee,
but hand-converting a helper to Python later means rewriting only the `return` expression:

```python
@template_number(name="Active HVAC Zones", min=0.0, ..., set_value=[])
def active_hvac_zones():
    return """{% set entities = [ ... ] %}
{{ entities | map('states') | ... | count }}"""
```

**Semantics (binding):**
- Both decompile branches emit the decorator form; the only difference is the body
  (inverted `TemplateExpr` expression vs. verbatim raw-string return). The call form stays
  valid DSL (F3) — it just stops being canonical output.
- The raw-string body must reproduce the stored template BYTE-FOR-BYTE on recompile (I3):
  choose quoting (triple-quote / escaping) mechanically so arbitrary template text —
  embedded quotes, backslashes, trailing newlines, `"""` inside the template — survives.
- `template_select.options=` (the second template) stays a kwarg, unchanged this round.
- Function names derive from slug(name), deterministic; collisions with other decompiled
  names follow the existing codegen uniquing rules.

**Write these tests first**
1. Golden update: the non-invertible fixture(s) (e.g. the gnarly-Jinja fallback fixture)
   now decompile to decorator-with-string form; `compile(decompile(x)) == x` still holds
   (I3 fallback branch).
2. Quoting torture test: templates containing `"""`, `'''`, backslashes, trailing/leading
   newlines, and both quote characters round-trip byte-exactly.
3. Invertible branch output unchanged (regression: the M13 decorator-expression golden is
   byte-identical before/after M14).
4. Splice REFRESH: a remote edit to a decorator-with-string helper re-splices in place;
   the M13 downgrade test now asserts decorator-with-string (not call form) as the result.
5. Byte-stable re-decompile (R8 determinism).

---

## M15 — Category-first bundle layout: coworkers in one file (owner-commissioned)

**Goal:** replace the type-tree layout (`automations/<cat>.py`, `scripts/<cat>.py`,
`helpers/misc.py`) with category-first, mixed-kind files at the bundle root: `hvac.py`
holds the HVAC automations AND their template helpers AND scripts; `misc.py` holds
everything uncategorized. Evidence base: docs/ha-api-notes.md §31 (source-verified) —
ALL helper domains (nine storage-collection + four template config-entry) carry
categories under the shared frontend scope `"helpers"`, so helper grouping round-trips
through HA; it is NOT source-only metadata. DESIGN §7.3 must be amended in the same PR
(R5-style: layout is a design-level surface).

**Binding semantics:**
- **Placement = category.** An object's file is derived from its own scope's category
  (`automation`→scope `automation`, `script`→scope `script`, every helper kind→scope
  `helpers`); same category name across scopes → same file (slug anchor per scope,
  independently — §31.6). No category → `misc.py`.
- **Local moves sync back (the key new behavior).** Moving an EXISTING object to a
  different category file is a category reassignment on push — extends M11's
  create-only write-back to updates. Three-way: `ManifestEntry` gains an optional
  `category` field (base category slug; F2 amendment — this line is that amendment,
  binding once merged) so a local move + a conflicting HA-side recategorization is
  surfaced as a conflict (I6), never silently overwritten in either direction.
- **Per-scope creation/divergence policy (§31.6.2):** a mixed-kind file maps to up to
  three category rows (scopes automation/script/helpers) sharing a name; push creates
  per scope on demand (CATEGORY global supplies the display name, else humanize_slug).
  If HA-side renames make the scopes' names diverge for what was one file, pull places
  each object by its OWN scope's category (files may split) and emits a
  divergence warning naming the scopes — never guesses a winner.
- **Backend simplifications from §31.5:** `_aassign_category` sends a single-scope
  merge payload (no read-first); integration teardown uses the now-confirmed
  `config/category_registry/delete`; the false "only two scopes" comments in
  `category_writeback.py`/`bundle_ops.py` (and §22-derived docstrings) are corrected.
- **Migration:** old-layout bundles are detected (type trees present) and restructured
  by the next `hassle pull`: managed objects move to their category files (splice DROP
  from old files, regenerate into new); old files are deleted ONLY when no user content
  remains (I6); every move is reported in pull output; `hassle.toml` bundle-format
  version bumps (M9 versioning surface: older CLI opening a newer bundle → clear
  upgrade error).
- `CATEGORY` global (M12) semantics unchanged, now applying to root-level
  `<slug>.py` files; `category_shaped_stem` learns the new shape (root-level, stem ≠
  `misc`, excluding `lib/`/`tests/`/`docs/`/dot-dirs).

**Work item A — sync semantics (do first):**
1. Pull placement reads helper categories (scope `helpers`) for all 13 helper kinds;
   FakeBackend models per-scope entity-registry categories incl. the same-object
   two-scope case (§31.5d) — live integration test assigns a category to a
   storage-collection helper AND a template helper via Hassle and reads both back.
2. Write-back extended: create AND move-update for every kind; manifest base category;
   conflict test (local move + remote recategorize → conflict, not silent win).
3. Single-scope merge payload + delete-based teardown; §31.5d same-object two-scope
   I6 test; corrected comments/docstrings.

**Work item B — layout + migration (after A merges):**
4. Root-level mixed-kind decompile placement + codegen imports across kinds in one
   file; `misc.py` fallback; predicate/init scaffold/AGENTS.md/docs updates.
5. Migration test: an old-layout bundle with user content in an old file pulls into
   the new layout with nothing lost (I6), byte-stable second pull, plan noop after.
6. Acceptance sample bundle regenerated in the new layout; harness presupposition
   tests updated; `hassle-dev acceptance-bundle` output stays deterministic.
7. Bundle-format version bump test (older-CLI clear error, M9 test 4 pattern).

---

## M16 — String-state expression vocabulary (owner-commissioned)

**Goal:** the `TemplateExpr` surface (M1.1) reads entity state ONLY numerically —
`expr(x)` renders `states('x') | float` — so a string-state check like
`is_state('sensor.keaton_watch_beacon_area', 'Living Room')` is inexpressible, and
(equivalently) `is_state`/bare-`states()` templates are not invertible. The owner wants
custom helper functions like `check_beacon(sensor, area)` composing with `&`/`|`/`~`.
Composition already works (plain Python functions returning `TemplateExpr`); the missing
piece is the string vocabulary.

**Surface (F3 additions only; exact names final unless pyright/collision forces change):**
- `state_of(entity_or_id) -> TemplateExpr` — bare string read, renders `states('<id>')`
  (accepts `e.`-registry refs and strings, like `expr`).
- String comparisons via the existing `.eq()/.ne()` methods against string literals
  (renders `states('x') == 'y'`); membership `.in_(["a", "b"])` renders `in ['a', 'b']`.
- Boolean composition/negation unchanged (`&`/`|`/`~`).

**Inverter coverage (both real-world spellings normalize to the DSL, then render
canonically):**
- `states('x') == 'y'` / `!=` / `in [...]` → `state_of(...)` forms.
- `is_state('x', 'y')` → `state_of('x').eq('y')` — NOTE: the renderer emits
  `states('x') == 'y'`, so a UI-authored `is_state(...)` template inverts to Python but
  its re-render differs textually → byte-exact gate fails → falls back THIS pull; after
  the user converts by hand (or pushes any edit), the canonical spelling is stored and
  inverts forever after. Document this explicitly in docs/DSL.md ("one-time
  canonicalization on push"). Do NOT weaken the byte-exact rule to force it.

**Write these tests first**
1. Unit: `state_of(...).eq("Living Room")` renders exactly `{{ states('sensor.x') ==
   'Living Room' }}`; composition `a | b`, `a & b`, `~a` parenthesization matches the
   renderer's precedence rules; `e.`-ref and string args both accepted.
2. Custom-function composition test mirroring the owner's case: a plain function
   returning `state_of(...).eq(...)`, composed with `|`, used as a
   `@template_binary_sensor` body, compiles to the exact expected template (golden pair
   fixture).
3. Inverter: `states('x') == 'y'`, `!=`, `in [...]` forms invert and re-render
   byte-exactly (I3 nice branch); the owner's real Bermuda template
   (`is_state(...) or is_state(...)`, multi-line) still falls back cleanly (byte-exact
   gate holds), while its hand-converted canonical form round-trips as Python.
4. Simulator: templates using bare `states()`/string equality evaluate correctly in
   `hassle test` (extend the M4 Jinja subset if bare `states()` string reads are not
   already supported there — verify, don't assume).
5. Error surface: `.eq()` against a non-literal/non-expr, or `state_of()` on a non-entity
   arg → R6 compile error, snapshot-tested.
6. Docs gate: new constructs in the construct map; DSL.md regenerated via `--update`.

---

## M17 — Bundle-as-uv-project scaffold (local path source; PyPI deferred) (owner-commissioned)

**Goal:** `uv run hassle ...` should work standalone inside a bundle directory, without the
user having to know this is a monorepo workspace member. `hassle init`/`hassle pull` scaffold
a `pyproject.toml` at the bundle root that declares the bundle as its own tiny uv project
depending on `hassle-cli`, using a local path source when a toolchain source checkout can be
resolved (this repo, cloned, not yet published to PyPI) and falling back to a bare dependency
otherwise (works once `hassle-cli` is published).

**Binding semantics:**
- `hassle init` and `hassle pull` scaffold `pyproject.toml` at the bundle root **if missing**,
  and **never touch an existing one** — pyproject is user territory once created (I6), unlike
  `.vscode/settings.json` (which is wholly machine-generated and rewritten every time). This
  holds even if the existing file is malformed TOML: Hassle never parses or validates it, just
  checks for its existence.
- Content when scaffolding: `[project]` `name` = slugified bundle directory name (reuses
  `hassle.ir.keys.slugify`), `version = "0.0.0"`, `requires-python = ">=3.12"`,
  `dependencies = ["hassle-cli"]`. When a toolchain source checkout is resolvable (see below),
  additionally: `[tool.uv.sources]` `hassle-cli = { path = "<toolchain>/packages/hassle-cli",
  editable = true }`.
- **Toolchain path resolution order** (first hit wins):
  1. An explicit `toolchain_path` key in `hassle.toml` (new config-surface field, `config.py`;
     documented in that module's docstring same as `ha_url`/`ignore`/etc.).
  2. Auto-detect: resolve `hassle_cli.__file__` upward looking for a directory containing a
     `pyproject.toml` whose `[project].name == "hassle-cli"` (i.e. the running CLI is an
     editable install from a source checkout, exactly this repo's own dev loop) — the
     `[tool.uv.sources]` path then points at that checkout's `packages/hassle-cli`.
  3. Neither resolves → scaffold WITHOUT `[tool.uv.sources]` (bare dependency, the shape that
     works once `hassle-cli` is on PyPI) and print a one-line note that `uv run hassle` needs
     either a published package or a `toolchain_path` set in `hassle.toml`.
- `.vscode/settings.json` is unchanged by this milestone (no settings-merge implemented; out of
  scope, left exactly as today's rewrite-every-time behavior).
- `hassle doctor` reports uv-project status as three offline, filesystem-only checks (no
  subprocess spawning `uv` in unit tests — a live `uv run hassle --help` invocation is
  mentioned in doctor's text but never executed by the check itself):
  1. `pyproject.toml` present?
  2. If present and it has a `[tool.uv.sources]` `hassle-cli` path entry, does that path exist
     on disk?
  3. A one-line "looks runnable via `uv run hassle`" / actionable-note summary derived purely
     from (1)+(2), never a real subprocess call.
- **Determinism:** the scaffolded `pyproject.toml` is byte-stable given the same bundle dir
  name + the same resolved toolchain path (or its absence) — no wall-clock, no randomness. The
  auto-detected path is machine-specific BY DESIGN (a comment line inside the generated
  `[tool.uv.sources]` block says so, and this is documented in `docs/ha-api-notes.md`) — but
  `hassle-dev acceptance-bundle`'s output must stay byte-identical across machines/runs
  regardless (R8/M9 test 3's harness precondition): since that generator drives the real
  `hassle pull` pipeline from inside THIS repo's own editable checkout, auto-detection would
  otherwise resolve to a real (machine/checkout-specific, but for CI still absolute-path-
  shaped) path and embed it — this generator suppresses `[tool.uv.sources]` in its output
  (bare-dependency shape only), the same normalize-after-the-fact convention
  `_normalize_for_determinism` already uses for `hassle.toml`'s `ha_url`/`synced_at`.

**Write these tests first**
1. `init` scaffolds `pyproject.toml` with a `[tool.uv.sources]` `hassle-cli` path entry when
   the toolchain resolution seam is faked to resolve (unit test fakes the seam — this repo's
   own checkout is also a real, incidental positive case, exercised separately).
2. Existing `pyproject.toml` is NEVER modified by `init` or `pull`, byte-identical before/after
   both — including when the existing file is malformed TOML (Hassle must not even attempt to
   parse it, only check existence).
3. `toolchain_path` in `hassle.toml` beats auto-detection (a fake auto-detect result present
   but a different explicit `toolchain_path` config wins); neither resolves → bare
   `dependencies = ["hassle-cli"]` with no `[tool.uv.sources]` table, plus the one-line note
   printed by `init`/`pull`.
4. `doctor` prints the right line for each of: no `pyproject.toml`; `pyproject.toml` present
   with a resolving sources path; present with a non-resolving (stale) sources path; present
   with no sources table at all (bare-dependency shape) — all filesystem-only, no `uv`
   subprocess spawned (assert via monkeypatching `subprocess.run`/`Popen` to raise if called).
5. `hassle-dev acceptance-bundle` output is byte-identical across two separate runs, and
   contains no absolute filesystem path anywhere under the generated `pyproject.toml` (or
   anywhere else in the tree) — extends the existing determinism test for this generator.
6. `config.py` round-trip: `toolchain_path` written/read via `load_config`/a
   `persist_toolchain_path`-style writer (line-surgical, same convention as `persist_ha_url`),
   defaults to `None` when absent.

---

## M18 — Typed service namespaces: `cover.close_cover(...)` (owner-commissioned)

**Goal:** almost every action decompiles to `service("cover.close_cover", target=..., ...)`.
The owner wants domain-namespaced calls — and the design already half-promised the sibling
form: `hassle stubs` has ALWAYS emitted typed service methods on entity classes
(`stubs._service_method`), but the runtime never implemented them (calling
`e.cover.x.close_cover()` is a TypeError today while Pylance blesses it — a latent
stub/runtime mismatch this milestone closes).

**Surfaces (F3: `hassle.services` is a new module, imported explicitly per domain — NOT
part of the `from hassle import *` star surface, since domains are instance-dynamic; note
in docs/dsl-f3.md):**
1. `from hassle.services import cover` → `cover.close_cover(target=..., **fields)` records
   byte-identical IR to the equivalent `service(...)` call. Module-level PEP 562
   `__getattr__` accepts any domain; domain objects accept any service name (offline
   compile never fails on an unknown service — that's validate's job: unknown
   `domain.service` → Finding with did-you-mean, wired through the existing
   `hassle.registry.didyoumean`/service-param machinery).
2. Entity-method sugar: `e.cover.x.close_cover(position=60)` records the same IR with
   `target={"entity_id": "cover.x"}` implicit. Bare attribute access stays an attribute
   ref (`.attr(...)` etc. unchanged) — only CALLS record actions.
3. Stubs: new generated `typings` for `hassle.services` (per-domain classes, typed kwargs
   from `snapshot.services`, reusing `_service_method`'s field typing); entity-method
   stubs already exist and become truthful.

**Decompiler canonical form:** a plain service-call action whose literal
`"domain.service"` exists in the registry snapshot and whose data is kwarg-expressible
emits the namespace call plus a per-file `from hassle.services import <domains>` line
(splice refresh path merges the import via the existing `merge_missing_imports` seam).
Everything else (templated service names, snapshot-absent services, no snapshot
available, non-kwarg-safe data keys) falls back to today's `service(...)` — I3 byte-exact
through BOTH branches. Entity-method form is author-only sugar, never emitted (one
canonical form; no placement-dependent output).

**Write these tests first**
1. Regression pinning today's mismatch: calling a stub-promised entity method currently
   raises TypeError (red against main); green = records the service action.
2. IR equivalence: namespace call, entity-method call, and `service(...)` compile to
   byte-identical IR for the same inputs (golden pair fixture incl. multi-domain file).
3. Decompiler: snapshot-present plain calls emit namespace form (golden update via
   `hassle-dev goldens --update`, diff visible); templated/unknown/no-snapshot inputs
   fall back to `service(...)`; both branches round-trip byte-stably (I3); refresh
   splice merges the new import into an existing file.
4. Validate: unknown service via namespace → Finding with did-you-mean, file:line of the
   call (span capture like other builders); service-param validation applies equally.
5. Stubs: generated hassle.services stub is deterministic, format-clean, typo-squiggle
   effective (extend the M8 pyright integration test with a misspelled service).
6. Simulator: namespace/entity-method calls execute identically to `service(...)` in
   `hassle test` (I5).
7. Docs gate: constructs documented; DSL.md regenerated via `--update`.

---

## M19 — Shared-script parameters are real template values (owner-commissioned)

**Goal:** inside a `@shared_script` body, the function's own parameters should BE the
runtime field references — `tag=tag` instead of `tag="{{ tag }}"`, composable with the
whole expression surface (`concat(tag, "_x")`, `tag.eq(...)`) — and the decompiler should
emit that form. Today the compiler invokes the body with the Python DEFAULTS (verified:
`tag` is literally `None` inside), `param("tag")` is the only marker surface, and
decompiled bodies carry raw `"{{ tag }}"` strings.

**Binding semantics:**
- Compiling a shared-script body binds EACH signature parameter to its `param(name)`
  marker (a `TemplateExpr`), regardless of declared defaults. Defaults remain
  metadata for the generated `fields` block only.
- Python operations a marker cannot honestly support (`bool()`/`range()`/`int()`-style
  compile-time use) fail LOUDLY with an R6 what/where/fix error naming the escape
  hatch — new `param_default("times")` returns the declared compile-time default for
  deliberate metaprogramming (the `for _ in range(...)` unroll pattern). Audit the
  fixture corpus + docs (LIB_README's `flash_lights`, COOKBOOK recipes) and migrate any
  defaults-bound bodies via the escape hatch in the same PR.
- Caller side unchanged: literals and expressions both remain valid call-site data.
- Decompiler: inside a shared-script body, a `"{{ <field> }}"` data value whose name is
  exactly one of the script's own fields decompiles to the bare parameter name (and
  larger invertible expressions containing field reads decompile through the M13/M16
  inverter with fields bound as parameters); byte-exact re-render gate as always,
  raw-string fallback otherwise. I3 both branches.

**Write these tests first**
1. Golden: body written with `tag=tag` and a composed `concat(tag, ...)` compiles to the
   exact `"{{ tag }}"` / `"{{ tag ~ '...' }}"` IR the string form produces (byte-identical
   to the `param()` form).
2. Marker misuse: `range(times)` / `if tag:` in a body → R6 error naming
   `param_default()`; `param_default` itself returns the declared default and its
   result is NOT a TemplateExpr.
3. Decompile: the owner's dismiss_notification shape round-trips as `tag=tag` (fixture);
   a field read inside a bigger invertible expression round-trips composed; a
   non-invertible template keeps the raw string (I3 fallback).
4. `param()` remains valid and equivalent (back-compat, F3).
5. Corpus/docs migration: every existing shared-script fixture still compiles
   byte-identically (or its golden is regenerated via the mechanism with the diff
   shown and a stated reason).
6. Simulator parity (I5) for marker-bound bodies.

---

## Milestone sizing (rough, for planning the swarm)

| Milestone | Size | Parallel workstreams inside |
|---|---|---|
| M0 (+M0.V) | M | 2 (IR / corpus+spike) |
| M1 | L | 3 (triggers+conditions / actions+control-flow / templates+macros) |
| M2 | L | 2 (codegen / splice+coverage) |
| M3 | M | 2 (validation / stubs) |
| M4 | L | 3 (triggers / actions+modes / templates+fixture) |
| M5 | M | 1–2 |
| M6 | M *(was L with the add-on)* | 2 (backend / integration harness + mirror) |
| M7 | M | 2 |
| M8 | S–M | 1 |
| M9 | M | 2 (docs generators / agent-acceptance harness) |
