# Home Assistant API notes — M0.V behavioral verification

**Purpose.** DESIGN §4 ("How Home Assistant stores these objects") was source-verified against HA
core in July 2026. MILESTONES M0.V requires it to be re-verified **behaviorally** against a live
instance, with real request/response captures that become the M5 `FakeBackend` fixtures.

This document records that verification: every DESIGN §4 table row, the four named quirks
(helper `{domain}_id` payload keys, `skip_condition` default, media-upload Content-Type gate,
blueprint config shape), plus several findings that **correct or extend DESIGN §4/§5.8/§8.5**.
Raw JSON captures live in [`ha-api-captures/`](ha-api-captures/) for direct fixture consumption.

Corrections are collected in **§10 — flagged loudly**. Read that section.

---

## 0. ⚠️ Environment caveat — verified on HA 2026.2.3, not 2026.7 (read this)

The milestone says to use `ghcr.io/home-assistant/home-assistant:stable`. In this sandbox that
was **not possible**, and the reason is worth recording because it affects how much trust to put
in the captures.

The egress proxy in this environment permits language package registries (PyPI, npm, crates) but
**403-blocks every binary / OS / source distribution channel**. Concretely, every route to HA
2026.7 failed:

| Route to HA 2026.7 (`stable`) | Result |
|---|---|
| `ghcr.io/home-assistant/home-assistant:stable` | ✗ blob CDN `pkg-containers.githubusercontent.com` → **403** |
| Docker Hub `homeassistant/home-assistant:stable` | ✗ blob CDN `production.cloudfront.docker.com` → **403** |
| `pip install homeassistant` (2026.7.1) | ✗ requires **Python ≥ 3.14.2** |
| Python 3.14 via `uv python install` | ✗ GitHub releases → **403**, and only 3.14.0rc2 offered (< 3.14.2) |
| Python 3.14 via apt / deadsnakes | ✗ `ppa.launchpadcontent.net` → **403** |
| CPython 3.14 source (python.org) | ✗ connection blocked |

HA 2026.7 bundles Python 3.14; the toolchain here tops out at the pre-installed **Python 3.13.12**,
whose newest compatible HA is **2026.2.3**. That is what was stood up and verified.

**Why the captures are still usable as M5 fixtures:** every row verified below exercises
long-stable API surface. The single largest finding — plural `triggers/conditions/actions` schema
normalization (§10.1) — landed in **HA 2024.10** and is therefore identical in 2026.2 and 2026.7.
Storage-collection helper commands, the config REST endpoints, `skip_condition`, and the media
gates have been stable for years.

**Action for M6:** M6 integration tests run in CI against the real `stable` **and** `dev` Docker
images (unrestricted registry there). M6 must re-confirm these captures against 2026.7, paying
attention to anything in §10. Do not treat 2026.2.3 as authoritative for a 2026.7-specific detail.

**Runtime used**
- Home Assistant **2026.2.3** (`pip install homeassistant`, Python 3.13.12), config in a temp dir
  with the standard `automation: !include automations.yaml` / `script: !include scripts.yaml`
  wiring (required — see §1.1), plus the nine helper domains, `media_source`, `person`,
  `config`, `api`, `websocket_api`.
- Auth: one long-lived access token minted via the onboarding API (§1.2).
- Base URL `http://localhost:8123`, WS `ws://localhost:8123/api/websocket`.

---

## 1. Standing up HA and minting a token

### 1.1 Config wiring gotcha (not an HA API finding, but bites the harness)

The config REST API (`POST /api/config/automation/config/{id}`) writes to `automations.yaml`
regardless of `configuration.yaml`, but the automations only **load** if `configuration.yaml`
contains the standard include:

```yaml
automation: !include automations.yaml
script: !include scripts.yaml
```

With a bare `automation:` key (no include), `POST` returns `{"result":"ok"}` and writes the file,
but the entity never appears and reloads load nothing. HA's default config ships the includes; a
real bundle target always has them. Flagged so M6's test harness configures HA correctly.

### 1.2 Onboarding → long-lived token (real captures)

```http
GET /api/onboarding
→ 200 [ {"step":"user","done":false}, {"step":"core_config","done":false},
        {"step":"analytics","done":false}, {"step":"integration","done":false} ]

POST /api/onboarding/users
     {"client_id":"http://localhost:8123/","name":"Hassle Owner",
      "username":"hassle","password":"…","language":"en"}
→ 200 {"auth_code":"ae3d73a3f42a4890b3b1e989c8e8de7d"}

POST /auth/token         (application/x-www-form-urlencoded)
     grant_type=authorization_code & code=<auth_code> & client_id=http://localhost:8123/
→ 200 {"access_token":"<JWT>","token_type":"Bearer","expires_in":1800,
       "refresh_token":"<opaque>"}
```

Then, over the WebSocket (authenticated with the short-lived `access_token`), mint the
long-lived token:

```jsonc
// server → { "type":"auth_required", "ha_version":"2026.2.3" }
// client → { "type":"auth", "access_token":"<JWT>" }
// server → { "type":"auth_ok", "ha_version":"2026.2.3" }
→ { "id":1, "type":"auth/long_lived_access_token",
    "client_name":"hassle-m0v", "lifespan":3650 }
← { "id":1, "type":"result", "success":true, "result":"<183-char long-lived token>" }
```

**Token validity has no introspection endpoint** (DESIGN §4 confirmed): validity is proven by
making any call.

```http
GET /api/config   Authorization: Bearer <good>  → 200 {"version":"2026.2.3","state":"RUNNING",…}
GET /api/config   Authorization: Bearer <bad>    → 401
GET /api/config   (no header)                     → 401
```

`hassle login` should validate exactly this way (`GET /api/config`, 401 ⇒ invalid).

---

## 2. Automations (config REST) — DESIGN §4 row 1 ✅ (with a correction)

| Operation | Verified call |
|---|---|
| Enumerate | `GET /api/states` → filter `entity_id` domain `automation`, read `attributes.id` |
| Fetch | `GET /api/config/automation/config/{id}` |
| Create/Update | `POST /api/config/automation/config/{id}` → `{"result":"ok"}` (**auto-reloads**) |
| Delete | `DELETE /api/config/automation/config/{id}` → `{"result":"ok"}` (**auto-reloads**) |

**Auto-reload confirmed.** After `POST`, with **no** explicit `automation.reload`, the entity
appears within ~300 ms; after `DELETE` it disappears within ~1 s.

```jsonc
// after POST hassle_auto_demo, GET /api/states/automation.hassle_demo_automation
{ "entity_id":"automation.hassle_demo_automation", "state":"on",
  "attributes": { "id":"hassle_auto_demo", "mode":"single", "current":0,
                  "last_triggered":null, "friendly_name":"Hassle Demo Automation" } }
```

