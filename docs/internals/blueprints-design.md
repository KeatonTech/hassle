# Blueprints as first-class objects — design

Status: **implemented** — the managed object kind on `feat/blueprint-objects`
(21 commits, `ae06bc3..HEAD`; reconciled against the code below on
2026-08-09), and DSL authoring (§8) on `feat/blueprint-dsl` (branched off
`a7ce338`), where the former sketch is now the full design section it was
built to; §8 carries two dated corrections of its own, and §6 a third from
the DSL's new rule. Everything
HA-behavioral here was probed live on
2026-08-10 against the owner's HA (see §2) and folded into
`docs/internals/ha-api-notes.md` §40.1–§40.6 with raw captures, per house
convention.

Where implementation found reality — or an underspecified corner of this
document itself — diverging from the text below, the statement is corrected
**in place** with a dated, boxed note naming the finding; §3 (three notes),
§4 (two notes) and §6 (two notes) each carry one or more. Read those before
trusting a claim below from memory.

Companion documents: [DESIGN.md](../../DESIGN.md), [CONTRIBUTING.md](../../CONTRIBUTING.md),
and the contracts this extends additively: [ir-format.md](ir-format.md),
[backend-protocol.md](backend-protocol.md). Builds directly on the simulator
blueprint support landed on `feat/simulator-blueprints`
(`hassle.testing.blueprints`, DESIGN §10.1's blueprint bullet).

---

## 0. Summary

Hassle gains a new object kind, `blueprint`: the blueprint **source files**
that `@blueprint_automation` instances reference become managed, planned,
pushed and ordered like every other object — instead of YAML on the side
that a human must remember to upload before the instances that need it.

Field motivation (BrandtCamp, 2026-08-10, the first bundle-authored
blueprint): the file had to be uploaded by a hand-run websocket script;
pushing the 17 instances before the file existed would have made HA reject
every one; and a validation bug in the blueprint itself (§6) surfaced as an
HTTP 400 forty minutes into a transactional push instead of as a
`hassle validate` finding. All three failure modes are sync-layer gaps this
design closes.

Part one (§1–§7): the blueprint file as a managed object.
Part two (§8): blueprints authored in the DSL, YAML as a compiled
artifact.

## 1. Object model

- **Kind**: `blueprint`. **Key**: `blueprint:<domain>/<path>`, e.g.
  `blueprint:automation/local/room-switch-controls.yaml`. `<domain>` is HA's
  blueprint domain (`automation`, `script`); `<path>` is exactly the string
  instances put in `use_blueprint`.
- **Source of truth**: the bundle file `blueprints/<domain>/<path>` —
  the layout `hassle.testing.blueprints.BLUEPRINT_SUBDIR` already reads and
  HA itself uses under `config/blueprints/`. (That constant currently pins
  `automation`; generalizing it to per-domain is part of this work and
  additive.)
- **IR object**: the raw YAML text (byte-preserved; a discovered file is
  authored, not generated — §8's DSL blueprints generate theirs) plus the parsed `blueprint.input` metadata for
  validation. Parsing reuses the loader in `hassle.testing.blueprints`,
  which is **promoted to `hassle.blueprints`** (core) and re-exported from
  its current name for compatibility — the validator (§6) must not import
  from a testing module.

## 2. Empirical API surface (probed 2026-08-10)

✅ Folded into `docs/internals/ha-api-notes.md` §40.1–§40.6, which reproduces
this exact table alongside the capture notes (no separate raw-capture JSON for
this kind — the captures live inline in that section, unlike dashboards'
`docs/ha-api-captures/dashboards-db0.json`).

| WS command | Exists | Notes |
|---|---|---|
| `blueprint/list` | ✅ | metadata only (name, inputs, source_url); no source text |
| `blueprint/save` | ✅ | `{domain, path, yaml, allow_override}` — used live for the first deploy |
| `blueprint/delete` | ✅ | errors `unknown_error`/ENOENT on a missing path (still distinguishable from `unknown_command`) |
| `blueprint/source`, `blueprint/get`, `blueprint/get_source` | ❌ | `unknown_command` — **HA cannot serve a blueprint's source back** |
| `blueprint/substitute` | ✅ | `{domain, path, input}` → expanded config **derived from HA's copy**; validates required inputs (its error enumerates missing ones) |

Two consequences shape everything below:

1. **No source read** → the object is push-authoritative. A three-way text
   merge is impossible; pull cannot materialize a remote-only blueprint.
2. **`blueprint/substitute` is a remote-expansion oracle** → drift IS
   detectable without source access: substitute remotely with a known input
   set, expand locally with the same inputs
   (`hassle.blueprints.expand_blueprint`), normalize, compare. Equal
   expansions ⇒ the copies agree in every way that can matter to an
   instance.

## 3. Plan semantics

Existence via `blueprint/list`; content via the manifest's stored hash of
the local file at last push; optionally corroborated by the
substitute-compare oracle (§2.2).

| Local file | In manifest | Remote (list) | Plan row |
|---|---|---|---|
| yes | no | no | `create` |
| yes | no | yes | `conflict` — remote has a same-path blueprint Hassle didn't put there; resolve `--accept-local` (overwrite) or copy HA's semantics into the bundle by hand (no source read; §2.1) |
| yes | yes | yes, hash differs from manifest | `update` |
| yes | yes | yes, substitute-compare mismatch (when enabled) | `conflict` — the remote copy was edited in place; same resolutions as above |
| no | yes | yes | `delete` (ordered §4) |
| no | no | yes | `adopt (unmanageable)` — warning row only: HA cannot serve the source, so adopting requires a human to place the file in `blueprints/<domain>/<path>`; the row's message says exactly that |
| yes | yes | no | `create` (same as row 1 — see the correction below) |
| no | yes | no | `drop` (see the correction below) |

> ⚠️ **CORRECTED 2026-08-09 (`hassle.sync.blueprint_plan.plan_blueprint`,
> pinned by `test_blueprint_plan_table`).** The original six rows above left
> two Local/manifest/Remote combinations undecided; rows 7–8 are the
> implementation's answer. **Local yes, remote no, whatever the manifest
> says** → `create` — row 1 already said this for "no manifest entry", but
> the same call applies when there IS one: the bundle has the file and HA
> does not, so pushing it is the only non-destructive answer. The generic
> (non-blueprint) plan table's `drop` for this shape would delete an
> *authored source file* just because somebody removed the blueprint in HA,
> which I6 forbids. **Local no, remote no, manifest yes** → `drop`, matching
> the generic table's own "both sides gone" row: nothing to push either way,
> and the stale manifest entry should not survive.

> ⚠️ **CORRECTED 2026-08-09 (ha-api-notes §40.6).** Row 4 as written above
> ("substitute-compare mismatch → conflict") is not what ships unconditionally.
> `blueprint/substitute` expands HA's copy against the bundle's copy **as it is
> now** — there is no way to expand the BASE (last-pushed) version, since the
> manifest stores only its hash and §2's "no source read" finding means HA
> will not serve one back either. A mismatch therefore has two indistinguishable
> causes: the remote was edited in place (this row, as written), or the local
> file was edited (fully explained by that edit — no news about the remote).
> Escalating both to `conflict` made *every* ordinary blueprint edit an
> unusable conflict in the golden fixture's push→edit→push cycle, training a
> user to click through conflict prompts — exactly what I6 exists to prevent.
> `plan_blueprint` therefore gates row 4 on `base_hash == local_hash`: an
> edited local file falls through to row 3's `update` instead, the same
> exposure every other kind already carries, no worse. **Residual exposure,
> documented and accepted**: a local edit and a remote edit landing in the
> same window pushes the local edit over the remote one with no conflict
> raised. Closing it needs either a future HA source-read command or the DSL's
> deterministic compiled artifact (§8). Full account: ha-api-notes §40.6.

> ⚠️ **CORRECTED 2026-08-09 (DESIGN §8.2, `hassle.sync.models.PlanEntry`).**
> "`adopt (unmanageable)` — warning row only" above could be read as a new
> outcome distinct from every other kind's `adopt`. It isn't one: the row is
> an ordinary `PlanAction.ADOPT` carrying a new `warning: bool` field (plus a
> `message: str | None`) on `PlanEntry`, not a ninth action — DESIGN §8.2's
> action set stays frozen at eight (`noop`/`update`/`delete`/`refresh`/
> `conflict`/`drop`/`create`/`adopt`). Nothing ever executes this row (apply
> only runs create/update/delete; pull excludes the blueprint kind entirely,
> §5), so the flag exists purely so a renderer can print "warning" instead of
> "adopt" — widening `PlanAction` to say that would have been out of
> proportion to what needed saying.

The substitute-compare check runs per blueprint using the inputs of one of
its own instances in the bundle (any instance covers all required inputs or
validate would have failed, §6); a blueprint with no instances skips the
check (nothing can be affected by drift).

## 4. Apply ordering

The one rule the field deploy taught: **HA validates an instance against the
blueprint at instance-save time** (the 400 class). Therefore, within one
apply:

1. blueprint `create`/`update` rows apply **before** any automation rows;
2. blueprint `delete` rows apply **after** all automation rows (an instance
   of the blueprint must be deleted first, and validate refuses a plan that
   deletes a blueprint while the bundle still declares an instance of it);
3. after a blueprint `update`, if the bundle declares instances of it, the
   backend issues `automation.reload` — HA does not re-expand live
   instances on `blueprint/save` alone. (Marked for empirical confirmation
   during implementation; capture the finding either way.)

> ⚠️ **STATUS 2026-08-09 (ha-api-notes §40.4).** Item 3 is implemented exactly
> as designed above — `hassle.sync.apply._reload_after_blueprint_update`
> issues `automation.reload` after a blueprint `UPDATE` whenever the bundle
> declares instances of it. It is still **unprobed**: the 2026-08-10 session
> captured every other §2 shape but not this one, so "HA does not re-expand
> live instances on `blueprint/save` alone" remains a belief carried as a
> `TODO` in that function, not a verified fact. Either outcome is safe — a
> redundant reload is harmless — so the eventual finding changes at most
> whether the call stays, never anything load-bearing today.

Rollback on a failed transactional apply must respect the same ordering in
reverse.

> ⚠️ **CORRECTED 2026-08-09 (ha-api-notes §40.5).** The line above assumes
> rollback is always possible; it is not, for this kind, and this was **not
> anticipated by this design** — surfaced during implementation and flagged
> to the owner rather than worked around silently (CLAUDE.md's workflow
> rule). `_rollback` restores each touched object from the `list_remote`
> snapshot taken before the write — the full config body, for every other
> kind. For a blueprint that snapshot is **metadata only** (§2.1: HA serves no
> source back), so rolling back an `UPDATE` would need the document HA held
> *before* the save, and rolling back a `DELETE` needs the document outright —
> neither exists anywhere the apply engine can reach: HA won't serve it, and
> the bundle file has already been edited or is already gone. **What shipped
> instead**: `_rollback` reports both cases as purpose-built `ROLLBACK_FAILED`
> outcomes whose message names the file and the real fix — recover it from
> git (the copy of record) and push again — so the loss is loud rather than
> silent (I6). A blueprint `CREATE` still rolls back perfectly (delete it back
> out). The exposure is narrow by construction: §4's own ordering puts
> blueprint deletes last, so nothing applied afterward can strand one — only a
> *second* blueprint delete failing in the same plan reaches the `DELETE`
> case, while the `UPDATE` case is reachable whenever a blueprint update
> shares a plan with a failing automation row. DSL authoring (§8) removes this
> entirely: a DSL-compiled blueprint is reproducible from the bundle's own git
> history, so a "previous version" always exists somewhere Hassle can reach.

## 5. Pull

Blueprints are excluded from pull's writes (no source read, §2.1). Pull's
report lists remote-only blueprints as the `adopt (unmanageable)` warning
(§3) so they are at least visible. A future HA release adding a source-read
command turns that row into a real adopt with no schema change here.

## 6. Validation additions (`hassle validate`, offline)

1. Every `@blueprint_automation` whose `use_blueprint` path matches a
   bundle-local blueprint file is checked against its parsed inputs:
   missing required inputs and unknown input names are findings. (Exactly
   the class HA rejects with an opaque 400 at push time.)
2. An instance referencing a path with **no** bundle-local file is a
   warning (it may legitimately reference a community blueprint that lives
   only in HA — e.g. the jay-kub tap-sequences instances — but the message
   names the file that would make it managed).

> ⚠️ **CORRECTED 2026-08-09 (`hassle_cli.cli._has_errors`).** Introducing this
> rule's `warning` severity exposed that `hassle validate` did not honor
> `Finding.severity` at all — every finding, of every kind, failed the command
> regardless of its stated severity, because until this rule every `Finding`
> in the codebase happened to be `severity="error"` and the distinction was
> never load-bearing. Failing on this rule's warning would break the
> `hassle validate && hassle test` loop (DESIGN §8.4) for a perfectly correct
> bundle that legitimately references a community blueprint, and would teach
> users to stop reading validate's output. `_has_errors` now reads
> `any(f.severity != "warning" for f in findings)`: warnings still print (in
> yellow) and still appear in `--json`, they just no longer fail the command.
> This is a **global** behavior change to `hassle validate`, applying to every
> kind's findings, not something scoped to blueprints.

3. **The empty-optional-entity rule**, from the field 400: an optional
   entity-selector input (`default: ""`) that appears as a literal
   `target.entity_id` / `entity_id` anywhere in the blueprint body is a
   finding — HA validates the *static* expanded config and rejects a
   literal empty id even inside a runtime-guarded branch. The fix the
   finding prescribes: bind the input to a variable and use a templated
   target (see the BrandtCamp blueprint's lights-pause arms for the
   worked example).
4. Expanded-config schema checks beyond that start as exactly this one
   rule; growing toward HA's full automation schema is future work — each
   new rule should be motivated by a real rejection, captured like this
   one.

> ⚠️ **KNOWN LIMITATION 2026-08-09 (the input parser; a code-level finding, not an HA
> probe).** `hassle.blueprints._parse_inputs` reads `blueprint.input` as a
> flat mapping of input name → spec. HA's blueprint schema also allows
> **grouped inputs** — an `input:` entry whose value is itself
> `{name: ..., input: {<nested-name>: <spec>, ...}}`, a `sections` grouping —
> and the parser does not flatten them: a section entry is read as if it were
> itself one input, so its nested `input:` block is never walked and every
> input inside it is invisible to `_required()`. Two consequences, both
> silent: a sectioned blueprint's genuinely-required nested input is never
> flagged as `blueprint-missing-input` when an instance omits it (rule 1 above
> misses it entirely), and an instance that *does* correctly supply one trips
> a false `blueprint-unknown-input` instead — reproducing, from the parser's
> blind side, the exact class of opaque rejection §0 exists to close. **Stated
> accepted non-goal**: flattening `sections` is out of scope for now — no
> real HA rejection has motivated it yet (item 4's own bar for a new rule),
> and neither BrandtCamp's blueprint nor the golden fixture uses sections.
> Revisit when one does.

## 7. Testing

- FakeBackend grows a blueprint store implementing the three WS commands
  with the probed semantics (including `substitute` against its stored
  YAML — the expansion logic is `hassle.blueprints`, shared).
- Golden fixture: a bundle with one blueprint + instances; plan/apply/
  delete ordering pinned.
- Tests-first per R1; every §2 finding gets its ha-api-notes entry with
  the capture.
- Live verification against the owner's HA mirrors the dashboards DB0
  pattern; the BrandtCamp bundle (17 instances, 1 blueprint) is the
  consumer smoke test and first adopter — its scratchpad upload script
  retires the day this lands.

## 8. Blueprints authored in the DSL

The payoffs, in the order the field demanded them: instance validation for
free (the declaration is right there), §6.3 becomes impossible to *write*
(not merely detectable — the compiler emits the templated form for optional
entity inputs), shared Python constants replace the pass-timings-as-inputs
dance the BrandtCamp blueprint does today to keep a single source of truth,
and — per §4's rollback correction — a compiled blueprint is reproducible
from the bundle's own git history, so the "previous version" that apply's
`_rollback` cannot reach for an authored file always exists for a generated
one.

> ⚠️ **SUPERSEDED 2026-08-10 (this section).** The original sketch this
> replaces proposed `@blueprint(domain=..., path=..., inputs={...})` — inputs
> as a dict argument on the decorator. What ships instead is §8.2's
> `bp_input(...)` called in the decorated body, for one reason the sketch had
> not yet met: an input must be usable as a *value* at its use site
> (`bp_input` returns the placeholder the body then passes to a service call),
> and a dict on the decorator gives the body no handle on those placeholders
> without a second lookup step (`inputs["button_up"]`) that no other Hassle
> DSL surface makes you perform. Declaration order — load-bearing for §8.6's
> byte-stability — also falls out of call order for free, where a dict would
> have relied on Python's mapping-order guarantee surviving a refactor.
> Metadata the sketch's dict had no place for (`name=`, `description=`) moves
> onto the decorator, where every other Hassle object kind already carries it.

### 8.1 Authoring surface

```python
@blueprint(
    domain="automation",
    path="local/room-switch-controls.yaml",
    name="Room switch controls",
    description="Tap/hold arms for a room's wall switch.",
)
def room_switch_controls() -> None:
    button = bp_input("button", selector={"entity": {"domain": "sensor"}})
    lights = bp_input("lights", selector={"entity": {"domain": "light"}}, default="")
    ...  # recorder DSL: triggers, choose/if_then, service calls, variables()
```

The body is recorded by **exactly the same recorder machinery as
`@automation`** — no parallel DSL, no second implementation of `choose`. The
decorator is a whole-object registration, the same seam `@blueprint_automation`
uses (`raw_automation.py`'s Registration note): it builds a `BlueprintConfig`
and hands it to `Registry.add_object`, which `compile_bundle` drains into
`CompileResult.objects` under `blueprint:<domain>/<path>`. That key is
the object kind's identity, unchanged (§1), so **every consumer — plan, apply,
ordering, drift — works on a DSL blueprint with no change at all**: the object
it receives is indistinguishable from one read off disk except in provenance.

### 8.2 Inputs

`bp_input(name, *, selector: dict, default=UNSET, description=None)` returns an
`InputRef` placeholder. `UNSET` (not `None`) marks "required", because `None`
is a legitimate YAML default and the object layer already relies on that distinction —
`BlueprintConfig.inputs` keeps a bare `room_key:` entry as `None` precisely so
"declared with no `default:`" stays distinguishable from `{}` (§1's model).

An `InputRef` is valid **wherever the DSL accepts an entity id or a scalar**:
service targets, trigger `entity_id`, condition entities, service `data`
values, and `variables()` values. It compiles to an `!input <name>` node.

`!input` is a YAML *tag*, not a string, so it is emitted through a representer
registered on the emitter's own dumper (§8.6) rather than by string splicing —
splicing would quote it and HA would read the literal text `!input button`.

### 8.3 Refs inside Jinja: bind through `variables()` first

HA's own rule: `!input` is substituted structurally, at blueprint-expansion
time, into YAML *nodes*. It cannot appear inside a template string — the
string is opaque to the substituter. The idiom HA documents is to bind the
input to a variable and reference the variable in the template.

Hassle enforces this at compile time rather than letting it fail as runtime
nonsense. `InputRef` refuses to become text: `__str__`, `__format__` and the
template-helper coercion path raise a compile error naming the fix ("bind
`lights` with `variables(lights=lights)` and use `{{ lights }}`"). This makes
the f-string that would silently interpolate a placeholder's `repr` into a
template — the natural first mistake — a loud, located failure instead.

### 8.4 Trigger ids

No new surface: the existing trigger builders' `id=` option carries through
unchanged. Recording a trigger inside a `@blueprint` body records its `id`
exactly as it does inside `@automation`, and `choose` arms keyed on trigger id
work the same way. This is called out only because it is the one piece of the
DSL authoring story that required nothing.

### 8.5 The structural §6.3 guarantee

§6.3 exists because HA validates the **static** expanded config: a literal
empty `entity_id` is rejected even inside a runtime-guarded branch, which is
the field HTTP-400 that motivated this whole design. Validation can only *detect*
that in a hand-written file. The DSL makes it unwritable:

| Input kind | Use as service target | Use as trigger `entity_id` |
|---|---|---|
| Required entity selector (no default) | literal `!input <name>` | literal `!input <name>` |
| Optional entity selector (`default=""`) | **auto-templated** via its bound variable | **compile error** |

- **Optional → service target.** The emitter binds the input to a
  blueprint-level variable and emits the target as `entity_id: "{{ <name> }}"`.
  A template is opaque to HA's static validation, so the empty case passes
  schema and resolves to "no targets" at runtime — the hand-written fix §6.3
  prescribes, applied automatically and unconditionally. The binding is emitted
  as a top-level `variables:` entry named exactly the input name.
- **Optional → trigger `entity_id`.** There is no templated escape here: HA
  does not template trigger entity ids. So this is a compile error whose
  message says to make the input required (drop the `default`) or to trigger
  on something else — the two real fixes.
- **Required entity inputs** may be used literally anywhere; they can never be
  empty, so §6.3's failure mode cannot arise.

> ⚠️ **CORRECTED 2026-08-10 (`hassle.compiler.blueprint_dsl`, pinned by
> `test_blueprint_dsl_guarantees`).** This section originally said that when the
> author had already bound the ref via `variables()`, the emitter "reuses that
> binding's name rather than creating a second one". That rule turned out not to
> be well-defined, and the reason is a scope difference the design text had
> flattened: in this DSL `variables()` is an *action* (`action_verbs.py` records
> `{"variables": {...}}` into the action list), so an author's binding is
> action-scoped and applies only to the actions after it, whereas the
> auto-binding must be a **top-level** blueprint variable to be in scope for
> every target that might read it. "Reusing" an action-scoped name for a
> top-level binding would silently change where the name is visible. What ships
> instead: the emitter **always** emits the top-level binding under the input's
> own name. If the author also binds the same ref in a `variables()` action, the
> value is identical, so the shadowing rebind is a no-op — which is why the
> simpler rule costs nothing. It is also the more deterministic of the two (§8.6
> rule 4 no longer depends on what the author happened to name a variable).

The result: the emitter has no code path that writes a literal empty entity id,
which is what "unwritable" means here — §6.3's *rule* remains, but for
DSL blueprints it becomes a check that can no longer fire.

### 8.6 Emission and byte-stability

A DSL blueprint compiles to an ordinary managed `BlueprintConfig` whose `source` is
generated YAML and whose `inputs` is the same parsed block the object layer stores,
derived from that generated source (so the two cannot disagree). **No file is
written into `blueprints/`** — the compiled object is the source of truth, and
the object layer's sync pushes it unchanged. This is the point at which its
"byte-preserved, because authored" note (§1, `ir/models.py`) flips meaning for
generated blueprints: byte-stability now comes from the emitter being a
function, not from preserving an author's bytes.

R8 determinism is a gate, so the emitter pins every degree of freedom:

1. **Header comment**, fixed text, naming compiled-from-Python and the
   bundle-relative POSIX source path. **No timestamp, no version, no hostname,
   no absolute path** — the classic determinism traps; a golden fixture would
   catch them, but the rule is stated so nobody adds one on purpose.
2. **`blueprint:` metadata in fixed order**: `name`, `description`, `domain`,
   `input`. Absent optional keys are omitted, never emitted as `null`.
3. **Inputs in declaration order** — `bp_input` call order, not sorted.
   Declaration order is what the HA UI shows the user, so sorting would
   reorder a real user-visible surface; call order also makes a diff of the
   emitted YAML track the diff of the Python.
4. **Auto-bound variables (§8.5) before author-declared ones**, themselves in
   input declaration order; author-declared `variables()` keep call order.
5. **Body sections in canonical HA order**: `variables`, `triggers`,
   `conditions`, `actions`, `mode`, `max`. Within a section, recorded order.
6. **Dumper settings pinned**: `sort_keys=False` (order is ours, above),
   block style throughout (`default_flow_style=False`), an effectively
   infinite line width so long templates never soft-wrap (wrapping is the
   subtlest byte-instability in a YAML emitter — it depends on content length,
   so it changes under edits far from the wrap), `allow_unicode=True`.
7. **Multi-line strings as block scalars** (`|-`), so Jinja bodies stay
   readable and their bytes don't depend on escape-quoting choices.
8. **LF line endings, exactly one trailing newline, no trailing whitespace.**

A golden fixture pins one DSL blueprint's emitted YAML byte-for-byte (§8.9).

### 8.7 Collision with an on-disk blueprint

Defining the same `domain`/`path` as both a DSL blueprint and a
`blueprints/<domain>/<path>` file is a **validate error naming both** — the
Python declaration site (`file:line`, via the decorator's captured span) and
the on-disk file. It is not a silent precedence rule in either direction: both
plausible winners are wrong often enough to be dangerous (silently ignoring
the file discards an edit — I6; silently ignoring the DSL makes the compiler's
output depend on a file's mere existence), and the fix is one deletion the
author can make in a second once told which two things collided.

### 8.8 Simulator

Instance expansion prefers compiled blueprint objects from the same
`CompileResult` over the on-disk lookup. The file lookup resolves a `use_blueprint`
path against the bundle directory via `CompileResult`'s bundle-dir sidecar;
the simulator now checks `CompileResult.objects` for `blueprint:<domain>/<path>` first,
falls back to that file lookup, and — absent both — stays **inert exactly as
today** (an unresolvable instance is not a simulator error; it may legitimately
reference a community blueprint that lives only in HA, §6.2).

### 8.9 Instance validation

The §6 checks (missing required inputs, unknown input names) upgrade to
read DSL declarations wherever a DSL blueprint provides them, and gain one the
declaration makes newly answerable: an **entity-selector input receiving a
non-entity-id value** (`blueprint-input-not-an-entity-id`). An instance passing
`"kitchen"` where an `entity` selector is declared is a finding rather than a
silent misfire.

> ⚠️ **CORRECTED 2026-08-10 (`hassle.registry.blueprint_rules`).** Two claims
> above needed narrowing once implemented. **First**, the new rule is not
> DSL-only. This section said a file-authored blueprint "could not check that — a parsed YAML
> selector is just a mapping", but a hand-written blueprint's `selector: entity:`
> parses into `BlueprintConfig.inputs` exactly as a DSL one does, so the rule
> applies to both and is implemented for both. What the DSL changed is not the
> rule's *feasibility* but its *worth*: with the declaration at a Python line the
> mistake became worth telling the author about. **Second**, unlike §6's other
> rules this one is NOT motivated by a real HA rejection — HA accepts the save
> and then silently never matches the entity. §6.4's bar ("each new rule
> motivated by a real rejection, captured like this one") is therefore bent here,
> deliberately: a silent no-op is worse than a rejection, not better, and it is
> the one failure mode `hassle validate` is uniquely placed to catch. The rule is
> kept deliberately narrow for that reason — only a plain string is judged, and
> only against `<domain>.<object_id>`; lists, device/area ids and templated
> values are all left alone rather than have the rule grow into a
> re-implementation of HA's selector schema.

Note this cannot regress the `sections` limitation boxed in §6: a DSL blueprint
declares its inputs flat by construction, so the parser's blind side is simply
not reachable for them. On-disk blueprints keep their existing behavior exactly.

### 8.10 Out of scope

Round-tripping UI-edited blueprints to DSL. They stay raw-YAML file objects
and promotion is a human act — the same asymmetry the decompiler already
accepts elsewhere.
