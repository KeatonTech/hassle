# Backend internals

Design rationale that's too long to keep inline in the source. See docs/backend.md for the
frozen `Backend` protocol and plan/apply data model; this file is for maintainers of
`hassle.backend`, in particular `DirectBackend`'s real-HA transport quirks.

## Config-entry template/group helpers: wire format

The four template-helper domains and twelve group-helper domains are backed by HA config
entries (the `template`/`group` integrations), not the WS storage-collection commands the
other nine helper domains use. Their create/read/update/delete mechanics are all driven
through the config-entry **flow** REST views, not WebSocket commands — only listing entries
(`config_entries/get`) is a genuine WS command. Reading a list of HA's own integration
source confirms this: `homeassistant/components/config/config_entries.py` registers flow
start/step submission as `ConfigManagerFlowIndexView`/`ConfigManagerFlowResourceView` under
`/api/config/config_entries/flow`, options-flow under
`/api/config/config_entries/options/flow`, and entry removal as
`ConfigManagerEntryResourceView`'s `DELETE /api/config/config_entries/entry/{entry_id}`.

Create is menu -> form -> `create_entry`: POST to start the flow, a menu-selection step to
pick the sub-kind/flavor (`{"next_step_id": <step_id>}`), then a form submission of exactly
the domain's own fields — no bookkeeping keys like a sub-kind tracker or a client-chosen
unique id may be included; HA's schema rejects unrecognized keys outright.

### Identity is derived from `name`, not a settable unique id

A config-entry flow's form schema does not accept a caller-supplied unique id at all.
Identity is instead derived from the declared `name` (slugified), exactly mirroring the
storage helpers' "id is a slug of name" rule (see `TemplateHelperConfig.identity` in
`hassle.ir.models`). On the wire, the entry's `title` (which the flow sets from the
submitted `name`) is what `list_remote` slugifies to re-derive the same identity on
read-back. HA does expose an explicit entry-rename primitive (`config_entries/update`, WS,
`vol.Optional("title")`) — the mechanism the UI's "rename" affordance uses — but this
backend never calls it: since identity is `slugify(name)`, a changed local `name` is a
changed object key, which the plan engine already treats as delete-old + create-new (or an
id-collision conflict) like every other kind. There is no code path where an UPDATE (same
object key, hence same `name`) would ever need to change the title, so that path is
recorded here rather than wired up as untested dead code.

### Reading back a config entry's options

There is no admin API that returns a config entry's options directly. `config_entries/get`
(and `config_entries/get_single`) both serialize `ConfigEntry.as_json_fragment`, whose JSON
body is `entry_id`/`domain`/`title`/`state`/... — there is no `options`/`data` key in that
shape at all. The only place options ever appear on the wire is as **suggested values baked
into an options-flow form's `data_schema`** — the same mechanism the UI's own edit dialog
uses to pre-populate its form (every HA write goes through the APIs the UI uses). Read-back
therefore opens an options flow, harvests each field's
`description.suggested_value` off `data_schema`, and **cancels the flow**
(`DELETE .../options/flow/{flow_id}`) rather than committing it — the same cleanup a user
closing the dialog without saving triggers.

### `name` is never resubmitted through the options flow

Neither the template nor the group options-flow schema includes `name` (`generate_schema`
only adds it for the initial `"config"` flow type, never `"options"`); submitting it 400s
with `"extra keys not allowed @ data['name']"`. `name` is not lost by omitting it from an
update, though: the entry's `title` is preserved server-side because HA's flow handler only
prunes/overwrites keys that appear in the *current* step's schema, and `name` was never in
the options-flow schema to begin with. So an UPDATE strips `name` from the payload before
submitting, and read-back's `options["name"] = str(title)` fallback is load-bearing (not
merely defensive) — it is the only source of `name` on read-back for both template and
group entries.

### The create response's `entry_id` is nested, never a silent fallback

The create-flow response's `entry_id` is not a top-level key: `_prepare_config_flow_result_json`
nests the whole `ConfigEntry.as_json_fragment` under a `"result"` key, and HA's own base
view class asserts `"result"` is never a pre-existing top-level key for any other flow-result
type — confirming `result` is unambiguously where the entry data lives. A naive
`result.get("entry_id", flow_id)` fallback would silently cache the flow_id instead (a real,
truthy string, so nothing would raise), corrupting the entry-id cache used by every later
update/delete. The client therefore raises immediately, from the call site that found
`entry_id` missing, rather than guess — surfacing the problem right away instead of a
confusing `LookupError` much later during category write-back.

### Cross-referencing sub-kind/flavor via the entity registry

A config entry's own JSON never carries which sub-kind it is (e.g. which of the four
template domains, or which of the twelve group flavors) — that lived in `options` prior to
the identity redesign above, and no longer does. `_config_entry_entity_domains` instead
cross-references the entity registry (`config/entity_registry/list`): a config entry that
creates exactly one entity has that entity's registry row's `config_entry_id` link back to
the entry, true of both a template config entry and a group config entry (both create
exactly one entity per entry). This is shared by both the template and group listing code,
since it isn't integration-specific at all — it doesn't filter by domain, so extending it
once and reusing it verbatim was simpler and safer than a near-duplicate method per
integration family. (A group entry's flavor is *also* visible for free as the options-flow's
own `step_id`, but the entity-registry cross-reference is preferred since it's already a
single WS call this class makes regardless.)