**⚠️ Correction (see §10.1 + §10.5): the automation entity_id is `slug(alias)`, not `slug(id)`.**
We `POST`ed id `hassle_auto_demo` with alias `"Hassle Demo Automation"`; the entity is
`automation.hassle_demo_automation`. The config `id` surfaces only as `attributes.id` and as the
registry `unique_id`. To trigger/target an automation by id, resolve the entity_id by matching
`attributes.id`.

### id ↔ unique_id (DESIGN §4 / invariant I2) ✅

```jsonc
// WS config/entity_registry/list → the automation's entry
{ "entity_id":"automation.hassle_demo_automation",
  "unique_id":"hassle_auto_demo",          // == the config id  ← I2 anchor
  "id":"f13e702886d3e49fc75b0d9bd207105d", // registry-row id (unrelated)
  "platform":"automation", "config_entry_id":null,
  "original_name":"Hassle Demo Automation", "labels":[], "categories":{} }
```

Confirmed: `unique_id == config id`. Never changing the `id` (I2) is what preserves entity_id,
areas, and labels.

---

## 3. Scripts (config REST) — DESIGN §4 row 2 ✅

Same pattern, keyed by **object_id** (derived from `entity_id` `script.<object_id>`):

```http
POST   /api/config/script/config/{object_id}   → {"result":"ok"}
GET    /api/config/script/config/{object_id}
DELETE /api/config/script/config/{object_id}    → {"result":"ok"}
```

Read-back is subject to the same key normalization as automations (§10.1): a sent `service:`
becomes `action:`; `sequence:` stays `sequence:`.

---

## 4. Storage-collection helpers (WebSocket) — DESIGN §4 row 3 ✅ + quirk #1 ✅

All nine domains verified with a full **create → list → update → delete** cycle:
`input_boolean, input_number, input_select, input_text, input_datetime, input_button, counter,
timer, schedule`.

**Quirk #1 — `{domain}_id` payload key on update *and* delete — CONFIRMED for all nine.** The
create response returns the object under `result.id`; update/delete key that id as `{domain}_id`:

| Domain | update/delete key |
|---|---|
| input_boolean | `input_boolean_id` |
| input_number | `input_number_id` |
| input_select | `input_select_id` |
| input_text | `input_text_id` |
| input_datetime | `input_datetime_id` |
| input_button | `input_button_id` |
| counter | `counter_id` |
| timer | `timer_id` |
| schedule | `schedule_id` |

Real capture (`input_number`):

```jsonc
→ { "id":7, "type":"input_number/create",
    "name":"H num", "min":0, "max":100, "step":1, "mode":"slider" }
← { "id":7, "type":"result", "success":true,
    "result":{ "id":"h_num", "name":"H num", "min":0.0,"max":100.0,"step":1.0,"mode":"slider" } }
                    // ^ result.id is the object_id, slugified from name

→ { "id":9, "type":"input_number/update", "input_number_id":"h_num",   // ← {domain}_id
    "name":"H num 2", "min":0, "max":200, "step":2, "mode":"box" }
← { "id":9, "type":"result", "success":true, "result":{ … updated … } }

→ { "id":10, "type":"input_number/delete", "input_number_id":"h_num" }  // ← {domain}_id
← { "id":10, "type":"result", "success":true, "result":null }
```

Also: `{domain}/list` returns the raw stored items (no `editable` field on the collection item),
but the **entity state** exposes `attributes.editable == true` for storage helpers:

```http
GET /api/states/input_boolean.hassle_flag
→ { "state":"off", "attributes": { "editable":true, "friendly_name":"Hassle Flag", … } }
```

DESIGN §4's "storage items are `editable: true`; YAML-defined helpers coexist as `editable:false`"
is confirmed (the flag lives on the entity state, not the collection list item).

`{domain}/subscribe` was not exercised (not needed by the sync engine; `list` is sufficient).

---

## 5. Registries + services (WebSocket) — DESIGN §4 rows 4–5 ✅

All four registry lists return arrays and are read-only for Hassle:

| Command | Shape |
|---|---|
| `config/entity_registry/list` | `[ {entity_id, unique_id, platform, area_id, device_id, labels, categories, …} ]` |
| `config/device_registry/list` | `[ {id, name, manufacturer, model, area_id, identifiers, …} ]` |
| `config/area_registry/list` | `[ {area_id, name, icon, floor_id, labels, aliases, …} ]` |
| `config/label_registry/list` | `[ {label_id, name, color, icon, description} ]` |

Real area entry (onboarding seeds Living Room / Kitchen / Bedroom):

```jsonc
{ "area_id":"living_room", "name":"Living Room", "icon":"mdi:sofa",
  "floor_id":null, "labels":[], "aliases":[], "picture":null,
  "temperature_entity_id":null, "humidity_entity_id":null,
  "created_at":1783119627.148, "modified_at":1783119627.148 }
```

`get_services` → `{ domain: { service: {name?, description?, fields, target?} } }`:

```jsonc
// input_boolean
{ "turn_on": { "fields":{}, "target":{ "entity":[ {"domain":["input_boolean"]} ] } },
  "turn_off": { … }, "toggle": { … }, "reload": { "fields":{} } }
```

The `fields` / `target` schemas are what M3 uses for stub generation and service-param validation.

---

## 6. Validation (WebSocket + REST) — DESIGN §4 row 6 ✅ (with a correction)

### `validate_config` — **⚠️ requires PLURAL block keys** (correction §10.1)

DESIGN §4 says "`validate_config` (trigger/condition/action blocks)". **The command actually
requires `triggers` / `conditions` / `actions` (plural).** Singular keys are rejected:

```jsonc
// SINGULAR outer keys → rejected
→ { "type":"validate_config",
    "trigger":[…], "condition":[…], "action":[…] }
← { "success":false, "error":{ "code":"invalid_format",
      "message":"extra keys not allowed @ data['action']. …
                 extra keys not allowed @ data['condition']. …
                 extra keys not allowed @ data['trigger']. …" } }

// PLURAL outer keys → validated
→ { "type":"validate_config",
    "triggers":[{"trigger":"state","entity_id":"input_boolean.hassle_flag"}],
    "conditions":[{"condition":"state","entity_id":"input_boolean.hassle_flag","state":"on"}],
    "actions":[{"action":"input_boolean.toggle","target":{"entity_id":"input_boolean.hassle_flag"}}] }
← { "triggers":{"valid":true,"error":null},
    "conditions":{"valid":true,"error":null},
    "actions":{"valid":true,"error":null} }
```

Note the asymmetry: **legacy `platform:` / `service:` discriminators *inside* a block are still
accepted** — only the outer block key must be plural. A plural-outer / legacy-inner mix validates
clean.

### `check_config` (REST)

```http
POST /api/config/core/check_config   {}
→ 200 { "result":"valid", "errors":null, "warnings":null }
```

---

## 7. Traces (WebSocket) — DESIGN §4 row 7 ✅

