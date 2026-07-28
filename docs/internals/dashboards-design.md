# Dashboards (Lovelace storage-mode) — design

Status: **implemented and behaviorally verified** (DB0 completed 2026-07-27
against a live HA **2026.7.4**). This document is the design and
implementation plan for DESIGN.md §13's "Dashboards" plugin — the last major
piece of the G12 extensibility story. It follows the same conventions as the
rest of `docs/internals/`: everything HA-behavioral is cited from
`docs/internals/ha-api-notes.md` — for this kind, **§39.1–§39.11**, whose raw
captures are in `docs/ha-api-captures/dashboards-db0.json`.

Where DB0 found reality diverging from an earlier hypothesis, the statement is
corrected **in place** with a dated, boxed note naming the finding; §2.1, §2.2
and §3.1 each carry one. Read those before trusting a §2 claim from memory.

Companion documents: [DESIGN.md](../../DESIGN.md) (invariants I1–I6 all apply),
[CONTRIBUTING.md](../../CONTRIBUTING.md) (R1–R8 all apply), and the three
frozen contracts this design extends additively:
[ir-format.md](ir-format.md), [backend-protocol.md](backend-protocol.md),
[dsl-extensions.md](dsl-extensions.md).

---

## 0. Summary

Hassle gains a new object kind, `dashboard`: Lovelace **storage-mode**
dashboards pulled down as Python, edited and tested locally, pushed back up —
while staying fully editable in the HA UI (I1). The DSL follows the shape of
the rest of Hassle:

- **Python is the metaprogramming layer** (DESIGN §5.5): compile-time `for`
  loops and lists generate cards; a card per heat-pump head is a list
  comprehension, not copy-paste.
- **Containers are context managers** (`with view(...)`, `with section()`,
  `with c.vertical_stack()`, `with c.conditional(...)`), exactly like
  `if_then`/`repeat_count`.
- **Leaf cards are typed function calls** (`c.tile(...)`, `c.entities(...)`),
  one builder per built-in HA card type.
- **Anything the DSL doesn't model round-trips as `raw_*`** (I3): third-party
  cards (`custom:bubble-card`), strategy dashboards, unknown future card
  options — never dropped, never guessed.

```python
from hassle import *
from hassle import cards as c
from hassle.cards import cond
from hassle.registry import entities as e

HEAT_PUMP_HEADS = [e.climate.living_room, e.climate.office, e.climate.bedroom]

@dashboard(url_path="climate-control", title="Climate", icon="mdi:thermostat")
def climate():
    with view(title="Overview", path="overview"):          # sections view
        with section():
            c.heading(heading="Heat pumps")
            for head in HEAT_PUMP_HEADS:                   # compile-time Python
                c.thermostat(entity=head)
        with section(column_span=2):
            c.entities(*HEAT_PUMP_HEADS, title="All heads")
            with c.conditional(cond.state(e.input_boolean.guest_mode, "on")):
                c.markdown(content="Guest mode is on — hallway stays warm.")
```

Scope of this v1: **all built-in HA card types** get typed builders;
third-party/custom cards are supported only through the raw escape hatch
(they still round-trip losslessly). Lovelace **YAML mode** stays out of scope
(DESIGN §1 non-goals — YAML-mode dashboards are files Hassle must never write,
per I1). Dashboard **resources** (`lovelace/resources`, the custom-card JS
registry) are out of scope in v1.

---

## 1. Goals and non-goals

### Goals

| # | Requirement | How |
|---|---|---|
| D-G1 | Pull every storage-mode dashboard into the bundle as Python | new kind `dashboard`, same pull/adopt machinery (§8.2/§8.3 of DESIGN) |
| D-G2 | Author dashboards with compile-time Python (loops, lists, functions, macros) | traced `@dashboard` body, same recording model as `@automation` |
| D-G3 | Context managers for nesting; function calls for cards | `view`/`section`/stack/conditional CMs; ~35 typed leaf builders |
| D-G4 | Full built-in card coverage, typed | `hassle.cards` namespace, one builder per built-in type |
| D-G5 | Lossless round-trip for ANY dashboard, incl. third-party cards | raw ladder: `raw_card` → `raw_section` → `raw_view` → `@raw_dashboard` (I3) |
| D-G6 | Everything stays UI-editable | writes only via the Lovelace WS API the UI uses (I1) |
| D-G7 | Entity references validated, tier 0–3 | pyright on `e.` refs; card-tree entity extraction lint |
| D-G8 | Dashboards participate in plan/apply/conflict like every kind | kind-agnostic `compute_plan` needs zero changes |
| D-G9 | Testable in the bundle's pytest suite | assertions over **compiled IR** (I5), via a query helper |

### Non-goals (v1)

- Lovelace **YAML-mode** dashboards (I1: no file writes).
- `lovelace/resources` management (custom card JS).
- Typed builders for third-party cards (raw round-trip only). The builder
  vocabulary is deliberately the *built-in* set; a plugin seam for third-party
  card builder packs is a designed-for follow-on (§10).
- Typed **strategy** dashboards/views (`strategy:` configs round-trip raw).
- Typed sub-vocabularies that are passthrough dicts in v1: card `features`,
  picture-elements `elements`, view `header`, entities-card special rows.
  Each is an additive follow-on that never breaks round-trip.
- Card-level diff/merge. The sync unit is the whole dashboard (§4.4).

---

## 2. The HA substrate (VERIFIED — DB0 ran 2026-07-27 against HA 2026.7.4)

✅ **This section is now captured**, in ha-api-notes.md §39.1–§39.11 with raw
request/response pairs in `docs/ha-api-captures/dashboards-db0.json`. DB0 stood
up a disposable HA **2026.7.4** (the real `stable`) and worked the checklist
below; three statements turned out to be wrong and are corrected in place, with
the finding cited inline. Everything else is confirmed as written.

### 2.1 Storage model — two objects per dashboard

| Store | Contents |
|---|---|
| `.storage/lovelace_dashboards` | the dashboard **registry**: one item per dashboard — `{id, url_path, title, icon, show_in_sidebar, require_admin, mode: "storage"}` |
| `.storage/lovelace` | the **legacy** default dashboard's view config (migrated away on HA 2026.x — see below) |
| `.storage/lovelace.<url_path>` | each other dashboard's view config |

A never-customized default dashboard has no config at all (HA auto-generates a
strategy view; fetching returns a `config_not_found` error) — Hassle treats it
as **absent from `list_remote`** until someone saves it. That much is
confirmed (§39.6).

> ⚠️ **CORRECTED 2026-07-27 (ha-api-notes §39.2).** This section used to say the
> default dashboard has "**no registry item** and `url_path = null` on the
> wire". That is obsolete on HA 2026.x: `_async_migrate_default_config` runs at
> every storage-mode startup and moves a legacy `.storage/lovelace` into a
> **real registry item at `url_path: "lovelace"`** (config moves to
> `.storage/lovelace.lovelace`). `lovelace/config`'s handler is
> `dashboards.get("lovelace") or dashboards[None]`, so once that item exists
> `url_path = null` is an **alias for it**, not a separate store — and
> `_alist_dashboards` was adopting the one dashboard as two Hassle objects
> (`"lovelace"` and `"default"`). The same alias exposes a YAML-mode default
> through the null probe despite the `mode` filter (item 8 below). Both are
> fixed: the default is probed **only when no `url_path: "lovelace"` item
> exists**. On such an instance the default dashboard is simply the ordinary
> storage dashboard `"lovelace"`, and `default=True` no longer addresses it
> (creating through it now fails loudly with that instruction).

### 2.2 WS API (the same commands the UI uses — I1)

| Command | Payload | Purpose |
|---|---|---|
| `lovelace/dashboards/list` | — | registry items |
| `lovelace/dashboards/create` | `url_path, title, icon?, show_in_sidebar?, require_admin?, mode:"storage"` | new dashboard (registry only) |
| `lovelace/dashboards/update` | `dashboard_id, title, icon, show_in_sidebar, require_admin` (PREVENT_EXTRA over exactly these four — `url_path` excluded, DB5 2026-07-27 finding, §4.1) | registry metadata |
| `lovelace/dashboards/delete` | `dashboard_id` | remove dashboard (+ its config) |
| `lovelace/config` | `url_path \| null, force?` | fetch view config |
| `lovelace/config/save` | `url_path \| null, config` | write view config |
| `lovelace/config/delete` | `url_path \| null` | revert to auto-generated |

DB0's checklist, resolved (ha-api-notes §39.1-§39.11, captures in
`docs/ha-api-captures/dashboards-db0.json`):

| # | Item | Outcome |
|---|---|---|
| 1 | `url_path` must contain a hyphen | ✅ confirmed (`invalid_format`, "Url path needs to contain a hyphen") -- **but bypassable**, see the correction below (§39.3) |
| 2 | Config opacity: the store saves the body verbatim | ✅ confirmed **byte-for-byte, key order included** -- `normalize_ha` and `storage_canonical` stay no-ops for this kind, no per-kind canonical entry needed (§39.4) |
| 3 | `dashboards/delete` also removes the config store | ✅ confirmed; a recreate at the same `url_path` is a clean slate, never a resurrection (§39.5) |
| 4 | View `type` materialization | ✅ a view with no `type:` key stays keyless -- §5.2's `type=None` spelling is right (§39.4) |
| 5 | Legacy `tap_action: {action: "call-service", service: ...}` round-trips | ✅ confirmed verbatim -- pinned against real HA, so §3.3's "never rewrite `service:` on dashboard bodies" is now behavioral, not assumed (§39.4) |
| 6 | Badges: modern object vs. legacy bare string | ✅ both round-trip verbatim at the wire level; the gap is in `badge()`, not in HA, so §39.0's `raw_view` escalation stands (§39.4) |
| 7 | `dashboards/list` on a fresh instance | ✅ returns `[]`, not an error (§39.6) |
| 8 | YAML-mode default dashboard (I1 risk) | ⚠️ **the risk was real** -- see the correction below (§39.2) |
| 9 | Registry item with a never-saved config | ✅ confirmed loud: a duplicate create fails with `home_assistant_error` / `url_already_exists` (note: **not** `invalid_format`). No product change needed (§39.6) |
| 10 | Does `icon: null` survive an update round-trip? | ✅ answered: it **removes the key**; HA never stores a null there. `DirectBackend` was already right; `FakeBackend` was not, and is fixed (§39.1) |

Three corrections came out of the run:

