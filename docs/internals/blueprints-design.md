# Blueprints as first-class objects — design

Status: **stage 1 implemented**, on `feat/blueprint-objects` (21 commits,
`ae06bc3..HEAD`; reconciled against the code below on 2026-08-09); stage 2
(§8) remains a sketch. Everything HA-behavioral here was probed live on
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
> raised. Closing it needs either a future HA source-read command or stage 2's
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
> shares a plan with a failing automation row. Stage 2 (§8) removes this
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

> ⚠️ **KNOWN LIMITATION 2026-08-09 (stage 1; a code-level finding, not an HA
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
> non-goal of stage 1**: flattening `sections` is out of scope for now — no
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