```jsonc
→ { "type":"trace/list", "domain":"automation", "item_id":"hassle_skipcond" }
← [ { "run_id":"79957469bca39307dad082e71e45dbd1", "state":"stopped",
      "script_execution":"finished", "last_step":"action/0", "timestamp":{…} },
    { "run_id":"c94890ae5aecd97482bdbd8028ff0ef3", "state":"stopped",
      "script_execution":"failed_conditions", "last_step":"condition/0/entity_id/0" } ]

→ { "type":"trace/get", "domain":"automation",
    "item_id":"hassle_skipcond", "run_id":"<run_id>" }   // all three required
← { "domain":"automation", "item_id":"hassle_skipcond", "run_id":"…",
    "state":"stopped", "script_execution":"failed_conditions",
    "last_step":"condition/0/entity_id/0",
    "trace": { "trigger":[…], "condition/0":[…], "condition/0/entity_id/0":[…] },
    "config": { "id","alias","triggers","conditions","actions","mode" },   // plural (§10.1)
    "context": { "id":"01KWN3XE5B…", … }, "trigger":{…}, "blueprint_inputs":null }
```

Confirmed: `trace/get` requires **domain + item_id + run_id**; admin-only; `trace` is keyed by
step path (`trigger`, `condition/0`, `action/0`, …) — this is what maps a live run back to DSL
source lines (DESIGN §10.4). The trace's embedded `config` uses the plural schema.

---

## 8. Templates — DESIGN §4 row 8 ✅

```http
POST /api/template   {"template":"{{ states('input_boolean.hassle_flag') }} / {{ 1 + 2 }}"}
→ 200  "off / 3"          (Content-Type: text/plain; charset=utf-8)
```

WS `render_template` is a **subscription** (result ack, then one or more `event`s):

```jsonc
→ { "id":N, "type":"render_template",
    "template":"{{ 1 + 2 }} {{ states('input_boolean.hassle_flag') }}", "report_errors":true }
← { "id":N, "type":"result", "success":true, "result":null }         // ack
← { "id":N, "type":"event", "event":{
      "result":"3 off",
      "listeners":{ "all":false, "entities":["input_boolean.hassle_flag"],
                    "domains":[], "time":false } } }
```

`strict` and `report_errors` flags behave as DESIGN §4 states. `listeners` (which entities/domains
the template depends on) is a bonus useful for tier-3 template lint.

---

## 9. Media source (mirror, §8.5) — DESIGN §4 row 9 + quirk #3 ✅ (and a big correction)

Flow verified: `browse_media` → upload → `resolve_media` → authenticated `GET` → `remove`.

```jsonc
→ { "type":"media_source/browse_media" }
← { "result":{ "media_content_id":"media-source://",
      "children":[ {"title":"Image Upload","media_content_id":"media-source://image_upload"},
                   {"title":"My media","media_content_id":"media-source://media_source"} ] } }

→ { "type":"media_source/browse_media", "media_content_id":"media-source://media_source" }
← { "result":{ "title":"media", "media_content_id":"media-source://media_source/local/.",
               "children":[…] } }
```

### Quirk #3 — upload Content-Type gate — CONFIRMED exactly

`POST /api/media_source/local_source/upload` (multipart: `media_content_id` + `file`). The gate is
on the **client-supplied multipart part `Content-Type`** — not bytes, not extension. Identical zip
bytes, three Content-Types:

| multipart `Content-Type` | Result |
|---|---|
| `application/zip` | **400 Bad Request** |
| `image/png` | **200** `{"media_content_id":"media-source://media_source/local/./bundle.zip"}` |
| `audio/mpeg` | **200** |

On-disk bytes after upload are **byte-identical** to the source (sha256 match). Upload is faithful.

### ⚠️ NEW: there is a SECOND, download-side gate (correction §10.3)

DESIGN §4 documents only the upload gate. **The authenticated `GET /media/{source}/{path}` view
has its own gate**, and it is by **file extension**: `mimetypes.guess_type(path)` must resolve to
`image/*`, `video/*`, or `audio/*`, else **404**
(`homeassistant/components/media_source/local_source.py::LocalMediaView._validate_media_path`).

```http
# uploaded as bundle.zip (via image/png Content-Type spoof) …
GET /media/local/hassle/bundle.zip   Authorization: Bearer <token>  → 404   (.zip → application/zip)
GET /media/local/hassle/bundle.zip?authSig=<signed>                  → 404

# SAME bytes uploaded as bundle.mp3 …
GET /media/local/hassle/bundle.mp3   Authorization: Bearer <token>  → 200, bytes identical ✅
GET /media/local/hassle/bundle.mp3?authSig=<signed>                 → 200, bytes identical ✅
```

**Consequence for §8.5:** a mirror that stores `bundle.zip` (as the design text shows) will
**upload fine but be un-downloadable** through the media view. The mirror must store the ZIP under
a **media file extension** (e.g. `bundle.mp3` / `bundle.png`) so that *both* gates pass. The bytes
are unchanged; only the name matters. `resolve_media` returns `mime_type` from the extension too
(`.mp3` → `audio/mpeg`), so a spoofed extension is internally consistent.

Authenticated `GET` accepts **both** a Bearer header **and** the signed `authSig` query param
(DESIGN §4 said "authenticated GET" — both mechanisms work).

`resolve_media` and `remove`:

```jsonc
→ { "type":"media_source/resolve_media",
    "media_content_id":"media-source://media_source/local/hassle/bundle.mp3" }
← { "result":{ "url":"/media/local/hassle/bundle.mp3?authSig=<JWT>", "mime_type":"audio/mpeg" } }

→ { "type":"media_source/local_source/remove",
    "media_content_id":"media-source://media_source/local/hassle/bundle.mp3" }
← { "result":null, "success":true }
```

### ⚠️ Minor: uploading to the media *root* (`local/.`) yields a broken signed URL (correction §10.4)

Uploading with target `media-source://media_source/local/.` (the browse root) produces a signed
URL whose JWT `path` contains a literal `/./` (`/media/local/./bundle.zip`) while the returned URL
has it collapsed (`/media/local/bundle.zip`). The two never match: the collapsed path → **401**
(signature mismatch), the `/./` path → **404** (file lookup). Uploading to a **subfolder**
(`media-source://media_source/local/hassle`, which DESIGN §8.5 already specifies) avoids it — the
signed path is clean. The subfolder must already exist on disk (the upload API does not `mkdir`).

---

## 10. Corrections / additions to DESIGN §4 (and §5.8, §8.5) — flagged loudly

> These are behavioral facts that differ from the design text. M1/M2/M5/M6 owners must read them.

### 10.1 Automation/script schema is **normalized to the plural, `2024.10+` form** on storage
The single most important finding for the round-trip invariant (I3).