> ⚠️ **CORRECTION 1 -- items 8 and §2.1 (ha-api-notes §39.2, BLOCKER, fixed).**
> `_alist_dashboards` filters registry items by `mode != "storage"` (I1), but
> it *also* probed `lovelace/config(url_path=null)` unconditionally. On HA
> 2026.x that probe is an alias for the `url_path: "lovelace"` dashboard
> whenever one exists -- so a migrated default was adopted **twice** (as
> `"lovelace"` and as `"default"`), and a YAML-mode default's
> ui-lovelace.yaml content was adopted despite the mode filter. Fixed by
> skipping the probe whenever a `url_path: "lovelace"` item is present (the
> scan runs before the mode filter, so it covers both cases). Mitigating fact
> captured for the record: HA **refuses** `config/save` against a YAML-mode
> dashboard (`{code: "error", message: "Not supported"}`), so Hassle could
> never actually have written over a YAML file -- the damage was adoption and
> a permanently failing push, not data loss.

> ⚠️ **CORRECTION 2 -- item 1 and §3.1 (ha-api-notes §39.3, fixed).**
> `lovelace/dashboards/create` accepts `allow_single_word: true`
> (`STORAGE_DASHBOARD_CREATE_FIELDS`), which bypasses the hyphen rule. A real
> dashboard at the literal `url_path: "default"` is therefore creatable, so
> §3.1's "the `default` sentinel is collision-free by construction" **does not
> hold**. HA's own default-dashboard migration uses this same flag, so it is
> not a theoretical path. `_alist_dashboards` now raises a clear, actionable
> error instead of letting two dashboards share one object key.

> ⚠️ **CORRECTION 3 -- item 1's charset half (ha-api-notes §39.7, no code
> change).** `url_path` has **no** charset constraint beyond the hyphen:
> `Has-Upper`, `has-space x`, `has-dot.x` and `has-slash/x` are all accepted
> and stored verbatim. `_dashboard_module_name`'s defensive sanitizing (drop
> everything outside `[a-z0-9_]`; hash-fallback for a degenerate result) is
> therefore load-bearing rather than paranoia -- the DB6 reviewer should-fix
> that added it was correct on the merits.

