# Blueprints as first-class objects — design

Status: **stage 1 approved for implementation** (this document); stage 2 is a
sketch. Everything HA-behavioral here was probed live on 2026-08-10 against
the owner's HA (see §2); those findings should be folded into
`docs/internals/ha-api-notes.md` with their raw captures during
implementation, per house convention.

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

Stage 1 (this design): the blueprint file as a managed object.
Stage 2 (sketch, §8): blueprints authored in the DSL, YAML as a compiled
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
- **IR object**: the raw YAML text (byte-preserved; the file is authored,
  not generated, in stage 1) plus the parsed `blueprint.input` metadata for
  validation. Parsing reuses the loader in `hassle.testing.blueprints`,
  which is **promoted to `hassle.blueprints`** (core) and re-exported from
  its current name for compatibility — the validator (§6) must not import
  from a testing module.

## 2. Empirical API surface (probed 2026-08-10)

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

Rollback on a failed transactional apply must respect the same ordering in
reverse.

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

## 8. Stage 2 sketch (future): blueprints authored in the DSL

A `@blueprint(domain=..., path=..., inputs={...})` decorator whose body is
the recorder DSL; declared inputs yield placeholder objects that compile to
`!input` nodes; the YAML becomes a deterministic compiled artifact (R7
byte-stability applies) and stage 1's object machinery pushes it unchanged.
Payoffs, in the order the field demanded them: instance validation for free
(the declaration is right there), §6.3 becomes impossible to write (the
compiler emits the templated form for optional entity inputs), and shared
Python constants replace the pass-timings-as-inputs dance the BrandtCamp
blueprint does today to keep a single source of truth. Pull-side, UI-edited
blueprints do not round-trip to DSL; they stay stage-1 raw-YAML objects,
and promotion is a human act — the same asymmetry the decompiler already
accepts elsewhere.