- **What HA does:** `POST /api/config/automation/config/{id}` accepts *either* the legacy singular
  keys (`trigger`/`condition`/`action`, `service:`) *or* the new plural keys
  (`triggers`/`conditions`/`actions`, `trigger:`/`action:`). It **stores and returns the plural
  form**, converting `service:` → `action:`. Scripts convert `service:` → `action:` (sequence
  keeps its name).
- **Evidence:** we `POST`ed singular `trigger/condition/action`+`service`;
  `GET /api/config/automation/config/{id}` returned `triggers/conditions/actions`+`action`.
  `POST`ing the plural form round-trips verbatim (read-back keys identical).
- **`validate_config` requires the plural outer keys** and rejects singular (§6).
- **Impact:**
  - **IR / compiler (M1, §7.1):** the IR's canonical/serialized form that Hassle sends and hashes
    should be the **plural** form, because that is what HA persists and returns. If the compiler
    emitted singular keys, `remote (plural) != local (singular)` and every object would look
    changed. Compile to plural; treat singular as input-only legacy.
  - **Decompiler / round-trip (M2, I3):** `compile(decompile(remote))` must reproduce the plural
    remote JSON. Canonical JSON hashing (§8) must be computed on the plural form on both sides.
  - This normalization has existed since **HA 2024.10**, so it is the same on 2026.2 and 2026.7.

### 10.2 Automation `entity_id` is `slug(alias)`, not `slug(id)`
`id` is identity; the **entity_id** is derived from the `alias` (or, absent an alias, from the id).
The id appears only as `attributes.id` (state) and `unique_id` (registry). **Enumerate/trigger by
matching `attributes.id`**, never by assuming `automation.<id>` (DESIGN §4's "read `attributes.id`"
for enumeration is right; just don't construct the entity_id from the id).

### 10.3 The media view has a **download-side extension gate** in addition to the upload gate
DESIGN §4 lists only the upload Content-Type gate. `GET /media/{source}/{path}` also 404s unless
the file's **extension** maps to `image/`, `video/`, or `audio/`. **The §8.5 mirror must store the
ZIP under a media extension** (e.g. `hassle/bundle.mp3`) so upload *and* download both pass. This
tightens §8.5's fragility note: the mirror depends on **two** incidental gates, not one.
(Aside: the view's `is_file()` existence check is a latent no-op — the executor job is never
awaited — so the extension MIME check is effectively the only guard; don't rely on the view to
report "missing file" vs "wrong type".)

### 10.4 Uploading to the media root (`local/.`) breaks the signed URL
Use a subfolder (`media-source://media_source/local/hassle`) — which §8.5 already does. Documented
so the mirror never targets the bare root.

### 10.5 Blueprint config shape — quirk #4 — key is `use_blueprint` with **`input` (singular)**

```jsonc
// POST /api/config/automation/config/{id} … read-back is byte-stable:
{ "id":"hassle_bp_demo", "alias":"Hall Motion (blueprint)",
  "use_blueprint": {
    "path":"hassle/motion_light.yaml",        // relative to blueprints/automation/, INCLUDES author dir
    "input": {                                // ← SINGULAR "input", a name→value map
      "motion_entity":"binary_sensor.hall_motion",
      "light_target":"light.hallway",
      "no_motion_wait":90 } } }
```

- A blueprint automation stores **only** `use_blueprint` — no `triggers/conditions/actions`
  (the blueprint is applied at runtime). It round-trips verbatim; the trace exposes
  `blueprint_inputs`.
- **DESIGN §5.8 shows the DSL decorator as `use_blueprint="motion_light.yaml", inputs={…}`.** Two
  mismatches with the stored JSON: (a) the JSON key is **`input`**, not `inputs`; (b) the path is
  **`<author>/motion_light.yaml`**, not a bare filename. The DSL surface can keep `inputs=` for
  ergonomics, but the compiler/decompiler IR must emit/read `use_blueprint.input` and the
  author-qualified `path`. Update §5.8's example (or note the DSL↔JSON mapping explicitly).
- **M2 finding:** a stored blueprint automation also carries the usual top-level
  `alias`/`description` fields alongside `use_blueprint` (see
  `fixtures/configs/automation_blueprint_based.json`), which the M1
  `blueprint_automation(id=, use_blueprint=, inputs=)` builder had no kwargs
  for. Fixed as an F3 *addition* (widening, not a break, per docs/dsl-f3.md's
  stability contract): `alias=`/`description=` optional kwargs added in M2 so
  the decompiler can round-trip a blueprint automation's alias/description
  without falling back to `raw_automation`.

### 10.6 `skip_condition` default — quirk #2 — CONFIRMED (`true`)
`automation.trigger` with **no** `skip_condition` runs the actions **even when conditions are
false** (default `skip_condition: true` ⇒ conditions skipped). With `skip_condition: false`,
conditions are evaluated and a false condition blocks the run. Verified against a false-condition
automation and a side-effect counter:

| `automation.trigger` data | condition (false) | action ran? | trace `script_execution` |
|---|---|---|---|
| `{entity_id}` (no skip_condition) | skipped | **yes** (counter 0→1) | `finished`, last_step `action/0` |
| `{entity_id, skip_condition:false}` | evaluated → false | **no** (counter 0→0) | `failed_conditions`, last_step `condition/0/…` |

`hassle run --live` (DESIGN §10.4) must therefore send `skip_condition: false` explicitly so a
default live run mirrors a real trigger — exactly as the design states.

---

## 11. Notes for M5 (FakeBackend fixtures)

- Raw captures: [`ha-api-captures/rest-ws-core.json`](ha-api-captures/rest-ws-core.json)
  (automations, scripts, all 9 helper cycles, registries, `get_services`, `validate_config`),
  [`validate-template-roundtrip.json`](ha-api-captures/validate-template-roundtrip.json)
  (plural validate, plural POST round-trip, `render_template`, `editable`),
  [`traces-skip-condition.json`](ha-api-captures/traces-skip-condition.json)
  (trace/list, trace/get, skip_condition matrix). Media captures are inline in §9 (curl-driven).
- **Model the plural schema (§10.1) in FakeBackend:** `list_remote` returns the plural form; the
  canonical hash is over the plural form; a `create/update` that receives singular input should
  normalize to plural before hashing, mirroring HA. Otherwise M5's plan table will show spurious
  `update`s.
- Helper apply must use the `{domain}_id` key on update/delete (§4).
- `apply` order helpers → scripts → automations (DESIGN §8.2) is independent of these findings.
- FakeBackend's media mirror stub should reproduce **both** gates (upload Content-Type + download
  extension) so M6's mirror tests exercise the real failure modes.

*Verified 2026-07-03 against Home Assistant 2026.2.3 (see §0 for why not 2026.7). Re-verify §10 on
2026.7 in M6.*

---

## 12. M1 internal-api contract gap: helpers / raw_automation / @blueprint_automation
not wired into `compile_bundle` (found by the templates/macros/object-types work item)