**Resolved fixture limitation (was: "FakeBackend cannot honestly simulate
this").** `FakeBackend.update` stored the local envelope verbatim rather than
modelling HA's registry merge. Now that §39.1 has settled what the merge
actually does, `_dashboard_registry_stored_shape` models it: an explicitly
null `icon` is dropped, exactly as HA stores it. Update convergence is
asserted end-to-end in `test_fake_backend_dashboard.py`, not just at the
payload level.

### 2.3 Built-in card inventory (the D-G4 checklist)

Container cards (context managers in the DSL): `vertical-stack`,
`horizontal-stack`, `grid`, `conditional`, `entity-filter`.

Leaf cards: `alarm-panel`, `area`, `button`, `calendar`, `clock`, `entities`,
`entity`, `gauge`, `glance`, `heading`, `history-graph`, `humidifier`,
`iframe`, `light`, `logbook`, `map`, `markdown`, `media-control`, `picture`,
`picture-elements`, `picture-glance`, `plant-status`, `sensor`, `statistic`,
`statistics-graph`, `thermostat`, `tile`, `todo-list` (plus its legacy alias
`shopping-list`), `weather-forecast`.

Energy family (leaf, mostly option-free): `energy-date-selection`,
`energy-usage-graph`, `energy-solar-graph`, `energy-gas-graph`,
`energy-water-graph`, `energy-distribution`, `energy-sources-table`,
`energy-grid-neutrality-gauge`, `energy-solar-consumed-gauge`,
`energy-carbon-consumed-gauge`, `energy-self-sufficiency-gauge`,
`energy-sankey`.

This inventory was written against HA 2026.7.4's frontend. DB0 did NOT
re-derive the whole ~60-name list from the wire — it verified the three
DSL-shape questions that were flagged as unconfirmed (`cond.not_`,
`energy_sankey`'s `title=`, and view `type` materialization) in ha-api-notes
§39.9, which also lists the three `energy_sankey` options the builder leaves
to `extra=`; the fixture corpus (§9.2) then covers every name. The
vocabulary is a **closed, versioned set** — unlike the purpose-trigger
vocabulary (DESIGN §5.4), it ships in HA frontend releases rather than being
enumerable from the instance, so typed builders are code, and an
unknown-to-us type is never an error: it decompiles to `raw_card` and shows
up in the coverage metric (§6.4), which is exactly the tracked signal that a
new HA release added a card.

---

## 3. Object model and IR

### 3.1 Kind, identity, key

- New kind string: `"dashboard"`, added as `DASHBOARD_KIND` in
  `hassle/ir/keys.py` and folded into `OBJECT_KINDS` (re-exported through
  `ir/__init__.py`, per the frozen-contract additive rule).
- **Identity = `url_path`** for registry-listed dashboards; the identity
  sentinel **`default`** for the default dashboard.
  > ⚠️ **CORRECTED 2026-07-27 (ha-api-notes §39.3).** This used to claim the
  > sentinel is "safe: a real `url_path` must contain a hyphen — §2.2 item 1 —
  > so `default` can never collide". The hyphen rule is real but **bypassable**
  > via `allow_single_word: true`, a public field on
  > `lovelace/dashboards/create`, so a dashboard at the literal `url_path:
  > "default"` IS creatable. The sentinel is therefore collision-free only by
  > convention. `DirectBackend._alist_dashboards` detects the collision and
  > raises with a fix instruction rather than silently merging two dashboards
  > into one object key. See also §2.1's correction: on HA 2026.x the default
  > dashboard usually has a real `url_path: "lovelace"` registry item, and is
  > adopted under **that** identity, not the sentinel. That `url_path` is
  > exempt from the DSL's hyphen rule — HA creates it without one, and after
  > the §2.1 fix it is the migrated default's only representation, so
  > `@dashboard(url_path="lovelace")` has to compile. Hassle can adopt and
  > update it but **never create** it: HA rejects that `url_path` on create
  > unconditionally (ha-api-notes §39.11).
- Object key: `dashboard:<identity>` (e.g. `dashboard:climate-control`,
  `dashboard:default`). Keys stay opaque downstream (ir-format.md's
  first-colon rule holds; `url_path` is colon-free by HA's own slug rules,
  but consumers must not rely on that).

### 3.2 `DashboardConfig` — the two-store envelope

A dashboard is **two HA-side objects** (registry item + config blob) but
**one Hassle object** — one decorator declares both, one plan row diffs both,
one conflict covers both. The IR body is therefore a Hassle-composed
envelope, the one deliberate departure from "the body mirrors one HA store":

```json
{
  "meta":   {"url_path": "climate-control", "title": "Climate",
             "icon": "mdi:thermostat", "show_in_sidebar": true,
             "require_admin": false},
  "config": {"views": [ ... ]}
}
```

- `meta` is the registry item **minus** `id` (HA-assigned, transport-only,
  never in the body — same rule as config-entry `entry_id`) and minus
  `mode` (always `"storage"`; a YAML-mode dashboard is filtered out of
  `list_remote` entirely, it is not ours to manage — I1).
- `meta` is `null` for the default dashboard (it has no registry item).
- `config` is the view config **verbatim** — a native-JSON passthrough
  (`Any`), exactly like `triggers`/`actions` in `AutomationConfig`. The typed
  card layer lives in the compiler/decompiler, not the IR (ir-format.md's
  "structural blocks pass through verbatim" rule).
- `DashboardConfig(IRObject)` gets `extra="allow"` like every model; identity
  is `meta.url_path` if `meta` is present, else `_key_id`, else `"default"`.
- `parse(config, kind="dashboard", key_hint=...)` branch in
  `ir/models.py`'s dispatch chain; `serialize(parse(x)) == x` holds because
  both halves are passthrough.

Rejected alternative: flattening `meta` into the config top level. The
Lovelace config historically allows its own top-level `title` key, so
flattening risks a silent collision between "sidebar title" and "config
title"; the envelope keeps the two stores' keyspaces disjoint by
construction, at the cost of one documented wrapper.

`compiled_hash` is the canonical hash of the envelope, so a UI edit to
*either* the sidebar metadata or the cards shows up as one drifted object —
which is the sync behavior we want (refresh/conflict at dashboard
granularity, §4.4).

### 3.3 Normalization — a required kind guard

`normalize_ha`'s generic branch (`ir/normalize.py`) recursively rewrites
`service:` → `action:` keys. Dashboard card bodies legitimately contain
`service:` keys inside `tap_action`/`hold_action`/`double_tap_action`
payloads (§2.2 item 5). **`normalize_ha` must be an identity function for
`kind == "dashboard"`**, and `FakeBackend`'s normalize-on-write must skip the
kind. This gets its own regression test before implementation (R4 applies
pre-emptively: it's a known bug class, we write the test first).

**DB1 implementation finding (2026-07-27):** the *live* corruption vector
turned out to be `modernize_for_comparison` (`ir/modernize.py`), not
`normalize_ha`. Both of modernize's rewrites walk every nested dict
unconditionally, so an unguarded run rewrote a card's `{"delay":
"00:00:30"}` option to HA's duration-dict form and a nested
`wait_for_trigger`'s `platform:` key — which would have made a faithfully
round-tripped dashboard compare as drifted forever. `normalize_ha`'s generic
branch happened to be identity for envelopes already (it only recurses into
top-level `actions`/`sequence` keys, which an envelope lacks), but the guard
is kept as a kind-level *contract* rather than an artifact of recursion
depth. Both functions are kind-guarded and regression-tested both ways
(`test_ir_dashboard_normalize.py`).

`storage_canonical` is identity for the kind, and **DB0 confirmed it stays
that way**: HA stores a dashboard config byte-verbatim, key order included, so
it materializes no defaults for the tables to absorb (ha-api-notes §39.4).
List order is
semantically meaningful everywhere in a dashboard (views, sections, cards) —
the existing canonical-JSON rules already preserve it.

### 3.4 ir-format.md contract update

Same PR as the IR change (R5): the kind-count update, the `dashboard` key
format, the envelope shape with its `meta`/`config` semantics, identity
derivation, and the normalization exemption. (DB1 finding: ir-format.md's
"11 kinds" enumeration was already stale — the 16 config-entry domains had
landed without updating it. The real count was 27 before dashboards, 28
after; DB1 corrected the enumeration rather than perpetuating the stale
number.)

**Identity-sentinel guard (DB1 review note, assigned to DB2):** at the IR
layer, a `meta` dict *lacking* `url_path` falls through to the `default`
sentinel, which would silently key a malformed dashboard as the default
dashboard. The IR keeps the permissive fallback (parse must accept anything,
I3), but the compile path must reject it loudly: `@raw_dashboard` bodies and
the `@dashboard` decorator both validate that `meta`, when present, carries
`url_path` — `DashboardUrlPathError` (§5.6) covers this case too.

---

## 4. Backend and sync

### 4.1 `Backend` Protocol — zero changes

Same result as the config-entry addendum (backend-protocol.md §3.1): the four
methods suffice. Per-kind mapping inside the two implementations:

| Protocol call | `DirectBackend` (WS, via the generic `ws_command`) |
|---|---|
| `list_remote("dashboard")` | `dashboards/list` → for each item + the default: `lovelace/config` → compose envelopes. `config_not_found` ⇒ omit that dashboard. YAML-mode items (`mode != "storage"`) filtered out. |
| `create` | non-default: `dashboards/create` (from `meta`) then `config/save`; default (`meta: null`): `config/save(url_path=null)` only |
| `update` | when `meta` is not null: `dashboards/update` with the FULL desired state of exactly `{title, icon, show_in_sidebar, require_admin}` (dashboard_id resolved via `dashboards/list` — see below); always `config/save` for `config` — see the 2026-07-27 implementation finding below |
| `delete` | non-default: `dashboards/delete`; default: `config/delete` (reverts to auto-generated — enumerated loudly in the plan like every delete) |

- **`dashboard_id` stays transport-internal.** `DirectBackend` re-resolves it
  from `url_path` via `dashboards/list` (cached per connection). No
  `ManifestEntry` change — unlike config-entry `entry_id` there is a stable
  user-visible correlator (`url_path`), so the manifest doesn't need to carry
  anything. Renaming a dashboard's `url_path` is an identity change and is
  therefore modeled as delete+create, exactly like changing an automation
  `id` (I2 — the tooling never mutates identity in place).
- **Partial-create rollback**: `create` is two writes; if `config/save`
  fails after `dashboards/create` succeeded, `DirectBackend` deletes the
  just-created registry item before surfacing the error, so the apply
  engine's snapshot/rollback model (DESIGN §8.2) keeps holding at the object
  level. (Same single-call-owns-multi-step pattern as the config-entry flow
  driving — the sync engine never sees the intermediate steps.)
- `_CALLER_KEYED_KINDS` (`sync/apply.py`) gains `"dashboard"` (the caller
  chooses `url_path`); `_create_body` needs no injection branch — identity
  always travels inside the envelope (`meta.url_path`, or `meta: null` ⇒
  `default`).
- `FakeBackend`: `_store` picks the kind up automatically from
  `OBJECT_KINDS`; it enforces the DB0-verified behaviors (hyphen rule on
  create, `config_not_found` composition, delete-removes-config, **no**
  normalize-on-write for this kind) so the sync engine is tested against the
  same quirks the real backend has.
- **Kind registration and `DirectBackend` support are inseparable** (DB1
  review finding, 2026-07-27): `DirectBackend.list_remote`'s else-branch
  falls through to the storage-collection generic (`ws_command
  ("<kind>/list")`), so a kind present in `OBJECT_KINDS` without explicit
  DirectBackend branches sends a nonexistent `dashboard/list` command and
  aborts `pull`/`plan`/`push` against live HA. Contained on this feature
  branch (DB5 closes it before anything reaches main); DB5 also makes the
  fallthrough explicit — `_alist_helpers` (and its write-side siblings)
  assert `kind in HELPER_DOMAINS`, the same "new kinds are added
  explicitly" rule `_KIND_ORDER` already follows.

**DB5 implementation finding (2026-07-27, reviewer-blocked, fixed forward on
`feat/dashboards-db5-fixes`):** the "diff internally" update semantics
originally written above were wrong on two counts, caught by review before
merge to `main`:

1. **Payload shape.** `lovelace/dashboards/update`'s real schema is
   PREVENT_EXTRA over exactly `{title, icon, show_in_sidebar,
   require_admin}` — `url_path` is deliberately excluded (a url_path change
   is delete+create, never an in-place rename, I2). The first implementation
   built the payload by copying `meta`'s own keys (minus `id`/`mode`), which
   still includes `url_path` (`meta` always carries it) — every non-default
   dashboard UPDATE would 400 with `invalid_format` against real HA. The fix
   (`DirectBackend._dashboard_registry_payload`) builds the payload from an
   explicit allowlist of the four fields, never from `meta`'s keys.
2. **Convergence.** HA's dashboard registry item is a storage collection
   that MERGES an update (`{**item, **update}`) rather than replacing it
   outright, so a field only clears when explicitly sent. A presence-based
   payload (only sending fields `meta` happens to carry) can therefore never
   converge a locally-deleted field (e.g. a removed `icon`) — the stale
   remote value lingers, `_advance_manifest` records it as the new base
   regardless, and every subsequent push silently re-plans the same
   ineffective update forever. The fix sends the FULL desired state of the
   allowlist on every update: `icon` explicitly `None` when absent from
   `meta`, `show_in_sidebar`/`require_admin` with source-informed defaults
   (`True`/`False`, verified against HA 2026.7.4 -- ha-api-notes §39.1)
   when absent.

Both are unit-tested against a `_FakeClient` that now models the real
PREVENT_EXTRA schema (rejecting `url_path` and any unknown key), so a future
regression of either kind fails the unit suite, not just a live HA push.
`FakeBackend` also gained a fidelity fix in the same pass: the create-time
hyphen exemption is keyed off `meta is None` (the actual default-dashboard
marker) rather than the derived identity string, and `update()` now raises
for an unknown non-default `url_path` (mirroring `DirectBackend`'s
`_aresolve_dashboard_id`), exempting only the true default dashboard.

### 4.2 Apply order

`_KIND_ORDER` gains `"dashboard"` **last** (after `automation`): cards
reference entities produced by helpers/scripts/automations, nothing
references a dashboard. (Explicit tuple entry — the sort-last fallback would
happen to be correct for this kind, but backend-protocol.md's rule stands:
new kinds are added explicitly.)

### 4.3 Plan semantics — unchanged table, two notes

`compute_plan` is kind-agnostic; the DESIGN §8.2 table applies verbatim. Two
kind-specific consequences to document and test:

- **Adoption on first pull after upgrade**: an existing bundle's next
  `hassle pull` adopts every storage-mode dashboard (the §8.2 "nothing is
  ever unmanaged" rule). The release notes say so, and the escape hatch is
  the existing ignore mechanism — `ignore = ["dashboard:*"]` in
  `hassle.toml` opts a household out entirely, per-dashboard globs opt out
  selectively. No new opt-in machinery: dashboards behave like every other
  kind from day one.
- **The default dashboard** is `create`-able (a local `@dashboard(default=True)`
  where remote has none — i.e. never customized) and `delete`-able (reverts
  to auto-generated). Both flow through the normal table; no special rows.

### 4.4 Sync granularity (accepted trade-off)

HA stores no stable per-card identity, so three-way merge below the
dashboard level would be heuristic — exactly the kind of guessing I6
forbids. The sync unit is the **whole dashboard**: a UI edit to one card +
a local edit to another card of the same dashboard is a `conflict`, shown
(like all conflicts) as a 3-way diff of the decompiled DSL — which is
per-line and therefore usually trivially mergeable by the human in the
editor. This mirrors how automations already behave (a UI edit to one
action conflicts with a local edit to another) and is listed in §11 risks.

### 4.5 backend-protocol.md contract update

Same PR as the backend change: a §3.2 "Dashboards addendum" documenting the
mapping table above, the envelope, the `dashboard_id` resolution rule, the
partial-create rollback, and the `_KIND_ORDER`/`_CALLER_KEYED_KINDS`
additions.

---

## 5. The DSL

### 5.1 Namespaces — why cards don't live in `hassle.__all__`

Card type names collide with the frozen surface (`area`, `calendar`,
`button`, `light`, `sensor` are already DSL names; `map` is a Python
builtin). Instead of renaming cards away from their HA names (`map_card`,
`area_card`, … — 35 warts), card builders live in a dedicated namespace
module, the same pattern as `hassle.services`/`hassle.registry` but with
**real typed functions** (the card vocabulary is closed and known, so pyright
gets full signatures — no `__getattr__` dynamism):

```python
from hassle import *                  # dashboard, view, section, badge, raw_* …
from hassle import cards as c         # c.tile(...), with c.vertical_stack(): …
from hassle.cards import cond         # cond.state(...), cond.screen(...)
from hassle.registry import entities as e
```

- `hassle.cards` — one builder per built-in card type, named exactly the
  snake_cased HA type (`c.tile`, `c.entity_filter`, `c.todo_list`,
  `c.energy_usage_graph`, …). Attribute access means HA names never fight
  Python names.
- `hassle.cards.cond` — the Lovelace condition vocabulary (below).
- `hassle.__all__` gains only the **structural** names (additive, F3-clean,
  no collisions): `dashboard`, `raw_dashboard`, `view`, `section`, `badge`,
  `raw_card`, `raw_section`, `raw_view`.
- dsl-extensions.md documents `hassle.cards` as a third dedicated
  non-star entry point (rationale: namespace hygiene, not
  instance-dynamism) and freezes its `__all__` under the same
  additive-only rule.

Implementation layout: builders in `hassle/compiler/dashboards/` (recorder,
structural verbs, card families); `hassle/cards.py` is the thin public
re-export, mirroring how the frozen surface is assembled today. The
package-layering test pins the dependency direction as usual.

### 5.2 Structural constructs

```python
@dashboard(url_path="climate-control", title="Climate", icon="mdi:thermostat",
           show_in_sidebar=True, require_admin=False)
def climate(): ...

@dashboard(default=True)          # THE default dashboard (no registry item)
def home(): ...
```

- `@dashboard` requires **either** `url_path=` **or** `default=True` —
  omitting both is a compile-time error that teaches both options (never a
  silent "you accidentally targeted the default dashboard").
  `default=True` **forbids** the registry-metadata kwargs
  (`title`/`icon`/`show_in_sidebar`/`require_admin`) — the default dashboard
  has no registry item to hold them; the error says where those live
  (HA sidebar settings) and what to do instead.
- `with view(title=, path=, icon=, type="sections", max_columns=, visible=,
  subview=, theme=, background=, header=, extra=)`: one builder for all view
  types. `type=` accepts `"sections"` (the authoring default, materialized
  explicitly into the config), `"masonry"`, `"sidebar"`, `"panel"`, or
  **`None`** — which emits *no* `type` key, the legacy-masonry storage shape
  (§2.2 item 4). The decompiler emits exactly what is stored: absent key →
  `type=None`, present value → that value; byte-stability holds in both
  directions with one builder.
- `with section(column_span=, extra=)`: a `type: grid` section inside a
  sections view. Sections-view discipline is enforced with teaching errors:
  a leaf card recorded directly under a sections view raises
  (`SectionRequiredError` — "wrap it in `with section():`"), a `section()`
  under a masonry/panel/sidebar view raises, and `panel` views require
  exactly one card.
- `badge(entity_or_dict, **options)` records into the enclosing view's
  `badges` list (object-badge form; a plain dict passes through verbatim
  for legacy/unknown badge shapes).
- Container cards: `with c.vertical_stack(title=, extra=)`,
  `c.horizontal_stack(...)`, `c.grid(columns=, square=, extra=)`,
  `c.conditional(*conditions)` (exactly one child card — recording a second
  raises with "nest a stack"), `c.entity_filter(entities=, state_filter=,
  show_empty=, extra=)` (zero or one child: the presentation card).
- Every card builder and structural builder accepts `visibility=[...]`
  (list of `cond.*` conditions and/or verbatim dicts) — the per-card
  visibility conditions the UI writes.

### 5.3 Leaf card builders

One typed function per built-in leaf type. Signature convention, uniform
across the family:

- Known options are typed keyword parameters mirroring the HA option name
  (`c.tile(entity=..., features=..., color=..., vertical=...)`).
  Entity-taking parameters accept `EntityRef | str` (and lists thereof) — so
  `e.`-refs, helper handles, and plain strings all work, as everywhere else.
- `entities`-shaped cards take rows as **positional varargs**
  (`c.entities(e.light.a, {"type": "divider"}, e.light.b, title=...)`) —
  rows are `EntityRef | str | dict` (dict = special row / per-row options,
  passthrough in v1).
- **`extra: dict | None = None`, keyword-only, on every builder**: verbatim
  passthrough merged into the card body. This is the forward-compatibility
  valve — when HA adds a card option Hassle doesn't know yet, the decompiler
  emits the *typed builder call plus `extra={...}`* instead of collapsing the
  whole card to `raw_card`, and an author can use new options the day HA
  ships them. A typo'd kwarg is still a loud `TypeError` (builders have no
  `**kwargs`), preserving tier-0/1 typo-catching. `extra` keys may not
  shadow a declared kwarg (compile error) so there is exactly one spelling
  of every option.
- Passthrough-in-v1 sub-vocabularies (typed follow-ons welcome, additive):
  `features=[...]` (tile/humidifier/etc. card features), `elements=[...]`
  (picture-elements), `header=` (view header), dict rows (entities card).

The full builder inventory matches §2.3 one-for-one; `c.shopping_list` exists
as the legacy alias and decompiles from a stored `shopping-list` card
verbatim (never silently upgraded to `todo-list` — byte-stability wins).

### 5.4 Dashboard conditions — `cond`, deliberately not automation conditions

Lovelace visibility/conditional conditions are a **different schema** from
automation conditions (`entity`/`state`/`state_not` keys vs.
`entity_id`/`condition` shapes; plus UI-only kinds `screen` and `user`).
They get their own small vocabulary:

```python
cond.state(entity, "on")                  # {condition: state, entity, state}
cond.state(entity, not_="on")             # {condition: state, entity, state_not}
cond.numeric(entity, above=25, below=30)  # {condition: numeric_state, ...}
cond.screen("(max-width: 600px)")         # {condition: screen, media_query}
cond.user(user_id, ...)                   # {condition: user, users: [...]}
cond.any(...) / cond.all(...) / cond.not_(...)
```

**DB2 implementation note (2026-07-27) — DB0 CONFIRMED:** the shapes above
are what the builders emit. `state`/`numeric_state`/`screen`/`user` are read
straight off the HA frontend's own condition schema; `cond.any`/`cond.all` emit
`{condition: "or"|"and", conditions: [...]}`. `cond.not_` emits
`{condition: "not", conditions: [...]}`, which was the one shape in this
vocabulary not corroborated by a second source. DB0 pinned it against HA
2026.7.4's shipped frontend bundle (ha-api-notes §39.9): the conditional-card
editor's type list is
`["location","numeric_state","state","screen","time","user","and","not","or"]`
and the `not` editor's own empty value is `{condition: "not", conditions: []}`.
The builder is correct as written; no change was needed.

Cross-vocabulary confusion is trap-caught in both directions with teaching
errors (the `CompileTimeBranchError` tradition): an automation
`ConditionBuilder` passed to `c.conditional`/`visibility=` raises
`DashboardConditionTypeError` naming the `cond.*` equivalent; a `cond.*`
object passed to `only_if`/`if_then` raises the mirror error. A verbatim
dict is accepted anywhere a condition is (unknown future condition kinds
round-trip raw).

### 5.5 The raw ladder (I3)

Granular escape hatches at every level, mirroring
`raw_trigger`/`raw_action`:

```python
raw_card({"type": "custom:bubble-card", ...})     # inside any container
raw_section({...})                                 # inside a sections view
raw_view({...})                                    # inside a @dashboard body
@raw_dashboard(url_path="weird-one")               # decorator over a function
def weird(): return {"meta": {...}, "config": {...}}
```

Design note: these take **dicts, not YAML strings**. The intake requirement
("anything unmodeled can stay raw") is honored, but the currency is the same
as every existing `raw_*` verb: Python dicts are what the IR, canonical
hashing, and golden pairs already speak, a dict is syntax-checked by Python
itself, and one raw currency beats two. (A YAML-string form was considered
and rejected: it would need a parse step anyway to hash and round-trip, and
would be the only YAML anywhere in a bundle.) The decompiler pretty-prints
raw dicts exactly as it does for `raw_automation` today, so the diff
experience is equivalent to YAML for a human reader.

Fallback selection is bottom-up, matching the container-recursion-tolerance
precedent (ha-api-notes §20.4): an unknown **card** type → `raw_card`; a
known container with an unknown child stays a typed container around a
`raw_card`; a section/view whose *own* keys are unmodeled → `raw_section`/
`raw_view`; a config whose top level is unmodeled (e.g. `strategy:`) →
`@raw_dashboard`. Never raw a parent merely because a child rawed (tested per
level).

### 5.6 Error surface (snapshot-tested, R6)

New what/where/fix errors, each with a `hassle_dev.snapshots` test:
`NoDashboardContextError` (card/view/section verb outside a `@dashboard`
body — and the mirror: `service()`/`when()`/action verbs inside one),
`SectionRequiredError`, `SectionOutsideSectionsViewError`,
`PanelViewArityError`, `ConditionalCardArityError`,
`DashboardConditionTypeError` (+ mirror), `DashboardUrlPathError` (missing
hyphen / missing `url_path=`+`default=True` / both given),
`DefaultDashboardMetadataError`, `ExtraShadowsKwargError`. Duplicate
`url_path` reuses `DuplicateObjectError` via the normal registry path.

**DB2 implementation note (2026-07-27)** — three refinements to this list, all
additive, all snapshot-tested:

1. **`DashboardNestingError` is new.** The list above covers a card under a
   `sections` view and a section under the wrong view type, but not three other
   real placement mistakes that must not be silently accepted: a card recorded
   straight into the `@dashboard` body (no view open), a `badge()` that is not
   directly inside a view, and a `view()`/`raw_view()` opened inside another
   container. Folding them into `SectionRequiredError` would have made that
   message lie about what is required, so they get their own message,
   parameterized by (what / where you are / what is required).
2. **The mirror trap reuses `NoRecordingContextError`.** §5.6 groups
   "`service()`/`when()`/action verbs inside a `@dashboard` body" under
   `NoDashboardContextError`, whose name describes the opposite direction. It
   really is "no *recording* context" — the automation recorder genuinely is
   absent — so the existing error gained an `in_dashboard=` flag that swaps in
   dashboard-specific teaching text (put the call on the card's `tap_action`)
   rather than a new class. `NoDashboardContextError` keeps the other
   direction, and sharpens its own message when an `@automation` body is
   active.
3. **`DashboardUrlPathError` has five trigger shapes, not four:** the three
   decorator ones, the §3.4 `meta`-without-`url_path` guard, and a `meta`
   `url_path` that contradicts the decorator's `url_path=` — the same class
   because it is the same question (what is this dashboard's identity?) and
   there must be exactly one answer.
4. **`RawDashboardReturnTypeError` is new** (DB2 review round). A
   `@raw_dashboard` body that returns a non-`dict` — a forgotten `return`, or a
   YAML string — fell through the envelope/config discrimination and became the
   stored config **verbatim**: `{"meta": ..., "config": null}` validates,
   hashes and compiles clean, FakeBackend accepts it, and the next push would
   replace the user's real dashboard with an empty one. That is a silently
   destructive write (I1/I6), so it is rejected at compile time; the decorator's
   `F` TypeVar is additionally bound to `Callable[[], dict[str, Any]]` (the
   `raw_automation` convention) so pyright flags it at edit time too.
5. **`DefaultDashboardMetadataError` branches on the raw case.** A
   `@raw_dashboard(default=True)` whose body returns a non-null `meta` is the
   same violation as `@dashboard(default=True, title=...)`, but the author
   expressed it as a KEY of a returned dict, not as a keyword — so the message
   names `@raw_dashboard(default=True)` and tells them to drop the `"meta"` key,
   rather than pointing at a `meta=` keyword that has no call site.

### 5.7 dsl-extensions.md contract update

Same PR as the surface lands: the eight structural `hassle.__all__`
additions, the `hassle.cards`/`hassle.cards.cond` entry-point sections, the
builder signature conventions (`extra=`, varargs rows, `visibility=`), the
trap table, and the new non-public extension seams (§6.1's recorder).

---

## 6. Compiler and decompiler

### 6.1 Recording — a sibling recorder, not a widened `Recorder`

The automation `Recorder` (triggers/conditions/actions + an action stack) is
the wrong shape for a card tree; widening it would couple every automation
code path to dashboard concerns. Instead `hassle/compiler/dashboards/`
gets its own small recorder, following the established conventions
one-for-one:

- `DashboardRecorder`: the assembled `config` dict under construction plus a
  **container stack** (dashboard → view → section/stack/conditional →
  cards); its own `ContextVar` stack (nested `@dashboard` tracing is
  impossible, but the ContextVar convention buys the same isolation and
  reentrancy the automation recorder has).
- `record_card(body, *, span)` / `push_container(...)` — the non-public
  extension seam card builders drive, mirroring
  `record_action`/`push_actions` (documented in dsl-extensions.md's seam
  list; every builder in `hassle.cards` is implemented on top of it, so
  third-party builder packs get the same seam later).
- Context managers are `@contextlib.contextmanager` generators using the
  established `_CM_DEPTH = 2` span convention (`control_flow.py`'s
  trampoline analysis applies unchanged; `test_span_depth_empirical`-style
  test included).
- Every recorded card/view/section carries a `SourceSpan` sidecar, so
  tier-2 validation findings point at the author's `c.tile(...)` line
  (`CompileResult.span_at` extended to index into dashboard bodies).

Registration plumbing (all existing seams, one branch each):
`@dashboard`/`@raw_dashboard` register a `RegisteredObject` with
`kind="dashboard"` (options allow-list added beside
`_AUTOMATION_OPTIONS`/`_SCRIPT_OPTIONS`); `compile_registered` gains a
`_build_dashboard` branch beside `_build_automation`/`_build_script` that
opens the dashboard recorder instead of `recording(...)`; `compile_bundle`'s
reset list gains the module's state reset. Compilation stays deterministic
and network-free (R8; sandbox unchanged).

### 6.1.1 F5 — the card-builder protocol (frozen)

Written by DB2 when the recorder landed. **This subsection is FREEZE F5**:
everything a DB3 card-family implementer, DB4's decompiler and DB7's validation
build against. Changing it after this point requires updating this document in
the same PR (§12.3's freeze discipline).

**Module layout.** `hassle/compiler/dashboards/` holds the vocabulary;
`hassle/cards.py` is the thin public re-export.

| Module | Owns |
|---|---|
| `recorder.py` | `DashboardRecorder`, its `ContextVar` stack, the record/push seams, the span sidecar |
| `builders.py` | `merge_extra` / `normalize_visibility` / `put` — the shared builder conventions |
| `conditions.py` | the `cond` vocabulary + `normalize_condition` |
| `structure.py` | `view` / `section` / `badge` / `raw_card` / `raw_section` / `raw_view` |
| `decorators.py` | `@dashboard` / `@raw_dashboard` + envelope assembly |
| `card_registry.py` | the card-type table below |
| `errors.py` | the §5.6 error surface |
| `cards/<family>.py` | **DB3 adds these** — one module per batch (`layout`, `visual`, `domain`) |

A DB3 batch adds one module under `cards/` plus one append-only import + one
`__all__` entry in `hassle/cards.py` (its "builder registration point" comment
block) and one `register_card(...)` call. No other file is touched, which is
what keeps the three batches rebase-trivial.

**The `record_card` seam.**

```python
record_card(body: dict[str, Any], *, span: SourceSpan | None,
            what: str = "A card builder") -> RecordedNode
record_badge(body: dict[str, Any], *, span: SourceSpan | None) -> RecordedNode
```

`record_card` places `body` in the innermost open container and enforces §5.2's
placement discipline (a card in the `@dashboard` body → `DashboardNestingError`;
a card directly under a `sections` view → `SectionRequiredError`). It takes
**ownership** of `body` — it is deliberately not copied, because a container
card keeps mutating the same dict after its children are collected; a builder
that receives an author-owned dict copies it first (as `raw_card` does).
`what` is a noun phrase used only in the "no dashboard context" message; a
builder passes its own spelling (`"`c.tile()`"`).

**Leaf-builder pattern** (a plain function, span at `depth=0`):

```python
def tile(entity: EntityRef | str, *, color: Any = None,
         visibility: VisibilityArg | None = None,
         extra: Mapping[str, Any] | None = None) -> None:
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "tile", "entity": str(entity)}
    put(body, "color", color)                      # omits None -- never materialize a default
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.tile", declared=_TILE_DECLARED, span=span)
    record_card(body, span=span, what="`c.tile()`")
```

**Container-card CM pattern** (a `@contextlib.contextmanager` generator, span at
`_CM_DEPTH`):

```python
@contextlib.contextmanager
def vertical_stack(*, title=None, visibility=None, extra=None) -> Generator[None]:
    span = capture_span(depth=_CM_DEPTH)              # 2 -- see recorder.py's docstring
    body: dict[str, Any] = {"type": "vertical-stack"}
    put(body, "title", title)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.vertical_stack", declared=..., span=span)
    with push_container(body, label="a `vertical-stack` card", span=span):
        yield
```

```python
push_container(body, *, label: str, span: SourceSpan | None,
               child_key: str = "cards", child_is_list: bool = True,
               assign: bool = True)
    -> Generator[RecordedNode]
```

places `body` through `record_card` (so it obeys the same discipline a leaf
does), redirects subsequent `record_card` calls into it, and on clean exit fills
`body[child_key]` from the children. `span` is a required keyword:
`push_container` is itself a contextmanager generator, so a span captured inside
it would point at the builder's line, not the author's.

**`child_is_list` describes the SHAPE of the stored child slot**, and both the
assignment and the span-path grammar follow from it:

| | stored shape | `body[child_key]` becomes | span path |
|---|---|---|---|
| `child_is_list=True` (default) | a list (`cards`) | the list of child bodies | `<key>[<index>]` |
| `child_is_list=False` | one dict (`card`) | that child's body; the key stays **absent** with no child | a bare `<key>` |

The single-child case is not cosmetic: a `conditional` card stores its child as
one dict under `card:`, so an indexed `…cards[0].card[0]` path addresses
**nothing** in the stored config and is unresolvable for DB4/DB7. The absent-key
rule is what lets `c.entity_filter` take zero or one presentation card without
materializing a `null` that would break round-tripping. Recording more than one
child into a single-child slot raises `ValueError` from the seam — a builder
owes the author its own arity error (`ConditionalCardArityError`) first, and
silently dropping the extra cards is not an option.

`assign=False` when the builder wants to place the children itself (e.g. after
its own arity check); `child_key`/`child_is_list` still govern the span-path
segment, so pass the real stored shape either way.

**Shared conventions** (`builders.py`, one implementation, no per-builder
copies): `put(body, key, value)` (skip `None` — never materialize a default HA
did not ask for), `merge_extra(body, extra, *, builder, declared, span)`
(verbatim merge + `ExtraShadowsKwargError` against ALL declared kwargs, not just
the passed ones), `normalize_visibility(visibility, *, span)` (one condition or
an iterable; `cond.*` objects and verbatim dicts; automation builders trap).
`normalize_condition(value, *, span)` is the same for `c.conditional(*conds)`.

**Span sidecar.** Every recorded node carries a `SourceSpan`, addressable by
PATH — dot-joined segments relative to the dashboard's `config`, each addressing
exactly what a plain traversal of the STORED config would:

- `<key>[<index>]` for a list slot — `views[0]`, `views[0].badges[1]`,
  `views[0].sections[0].cards[2]`, `views[0].cards[0].cards[1]`;
- a bare `<key>` for a single-child slot — `views[0].sections[0].cards[0].card`
  for the one card a `conditional` stores under `card:` (see `child_is_list`
  above).

Reachable as `CompileResult.node_spans_for(obj)` /
`CompileResult.node_span(obj, path)`.
(DB2 deviation from §6.1's "`CompileResult.span_at` extended": `span_at`'s
per-section positional index cannot address a card nested three containers
deep, so the tree gets its own additive accessor rather than an overloaded one.
`spans_for`/`span_at` are unchanged and simply return nothing for this kind.)

**The card-type table** (`card_registry.py`) — one row per modelled type, the
single source of truth for DB3 (registration), DB4 (emitter selection) and DB7
(entity extraction, explicitly table-driven rather than per-card code, §8):

```python
@dataclass(frozen=True)
class CardSpec:
    type: str                      # the HA `type` string as stored
    builder: str                   # the DSL name, as an author writes it ("c.tile")
    entity_params: tuple[str, ...] = ()    # STORED KEYS holding an entity id (or list)
    declared: frozenset[str] = frozenset() # every STORED KEY the builder writes
    container: Literal["leaf", "cards", "card", "sections"] = "leaf"
    context_manager: bool = False  # is the builder a `with` block?

CARD_REGISTRY: dict[str, CardSpec]      # type string -> spec; append-only
STRUCTURE_REGISTRY: dict[str, CardSpec] # the structural pieces (below)
```

- `container` says how children are stored: `"leaf"` (none), `"cards"` (list
  under `cards`), `"card"` (exactly one under `card`), `"sections"` (a view's
  section list). `context_manager` is stated rather than inferred.
- **`entity_params` and `declared` name STORED CONFIG KEYS, not Python
  parameter names.** The two usually coincide (a builder's kwarg mirrors the HA
  option name), but where they diverge it is the stored key that matters: both
  consumers operate on a compiled card body, never on the DSL call.
- `entity_params` is what DB4 rewrites to `e.<domain>.<object_id>` and what DB7
  extracts for the unknown-entity lint. Freeform strings inside
  `raw_card`/`markdown` content are never in it. Every one of them is by
  definition also in `declared`.
- **`declared` is REQUIRED of every registration.** It is the set a generic
  decompiler emitter subtracts from a stored card body to decide what must go
  into `extra={...}` (§5.3's forward-compatibility valve) — an empty `declared`
  makes the emitter dump the whole card into `extra=`. Include the `type` key
  and any structural child key (`cards`/`card`) the builder writes itself. It is
  defaulted on the dataclass only so a row stays one line to add;
  `tests/test_dashboard_card_registry.py` fails any row that leaves it empty, so
  a DB3 family cannot merge without it. (A follow-up pass backfills any family
  that merged before this rule landed.)
- **A type absent from the table is never an error**: it decompiles to
  `raw_card` and shows up in the coverage metric (§6.4) — the tracked signal
  that a new HA release added a card.

DB2 populates the structural rows. They are keyed `structure:*` and kept OUT of
`CARD_REGISTRY` so a decompiler looking up a stored card's `type` can never
match them:

| Key | type | builder | entity_params | declared | container | CM |
|---|---|---|---|---|---|---|
| `structure:view` | `structure:view` | `view` | — | `type`, `title`, `path`, `icon`, `theme`, `background`, `max_columns`, `subview`, `visible`, `header`, `visibility`, `badges`, `cards`, `sections` | `sections` (or `cards`, decided by the view's own `type`) | yes |
| `structure:badge` | `structure:badge` | `badge` | `entity` | `type`, `entity`, `visibility` | `leaf` | no |
| `structure:section` | `grid` | `section` | — | `type`, `column_span`, `visibility`, `cards` | `cards` | yes |

The view row's `declared` set mirrors `structure._VIEW_DECLARED` exactly — the
same set `extra=` may not shadow, which is by construction the same set an
emitter must not put into `extra=`. It includes the STRUCTURAL keys
`cards`/`sections`/`badges` that `view()` writes itself after its block closes:
letting `extra=` spell those meant `extra={"cards": [...]}` was accepted and
then overwritten, and `extra={"badges": [...]}` survived only while the block
contained no `badge()` call — conditional silent data loss.

The section row deliberately carries the type string `grid`, the SAME one
DB3a's `c.grid(...)` card will use: **position disambiguates**. A `grid` in a
view's `sections` list decompiles to `with section(...):`; a `grid` in a
`cards` list decompiles to `with c.grid(...):`. A consumer walking a `sections`
list looks the node up in `STRUCTURE_REGISTRY`; one walking a `cards` list uses
`CARD_REGISTRY`.

**Two coordination points DB4 must handle** (recorded here, not worked around):
`view()` always materializes its child list (`sections: []` / `cards: []`), and
a `sections` view never emits a sibling `cards` key. A stored view that carries
both, or neither, is not expressible through `view()` and must fall to
`raw_view` (§5.5's ladder already covers it, and DB0 should confirm which shape
the UI actually writes — §2.2 item 4).

### 6.2 Decompiler

- `decompile_object` dispatch gains a `DashboardConfig` branch →
  `_dashboard_source`: emits the `@dashboard(...)` decorator from `meta`
  (`default=True` when `meta` is null), then walks `config` emitting
  `with view(...):` / `with section():` / container CMs / leaf builder
  calls, choosing per §5.5's ladder. Known-type cards with unmodeled keys
  emit `extra={...}` (§5.3) rather than falling to raw.
- Ordering, naming, imports follow the existing rules: function name =
  `slugify(title)` (falling back to `slugify(url_path)`, then
  `dashboard_<n>`), deduped through the shared `_object_function_name`
  pre-pass; the import header adds `from hassle import cards as c` /
  `from hassle.cards import cond` only when used; ruff-formatted; byte-stable
  (R8). Entity-position strings emit as `e.<domain>.<object_id>` via the
  same registry-accessor rule automations use (DESIGN §7.3) — applied only
  to *known* entity-bearing parameters of typed builders, never to freeform
  strings inside `raw_card`/`markdown` content.
- **Splice**: `_DEF_DECORATOR_KINDS` gains `dashboard`/`raw_dashboard` so
  refresh targets resolve by declared identity, not name-fallback (fixing
  the recognized gap rather than inheriting the template/group weakness).
  A dashboard refresh splices the one decorated def like any drifted object.
- **Coverage**: `decompile-coverage` counts `raw_card`/`raw_section`/
  `raw_view`/`raw_dashboard` nodes with per-shape justification strings.
  Dashboards get their own reported percentage; the corpus of *built-in-only*
  dashboards must decompile 100% clean, while corpus entries containing
  `custom:` cards assert the raw fallback exactly (they are the backstop
  proof, not a coverage failure — same philosophy as DESIGN §5.8).

**DB4 implementation note (2026-07-27, superseded below):** on the base DB4
was first built against, none of the card-builder workstreams (DB3) had
merged, so `CARD_REGISTRY` (§6.1.1) was empty and every real dashboard
fixture's actual leaf cards (`tile`, `heading`, `button`, ...) were unmodeled
— 0/12 corpus dashboards decompiled clean, dragging the corpus-wide fraction
from ~95% to ~84% purely because of a dependency this workstream didn't own
yet (item 8 of DB4's brief anticipated exactly this). `hassle_dev.
decompile_coverage` temporarily computed the pass/fail gate over every kind
EXCEPT `"dashboard"` for this period, reporting dashboards' own (then 0%)
fraction separately via `by_kind`/`full_*` JSON fields.

**DB4 interop round (2026-07-27):** with all 47 built-in card builders now
merged (DB3) and the registry-driven emitter extended to handle two shapes
those builders introduced — varargs-rows cards (`entities`/`glance`/
`history_graph`/`statistics_graph`/`calendar`/`logbook`/`map`/
`picture_glance`: the stored `entities:`/`conditions:` list maps onto the
builder's one `VAR_POSITIONAL` parameter, resolved via the parameter's own
name or, when that differs from the stored key, the one `entity_params`
entry that is itself list-valued) and single-dict-child containers
(`conditional`/`entity_filter`, `container="card"`, DB3's
`push_container(..., child_is_list=False)` fix: the child key is absent for
zero children, a bare dict for exactly one) — the temporary exclusion above
is **removed**: `hassle_dev.decompile_coverage`'s gate is once again the
plain corpus-wide fraction, dashboards included, and it holds >= 90%
(verified: 90/98 = 91.8% blended; automation/script/helper alone unchanged
at 95.3%). The `by_kind` breakdown stays (still useful for spotting a
future per-kind regression), but the `full_*`/`gate_excluded_kinds` fields
are gone along with the exclusion they described.

**Remaining, individually-justified exceptions (8/12 corpus dashboards now
decompile 100% clean):** `dashboard:custom-cards` (two genuine `custom:`
cards), `dashboard:auto-generated` (the strategy dashboard, no `views` key
at all), `dashboard:badges-showcase` (a legacy bare-string badge entry,
ha-api-notes.md §39), and `dashboard:entity-filter-demo` — ONE card,
`{"type": "glance"}` with no `entities:` key at all, stored as an
`entity_filter`'s presentation card. This is NOT a gap: `c.glance()`
unconditionally writes `body["entities"] = normalize_rows(...)` even for
zero rows (verified empirically: compiling `c.glance()` produces
`{"type": "glance", "entities": []}`, never the bare dict), so using the
typed builder here would materialize a key the original stored form never
had — raw_card is the only byte-exact choice, the same always-materialized-
key rule that already governs every varargs-rows family. (This is one more
exception than a prior, unverified estimate of "exactly 3" assumed; verified
against the literal fixture and a live compile before writing this note.)

**DB4 implementation note (2026-07-27), badges:** `badge()`'s own docstring
(§5.2) reads as if its "verbatim dict" passthrough branch also covers a
legacy bare-string badge entry — it does not; there is no `badge()` call
shape that appends a bare string to the `badges` list (see ha-api-notes.md
§39 for the full finding). The decompiler resolves this by escalating the
WHOLE enclosing view to `raw_view` when its stored `badges` list contains a
non-dict entry (or is present as an explicit empty list, which `view()`
likewise never produces) — a legitimate use of the existing ladder (`badges`
is an own-structure key of the view, not a nested card), not a new verb.

**DB4 implementation note (2026-07-27), CardSpec.declared forward-compat:**
a parallel review round is adding an optional `declared: frozenset[str]`
field to `CardSpec` (the authoritative known-kwarg set for a card's typed
builder). DB4's generic emitter reads it via
`getattr(spec, "declared", frozenset())` so it works unchanged whether or
not the field exists: absent/empty, every REQUIRED (no-default) builder
parameter is still resolved by name (never through `extra=`, since a call
cannot omit a required argument) and every OPTIONAL leftover key routes
through `extra=` wholesale; populated, `declared` becomes the authoritative
split instead. This also transparently covers the two DB3-review
coordination points about card families that always materialize a
particular list key (`entities` for the entities/glance/history-graph/.../
entity-filter family, `conditions` for `conditional`) and about
`conditional`'s single-dict `card:` child (container="card") — a card whose
required key is absent from the stored body already falls back to
`raw_card` via the same "missing required parameter" check, and a
`container="card"` row already requires its child to be a dict (any other
shape, including a legacy list, degrades to `raw_card` defensively). No
code change was needed for either point; both are exercised by fake
`CardSpec` rows in `test_decompile_dashboards.py` since no real card family
has landed on this base to test against directly.

### 6.3 Round-trip acceptance

The I3 gate extends over the new corpus: for every dashboard fixture `x`,
`serialize(parse(x)) == x` and `compile(decompile(x)) == x` (envelope
equality; no HA-side normalization expected per §2.2 item 2, else modulo the
DB0-captured `storage_canonical` rules). The whole-corpus pull→plan-noop
invariant test (ha-api-notes §23.3) picks the kind up automatically once
fixtures exist.

---

## 7. Placement, CLI, and bundle layout

- **Default placement: one file per dashboard, `dashboards/<module_name>.py`**
  inside a root-level `dashboards/` directory. `<module_name>` is the
  identity made module-safe: hyphens → underscores, a leading digit prefixed
  with `_` (the stub generator's rule), e.g. `dashboard:climate-control` →
  `dashboards/climate_control.py`, `dashboard:default` →
  `dashboards/default.py`. `default_source_path` returns this for the kind.
  The directory is a plain namespace dir (scaffolded on demand by pull,
  **without** `__init__.py` — an `__init__.py` would make it a *category
  package* named "dashboards", which is not the intent; `compile_bundle`
  already recurses into subdirectories, M7.1). Dashboards have no
  category-registry scope — `_SCOPE_FOR_KIND` deliberately has no entry, and
  HA has no `lovelace` category scope to write back to.
- **The per-file default is a default, not a rule.** The compiler imposes no
  file discipline: any number of dashboards may share one file, dashboards
  may mix with other kinds in any file, and placement is user-controlled
  after first write, like every kind. Enforced by a golden pair compiling
  two dashboards from one module.
- **Adopt never clobbers an existing file.** Pull creates a file only for a
  truly never-seen object; an object already defined anywhere in the bundle
  routes to its recorded source (manifest `source`, standard §8.3 behavior —
  refresh splices in place wherever the user keeps it). If a brand-new
  adopted dashboard's default target path already exists on disk (a
  hand-authored file, or two identities collapsing to one module-safe name),
  the adopt lands **in** that file through the splice/append path
  (`SplicingSourceWriter`'s append-under-marker behavior) — never a
  `write_whole_file` onto an existing path. The adopt batcher already groups
  by target file, so N new dashboards yield N files in the common case and
  clean appends in the collision case.
- **DESIGN §13 note**: this honors DESIGN's original `dashboards/`
  directory reservation, refined from "a reserved directory" to "a
  per-dashboard-file default inside it" — the pointer added to DESIGN §13
  says so. (The category-first flat layout of §6 is unaffected: it governs
  category-*scoped* kinds; dashboards have no category scope.)
- Pull/adopt/refresh/drop/conflict need no new engine code (`apply_pull`
  dispatches on `PlanAction` only); the adopt batcher routes all dashboards
  into one `decompile_bundle` call per file as usual. `hassle pull` output
  flags dashboards that decompiled with raw nodes as DSL-coverage gaps,
  same as automations.
- CLI kind lists are `OBJECT_KINDS`-driven and pick the kind up; `hassle
  explain` renders the compiled envelope (YAML view) generically. `hassle
  plan`'s DSL-level 3-way conflict diff works via the decompiler as-is.
- `hassle_dev/corpus.py`'s `_kind_for` learns the `dashboard_*` filename
  prefix **before** the first fixture lands (it hard-crashes on unknown
  prefixes today).

---

## 8. Validation

| Tier | What dashboards add |
|---|---|
| 0 (pyright) | typo'd card kwargs are `TypeError`s at edit time (no `**kwargs` on builders); `e.`-refs check as today |
| 1 (compile) | structure discipline (§5.2/§5.6 errors), duplicate `url_path`, hyphen rule, `extra` shadowing |
| 2 (registry, offline) | **card-tree entity extraction**: typed builders declare their entity-bearing parameters (extraction is table-driven off the builder registry, not per-card ad-hoc code); raw/unknown nodes get the same conservative entity-shaped-string + Jinja scan `raw_action` bodies get today. Unknown entities produce the standard did-you-mean Finding pointing at the card's `file:line` span |
| 3 (template lint) | markdown-card content and any `{{ … }}` string values run the existing Jinja lint |
| 4 (server-side) | **absent by design** — HA has no `validate_config` analogue for Lovelace bodies (§2.2 item 2); the plan/apply path performs no server round-trip validation for this kind, and `hassle validate --live` says so rather than silently passing |

The registry snapshot already contains everything tier 2 needs (entities,
areas for the `area` card, users are *not* in it — `cond.user` ids are
validated only for shape, documented).

**DB7 implementation notes (2026-07-27):**

1. **Two shapes table-driven `entity_params` cannot express, both handled**:
   a card's own `badges` list (currently only `heading` — its badges are
   entity refs, not a flat parameter) is walked the same both-shapes way as a
   view's `badges`, gated on `"badges" in CardSpec.declared` rather than a
   hardcoded type name; the `area` card's `area` key (an HA AREA id, not an
   entity id — `entity_params` deliberately excludes it, DB3c's own note)
   gets its did-you-mean `unknown-area` Finding via a small card-type -> key
   table in `hassle.registry.dashboard_extract`, reusing the same
   `_check_id`/area-list machinery purpose-trigger targets already use — no
   new validation machinery was needed, so no TODO is left here.
2. **Span-path grammar discrepancy, resolved (DB3-fixes, update 2026-07-27).**
   This section's `child_is_list=False` convention (bare `card` path) is now
   correctly reflected in the merged `c.conditional`/`c.entity_filter`
   builders (`cards/layout.py`) — both pass `child_is_list=False` to
   `push_container`, so `CompileResult.node_span` returns spans keyed by the
   bare `...cards[0].card` spelling this section documents, not the indexed
   `...cards[0].card[0]` one. DB7's extraction
   (`hassle.registry.dashboard_extract._resolve_span`) now uses the bare
   spelling as its primary lookup and keeps the indexed spelling only as a
   fallback (for robustness against any future container that does not set
   the flag), falling back further to the nearest ancestor span if neither
   resolves — so no Finding silently loses its `file:line` either way.
3. **`hassle validate --live` did not exist before this change** — DESIGN
   §9's tier table and this section both describe it as already running
   "server-side checks per object kind," but `hassle validate` had no
   `--live` flag at all, and `DirectBackend.validate_config` (which already
   existed) was never called from anywhere. The minimal, honest version
   built here: `--live` runs HA's real `validate_config` against every
   automation (the one kind that command is actually shaped for — plural
   `triggers`/`conditions`/`actions`, ha-api-notes.md §6), and prints this
   section's dashboards-tier-4-absence notice exactly once per run. Scripts
   and helpers get no live check of their own yet (`validate_config` doesn't
   apply to them) — extending tier 4 to those kinds is unscoped future work,
   not silently added here.

---

## 9. Testing

### 9.1 The bundle author's story (D-G9)

Dashboards don't execute, so the simulator is not the vehicle; assertions run
against **compiled IR** (I5's spirit: test the artifact). The existing `sim`
fixture (which already auto-loads the compiled bundle) gains a query
accessor, also available standalone for non-simulator tests:

```python
def test_every_head_gets_a_thermostat(sim):
    dash = sim.dashboard("climate-control")        # DashboardQuery over compiled IR
    tiles = dash.cards(type="thermostat")           # recursive: sections, stacks, …
    assert [t["entity"] for t in tiles] == [str(h) for h in HEAT_PUMP_HEADS]

def test_guest_banner_is_conditional(sim):
    banner = sim.dashboard("climate-control").cards(type="markdown")[0]
    assert banner.parent["type"] == "conditional"
```

`DashboardQuery` is a thin read-only wrapper: `.meta`, `.config`, `.views`,
`.view(path_or_index)`, `.cards(type=, entity=)` (recursive walk through
sections/stacks/conditional/entity-filter), each node exposing the plain
dict plus `.parent`. No assertion DSL beyond that — plain dict asserts keep
tests honest and future-proof.

### 9.2 Hassle's own test contract (the workstream gates in §12 reference these)

- **Fixture corpus** (`fixtures/configs/dashboard_*.json` + PROVENANCE):
  ≥ 10 realistic dashboards — every built-in card type covered at least
  once across the corpus, sections *and* masonry *and* panel views, badges
  (both shapes), visibility conditions of every kind, nested stacks,
  conditional, entity-filter, a `custom:` card, a strategy dashboard, a
  default-dashboard config. `corpus-stats` gains `REQUIRED_CARD_TYPES`
  (the §2.3 inventory) the way it tracks trigger types today.
- **Golden pairs** (`fixtures/dsl/dashboard_*/`): the structural constructs,
  each card family, `extra=` round-trip, the full raw ladder, error cases
  (`expected_error.json`) for every §5.6 message. Picked up automatically by
  `hassle-dev goldens` / `test_dsl_golden_pairs`.
- **Round-trip**: corpus-wide `test_ir_roundtrip_corpus` +
  `test_roundtrip_corpus` extension; decompile-coverage gate per §6.2.
- **Sync**: plan-table rows exercised for the kind (create/update/refresh/
  conflict/drop/adopt, default-dashboard create/delete), apply-order test,
  FakeBackend behavior tests (hyphen rule, config_not_found, delete
  semantics, **no-normalize regression test** from §3.3), partial-create
  rollback test, pull placement (per-dashboard `dashboards/<module_name>.py`
  files, adopt-append into an existing file, multi-dashboard modules),
  splice-refresh test, ignore-glob test, **I6 fuzz**: the lost-edits
  fuzzer's kind pool gains `dashboard`.
- **Error snapshots** for every new message (R6). **pyright strict** over
  the new modules incl. the public builder signatures (R7).
- **Integration** (`tests/integration/`, live HA): DB0's captures replayed
  as assertions — the CRUD cycle, envelope composition, verbatim-storage
  check, UI-edit-then-pull.

---

## 10. Docs and DX

- `docs/DSL.md`: the eight structural names get `NAME_TO_CASES` entries
  (CI's docs gate enforces this the moment they enter `hassle.__all__`);
  the docs generator gains a **card reference** section produced from the
  builder registry + golden pairs — every card builder with its DSL ↔
  compiled-JSON pair, same pattern-matchable format agents and humans
  already rely on.
- `docs/COOKBOOK.md`: at least two recipes with passing tests ("a dashboard
  from a Python list" — the heat-pump case; "conditional guest-mode
  section"), which also satisfies the ≥ 20-recipe gate trivially.
- `AGENTS.md` additions: the `cards as c`/`cond` import convention, "Python
  `for` generates cards at compile time", the conditional-vs-automation
  condition trap and its error, and "third-party cards stay `raw_card`".
- Stubs: nothing to generate — card builders are static typed functions;
  `e.`-completion already covers entity params. `.vscode` untouched.
- Acceptance (M9-style): a fresh agent session, given only a pulled bundle,
  must complete "add a card for each new device to the right section" from
  the docs alone; `hassle-dev acceptance-tasks` gains one dashboard task.

**DB8 implementation note (2026-07-27):** the stubs bullet above ("nothing to
generate") was incomplete, discovered once the acceptance sample bundle
actually gained a dashboard and `packages/hassle-dev/tests/
test_annotation_truth_pyright_gate.py`'s real pyright run over it broke:
`hassle.cards` is indeed fully static/typed source needing no PER-INSTANCE
generation, but `typings/hassle/__init__.pyi` already exists (generated
alongside `services.pyi`/`registry/__init__.pyi` for the unrelated reason
§10's own bullet above states — guarding `hassle.__all__`'s top-level
surface against pyright's namespace/partial-stub-package fallback). Once ANY
stub exists under `typings/hassle/`, pyright treats that whole dotted path as
a COMPLETE stub package, so the real, un-stubbed `hassle.cards` submodule
becomes an unresolvable "unknown import symbol" the moment a bundle does
`from hassle import cards as c` — even though the real module needs no
generated types at all. Fix (additive, same mechanism as the existing
top-level re-export stub): `hassle stubs`/`hassle pull` also write
`typings/hassle/cards.pyi`, re-exporting every `hassle.cards.__all__` name
from its true defining module (`hassle_cli.cli._generate_cards_reexport_stub`,
reusing `hassle.registry.stubs.generate_reexport_stub_lines` — a generic
extraction of `generate_hassle_reexport_stub`'s own logic, since
`hassle.registry` may not import `hassle.cards` itself per the internal
package-layering rule). Nothing else in this section changes: `.vscode`
stays untouched, and no PER-SNAPSHOT generation is needed for cards (the new
stub is a pure function of `hassle.cards.__all__`, exactly like the
top-level one is a pure function of `hassle.__all__`).

---

## 11. Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Lovelace WS shapes differ from §2 hypotheses | High (transport correctness) | DB0 verifies **before** backend code lands (the M0.V pattern); FakeBackend mirrors verified quirks; integration tests replay captures |
| Card vocabulary drifts with HA frontend releases | Medium (coverage, not correctness) | unknown types/options never error: `extra=`/`raw_card` absorb them losslessly; coverage metric surfaces the gap; builder additions are additive and cheap |
| `service:` keys inside `tap_action` corrupted by normalization | High (silent data change) | §3.3 kind guard, regression-tested first |
| Whole-dashboard conflict granularity frustrates users | Medium | DSL-level 3-way diff makes manual merges line-sized; documented; card-level merge explicitly out of scope (I6 over heuristics) |
| Mass adoption on first pull post-upgrade surprises users | Low | pull output lists adoptions loudly (existing behavior); `ignore = ["dashboard:*"]`; release note |
| No server-side validation tier for dashboards | Medium | tiers 0–3 carry more weight (typed builders, entity lint); `--live` states the gap; a broken card degrades to an error card in the UI, never breaks HA itself |
| Two-store create/delete is not atomic | Medium | backend-internal rollback (§4.1) + apply-engine snapshot/rollback; integration-tested |
| Decompiled mega-dashboards produce long functions | Low | one `def` per dashboard mirrors the UI's own mental model; humans reorganize freely afterward (placement is user-controlled) |

---

## 12. Implementation plan — agent swarm

This section is written to be executed by a swarm of Claude agents
coordinated by one orchestrator session, following the project's existing
subagent roles (`.claude/agents/`): **Opus** for contract-freezing and
review work, **Sonnet** (`implementer`) for scoped test-first
implementation, **Haiku** (`fixture-wrangler`) for corpus/mechanical work.
The structure deliberately mirrors docs/history/milestones.md: freeze points
make parallelism safe (R5), and every workstream's "write these tests first"
list is its acceptance contract (R1).

### 12.1 Workstreams

**DB0 — Wire-shape capture** — ✅ **DONE 2026-07-27** (HA 2026.7.4)
Ran against a disposable HA **2026.7.4** — the real `stable`, from
`pip install homeassistant` under Python 3.14 (no Docker needed, and the
first captures in this repo from 2026.7 rather than §0's 2026.2.3). Every
§2.2 command driven; 48 request/response pairs captured into
`docs/ha-api-captures/dashboards-db0.json`; all ten known-risk items
resolved and written up as ha-api-notes **§39.1–§39.11**. Three statements in
§2 were wrong and are corrected in place (see §2.1/§2.2/§3.1's boxed
corrections); one was a **blocker** — the default dashboard was adopted
twice. The §12.1 acceptance loop was then run end-to-end (ha-api-notes
§39.10), against an ordinary dashboard: the migrated-default path cannot be
reached from a test, because §39.11 makes that shape impossible to construct
through the API, so it was verified by hand and its regression lives in the
unit suite.

Still open from this workstream's original scope: harvesting ≥ 10 **real**
dashboard configs into `fixtures/configs/dashboard_*.json` + PROVENANCE. The
current 12 fixtures remain hand-built and marked provisional; corpus
enrichment against a real household is an independent follow-on and does not
gate anything DB0 was verifying.
*Tests first*: integration-marked tests asserting each captured behavior
(they double as the permanent `tests/integration/` suite).

**DB1 — IR + kind registration (Opus)** — *depends: nothing (reconciled
against DB0 before freeze)*
`ir/keys.py` kind + `object_key`; `DashboardConfig` + `parse()` branch;
normalization kind guard (§3.3); `storage_canonical` entries per DB0;
ir-format.md update in the same PR.
*Tests first*: `test_ir_keys` extension, envelope parse/serialize round-trip,
`test_ir_preserves_unknown_fields` for the kind, canonical-hash stability,
the §3.3 `tap_action` regression test.
**→ FREEZE F4**: envelope shape + key format + identity rules. DB2/DB5/DB6
build against F4 independently.

**DB2 — Recorder core + structural DSL (Opus design, then Sonnet)** —
*depends: F4*
`DashboardRecorder`, `record_card`/`push_container` seam, `@dashboard`/
`@raw_dashboard` registration, `view`/`section`/`badge`/raw ladder,
`cond` vocabulary, all §5.6 traps, `compile_bundle` wiring; dsl-extensions.md
update. Opus writes the recorder module and the seam contract (the subtle
span/ContextVar/trap work); Sonnet finishes the structural builders against
it.
*Tests first*: golden pairs for structure-only dashboards (empty view,
sections vs. masonry vs. panel, badges, raw ladder), every error snapshot,
span-depth empirical test, control-flow trap tests.
**→ FREEZE F5**: the card-builder protocol (builder signature conventions,
`record_card` seam, `extra=` semantics, decompiler emitter registration
seam from DB4). F5 is what makes DB3's fan-out embarrassingly parallel.

**DB3 — Card builder families (3 Sonnet implementers in parallel)** —
*depends: F5*
Each batch delivers, for its card set: typed builders + decompiler emitters
+ golden pairs (compile AND decompile proven by the same pair) + card-doc
entries + corpus fixtures exercising the family. Batches are sized to be
independent (no shared files beyond one registration line each, kept
append-only to merge cleanly):
- *DB3a — layout & display*: vertical/horizontal stack, grid, conditional,
  entity-filter, entities, glance, tile, entity, button, heading.
- *DB3b — visual & history*: gauge, history-graph, statistics-graph, sensor,
  statistic, markdown, iframe, picture, picture-glance, picture-elements,
  map, clock, calendar, logbook.
- *DB3c — domain & energy*: alarm-panel, area, light, thermostat,
  humidifier, media-control, plant-status, todo-list (+ shopping-list
  alias), weather-forecast, the 12 energy cards.
*Tests first (per batch)*: golden pair per card incl. an `extra=` case and
an entity-lint case.

**DB4 — Decompiler core + splice (Sonnet, Opus review emphasis)** —
*depends: F5 (starts alongside DB3 with the structural emitters)*
`_dashboard_source`, dispatch branch, the raw-ladder fallback logic
(§5.5's bottom-up rules, the correctness-critical 20%), naming/imports,
splice recognizer entries, coverage integration.
*Tests first*: fallback-ladder table tests (each level raws itself and only
itself), `test_decompile_stable` extension, splice-refresh test, decompile
of every DB0-harvested real config.

**DB5 — Backends (Sonnet)** — *depends: F4 + DB0*
FakeBackend kind support (verified quirks encoded), DirectBackend WS calls +
`dashboard_id` resolution + partial-create rollback, `_KIND_ORDER`,
`_CALLER_KEYED_KINDS`; backend-protocol.md addendum in the same PR.
*Tests first*: FakeBackend behavior suite (§9.2's sync list), backend-
protocol conformance test, integration CRUD test (replaying DB0 captures).

**DB6 — Sync, placement, CLI (Sonnet)** — *depends: F4 (uses DB5's
FakeBackend when it lands; plan-table tests need only the kind + fixtures)*
`default_source_path` → `dashboards/<module_name>.py` (§7's module-safe
naming + scaffolding rules); plan-table rows for the kind; pull
adopt/refresh/drop/conflict paths incl. the adopt batcher and the
adopt-into-existing-file append path; ignore globs; I6 fuzzer kind-pool
extension; `corpus.py` `_kind_for`; DESIGN §13 pointer edit; release-note
draft for the mass-adoption behavior.
*Tests first*: `test_plan_table` extension, pull-placement tests (N new
dashboards → N files; adopt into an existing file appends, never
overwrites; refresh splices wherever the user moved the object;
`dashboards/` scaffolded without `__init__.py`), a
two-dashboards-one-module golden pair, pull→plan-noop over dashboard
fixtures, fuzz run green.

**DB7 — Validation + testing API (Sonnet)** — *depends: F5*
Table-driven entity extraction over the builder registry, raw-node
conservative scan, tier-1 checks, Finding snapshots; `DashboardQuery` +
`sim.dashboard()`; `--live` tier-4-absent messaging.
*Tests first*: extraction unit tests per entity-bearing parameter class,
did-you-mean snapshot, `DashboardQuery` API tests (they double as the
documented examples).

**DB8 — Docs, cookbook, acceptance (Sonnet + Haiku)** — *depends: DB3
complete*
Card-reference generator section, `NAME_TO_CASES` entries, two cookbook
recipes with tests, AGENTS.md additions, acceptance task; `hassle-dev docs
--update` with the diff in the PR (R3).
*Tests first*: docs-gate tests (`test_docs_dsl_reference` extension),
cookbook recipe tests.

**DB9 — Integration & final gate (Opus reviewer)** — *depends: everything*
Full-suite run (unit + integration vs. `stable` and `dev` HA images), all
five CI gates green (goldens, corpus-stats incl. `REQUIRED_CARD_TYPES`,
decompile-coverage incl. the dashboard percentage, docs, pyright/ruff),
whole-corpus round-trip + pull→plan-noop, a real-instance end-to-end:
pull → edit in UI → pull (refresh) → edit locally → push → verify in UI.

### 12.2 Dependency graph and waves

```
wave 1:  DB0 ──────────────┐        DB1 ──► F4
wave 2:  (F4) ──► DB2 ──► F5        (F4+DB0) ──► DB5        (F4) ──► DB6
wave 3:  (F5) ──► DB3a ∥ DB3b ∥ DB3c        (F5) ──► DB4        (F5) ──► DB7
wave 4:  (DB3) ──► DB8 ──────────────► DB9 (final gate)
```

Peak parallelism is wave 3: five Sonnet implementers (DB3a/b/c, DB4, DB7)
plus DB5/DB6 finishing from wave 2 — seven concurrent worktrees. DB0 runs
through waves 1–2 (live-HA work is wall-clock-bound, not agent-bound) and
must complete before DB5 merges; DB1's freeze is deliberately allowed to
front-run DB0's completion, with an explicit orchestrator checkpoint
reconciling F4 against DB0's findings before any F4-dependent branch merges
(if DB0 falsifies an envelope assumption, only DB1 reworks — that is the
point of freezing the envelope first and the transport second).

### 12.3 Orchestration mechanics

- **One branch per workstream** (`feat/dashboards-db<N>-<topic>`), each an
  `implementer` run in an isolated git worktree branched from local `main`
  (the implementer agent definition already mandates both). No agent ever
  commits to another's branch; the orchestrator owns merges to `main`.
- **Merge gate**: every branch goes through the `reviewer` (Opus) agent —
  diff vs. its workstream's test contract + the invariant checklist — before
  the orchestrator merges. Reviewer findings go back to the same implementer
  (fresh context, findings quoted verbatim in the prompt).
- **Contested-file discipline**: the files every workstream wants to touch
  (`ir/keys.py`, `hassle/__init__.py`'s `__all__`, `construct_map.py`,
  `corpus.py`, `_KIND_ORDER`, splice maps) are edited **only** in DB1/DB2/
  DB5/DB6 as designated above, or by the orchestrator in tiny serialized
  integration commits. DB3 batches only add new modules plus one append-only
  registration line each — rebase-trivial by construction.
- **Freeze discipline (R5)**: F4/F5 changes after freeze require updating
  this document in the same PR, exactly like F1–F3. Implementers are told
  the freeze status in their prompt and instructed to *stop and report*
  (not work around) if a frozen surface blocks them — the DB0-vs-F4
  checkpoint above is the sanctioned path for post-freeze corrections.
- **Prompt contract per implementer**: scope (this doc's § reference), the
  tests-first list verbatim, the frozen surfaces it may not change, the
  files it owns vs. must not touch, and the standing CONTRIBUTING gates
  (`pytest` / `ruff` / `pyright` / relevant `hassle-dev` gates green before
  reporting done).
- **Progress ledger**: the orchestrator keeps a checklist (waves × 
  workstreams × gate status) in the PR description of an umbrella tracking
  issue, updated at every merge, so any session (human or agent) can pick
  up mid-flight.

### 12.4 Definition of done

All of: every workstream's test contract green; all previously green tests
still green; the five CI gates green with the new dashboard coverage
included; `compile(decompile(x)) == x` over the full dashboard corpus;
pull→plan-noop over the corpus; I6 fuzz including the kind; the three
contract docs + DESIGN §13 pointer updated; DB9's live end-to-end verified
on `stable` and `dev` HA images; docs acceptance task passing. Then the
feature ships in the next release with the mass-adoption release note.