> **RESOLVED in the M1 integration pass (branch `m1/dsl-compiler`).** The
> minimal fix sketched below was implemented as-is: `Registry.add_object(obj,
> span)` (registry.py) registers a pre-built `IRObject` with no `func`;
> `compile_registered` (bundle.py) drains a `prebuilt` stream and calls
> `result.add(...)` directly, before the function-shaped registrations.
> `helpers.py` and `raw_automation.py` builders now register into the active
> bundle registry; `compile_bundle` resets their process-wide `_DECLARED` lists
> per compile (R8). Public names (`input_boolean`…`schedule`, `raw_automation`,
> `blueprint_automation`) are in `hassle.__all__`. Goldens:
> `fixtures/dsl/{helper_declarations,raw_automation_legacy,blueprint_automation}`.
> The rest of this section is retained as the original gap report.
>
> **Also renamed 2026-07-03 (owner decision, same integration pass):** the
> `hassle-core` distribution collapsed its two top-level import packages
> (`hassle_core` + a thin `hassle` facade) into one, `hassle`. Every
> `hassle_core.*` path in the retained report below is now `hassle.*`; see
> docs/ir-f1.md and docs/dsl-f3.md for the full rename note.

**Not an HA-behavior finding — an internal extension-contract gap in
docs/m1-internal-api.md**, flagged here per CLAUDE.md's "if the internal-api
contract is insufficient, stop and report rather than modifying core."

`compile_bundle`/`compile_registered` (`packages/hassle-core/src/hassle/compiler/bundle.py`
-- path renamed 2026-07-03 from `hassle_core/compiler/bundle.py`, owner decision, see
docs/ir-f1.md; frozen for follow-on M1 workstreams) only drain `registry.Registry` -- a list of
`RegisteredObject`, each of which is compiled by opening a `Recorder` and calling
`reg.func()` once, i.e. "run a function, record trigger/condition/action calls
into it." That model fits automations, scripts, and (via a caller-side wrapper)
`@shared_script` calls -- all trigger/condition/action-shaped. It does **not**
fit:

- **Helper declarations** (DESIGN §5.7: `input_boolean(id=..., name=...)` etc.)
  -- a helper is a plain declarative object with no function body to record.
- **`raw_automation`/`@raw_automation`/`@blueprint_automation`** (DESIGN §5.8)
  -- each is a whole *top-level object* that must land in
  `CompileResult.objects` under `"automation:<id>"`, not a trigger/condition/
  action recorded *inside* one (unlike `raw_trigger`/`raw_condition`/
  `raw_action`, which fit the existing seam fine and are fully wired up).

Getting either into `CompileResult.objects` requires a change to one of the
two files the m1/templates work item was told not to edit:

- `registry.py`: `RegisteredObject` requires a `func: Callable`; there is no
  registration path for a pre-built IR object today (only `automation()`/
  `script()` populate a `Registry`, both function-decorator shaped).
- `bundle.py`: `compile_registered`'s loop unconditionally opens a `Recorder`
  and calls `reg.func()` before an `if reg.kind == "automation" / elif
  "script" / else: raise ValueError` branch (bundle.py, `compile_registered`).
  There is no branch that skips the recorder and calls the already-public
  `CompileResult.add()` directly with a pre-built `HelperConfig`/
  `AutomationConfig`.

**What was built instead:** `hassle.compiler.helpers` and
`hassle.compiler.raw_automation` (paths renamed 2026-07-03 from
`hassle_core.compiler.*`) implement the full model/builder layer
correctly and with test coverage (`HelperConfig`/`AutomationConfig`
construction, the nine helper domains, JSON-serializability validation for raw
bodies, the DESIGN §5.8 `inputs=` -> stored `use_blueprint.input` singular-key
mapping per §10.5 above, `normalize_ha` applied) and track their declarations
in a process-wide list (`declared_helpers()` / `declared_raw_automations()`,
mirroring `registry.Registry`'s own pattern) -- but nothing compiles them into
`compile_bundle(bundle_dir).objects`. They are deliberately **not** added to
`hassle.__all__` (the F3 public DSL surface) so as not to advertise a
half-working construct.

**Minimal fix (for whoever picks this up, likely alongside the actions/
control-flow or a dedicated integration pass):** add a `Registry.add_object
(kind, obj: IRObject, span)` (or equivalent) path in `registry.py` that
doesn't require a `func`, and a branch in `compile_registered` (bundle.py)
that, for such entries, skips `with recording(...): reg.func()` entirely and
calls `result.add(obj, spans={}, decl_span=reg.span, duplicate_of=reg.span)`
directly. Both `helpers.py`'s and `raw_automation.py`'s constructor functions
already produce the exact `IRObject` this would need — only the last
"register it" step is missing.

---

## 13. M1 integration-pass DSL-surface decisions (branch `m1/dsl-compiler`)

Merging the three M1 workstreams (triggers, actions, templates) onto the core
surfaced two public-name collisions and required API smoothing before the F3
freeze. These are DSL-surface facts (not HA-behavior findings), recorded here
per CLAUDE.md and backed by `packages/hassle-core/tests/test_integration_api.py`.

### 13.1 `event` is the trigger; the fire-event action is `fire_event`
Both the triggers workstream (event **trigger**, DESIGN §5.4) and the actions
workstream (fire-event **action**) exported a public `event`. They are different
functions and cannot share a name. Resolution: `event` = the trigger builder
(DESIGN §5.4 lists it among triggers); the fire-event action was renamed
`fire_event`. Both are public.

### 13.2 `template()` is one builder serving both contexts
The triggers workstream exported `template()` → a template **trigger/condition**;
the templates workstream exported `template()` → a raw-Jinja **value** string.
DESIGN §5.4 sanctions both spellings of `template()`. Resolution: a single
`str`-subclass `TemplateExpr` (templates.py) that also implements
`to_trigger`/`to_condition`, so `template("{{…}}")` is a Jinja value as a bare
expression and a template trigger/condition inside `when`/`only_if`. The
triggers-module duplicate was deleted.

### 13.3 API smoothing folded two wrapper functions away (pre-F3)
The workstreams honored the core freeze by shipping wrappers instead of editing
`builders.py`/`actions.py`. The integration pass (which has core-edit rights)
folded them in and deleted the wrappers so the public surface has one way to do
each thing:
- `with_trigger_options(state(...), id=, enabled=, variables=, for_=)` →
  folded into `state().to(...)`/`.is_(...)`/`.with_options(...)`; wrapper deleted.
- `service_ext(..., response_variable=, continue_on_error=)` → folded into
  `service(...)`; `service_ext` deleted.

### 13.4 `StateExpr.entity_id` is now public (deviation note retired)
templates.py's `state(x).value` previously read `StateExpr`'s private
`_entity_id` (a documented coupling / deviation, formerly noted here). The
integration pass added a public read-only `StateExpr.entity_id` accessor and
switched `.value`/`expr()` to use it; the private-attr coupling and its
deviation note are gone.

## 14. M2 finding: the compiler always materializes an explicit automation `id`

`hassle.compiler.bundle._build_automation` sets `body["id"] = options.get("id")
or reg.func.__name__` unconditionally -- there is no DSL shape that produces an
automation with no `id` at all; every `@automation`-decorated function compiles
to an explicit `id` field (the decorator's `id=` kwarg, or the function name).

This is a real constraint the M2 decompiler/round-trip test had to account for:
about 50 of the `fixtures/configs/automation_*.json` fixtures have **no** `id`
field at all (they're hand-authored docs examples predating the corpus's
identity convention; real HA always assigns an `id` on creation and returns it
on every read, docs/ha-api-notes.md §2). Decompiling one of these fixtures and
recompiling it therefore always adds an explicit `id` (the fixture's filename
stem, used as the synthesized identity) to the output -- correctly matching
what a real HA automation would already have, not a lossy round-trip. M2's
`test_roundtrip_corpus` (`packages/hassle-core/tests/test_roundtrip_corpus.py`)
compares against `normalize_ha(x)` **with that synthesized id added** for these
fixtures specifically, rather than bare `normalize_ha(x)`.

No DESIGN.md text is contradicted by this (§7.1/§7.3 don't claim decompiled
output is byte-identical-including-omitted-fields; I3 is about round-tripping
*any config*, and a config missing its own identity is not really "any config"
HA would ever hand back) -- flagged here per CLAUDE.md's "record + flag" rule
because it was non-obvious until the round-trip test was written against the
real corpus.

## 15. M2 correction: most of the corpus is legacy singular-form, not "two fixtures"

MILESTONES M2 test 1 names ``automation_legacy_platform_naming`` and
``automation_service_call_longhand`` as "the cases where normalization
applies," implying they are the exception. Checking the actual corpus:
**48 of the 55 ``automation_*.json`` fixtures** use the legacy singular schema
(`trigger`/`condition`/`action` outer keys, some with `service:`) -- the corpus
was built before M0.1 added the 2026.7 purpose-vocabulary fixtures (which are
plural by construction, since that vocabulary postdates the singular/plural
split). Only 6 automation fixtures are already plural.

This doesn't change any test's correctness (`test_roundtrip_corpus` and
`test_normalize_ha_is_identity_for_plural_fixtures`,
`packages/hassle-core/tests/test_roundtrip_corpus.py`, are fixture-shape-driven,
not hardcoded to the two named fixtures), but the milestone text's framing is
misleading for anyone reading it as "normalization is a rare edge case in this
corpus" -- it is the majority case. Flagged here rather than silently
worked around.

## 16. M2 finding: typed trigger builders cannot reproduce a legacy `platform:` key

`normalize_ha` correctly preserves an inner `platform:` discriminator verbatim
(§10.1, §14 above -- verified against real HA: it is never rewritten to
`trigger:` on storage). But **every typed trigger builder in
`hassle.compiler.{triggers,builders,purpose}.py` always emits the modern
`trigger:` key** (`_TriggerBase.to_trigger()`'s `{"trigger": self._trigger_type(), ...}`)
-- there is no builder-level way to ask for the legacy spelling. DESIGN §5.8's
own example shows a `platform:`-keyed device trigger going through
`raw_automation`/`raw_trigger`, which is the intended path for exact-spelling
preservation.

48 of the 55 corpus automation fixtures use `platform:` (see §15). Decompiling
all of them to `raw_trigger` (to preserve the spelling exactly) would leave the
M2 DSL-coverage metric far under the 90% gate, on a corpus that is mostly
legacy-form fixtures by historical accident (see §15) rather than
representative of what a 2026.7 UI actually writes today.

**Decision (recorded, scoped to the decompiler's own round-trip test only):**
the decompiler emits the typed builder for a `platform:`-keyed trigger
(`state(...)`, `zone(...)`, etc.) rather than falling back to `raw_trigger`,
accepting that this modernizes the discriminator spelling on the next
recompile -- a decompile+recompile cycle is expected to modernize a config to
the current schema, exactly as HA's own schema migrations behave when a config
is re-saved through a newer editor. This is purely cosmetic (the trigger's
meaning is unchanged) and does **not** touch `normalize_ha` itself, which stays
byte-faithful to verified real-HA behavior for the sync engine's actual hashing
(M5+ — `manifest.lock` still hashes exactly what HA stores). The test-local
`_modernized()` helper in `test_roundtrip_corpus.py` documents and implements
this narrowly (only at trigger positions, never conditions/actions, which have
no such legacy synonym).

## 17. M2 finding: the compiler always materializes `triggers`/`conditions`/`actions`

`hassle.compiler.bundle._build_automation` sets all three keys unconditionally
(`body["triggers"] = [...]`, etc., even when the corresponding DSL call was
never made), so a compiled automation always has explicit `triggers: []`/
`conditions: []`/`actions: []` for any block the DSL body didn't populate. This
is already accepted M1 behavior (`fixtures/dsl/minimal/expected_ir.json` has
`"triggers": []` for an automation with no `when(...)` call), not new M2
behavior -- but it means a fixture with no `condition` key at all recompiles
with an explicit `conditions: []`, which the M2 round-trip test's expectation
must account for the same way (`test_roundtrip_corpus.py`'s `setdefault` calls
before comparing).

## 17. M6 behavioral re-verification (DirectBackend + real-HA integration)

> Verified 2026-07-04 while building `DirectBackend`/`HaClient`. **Environment
> caveat (same as §0):** Docker image *layers* are still 403-blocked in this
> sandbox (the `stable`/`dev` manifests fetch, but blob pulls from
> `pkg-containers.githubusercontent.com` 403), so local verification again ran
> against **HA 2026.2.3** (pip, Python 3.13.12). The M6 CI `integration` job runs
> the *same* `integration/`-marked suite against real `stable` **and** `dev`
> containers (Docker works in CI) — that is where the 2026.7-specific rows below
> are confirmed. Everything here exercises long-stable surface unless flagged.

### 17.1 Inner `platform:` is NOT rewritten to `trigger:` on storage (M4 finding) ✅
The open M4 question (MILESTONES M6 test 5): does HA rewrite an inner legacy
`platform:` discriminator to `trigger:` when it stores an automation? **No.**
POSTing `triggers:[{"platform":"state",…}]` (or legacy `trigger:` outer) reads
back with the inner key **unchanged** (`"platform":"state"`); only the *outer*
block key is pluralized and `service:`→`action:`. So `normalize_ha`'s current
rule (preserve inner `platform:`, §10.1/§16) is correct and needs no extension.
`test_ha_does_not_rewrite_inner_platform_to_trigger` (integration) asserts
`normalize_ha(posted) == stored` against real HA and is the standing evidence:
if a future HA changes this, that test fails and `normalize_ha` gets the rule.
(Also observed: scalar `delay: 5` is stored verbatim, not expanded.)

### 17.2 Purpose-vocabulary enumeration WS API — found ✅ (provisional fixture shape kept, no R5 break)
M0.V could not capture the enumeration API (§0). It is the pair of WS
subscriptions **`trigger_platforms/subscribe`** and
**`condition_platforms/subscribe`** (`homeassistant/components/websocket_api/
commands.py`: `handle_subscribe_trigger_platforms` /
`handle_subscribe_condition_platforms`). Each **acks with a `result`, then
pushes an `event`** whose payload is a map `{ "<domain>.<event>": <description>,
… }` (a full snapshot), followed by incremental `event`s as more platforms load.
The **enumerated vocabulary is the set of keys**; each value is a UI description
object Hassle currently discards. `DirectBackend.fetch_purpose_vocabulary()`
reads the first snapshot event of each and returns
`PurposeVocabulary(triggers=sorted(keys), conditions=sorted(keys))`.

- On **2026.2.3 the snapshot is empty** (the purpose vocabulary is a 2026.7
  feature) — so `fetch_purpose_vocabulary()` returns empty lists there, and the
  round-trip half of MILESTONES M6 test 8 skips locally and runs in CI on
  `stable`/`dev`.
- **R5 note:** the provisional M0.1 fixture shape
  (`registry.purpose_vocabulary = {triggers: [str], conditions: [str]}`) is
  *derivable directly* from `sorted(payload.keys())`, so the shape does **not**
  differ — the fixture and `RegistrySnapshot.PurposeVocabulary` are kept
  unchanged, and no MILESTONES update is required. (Only the *source* moved from
  "provisional" to "these two subscribe commands.")

### 17.3 Parallel-branch `stop` semantics (M4 finding) ✅
From `homeassistant/helpers/script.py` (`_async_step_parallel` + `async_run`'s
`_StopScript` handling), authoritative and version-stable: each `parallel:`
branch runs as its own sub-`Script`. A `stop` in a branch raises `_StopScript`,
which re-raises out of the (non-top-level) branch; the branches run under
`asyncio.gather(return_exceptions=True)`, so **sibling branches are NOT
cancelled — they all run to completion**, and *then* the first `_StopScript`
re-raises and propagates up, ending the whole run (actions in the enclosing
sequence *after* the `parallel:` block are skipped). Net for the M4 simulator:
`stop` in one branch stops the automation, but does not interrupt in-flight
siblings.

### 17.4 Media mirror: two gates reconfirmed + folder IS auto-created (corrects §10.4) ✅
Full flow reconfirmed on 2026.2.3 (MILESTONES M6 test 9): upload
`application/zip` → **400**, `image/png` → **200**; `resolve_media` → signed URL
with `mime_type: audio/mpeg`; authenticated GET of the `.mp3` → **200**, bytes
sha256-identical; `remove` → success. **Correction to §10.4:** the upload
endpoint now `mkdir(parents=True, exist_ok=True)`s the target subfolder
(`local_source.py::async_upload_media`) — verified by uploading to a
non-existent subfolder, which returned 200 and created the folder on disk. So
the mirror does **not** need to pre-create its folder (it still must avoid the
media root — §10.4 — and still rides both incidental gates, so `MediaMirror`
keeps the `folder != ""/"."` guard and the `image/png`-upload / `.mp3`-name
strategy). Re-verify on 2026.7 in CI.

### 17.5 Helpers derive their id from the name slug, ignoring a supplied `id`
Real HA storage-collection `create` **assigns the item id by slugifying `name`
and ignores any caller-supplied `id`** (§4). `DirectBackend.create` therefore
strips `id` from the create payload and returns HA's assigned `result.id`.
**Divergence from `FakeBackend`:** the M5 `FakeBackend._derive_identity` honors a
supplied helper `id` if present. This does not affect M6 (DirectBackend matches
real HA), but the compiler/CLI (M5/M7) should ensure a declared helper's `name`
slugifies to its intended `id`, or the plan's object key will drift from HA's
assigned identity. Flagged for M7.

### 17.6 The config API validates the full schema on every write
`POST /api/config/automation/config/{id}` rejects a partial body — e.g. an
"update just the alias" payload missing `actions` returns
`400 {"message":"Message malformed: required key not provided @ data['actions']"}`.
So `update` must send a complete config (the sync engine always does; it pushes
freshly compiled full configs).

### 17.7 Config-REST auto-reload is asynchronous — `DirectBackend` blocks until it settles
Confirming §2 behaviorally with timing: after a `POST`, the automation entity
appears in `/api/states` after **~200–300 ms** (not synchronously); after
`DELETE` it disappears within ~1 s. Because the `Backend` contract is
synchronous (a `list_remote` right after a `create` must see it), `DirectBackend`
**bounded-polls `/api/states` until the entity appears (create/update) or
disappears (delete)** before returning (`_await_config_entity`, 10 s cap). This
is transport-layer I/O waiting, not core-logic wall-clock (R8 governs
compiler/simulator determinism). Helpers (WS storage collections) are
synchronous and need no such wait.

### 17.8 Hassle bug found + fixed (regression-tested): planned `delete` carried no re-verify hash
The M6 core-loop integration test surfaced an M5 latent bug: `compute_plan`
produced `delete` entries with `remote_hash_at_plan = None`, but `apply_plan`
re-verifies the remote hash before deleting (DESIGN §8.2) — so every planned
delete aborted as spurious "drift". No prior test ran a `compute_plan` delete
through `apply_plan`. Fixed in `plan.py` (populate `remote_hash_at_plan` on the
`delete` entry, mirroring `update`); regression-tested by
`tests/test_plan_apply_delete_roundtrip.py` (R4). No interface change.

### 17.9 DESIGN §6 mismatch found in M7: `compile_bundle` does not recurse into subdirectories — RESOLVED 2026-07-04 (M7.1)
DESIGN §6's documented bundle layout has DSL sources split across
`automations/`, `scripts/`, `helpers/`, `lib/` subdirectories under the
bundle root. The real M1 implementation
(`hassle.compiler.bundle._import_bundle_modules`) only globs **top-level**
`*.py` files directly in the bundle directory (`bundle_path.glob("*.py")`,
non-recursive) — every fixture from M0 through M6
(`fixtures/dsl/*/bundle/`, `fixtures/registry/{clean,broken}_bundle/bundle/`)
is in fact flat, one or more `.py` files directly at the bundle root, and
every milestone's test suite was built and passed against that flat
convention despite §6 showing subdirectories.

Found while wiring M7's CLI test fixtures (nesting DSL sources under
`automations/`, per §6) against `compile_bundle` and getting an empty
`CompileResult.objects` with no error. Not fixed as part of M7 itself
(changing `_import_bundle_modules` to recurse was a behavior change to a
frozen, heavily-tested M1 module with no M7 test-contract requirement forcing
it); M7's own fixtures and the `hassle init` scaffold used the flat
convention that matched actual `compile_bundle` behavior at the time.

**Decision (owner, M7.1): DESIGN §6's tree layout wins — the loader
recurses.** `compile_bundle` now walks the whole bundle tree
(`hassle.compiler.bundle._iter_bundle_source_files`), skipping `tests/`,
`.hassle/`, `stubs/`, any dot-directory, and `__pycache__` at every depth.
Each file is imported under its dotted, package-relative module name
(`automations.hallway`, not bare `hallway`) so a cross-file
`from helpers.modes import guest_mode` / `from lib.notify import
notify_adults` (DESIGN §5.3/§5.6 verbatim) resolves through **PEP 420
namespace packages** — no `__init__.py` anywhere in the tree, since the
bundle root is already on `sys.path` and namespace packages need none for
this. `hassle init` now scaffolds `automations/scripts/helpers/lib/tests/`,
none with an `__init__.py`. Flat bundles (every pre-M7.1 fixture) are
unaffected: a bundle with no subdirectories compiles exactly as before, byte
for byte (zero golden drift verified). Duplicate-id detection and source
spans now span the whole tree (a span from a nested file reads like
`automations/hallway.py:12`). Placement defaults for never-seen/adopted
objects (`hassle_cli.bundle_ops.default_source_path`) now land under
`automations/misc.py` / `scripts/misc.py` / `helpers/misc.py` per DESIGN
§7.3, instead of the flat one-file-per-object fallback this finding
previously documented as the workaround.

**Review finding (M7.1 review, fixed same branch): the recursive walk
followed symlinks.** A symlinked directory or `.py` file inside the bundle,
pointing outside it, was imported and executed — a sandbox escape (§14) —
and because the target's `__file__`/`__path__` resolves outside
`bundle_path`, the cleanup pass never removed it from `sys.modules`; the
next compile's double-import guard then served that stale leaked module
instead of re-importing anything, silently dropping the escaped object from
the second compile onward. **Policy: every symlink under the bundle is
skipped, silently, whether it targets a directory or a file** — see
`_iter_bundle_source_files`'s and `_import_bundle_modules`'s docstrings in
`hassle.compiler.bundle` for the mechanism (walk-time `is_symlink()` check
plus a belt-and-suspenders resolve-under-`bundle_path` re-check immediately
before import, to also catch a symlinked intermediate directory).

## 19. Real-world smoke-test findings (task #5): three mundane UI-authored shapes DESIGN §5.4 missed

> Source: the owner's first live smoke test against a real 2026.7 Home Assistant
> instance surfaced 118 granular `raw_*` decompiler fallbacks across 101 real
> objects, tracing to three root causes below. All three are ordinary shapes the
> HA UI writes on every save; none are exotic. Fixtures:
> `fixtures/configs/automation_action_metadata_ui_authored.json`,
> `fixtures/configs/automation_state_trigger_list_valued_fields.json`,
> `fixtures/configs/automation_time_trigger_weekday_and_entity_at.json`.

### 19.1 Every UI-saved action carries `"metadata": {}` — must round-trip even when empty
Not mentioned anywhere in DESIGN. Confirmed present on all 87 raw actions in the
smoke-test sample. Since a real live `GET` always returns this key, eliding an
empty `metadata: {}` on decompile+recompile would hash-drift *every*
UI-authored action forever (I3) — this is not optional/cosmetic the way the
`platform:`→`trigger:` or scalar-delay modernizations are (§16/§18), because HA
itself never strips the key, so there is no "already canonical" case where it's
absent from a live object. **Fix:** `service()`/`ServiceAction` gained an
optional `metadata=` kwarg (F3-additive, docs/dsl-f3.md's "widening a signature
with a new optional keyword is an addition, not a change"); the decompiler
emits `metadata={...}` whenever the key is present in the stored action,
including `metadata={}`, and omits the kwarg entirely when absent (so
DSL-authored actions with no `metadata` at all are unaffected).

### 19.2 `state`/`numeric_state` trigger `entity_id`/`to`/`from` are stored as lists, even for one value
DESIGN §5.4 and every existing fixture used bare scalars
(`"entity_id": "binary_sensor.x"`). A real 2026.7 UI-authored automation always
stores these fields as a **list**, even when there is exactly one entity/value
— and a singleton list must decompile back to a list, never normalized to a
scalar, or the round-trip hash drifts (I3) on every such trigger. **Fix:**
`state()`'s `entity_id` param (and `.to()`/`.is_()`'s value) and
`numeric_state()`'s `entity_id` param now accept `str | list[str]`
(F3-additive widening); the decompiler's entity-id shape check
(`_is_entity_id_shape` in `hassle.decompiler.exprs`) accepts either shape and
renders it with `render_literal` (which already handles lists), so a
singleton list source (`entity_id: ["binary_sensor.x"]`) decompiles to
`state(['binary_sensor.x'])`, not `state('binary_sensor.x')`. **Follow-on
typing note:** `StateExpr.entity_id`'s public accessor is also used by
`hassle.compiler.templates._entity_ref_str` (the `expr()`/`state(...).value`
template-read path, which always names exactly one entity); a `StateExpr`
built from a list there now raises a what/where/fix `TypeError` rather than
silently stringifying the list — recorded because it's a new, narrow trap at
an existing seam, not because the seam's behavior changed for the scalar case.

### 19.3 `time` trigger accepts `weekday`, and `at` as an entity reference — not just condition-only/literal-only
DESIGN §5.4's `time()` builder doc (and the pre-existing `TimeExpr` docstring)
stated `at=` is trigger-only and `after=`/`before=`/`weekday=` are
condition-only. A real 2026.7 UI-authored automation showed a `time` **trigger**
with a `weekday` field (a day-abbreviation list, e.g. `["mon","tue","wed","thu","fri"]`)
scoping a fixed-time trigger to specific days — HA's `time` trigger schema
does accept this filter; DESIGN's description was incomplete, not the whole
condition-only claim being wrong (`after`/`before` are still condition-only —
only `weekday` turned out to also apply to the trigger). Separately, the same
smoke test showed `at` set to an entity reference (`input_datetime.wakeup`)
rather than a literal `"HH:MM:SS"` string — schedule-driven wakeups, a
documented native HA feature (a `time` trigger's `at` accepts either an
`input_datetime`/`sensor` entity id or a fixed time). This required no builder
change (`at` was always typed as a plain `str`, so an entity-id string already
flows through unchanged) but is recorded because it wasn't called out. **Fix:**
`TimeExpr`/`time()` now also emit `weekday` on the *trigger* side (was
condition-only before); the decompiler's `_trig_time` accepts and emits
`weekday` alongside `at`. `time(at="input_datetime.wakeup")` already worked and
needed no code change, only this note.
