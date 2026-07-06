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

**Amendment 2026-07-05 (smoke #7 field evidence): the slug rule only
constrains the WS-API *creation* path — `.storage` contents themselves are
unconstrained.** The owner's live registry has helpers whose id does **not**
equal `slugify(name)` — e.g. an `input_text` with id
`material_you_image_url_6814bc` and name "Material You Base Color Source
Image Path/URL Keaton" (slug: `material_you_base_color_source_image_path_
url_keaton`). These were created by an external integration writing HA's
`.storage/*` files directly, bypassing the WS `create` call entirely — so the
id/name-slug relationship above never applied to them in the first place.
Nothing in HA enforces id == slugify(name) as an invariant of storage
*contents*; it is purely a derivation rule of one specific creation path.

Consequence for the M7 `helper-id-name-mismatch` validator Finding
(`hassle.registry.validate._validate_helper_slugs`): the original,
unconditional form of this check would tell an owner to "fix" the id of an
already-live, adopted helper like the one above — advice that, if followed,
would change `HelperConfig.id` for an object Hassle does not own the
creation of, breaking the bundle's mapping to a real pre-existing entity
(a de facto I2 violation via user-actioned "fix" text). **The check is now
scoped to NEW declarations only**: it fires exclusively when
`<domain>.<supplied_id>` is absent from the registry snapshot (i.e. nothing
with that identity exists yet, so Hassle would create it fresh via the WS
path, where the slug rule genuinely does bite). An id already present in the
snapshot is adopted, live truth — exempt regardless of name/id mismatch. When
no registry snapshot is available at all (validation can't distinguish new
from adopted), the Finding still fires so a real bug isn't silently hidden,
but at softened `"note"` severity with fix text explaining the uncertainty
and pointing at `hassle pull`/`hassle stubs --refresh`.

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

## 20. Residue coverage, round 2 (task #8): four more UI-authored shapes DESIGN §5.4/§5.5 missed

> Source: a second live smoke test against the owner's real 2026.7 Home
> Assistant bundle (101 objects) surfaced 12 more granular `raw_action`
> decompiler fallbacks, tracing to four root causes below — extending the
> round-1 pattern (§19) directly. All four are ordinary shapes the HA UI
> writes on every save; none are exotic. Fixtures:
> `fixtures/configs/automation_action_data_template_ui_authored.json`,
> `fixtures/configs/automation_condition_state_list_valued_fields.json`,
> `fixtures/configs/automation_action_step_alias_and_enabled.json`,
> `fixtures/configs/automation_container_recursion_ui_shapes.json`.

### 20.1 A service action's legacy `data_template` key is a sibling of `data`, never folded into it
Not mentioned in DESIGN. A real 2026.7 UI-authored `climate.set_temperature`
action carried `data_template: {"temperature": "{{ ... }}"}` alongside
`target`, with no `data` key at all. HA still accepts and stores this legacy
key verbatim (it predates the `data`/`data_template` unification in newer HA
versions, but the *storage* layer never migrates an already-saved config's key
spelling on its own — only re-saving through the UI would). Folding it into
`data` would drop the distinction and hash-drift on every recompile (I3), so
it must round-trip as its own field. **Fix:** `service()`/`ServiceAction`
gained an optional `data_template=` kwarg (F3-additive, docs/dsl-f3.md's
"widening a signature with a new optional keyword is an addition, not a
change") — the least-surface option, mirroring `metadata=`'s existing
treatment rather than inventing a new builder. The decompiler emits
`data_template={...}` whenever the key is present, as a sibling `service()`
kwarg alongside (never merged with) any `data=`/bare-kwarg data fields, and
omits it entirely when absent.

### 20.2 List-valued `state` **condition** fields — the condition-side mirror of round 1's trigger fix
Round 1 (§19.2) fixed `state`/`numeric_state` **trigger** `entity_id`/`to`/
`from` being stored as singleton lists. The same real bundle showed the
identical shape on the **condition** side: `{"condition": "state",
"entity_id": ["input_boolean.x"], "state": ["on"]}`, including nested inside
`if`/`then` action blocks and `choose` branch conditions. The **compiler**
side needed no change — `StateExpr.to_condition()` already emitted whatever
`entity_id`/`state` it was constructed with (`str | list[str]` since round 1),
so `state(["input_boolean.x"]).is_(["on"]).to_condition()` already produced
the list-valued shape. The gap was purely in the **decompiler**:
`hassle.decompiler.exprs._cond_state` required `entity_id` to be a bare `str`
and fell back to `raw_condition` for a list, tanking coverage on every such
condition and, transitively, forcing any container (`if`/`choose`) with one
nested inside to fall back to whole-block `raw_action` too (§20.4). **Fix:**
`_cond_state` now uses the same `_is_entity_id_shape` check round 1 added for
triggers, rendering via `render_literal` so a singleton list decompiles back
to a list, never a scalar (I3). No DSL surface change — `state()` is the same
dual-purpose builder already documented as list-capable.

### 20.3 Per-step `alias`/`enabled` — the UI names and toggles individual steps
Not mentioned in DESIGN. A real 2026.7 UI-authored automation named steps
(`{"alias": "Turn on bedroom", "action": "light.turn_on", ...}`) and toggled
them off (`{"delay": {...}, "enabled": false}`) — both are ordinary UI
affordances (the automation editor's step-options menu) exercised on nearly
every hand-edited step, on both leaf actions (service calls, delays) and
whole containers (`if`/`choose`/`repeat`/`parallel`/`wait_for_trigger`/
`wait_template` all accept the same two fields on the assembled container
body, not just on a child step). Eliding either would drop UI-authored
metadata and hash-drift on recompile (I3). **Fix (F3-additive on every
listed builder):** `service()`/`ServiceAction`, `delay()`/`DelayAction`, and
every control-flow context manager in `hassle.compiler.control_flow`
(`if_then`, `choose`, `repeat_count`/`repeat_while`/`repeat_until`/
`repeat_for_each`, `parallel`, `wait_for`, `wait_template`) gained optional
`alias=`/`enabled=` keyword-only kwargs, each emitting the corresponding
top-level `alias`/`enabled` key on the assembled body when passed (omitted
entirely by default, so no pre-existing caller's compiled output changes).
`with if_then(cond, alias="Guard block"):` compiles `alias` onto the
assembled `{"if": [...], "then": [...], "alias": ...}` body — the *block's*
name, not a child step's — matching how the HA UI actually applies a
container's own alias. The decompiler emits `alias=`/`enabled=` on any action
or container shape that carries them, everywhere `_step_option_kwargs_src`
is threaded through (every handler in `hassle.decompiler.actions`).

### 20.4 Container recursion tolerance — a container must not raw itself merely because a child carries any of the above
This is a consequence of §20.1–§20.3 rather than an independent HA-behavior
finding, but it was the largest single coverage loss in the smoke sample: an
`if`/`else`, `choose`, or `parallel` action whose **inner** steps carried
`metadata`/`data_template`, a list-valued `state` condition, or `alias`/
`enabled` fell back to a whole-block `raw_action` even before this round's
fixes, in the pattern established by round 1 — `decompile_action`'s handlers
for `if`/`choose`/`repeat`/`parallel`/`wait_for_trigger` already recurse into
their children via `decompile_action`/`decompile_condition` (so nothing new
was needed for the recursion *itself*), but each of those handlers'
`set(body) <= known` guard has to also tolerate `alias`/`enabled` appearing on
the **container's own** body (a container can carry the option too, §20.3),
or the container itself falls back to raw before ever reaching its children.
**Fix:** every container handler's `known` set in
`hassle.decompiler.actions` (`_if_then`, `_choose`, `_repeat`, `_parallel`,
`_wait_for`, `_wait_template`) now includes `alias`/`enabled` alongside its
existing keys (`_STEP_OPTION_KEYS`), and §20.1/§20.2's fixes mean a child
carrying `data_template`/list-valued conditions no longer forces a fallback
either — so a container is never raw'd merely because a descendant (at any
nesting depth) carries one of these ordinary UI shapes.

*Verified 2026-07-05 against the owner's real 2026.7 Home Assistant bundle
(101 objects, 12 raw_action fallbacks traced to these four causes).*

## 21. Residue coverage, round 3, final (task #8 cont'd): branch-level `alias`/`enabled` and multi-step `parallel` branches

> Source: field measurement of the owner's real 2026.7 bundle after round 2
> (§20) landed: `raw_action` count dropped 14 → 7. Of the remaining 7, five
> are fixable (traced to the two root causes below); two are device actions
> that stay raw by design (no stable cross-integration schema, same rationale
> as `device()` triggers/conditions, §16/§19 — not addressed here). Fixtures:
> `fixtures/configs/automation_choose_template_condition_branch_alias.json`,
> `fixtures/configs/automation_choose_numeric_state_attribute_condition.json`
> (regression/verification, no fix needed),
> `fixtures/configs/automation_parallel_multistep_branch_composite.json`.

### 21.1 A `choose`/`parallel` **branch** can carry its own `alias`/`enabled` — a third, distinct layer round 2 missed
Round 2 (§20.3) added `alias=`/`enabled=` at two layers: individual leaf steps
(a service call, a delay) and the whole container block (`choose(alias=...)`,
`parallel(alias=...)`). A real 2026.7 UI-authored automation showed a third,
independent layer: the HA UI also lets a user name/toggle one **branch** of a
`choose` or `parallel` — e.g. `{"alias": "Cover open or opening", "conditions":
[...], "sequence": [...]}` inside `choose`, or `{"alias": "Notify branch",
"sequence": [...]}` inside `parallel`. This is not the same key position as
either of round 2's layers (it is per-branch, sitting alongside that branch's
own `conditions`/`sequence`, not on the assembled `{"choose": [...], ...}` /
`{"parallel": [...], ...}` body, and not on a step inside the branch's
`sequence`). The reported real shape's tripping element was specifically this
branch-level `alias` — the `template` condition it sat next to (with a
script-variable reference in its Jinja body) decompiles fine standalone and
was a red herring; diagnosis confirmed by reproducing the exact fixture shape
with and without the branch `alias` and observing only the alias's presence
flips the result to `raw_action`. **Fix:**
- `_ChooseBuilder.when_(condition, *, alias=, enabled=)` (F3-additive keyword
  widening) — the branch built by `with c.when_(cond, alias=..., enabled=...):`
  now carries its own `alias`/`enabled` alongside `conditions`/`sequence`.
- `parallel()` now yields a `_ParallelBuilder` (bound via `with parallel() as
  p:`) whose new `with p.branch(alias=, enabled=): ...` sub-context builds one
  explicit branch carrying its own `alias`/`enabled` (and, per §21.2, any
  number of steps). Existing bundles that write `with parallel(): action();
  action()` with **no** `as p:` binding are completely unaffected — each bare
  top-level action still becomes its own single-action branch with no
  alias/enabled, exactly as before (verified:
  `test_bare_parallel_with_no_as_binding_still_works_unchanged`).
- Decompiler: `_choose`'s and `_parallel`'s per-branch shape checks
  (`set(branch_dict) != {"conditions", "sequence"}` /
  `set(branch_dict) != {"sequence"}`) now tolerate `alias`/`enabled` alongside
  the required keys, emitting them as `c.when_(cond, alias=...)` kwargs or
  routing the branch through the new `with p.branch(alias=...):` form.

### 21.2 `_parallel`'s branch handler only accepted a `sequence` of exactly one action
DESIGN §5.5's own `parallel()` example, and every fixture through round 2,
show one action per branch — which is *all* the compiler could ever emit,
since `parallel()` auto-derives one branch per bare top-level action with no
way to group more than one step into a branch. A real 2026.7 UI-authored
automation had a `parallel` branch running **two** steps in the same
`sequence` (a `script.notify_all` call with a rich `data` payload, then a
`delay` with all four duration units) — an entirely ordinary HA
`parallel`/`sequence` shape the compiler-side model just couldn't produce or
the decompiler recognize. Diagnosis: both the delay (including its
`milliseconds` field) and the sibling branch's `if`/`then` decompile cleanly
in isolation, confirming the step *content* was never the issue — the
decompiler's `len(seq) != 1` check on each branch's `sequence` was the actual
trip. **Fix:** `_parallel` now accepts a branch `sequence` of any length,
decompiling a multi-step (or otherwise non-bare) branch through the same new
`with p.branch(): ...` sub-context from §21.1 (steps decompiled via the usual
`_actions_block`/`decompile_action` recursion, so a two-step branch is just
two ordinary statements inside the `with p.branch():` body — no new step-level
logic needed). The compiler's `_ParallelBuilder.branch()` records however many
actions are called inside it into that one branch's `sequence`, verified
round-trip-exact against the real composite shape.

### 21.3 Verified, not fixed: a `numeric_state` condition with `attribute` nested inside `choose` `conditions` already worked
The field measurement's shape list also named a `choose` branch whose
`conditions` carries `{"condition": "numeric_state", "entity_id": "cover.x",
"attribute": "current_position", "above": 0}`. Checked against both the
pre-round-3 and current decompiler: `_choose` calls the same top-level
`decompile_condition` dispatcher `_cond_numeric_state` already goes through
for a bare automation-level condition, and `_cond_numeric_state`'s `known` set
already included `attribute` (an M1.1-era addition, docs/ha-api-notes.md's
sun-elevation condition note). No code path exists that treats a
choose-nested condition differently from a top-level one. **No fix was
needed** — `automation_choose_numeric_state_attribute_condition.json` is a
regression/verification fixture only, pinning this so it never silently
breaks if the nested-condition path is ever refactored.

*Verified 2026-07-05 against the owner's real 2026.7 Home Assistant bundle
(field measurement: 14 → 7 raw_action fallbacks after round 2, 5 of 7 traced
to §21.1/§21.2 above and fixed; 2 remaining are device actions, out of scope).*

---

## 22. Pull organization + ignore filtering (owner feedback after first real pull, `ux/pull-organization`)

> **Correction (2026-07-06):** this section's claim that HA's category registry
> only covers `automation`/`script` scopes is wrong (and was wrong when written) —
> the frontend also uses `scene` and a shared plural `helpers` scope covering all
> helper domains, storage-collection and config-entry alike. See §31.

### 22.1 Category registry — `config/category_registry/list`, scoped, and per-entity `categories`

DESIGN §7.3/§6 always said placement should follow HA's UI category registry, but it was never
implemented (`bundle_ops.default_source_path` unconditionally fell back to `automations/misc.py`).
Implemented this round, unit-tested against `FakeBackend`/a stand-in WS client (no live-HA capture
was taken for the category registry itself — see the caveat below):

- **`config/category_registry/list`** takes a `scope` argument (confirmed by DESIGN's own prose
  and HA core's `websocket_api` convention for scoped registries — e.g. `entity_category` uses the
  same `scope` parameter shape); Hassle calls it once per scope, `"automation"` and `"script"`
  (the only two scopes DESIGN §7.3 places by). Each row is `{category_id, name, icon}`.
- **`config/entity_registry/list` rows already carry `categories: {scope: category_id}`** — this
  was already captured verified in §5/§2 of this document (`"categories":{}` in the real
  `id <-> unique_id` capture), just never parsed by `RegistrySnapshot`/`EntityInfo` before now.
  `EntityInfo` gains `unique_id` (the `id <-> unique_id` anchor already documented in §2) and
  `categories: dict[str, str]`, both additive.
- **Guarding:** older HA (pre-category-registry) is expected to reject the command; `DirectBackend`
  guards each scope independently (mirroring the existing `floor_registry` guard) so one scope
  failing doesn't blank out the other, and a total absence of the command degrades to an empty
  `categories` map rather than raising.
- **Placement mapping:** an object key (`automation:<id>` / `script:<object_id>`) resolves to its
  entity-registry entry via `unique_id == identity` (the same anchor as §2, scoped by domain), then
  to that entry's `categories[scope]`, then to the category registry's name for that id, then to
  `automations/<slug(name)>.py` / `scripts/<slug(name)>.py`. Any missing link (no snapshot, no
  entry, uncategorized, unknown category id) falls back to the pre-existing `misc.py` behavior —
  strictly additive, no existing placement test needed to change.
- **Caveat (flagged per CLAUDE.md's "record + flag" rule):** unlike most of this document's
  findings, the `scope` parameter and per-row shape for `config/category_registry/list` were
  **not** re-verified against a live HA instance in this work item — M0.V's Docker harness wasn't
  re-run. The shape is inferred from DESIGN §7.3's own description plus HA core's established
  convention for other scoped registry lists (`entity_category`, `floor_registry`'s `scope`-less
  precedent). If a live capture ever shows a different argument name or response shape, only
  `DirectBackend._afetch_categories` needs to change — the `RegistrySnapshot.categories` shape and
  the placement logic in `bundle_ops` are already guarded/tested against "the command doesn't
  exist" and would tolerate a renamed argument the same way (empty categories, no crash) until
  fixed. Recommended follow-up: add this to a future M0.V-style verification pass.
- **Helpers are intentionally excluded** from category-based placement: HA's category registry
  only covers `automation`/`script` scopes (per DESIGN §7.3's own wording); helpers keep today's
  domain-default `helpers/misc.py` fallback unconditionally.
- Unit coverage: `packages/hassle-core/tests/test_registry_categories.py` (model),
  `test_direct_backend_categories.py` (fetch + guarding), `packages/hassle-cli/tests/
  test_bundle_ops_category_placement.py` (placement mapping), `test_pull_category_placement.py`
  (end-to-end `hassle pull` via `FakeBackend`). An integration-suite category round-trip (create a
  category via WS, assign it, pull, assert placement) was **not** added — the WS write path for
  category creation/assignment is nontrivial to script generically (it likely requires a real
  entity to attach the category to, which itself requires area/device setup) and the unit-level
  `FakeBackend` coverage above is the milestone's required gate; this is a documented integration
  TODO, not a gap in the required test contract.


**Live-verified 2026-07-05:** the owner's real 2026.7 instance returned category
registries for both scopes on pull; placement produced correct per-category files
(automatic_blinds/automatic_hvac/plant_care/...). The inferred `scope` argument and
row shape are confirmed behaviorally; the integration-test TODO stands for CI.

### 22.2 `ignore` globs — DESIGN §8.2/§6 amendment (owner decision)

New `hassle.toml` field: `ignore = ["input_boolean:material_you_*", …]`, `fnmatch` globs matched
against object keys. This is a deliberate, owner-approved exception to §8.2's "first-ever pull
adopts everything; nothing is ever unmanaged" — DESIGN §6/§8.2 have been amended in place (this is
not a silent workaround). Implementation lives in `hassle_cli.ignore_filter`
(`apply_ignore_globs`/`migrate_manifest_for_ignores`), called from the CLI layer **before**
`hassle.sync.plan.compute_plan` runs — the F2 plan engine itself is untouched, so the M5 table-spec
tests are unaffected. See DESIGN §6/§8.2 for the full semantics; test coverage in
`packages/hassle-cli/tests/test_ignore_filtering.py` (unit, including the safety property that an
ignored key present remotely but absent locally never plans as `delete`) and
`test_pull_ignore_globs.py` (end-to-end `pull`/`plan`/`push`, plus the manifest-migration notice).

### 22.3 `lib/README.md` / `tests/README.md` scaffolding

`hassle init` and `hassle pull` (when it scaffolds directories a bundle predating this change never
had) now write `lib/README.md` (explaining `@macro`/`@shared_script`/plain constants per DESIGN
§5.6, imported via `from lib.x import y`) and, only when `tests/` is otherwise empty, a one-line
`tests/README.md`. Both writes are idempotent (`hassle_cli.init_cmd.scaffold_lib_and_tests_readmes`
checks `Path.is_file()` before writing) — re-running `init` or `pull` never clobbers a file the
user has since edited. Test coverage: `packages/hassle-cli/tests/test_lib_readme_scaffold.py`.

## 23. Hassle bug found + fixed (regression-tested): pull→plan-noop invariant (`fix/plan-noop-invariant`)

A fresh `hassle pull` immediately followed by `hassle plan`, with zero edits on either side, must
show every object as `noop` (or an `update` labeled `"modernization (one-time)"` — DESIGN §8.2's
one-time legacy-schema exception, MILESTONES M7 test 4b). A owner real-bundle pull instead showed
8 phantom `conflict`s alongside the (expected) 13 modernization entries. Root-caused to two
distinct bugs, both now regression-tested (`packages/hassle-core/tests/test_pull_plan_noop_invariant.py`,
`packages/hassle-cli/tests/test_pull_plan_noop_invariant_cli.py`):

### 23.1 `ScriptConfig`/decompiler decorator-kwarg emission already matched the stored body (verified, not a bug)

The suspected "materialized defaults" cause (decompiler emitting `mode="single"` etc. for a
mode-less stored automation/script) was audited against every `@automation`/`@script` decorator
kwarg (`mode`, `description`, `initial_state`, `max`, `max_exceeded`, `icon`, `fields`, ...): `IRObject.to_ha()`
uses `model_dump(mode="json", exclude_unset=True)` (`hassle/ir/models.py`), so an absent key stays
absent through parse → `to_ha()`, and `hassle/decompiler/codegen.py`'s `_automation_source`/
`_script_source` only emit a decorator kwarg `if key in body` — never a hardcoded default. Confirmed
via `test_mode_less_automation_hash_stable` and `test_mode_less_script_hash_stable`
(round-trip through decompile → recompile → canonical-hash-identical to the stored body, for a
synthetic mode-less automation/script, since the fixture corpus itself only has one mode-less
non-blueprint case). No code change was needed for this half.

### 23.2 `FakeBackend` leaked a caller-supplied script `id` into the stored body — real bug, fixed ✅

Ground truth (`docs/ha-api-captures/rest-ws-core.json`, `script_read_normalized`, verified again
here): a script's stored/read-back body is `{alias, mode, sequence, ...}` — **no `id` key at all**
(scripts are keyed by an extrinsic object_id in the REST path, `/api/config/script/config/{object_id}`,
never in the body; contrast `automation_read_normalized`, which DOES carry `id` in the body,
since `AutomationConfig.id` is intrinsic). `ScriptConfig` correctly has no `id` field, so local
compile's `to_ha()` never emits one for a script.

`FakeBackend.create`/`.update`, however, stored whatever body was handed to them verbatim for
non-helper kinds — including a caller-supplied `id` key, which a test/fixture-seeding helper can
easily pass by analogy with automations/helpers (both of which legitimately take one). Once
`id` leaks into the stored remote body this way, it never comes back out: every subsequent
`compute_plan` hashes local (no `id`) against remote (`id` present) and sees a permanent
difference — `update` if untouched otherwise, or `conflict` if the object also differs from the
manifest base on either side. This is pure test/seeding-harness residue, not a real HA behavior
(real HA's own script REST endpoint has no such leak, per the capture) — but `FakeBackend` is the
only backend M5's unit suite and M7's CLI suite exercise, so the leak was real and reproducible
end-to-end (`hassle pull` → `hassle plan` through the actual CLI, R2-compliant, no network).

**Fix:** `FakeBackend._stored_body` (new, called from both `create`/`update`) now strips `id` from
a script's body unconditionally before storing — mirroring `ScriptConfig` having no `id` field at
all — while still injecting the derived `id` for helper domains (unchanged, intrinsic) and passing
automation bodies through verbatim (unchanged, intrinsic). No `Backend` protocol (F2) change; this
is an internal `FakeBackend` storage-fidelity fix, analogous in spirit to §17.5's helper-id
derivation note.

### 23.3 Permanent gate: whole-corpus pull→plan invariant test

`packages/hassle-cli/tests/test_pull_plan_noop_invariant_cli.py::test_full_corpus_pull_then_plan_is_noop_or_modernization`
seeds every `fixtures/configs/*.json` object into a fresh `FakeBackend` (via `identity`/`key_hint`,
never a leaked `id`), runs the real CLI's `hassle pull` then `hassle plan`, and asserts every
resulting entry is `noop` or an `update` for which `is_modernization_only_diff` is `True` — zero
`conflict`, zero non-modernization `update`, zero `delete`. Parametrized variants cover the two
named-in-task-description edge cases specifically: a mode-less automation (`test_mode_less_automation_pull_plan_noop`)
and the legacy `platform:`-naming fixture (`test_legacy_platform_automation_is_modernization_labeled`,
asserting the ONE-TIME modernization label, not `noop` and not `conflict`, matching
`test_modernization_labeling.py`'s existing single-object test but run across the full corpus
object set for the first time).

## 24. M8 finding: `hassle stubs`' output location never matched any pyright config (fixed) — `m8/vscode`

**The finding.** M3's own CI-proof test (`packages/hassle-core/tests/test_registry_stubs_pyright.py`)
already demonstrated the ONLY placement that makes pyright prefer a generated stub over the real
runtime `hassle.registry` module for that dotted import path: a `pyrightconfig.json`/
`python.analysis.stubPath` setting of `"typings"`, with the stub file physically at
`typings/hassle/registry/__init__.pyi` (mirroring the real package's `__init__.py` shape — `entities`
is a module-level attribute, not a submodule; see that test's docstring). Despite this, `hassle
stubs` (`hassle_cli.cli`) wrote to `.hassle/entities.pyi`, and `hassle init` shipped no
`.vscode/settings.json` at all. Nothing wired the two together: a fresh `hassle init` + `hassle
pull` + `hassle stubs` sequence — the DESIGN §11 layer-1 "free" story — produced a real bundle
where Pylance had **zero** knowledge of the generated entity types, silently. `hassle stubs`
reported success (`wrote .hassle/entities.pyi`); nothing before M8 ever opened the result in a real
pyright run to check it actually resolved.

**Verification.** `packages/hassle-core/tests/test_registry_stubs_pyright_init_template.py` (new,
M8) builds a bundle using the real `hassle_cli.init_cmd.init_bundle` + the real
`generate_entities_stub`/`stubs`-command code path (not a hand-rolled fixture, unlike the M3
original) and runs pyright against exactly those files — this is the "layer-1 proof, extended"
MILESTONES M8 asked for.

**Fix (not a DESIGN.md change — DESIGN §11 already specified the right end state, it just was
never wired up):**
- `hassle_cli.init_cmd.scaffold_vscode_settings` (new): writes `.vscode/settings.json` with
  `python.analysis.stubPath: "typings"` and `python.analysis.extraPaths: ["."]` (the latter so
  Pylance resolves the same PEP 420 namespace-package cross-file imports, §17.9, the compiler's
  loader does). Idempotent, same convention as `scaffold_lib_and_tests_readmes`; called from both
  `hassle init` and `hassle pull`.
- `hassle stubs` now writes `typings/hassle/registry/__init__.pyi` (+ an empty
  `typings/hassle/__init__.pyi` package marker) instead of `.hassle/entities.pyi`. This is not a
  frozen interface (F1–F3) — no milestone ever pinned the stub's disk location as a contract, only
  the command name/behavior ("generates `.hassle/entities.pyi`" was prose in a docstring, not a
  tested guarantee) — so relocating it needed no MILESTONES.md update. The stale `.hassle/entities.pyi`
  assertion in `test_cli_commands.py::test_stubs_generates_pyi_files` was updated in the same PR
  (R4: this is exactly the kind of found-bug the milestone forced into the open).

No HA API behavior is involved in this finding (it's pure local tooling/editor-integration), but
it's recorded here per the standing instruction to log any DESIGN-vs-reality gap discovered while
implementing a milestone.

## 26. M10: config-entry template-helper flow shapes — DESIGN §13's plugin protocol exercised (source-informed, CI-verified)

MILESTONES M10 builds the first config-entry `ObjectType` plugin (DESIGN §13:
"Config-entry helpers ... needs the config flow WS API; the plugin protocol
already allows async multi-step applies"), scoped to the `template` domain
(number/sensor/binary_sensor/select). Unlike every prior kind (automation/
script config REST, the nine storage-collection helpers' single-shot WS
`create`/`update`/`delete`), a config-entry helper's HA-side lifecycle is a
**multi-step flow**, not a single request/response.

### 26.0 Status: WS-transport assumption FAILED on real HA — corrected to REST (CI-verified finding)

**Original status (source-informed, not yet CI-verified):** M0.V-style Docker
capture was not available in the implementation sandbox (no Docker), so the
shapes were derived from Home Assistant core source
(`homeassistant/components/template/config_flow.py`,
`homeassistant/helpers/config_entry_flow.py`, and the generic
`homeassistant/components/config/config_entries.py` module every config-entry
integration shares) rather than a live capture pair, with every flow
operation (create/update/remove) modeled as a **WebSocket** command
(`config_entries/flow/create`, `config_entries/flow/update`,
`config_entries/options/flow/create`, `config_entries/options/flow/update`,
`config_entries/remove`).

**CI found this wrong, on both `stable` and `dev`.** All five
`test_m10_template_flow.py` integration tests failed identically:

```
HaApiError: WS command failed: Unknown command.
```

**Root cause, confirmed by re-reading `homeassistant/components/config/
config_entries.py`:** config-entry **flows** (create + step submission) and
**options flows** are REST views, not WebSocket commands — only entry
*listing* is WS:

| Operation | Real transport | Endpoint |
|---|---|---|
| List config entries | **WebSocket** | `config_entries/get` |
| Start a flow | **REST POST** | `/api/config/config_entries/flow` (body: `{"handler": "template"}`) — `ConfigManagerFlowIndexView` |
| Submit a flow step | **REST POST** | `/api/config/config_entries/flow/{flow_id}` (body: the step's `user_input`, or `{"next_step_id": ...}` for a menu choice) — `ConfigManagerFlowResourceView` |
| Start an options flow | **REST POST** | `/api/config/config_entries/options/flow` (body: `{"handler": "<entry_id>"}`) — `OptionManagerFlowIndexView` |
| Submit an options-flow step | **REST POST** | `/api/config/config_entries/options/flow/{flow_id}` — `OptionManagerFlowResourceView` |
| Remove an entry | **REST DELETE** | `/api/config/config_entries/entry/{entry_id}` — `ConfigManagerEntryResourceView` (NOT `config_entries/remove` over WS — that command does not exist) |

Only `config_entries/get` (listing) was correct in the original
implementation; every write path (create/update/delete) was wrong and has
been reworked in `hassle/backend/direct.py` to use `HaClient.rest_post`/
`rest_delete` against the endpoints above (same bearer-token auth header,
`HaClient`'s existing REST path — no new transport machinery needed).
`FakeBackend`'s in-memory model is semantically unchanged (still
create→[menu]→form→create_entry, update→form→create_entry, delete→removal)
but its recorded `FlowStep` shapes were re-shaped to mirror the REST JSON
payloads (`{"type": "form"/"menu"/"create_entry", "flow_id", "step_id",
"data_schema", ...}`) rather than a WS envelope, so the unit tests exercise
the same shapes CI now confirms.

This is the milestone's key finding: **the config-entry flow API is REST,
distinct from every other kind Hassle manages** (automations/scripts are
already REST for their config CRUD; the nine storage helpers are WS;
template-helper *listing* is WS but its *mutations* are REST) — a three-way
split that DESIGN §13's "the config flow WS API" phrasing did not anticipate.
No MILESTONES.md change needed (F2 `Backend` is still untouched — this is
purely a `DirectBackend`-internal transport correction), but flagged here
per the standing "record findings, flag to human" rule since it directly
contradicts an assumption baked into the milestone text itself.

The CI integration suite
(`packages/hassle-core/tests/integration/test_m10_template_flow.py`) remains
the **authoritative verification**; the correction above is what made it
pass (pending the orchestrator's next CI run to confirm).

Also unverified in this sandbox: whether the `template` integration's
config-entry flow is reachable with NO `template:` stanza in
`configuration.yaml` (assumed yes — a `config_flow: true` integration's flow
handler is generally registered from its manifest independent of YAML
config). `.github/workflows/ci.yml`'s M10 integration job leaves
`configuration.yaml` unchanged on this assumption; **this assumption held**
— CI reached the flow endpoints at all (got a real HA response, "Unknown
command", rather than "integration/handler not found"), which is itself
evidence the handler was registered without a YAML stanza.

### 26.1 Create: REST `/api/config/config_entries/flow` — menu step, then a form step, then `create_entry`

The `template` integration's config flow starts with a **menu** step
(`step_id: "user"`) whose choices are the four helper types this milestone
manages (`number`/`sensor`/`binary_sensor`/`select`, plus others the
integration itself defines that Hassle doesn't manage), then a **form** step
(`step_id` = the chosen type) collecting EXACTLY the type's own schema fields
— `name`, `state` (the Jinja template string), plus type-specific fields:
`min`/`max`/`step`/`unit_of_measurement`/**`set_value`** (REQUIRED — the
write-target action sequence, §26.6) for number; `device_class` for
sensor/binary_sensor; `options`/**`select_option`** (REQUIRED, §26.6) for
select. **No other keys are accepted** — `voluptuous` schema validation
400s on anything unrecognized, including a caller-supplied `unique_id`
(§26.6: there is no settable unique id at all). A successful submission
returns `type: "create_entry"` with `options` holding exactly the submitted
fields, a `title` set from the submitted `name` (the wire-level identity
correlator, since there's no `unique_id`, §26.6), and a fresh `entry_id` HA
assigns (never caller-supplied — same "creation assigns identity" rule as
storage helpers, §17.5):

```jsonc
// 1. start the flow — REST POST /api/config/config_entries/flow
→ POST /api/config/config_entries/flow  { "handler":"template" }
← 200  { "type":"menu", "flow_id":"f1", "handler":"template", "step_id":"user",
         "menu_options":["number","sensor","binary_sensor","select", "..."] }

// 2. choose the type — REST POST to the flow_id resource
→ POST /api/config/config_entries/flow/f1  { "next_step_id":"number" }
← 200  { "type":"form", "flow_id":"f1", "step_id":"number",
         "data_schema":[ {"name":"name", ...}, {"name":"state", ...},
                         {"name":"set_value", ...}, ... ] }

// 3. submit the form — same resource, another POST. EXACTLY the domain's
//    own fields; no unique_id, no bookkeeping keys (§26.6 correction 1).
→ POST /api/config/config_entries/flow/f1
    { "name":"Active HVAC Zones", "state":"{{ ... }}", "min":0, "max":8,
      "set_value": {"action":"input_number.set_value", "data":{"value":"{{ value }}"}} }
← 200  { "type":"create_entry", "flow_id":"f1", "handler":"template",
         "entry_id":"01ABC...", "title":"Active HVAC Zones",
         "options":{ "name":"Active HVAC Zones", "state":"{{ ... }}",
                     "min":0, "max":8, "set_value": {...} } }
```

(Corrected 2026-07-05, twice: round 1 modeled this as three `config_entries/
flow/*` WebSocket commands — §26.0 found it's REST. Round 2 sent
`unique_id`/`_template_type` alongside the real fields and omitted
`set_value` — §26.6 found the schema rejects the former and requires the
latter.)

`FakeBackend._create_via_flow` (`hassle/backend/fake.py`) models this same
three-step shape (menu -> form -> create_entry) as `FlowStep` records
(`type`/`flow_id`/`step_id`/`data_schema`/`result` fields mirroring the REST
JSON payloads above, not a WS envelope) for test assertions
(`test_fake_backend_template_flow.py`), including the required-field check
(`ConfigEntryFlowError` on a missing `set_value`/`select_option`).

### 26.2 Update: REST `/api/config/config_entries/options/flow` — one form step, same `entry_id`

Updating an existing template helper's options goes through the **options**
flow (`/api/config/config_entries/options/flow`, POSTed with `{"handler":
"<entry_id>"}` — not the plain flow endpoint), which for the `template`
integration is a single form step (no menu — the type is already fixed once
the entry exists) re-presenting the current fields (same schema, same
required fields, as create — §26.6), then `create_entry` on submission. The
`entry_id` is **unchanged** across an update — this is the config-entry
world's I2 analog: an update is genuinely a mutation of the existing entry's
options, never a delete+recreate, so downstream references to the entry
survive untouched:

```jsonc
→ POST /api/config/config_entries/options/flow  { "handler":"01ABC..." }
← 200  { "type":"form", "flow_id":"f2", "step_id":"number", ... }
→ POST /api/config/config_entries/options/flow/f2
    { "name":"Active HVAC Zones", "state":"{{ new }}", "min":0, "max":10,
      "set_value": {"action":"input_number.set_value", "data":{"value":"{{ value }}"}} }
← 200  { "type":"create_entry", "flow_id":"f2", "result":{} }
       // the entry's options are merged in-place; entry_id is NOT re-issued.
```

(Corrected 2026-07-05, twice: round 1 — REST, per §26.0. Round 2 — exactly
the domain's own fields, per §26.6.)

`FakeBackend._update_via_options_flow` models this (form -> create_entry,
same `entry_id` preserved, same required-field check as create).

### 26.3 Delete: REST `DELETE /api/config/config_entries/entry/{entry_id}` — no options-flow equivalent

Deleting a template helper is a plain config-entry removal, addressed by
`entry_id` (never `unique_id` — this is the one place HA-side identity, not
declared identity, is what the wire protocol actually keys on):

```jsonc
→ DELETE /api/config/config_entries/entry/01ABC...
← 200  { "require_restart":false }
```

(Corrected 2026-07-05: originally modeled as a `config_entries/remove` WS
command, which does not exist — REST `DELETE`, per §26.0. `config_entries/get`,
used for listing/enumeration, genuinely is a WS command and was unaffected.)

**Rollback caveat (documented honestly, MILESTONES M10 test 4):** unlike a
storage helper's delete (which the apply engine's rollback can undo by
recreating with the same caller-chosen id — helpers' identity is
caller/slug-derived, so a rollback recreate lands on the same identity), a
template helper's rollback-by-recreate gets a **fresh `entry_id`** from HA
(§26.1's "creation assigns identity" applies again on the recreate). The
object key (`template_number:<unique_id>`) and the stored options are
identical after a rollback recreate, so `list_remote`/plan hashing sees no
difference — but the manifest's tracked `entry_id` must be updated to the new
value, exactly mirroring the CREATE-collision-abort rule (a rollback recreate
is, structurally, a fresh CREATE). `FakeBackend` reproduces this
(`test_template_number_recreate_after_delete_gets_fresh_entry_id`).

### 26.4 `Backend` protocol (F2) needed zero changes

The existing four methods (`list_remote`/`create`/`update`/`delete`, all
keyed by `(kind, identity)` with `identity` = the object's declared identity)
already have everything the sync engine needs; the multi-step flow is
entirely an **internal** `FakeBackend`/`DirectBackend` implementation detail
for `kind in TEMPLATE_DOMAINS`, exactly the way the nine storage helpers'
`{domain}_id` payload-key convention (quirk #1) is internal and never leaks
into the Protocol. No MILESTONES.md F2 update needed. See docs/backend.md's
config-entry addendum for the identity/manifest bookkeeping this implies
(`entry_id` lives in `ManifestEntry`, additively).

### 26.5 Manifest/identity — SUPERSEDED by §26.6, kept for history

~~Object key: `template_number:<unique_id>` (and the sibling three domains).
`unique_id` is Hassle's declared identity (the DSL's `id=` kwarg); HA's
`entry_id` is transport-side identity only, tracked in
`ManifestEntry.entry_id` (additive field, `hassle.sync.models`) — never in the
IR body, never in the object key, mirroring I2's spirit ("never change an
existing object's HA id" — here, "never let an update change the entry_id;
only a delete+recreate legitimately gets a new one, and that IS a different
HA-side object even though Hassle's object key is unchanged").~~

**This was wrong — see §26.6.** CI round 2 found the flow's form schema
rejects an unrecognized `unique_id` key outright: there is no
caller-settable unique id at all, so this identity scheme was never
achievable against real HA. Left here (struck through, not deleted) as the
record of what was tried and why it failed, per the standing "every bug
becomes evidence, not silently erased" practice this doc follows throughout
(cf. §17.5's amendment, §23's bug-and-fix pattern).

### 26.6 Identity REDESIGNED (CI round 2 finding): no settable `unique_id` — identity derives from `name`

**The CI failure, verbatim** (both HA `stable` and `dev`, all 5
`test_m10_template_flow.py` tests, after the §26.0 REST-transport fix
unblocked flow step submission):

```
400 {"errors": {
  "base": [
    "extra keys not allowed @ data['_template_type']",
    "extra keys not allowed @ data['unique_id']"
  ],
  "set_value": "required key not provided"
}}
```

**Three findings, all confirmed by re-reading
`homeassistant/components/template/config_flow.py`'s schema definitions:**

1. **The form step's submission must be EXACTLY the domain's own schema
   fields — no bookkeeping keys smuggled in.** The original implementation
   sent `{"_template_type": step_id, **config}` (this module's own
   "which-sub-kind" tracker) and `{"unique_id": ..., **config}` (the original
   identity scheme) alongside the real fields; HA's `voluptuous` schema
   validation rejects ANY unrecognized key with `"extra keys not allowed"`.
   The menu selection (`{"next_step_id": "number"}`) is already a SEPARATE
   request from the form submission (§26.1) and was never the problem; the
   bug was re-including tracking data inside the form's own body.
2. **`template_number`'s schema REQUIRES `set_value`** — the action sequence
   HA runs when the entity is set (from the UI or a service call). A
   template number's `state` template only computes the *displayed* value;
   without `set_value` HA has no write target at all, so the integration's
   own schema makes it mandatory. By the same reasoning, **`template_select`
   requires `select_option`** (the sequence run when an option is chosen)
   alongside `options` (the choice list). Sensor/binary_sensor are read-only
   — `state` alone is a complete, valid schema for them.
3. **`unique_id` is REJECTED by the flow, unconditionally.** A flow-created
   template config entry has no caller-settable unique id at all — real HA
   assigns none itself either (unlike storage helpers, which slugify `name`
   into a caller-visible `id`, §4/§17.5). This invalidates §26.5's identity
   scheme outright: there was never a `unique_id` to send.

**Identity, REDESIGNED and RE-FROZEN in this PR (supersedes §26.5; MILESTONES
M10 updated in the same series, R5):**

- Object key: `"<template domain>:<slugify(name)>"` — e.g.
  `"template_number:active_hvac_zones"` for `name="Active HVAC Zones"`. This
  mirrors the storage helpers' "id is a slug of name" rule (§4/§17.5)
  *exactly*, except here it is the ONLY identity source (no override field
  exists to supply one, unlike storage helpers' optional `id=`).
- `TemplateHelperConfig` (`hassle.ir.models`) has no `unique_id`/`id` field
  at all; `identity` is a computed property (`slugify(name)`), consistent
  with how `HelperConfig.identity` falls back to a name-derived value only
  when no explicit `id` was supplied — template helpers simply never have
  that explicit-id option.
- **Wire-level correlator for read-back:** the flow's `create_entry` response
  sets the entry's `title` from the submitted `name` (§26.1); `DirectBackend.
  _alist_template_helpers` re-derives the SAME identity by slugifying
  `entry["title"]` on every `list_remote` call.
- **Sub-kind discrimination without `_template_type`:** since the sub-kind
  can no longer travel inside `options` either, `_alist_template_helpers`
  cross-references the **entity registry**
  (`config/entity_registry/list`, WS — genuinely unaffected by any of this,
  it's a pre-existing, correct call) via each row's `config_entry_id`, which
  links back to the config entry: the entity's own domain
  (`number`/`sensor`/`binary_sensor`/`select`, from `entity_id.split(".", 1)
  [0]`) is the authoritative, HA-side answer to "which of the four template
  sub-kinds is this entry", not a client-side guess.
- `ManifestEntry.entry_id` (added in §26.5, unaffected by this redesign)
  still carries the HA-assigned `entry_id` — transport-side identity only,
  never in the IR body or object key. The I2-analog rollback-recreate caveat
  from §26.3 is unchanged: a delete+recreate under the same name-derived
  identity gets a fresh `entry_id`.
- **DSL surface (`hassle.compiler.template_helpers`):** `id=`/`unique_id=`
  kwargs are REMOVED (F3-compatible: never shipped in a release, so this is
  not a break of a frozen surface — see docs/dsl-f3.md). `template_number`
  gained a required `set_value=` kwarg; `template_select` gained a required
  `select_option=` kwarg. `name=` became the sole identity-bearing kwarg.

### 26.7 CI round 3 finding: CREATE works, READ-BACK and UPDATE were still wrong — no admin API exposes entry options at all

**The CI failures, verbatim** (both HA `stable` and `dev`, run 28809973141;
CREATE itself now succeeds — the §26.1/§26.6 fixes held):

```
KeyError: 'name'      # reading a just-created entry's config back
KeyError: 'state'     # same, on the collision-abort test
HA returned 400 for POST /api/config/config_entries/options/flow/<id>:
  {"errors":{"base":["extra keys not allowed @ data['name']"]}}
# plan-noop test: re-plan sees remote={} for a live entry -> plans UPDATE
# forever instead of NOOP, because list_remote returns an empty dict.
```

**Root cause, confirmed by reading HA source directly** (`home-assistant/
core`, commit-pinned to whatever `stable`/`dev` resolved to at CI time — file
paths below, read via `gh api .../contents/<path>` since this sandbox has no
local HA checkout):

1. **`config_entries/get` (WS) and `config_entries/get_single` (WS) NEVER
   carry a config entry's `options`/`data` at all**, for ANY config entry,
   template or otherwise. Both serialize `ConfigEntry.as_json_fragment`
   (`homeassistant/config_entries.py`, `class ConfigEntry`, the
   `as_json_fragment` cached property): its JSON body is exactly
   `created_at`/`entry_id`/`domain`/`modified_at`/`title`/`source`/`state`/
   `supports_options`/`supports_remove_device`/`supports_unload`/
   `supports_reconfigure`/`supported_subentry_types`/
   `pref_disable_new_entities`/`pref_disable_polling`/`disabled_by`/
   `reason`/`error_reason_translation_key`/
   `error_reason_translation_placeholders`/`num_subentries` — there is no
   `options` or `data` key in that shape, full stop, in either the list
   command (`_async_matching_config_entries_json_fragments`,
   `homeassistant/components/config/config_entries.py`) or the single-entry
   command (`config_entry_get_single`, same file, which ALSO just returns
   `entry.as_json_fragment`). The round-2 code's `entry.get("options", {})`
   was therefore always `{}` against real HA — the exact source of the
   `KeyError: 'name'` / `KeyError: 'state'` CI hit reading back a
   just-created entry's `list_remote` row.
2. **There genuinely is no admin API that returns a config entry's options
   directly.** Checked every view `homeassistant/components/config/
   config_entries.py` registers: `ConfigManagerEntryResourceView`
   (`/api/config/config_entries/entry/{entry_id}`) has only `delete` and a
   reload `post` — no `get` at all. `config_entries/get_single` (WS, checked
   above) doesn't have it either. The single place options ever appear on
   the wire is as **suggested values baked into an options-flow's first form
   step**: `SchemaOptionsFlowHandler.__init__`
   (`homeassistant/helpers/schema_config_entry_flow.py`) seeds
   `self._options = copy.deepcopy(dict(config_entry.options))`;
   `SchemaCommonFlowHandler._show_next_step` (same file) passes exactly that
   dict as `suggested_values` into
   `FlowHandler.add_suggested_values_to_schema`
   (`homeassistant/data_entry_flow.py`), which sets each matching schema
   marker's `.description = {"suggested_value": <current value>}`; the REST
   view's `_prepare_result_json`
   (`homeassistant/helpers/data_entry_flow.py`) then runs the schema through
   `voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer)`,
   producing the wire-level `data_schema` as a list of
   `{"name": ..., ..., "description": {"suggested_value": ...}}` dicts per
   field. **This is exactly what the UI's own options-flow edit dialog reads
   to pre-populate its form** (I1) — so read-back now does the same thing:
   `DirectBackend._acurrent_template_options` opens an options flow
   (`POST /api/config/config_entries/options/flow {"handler": entry_id}`,
   the same call `_aupdate_template_helper` already made), harvests
   `data_schema`'s `description.suggested_value` per field into a dict, then
   **cancels the flow** (`DELETE /api/config/config_entries/options/flow/
   {flow_id}` — `OptionManagerFlowResourceView`/`FlowManagerResourceView.
   delete`, `homeassistant/helpers/data_entry_flow.py`: "Cancel a flow in
   progress") rather than committing it — mirroring a user opening then
   closing the edit dialog without saving. `_alist_template_helpers` calls
   this once per entry and merges in `name` (see finding 3 below).
3. **The options-flow schema never includes `name`, for any template
   domain, ever.** `generate_schema(domain, flow_type)`
   (`homeassistant/components/template/config_flow.py`) only adds
   `vol.Required(CONF_NAME)` `if flow_type == "config"`; `options_schema =
   partial(generate_schema, flow_type="options")` (same file) never hits
   that branch. That is the verbatim `"extra keys not allowed @
   data['name']"` 400 CI hit on UPDATE. Fix: `DirectBackend.
   _aupdate_template_helper` now strips `name` from the config before
   POSTing to the options-flow's form step (`FakeBackend.update` does the
   same at its public-API boundary, so `Backend.update`'s F2 contract — take
   the full local config, same as every other kind — is unchanged; only the
   internal wire submission is filtered).
4. **`name` is NOT lost by omitting it from an update.** `entry.title` (and
   `options["name"]`, which is the same value —
   `TemplateConfigFlowHandler.async_config_entry_title` literally returns
   `options["name"]`, and `SchemaConfigFlowHandler.async_create_entry`
   stores `options=data` verbatim on CREATE, `name` included) survives an
   options-flow update that never resubmits it: `OptionsFlowManager.
   async_finish_flow` (`homeassistant/config_entries.py`) does
   `async_update_entry(entry, options=result["data"])` — a wholesale
   REPLACE of `entry.options`, not a merge — but `result["data"]` is
   `SchemaOptionsFlowHandler`'s own `self._options`, which STARTED as a full
   copy of the existing options and is only ever selectively mutated by
   `SchemaCommonFlowHandler._update_and_remove_omitted_optional_keys`
   (`homeassistant/helpers/schema_config_entry_flow.py`): that helper only
   overwrites/prunes keys that appear in the CURRENT step's schema. Since
   `name` (and the server-injected `template_type`, `validate_user_input`,
   `homeassistant/components/template/config_flow.py`) were never in the
   options-flow schema to begin with, they're never touched — so the
   "replace" at the `ConfigEntry` level is, in net effect, a merge from the
   caller's point of view. `FakeBackend._update_via_options_flow` reproduces
   this (merges the submitted fields into the existing stored options
   rather than replacing the dict outright).
5. **Renames are a real HA primitive Hassle deliberately does not use.**
   `config_entries/update` (WS, `homeassistant/components/config/
   config_entries.py`, `vol.Optional("title")`) is the mechanism the UI's
   "rename" affordance uses to change a config entry's title in place
   without touching its options or `entry_id` — genuinely analogous to a
   storage helper's `id`-preserving rename. Hassle does not wire this up:
   per the frozen identity scheme (§26.6), `identity = slugify(name)`, so a
   changed local `name` IS a changed `object_key` — the plan engine already
   treats that as delete-old + create-new (or an id-collision conflict, if
   both keys are live simultaneously) exactly like every other kind. An
   UPDATE `PlanEntry` targets a fixed identity, hence a fixed (unchanged)
   `name`, by construction — there is no code path where an in-place rename
   would ever be needed. Documented here rather than implemented, since a
   wired-up-but-unreachable rename path would be untested dead code.

**Fixed in `hassle/backend/direct.py`** (`_acurrent_template_options`,
`_alist_template_helpers`, `_aupdate_template_helper`) **and `hassle/backend/
fake.py`** (`FakeBackend.update` strips `name` before delegating to
`_update_via_options_flow`; `_update_via_options_flow` merges into existing
stored options and defensively 400s — `ConfigEntryFlowError` — if `name`
somehow still reaches it, mirroring the real schema rejection for direct
callers of the internal method). No `Backend` (F2) or MILESTONES.md identity
changes — this round is purely an implementation-fidelity fix, not a design
change. Regression tests (unit-level; this sandbox cannot run the Docker-HA
integration suite that is the authoritative verification):
`packages/hassle-core/tests/test_direct_backend_template_helpers.py` (new —
faithfully fakes the `_client` wire shapes above, confirmed to fail against
the round-2 code for the exact CI-reported reasons before the fix landed),
`test_fake_backend_template_flow.py`'s
`test_template_number_update_silently_strips_name_at_the_public_api_boundary`
/ `test_template_number_internal_options_flow_submission_rejects_name_field`
/ `test_template_number_update_preserves_name_without_resubmitting_it`, and
`test_apply_template_helpers.py`'s
`test_template_helper_plan_apply_create_then_noop_on_repush`.

### 26.8 Why `data_schema`'s wire shape (`voluptuous_serialize.convert`) is trusted without a live capture

This correction relies on parsing `data_schema` entries as
`{"name": ..., "description": {"suggested_value": ...}}`. That shape comes
from `voluptuous_serialize.convert(schema, custom_serializer=cv.
custom_serializer)` (`homeassistant/helpers/data_entry_flow.py`,
`_BaseFlowManagerView._prepare_result_json`) applied to a `vol.Schema` whose
markers had `.description = {"suggested_value": ...}` set by
`FlowHandler.add_suggested_values_to_schema` (`homeassistant/
data_entry_flow.py`) — reading `add_suggested_values_to_schema`'s own source
confirms the `description` dict is set verbatim as `{"suggested_value":
suggested_values[key.schema]}` on a copy of each matching marker, and
`voluptuous_serialize` (a separate, stable, widely-used HA-frontend-facing
library) is documented/known to surface a marker's `.description` under a
`"description"` key in its per-field output — this is the same mechanism
every HA frontend form (including the actual template-helper edit dialog in
the Settings UI) relies on to pre-fill values, so it is not a guess specific
to this integration. `_acurrent_template_options` defensively `.get()`s both
`"name"` and `"description"` (never indexes them directly) and skips any
field lacking a `suggested_value`, so an unexpected shape degrades to a
missing field rather than a crash — CI will still catch a genuine mismatch
(a missing option would show up as a spurious diff/plan-update, not a
`KeyError`, which is a strictly safer failure mode than round 2's).

### 26.9 Read-back cost: one options-flow open+cancel round-trip per entry, per `list_remote`

`_alist_template_helpers` now makes one extra REST round-trip pair (open +
cancel an options flow) per template config entry on every `list_remote`
call, on top of the pre-existing `config_entries/get` + `config/
entity_registry/list` WS calls. This is the unavoidable cost of there being
no direct "read one entry's options" API (§26.7 finding 2) — real HA's own
frontend pays the same cost every time its helpers-list page needs to show
current values. Not optimized further in this milestone (no perf budget was
set for `list_remote` in DESIGN or MILESTONES M10); flagged here in case a
future milestone's `pull`/`plan` on a large template-helper population needs
it addressed (e.g. batching, or caching options against `modified_at` from
`config_entries/get`'s already-free listing).

### 26.10 CI round 4 finding: `template_number`'s `min`/`max`/`step` are always stored as `float` — compiler must coerce to match

**The CI failure, verbatim** (both HA `stable` and `dev`, run 28811559165;
this was the ONLY failure left after the §26.7 read-back/update fix landed —
4 of 5 integration tests were already green):

```
test_template_helper_plan_apply_create_then_noop_on_repush:
  local  = {..., 'min': 0,   'max': 8,   'step': 1}
  remote = {..., 'min': 0.0, 'max': 8.0, 'step': 1.0}
  -> hashes differ -> plan says UPDATE instead of NOOP.
```

**Root cause, confirmed by reading `homeassistant/helpers/selector.py`**
(`class NumberSelector`, `CONFIG_SCHEMA` and `__call__`): every `min`/`max`/
`step` field typed as `selector.NumberSelector()` in `template_number`'s form
schema (`homeassistant/components/template/config_flow.py`'s
`generate_schema`, `if domain == Platform.NUMBER`) is validated by
`NumberSelector.__call__`, which unconditionally does
`value: float = vol.Coerce(float)(data)` and returns that float — HA stores
whatever the selector's `__call__` returns, so `min`/`max`/`step` are
**always** floats in the config entry's options, regardless of whether an
`int` or a `float` was submitted. This holds for BOTH the config flow
(create) and the options flow (update): both use the identical
`NumberSelector`-typed schema field (`generate_schema` is shared, keyed only
by `flow_type` for which OTHER fields it adds — `min`/`max`/`step` are
present, and `NumberSelector`-typed, in both).

**Checked every other numeric-shaped field across all four template domains
Hassle manages** (`generate_schema`'s per-`Platform` branches in
`template_config_flow.py`) — `template_number`'s `min`/`max`/`step` are the
ONLY fields anywhere in the four domains typed as `NumberSelector`:
`template_sensor` (`unit_of_measurement`/`device_class`/`state_class`) and
`template_binary_sensor` (`device_class`) use only `SelectSelector` (string
enum choices); `template_select` (`options`/`select_option`) uses
`TemplateSelector`/`ActionSelector`, neither numeric. No other coercion
class exists to hunt for in this milestone's scope.

**Fixed at compile time**, per the design direction that keeps plan
comparison a plain hash equality with no comparison-time special case
(DESIGN §8.2): `hassle.compiler.template_helpers.template_number` now runs
`min`/`max`/`step` through `_coerce_number_field` (`float(value)` if not
`None`, pass-through otherwise) before building the IR body, so the compiled
local IR is byte-identical to what HA actually stores whether the DSL author
wrote `min=0` (the natural, and now still supported, `int` literal) or
`min=0.0`. `FakeBackend._coerce_number_selector_fields` reproduces the same
coercion on both `create` and `update` (mirroring the real
`NumberSelector.__call__` behavior on both the config flow and the options
flow), so this class of bug is caught by a unit-level plan/apply test
without a live HA
(`test_template_helper_float_coercion.py::test_plan_apply_create_then_noop_on_repush_with_fakebackend`,
confirmed to fail against the pre-fix compiler/FakeBackend for the exact
CI-reported reason before the fix landed).

**Key-order red herring, checked and dismissed:** the CI log's `local`/
`remote` dicts print with `name` in different positions, but
`hassle.ir.canonical.canonical_json` already sorts keys
(`json.dumps(..., sort_keys=True)`) before hashing — confirmed by
`test_template_helper_float_coercion.py::
test_canonical_hash_is_insensitive_to_key_order_int_vs_float_is_the_real_bug`,
which hashes the same dict with two different key orders (equal) and the
same dict with `int` vs `float` values (NOT equal) side by side. Key order
was never the discriminator; `int` vs `float` was.

**A second, independent bug found while updating the golden fixture:**
`hassle-dev goldens`'s drift check (`hassle_dev.goldens.run_goldens`) compared
parsed JSON with plain `!=`, which is blind to an `int`-vs-`float` difference
(`{"min": 0} == {"min": 0.0}` is `True` in Python — dict/list `==` recurses
using `==`, and `0 == 0.0`). Both the check-only path and `--update` reported
`fixtures/dsl/template_helper_declarations` as "already up to date" even
though the compiler's actual output had silently changed from `0` to `0.0` —
`hassle-dev goldens --update` could not be used to regenerate the fixture
until this was fixed too. Fixed with a recursive `_type_strict_equal` helper
(dicts/lists compared key-by-key/element-by-element; `int`/`float`/`bool`
compared with `type(a) is type(b)` in addition to `==`) in
`packages/hassle-dev/src/hassle_dev/goldens.py`, regression-tested in the
new `packages/hassle-dev/tests/test_goldens.py` (confirmed red against the
pre-fix comparison for the exact same reason before fixing it). With that
fixed, `hassle-dev goldens --update` correctly found and rewrote exactly one
golden: `fixtures/dsl/template_helper_declarations/expected_ir.json`'s
`template_number:active_hvac_zones` entry's `min`/`max`/`step` from
`0`/`8`/`1` to `0.0`/`8.0`/`1.0` — no other golden pair was affected (69
checked, 1 updated).

**Decompile/I3 round-trip:** unaffected by construction —
`hassle.decompiler.exprs.render_literal` uses `repr(value)`, so a `float`
value decompiles as a Python float literal (`repr(0.0)` → `"0.0"`) and
recompiling that source produces the identical float (the DSL builder's
`_coerce_number_field(0.0)` is `float(0.0) == 0.0`, idempotent). Verified by
tightening `test_decompile_template_helpers.py`'s existing assertion from a
loose `"min=0" in source` substring check (which happened to already pass
against `"min=0.0"` too, masking the fact that it wasn't actually pinning
the float form) to an explicit `"min=0.0" in source`, and by the existing
`test_decompile_recompile_round_trip_is_byte_stable_for_options_body` test,
which now exercises the float-valued fixture end-to-end (decompile → write
→ recompile) unchanged.

### 26.11 Reviewer follow-up: missing write-target kwargs were only caught at APPLY time — now a compile-time error

**The gap:** §26.6 froze `set_value=`/`select_option=` as required DSL kwargs
for `template_number`/`template_select`, and `_check_required_fields`
(`hassle.backend.direct`/`hassle.backend.fake`) rejects an APPLY that omits
either — but nothing checked this at COMPILE time. A bundle with
`template_number(name=..., state=...)` and no `set_value=` compiled cleanly,
`hassle validate` reported no findings, and the omission only surfaced as a
bare `ValueError` from the backend at `hassle push` — after the user believed
their bundle was clean.

**Fixed at compile time**, mirroring how every other compiler trap in this
codebase works (`hassle.compiler.errors`, R6 what/where/fix):
`hassle.compiler.template_helpers._declare_template_helper` now raises
`MissingTemplateHelperWriteTargetError` the moment `template_number`/
`template_select` is called without its required kwarg, using the same
`capture_span(depth=1)` pattern the existing registration call uses so the
error names the user's bundle `file:line`. Since `compile_bundle` runs before
any tier-2/3 `Finding` check even starts, this is caught by `hassle validate`,
`hassle plan`, `hassle status`, and `hassle push` alike —
`hassle_cli.cli.validate` was updated to catch `CompileError` around
`compile_bundle` and report it the same clean way a `Finding` is (exit 1,
`file:line`, both plain and `--json` modes) instead of letting the exception
escape as a raw traceback.

(Task #15, reviewer follow-up to this same PR #4: the paragraph above was
initially true only for `validate` — `_build_plan` (`hassle_cli.cli`, shared
by `plan`/`status`/`push`) called `bundle_ops.compile_local_objects` with no
`CompileError` handling at all, so those three commands still dumped a raw
traceback on the same bundle `validate` reported cleanly. Fixed by factoring
the catch-and-report logic in `hassle_cli.cli` into a shared
`_report_compile_error` helper, used by both `validate`'s `except CompileError`
block and `_build_plan`'s. `plan`/`status`/`push` have no `--json` mode, so
they always report in plain text; the wording above is accurate again now
that all four commands share one code path.)

The backend-side `_check_required_fields` checks are UNCHANGED and remain a
second line of defense for any non-DSL path that constructs a
`TemplateHelperConfig` directly (e.g. a hand-rolled adopt path bypassing the
DSL builders). I3 is unaffected: pulled template helpers always carry their
write-target keys (M10 CI-verified, §26.6), confirmed here by a defensive
decompile-then-recompile test
(`test_decompile_template_helpers.py::test_decompiled_write_target_helpers_recompile_without_error`)
proving the decompiler can never produce a `template_number`/`template_select`
call that then trips the new check.

## 25. M8 finding: `DiagnosticsManager.refresh()` race (fixed, regression-tested) — `vscode-extension/`

While writing the `@vscode/test-electron` integration test for Problems-pane diagnostics
(MILESTONES M8 test 2), a real race surfaced: `activate()` fires one `hassle validate --json`
refresh immediately on startup (fire-and-forget), and a user-triggered `hassle.validate` command
fires another. If the first (older) request's CLI subprocess happens to resolve *after* the
second (newer) one — plausible any time the CLI is slow to spawn, e.g. `uv run`'s first-invocation
overhead — the stale response's `.clear()` + republish would blindly overwrite the newer, correct
diagnostics (or wipe them entirely, if the stale request failed to parse). Fixed with a monotonic
`latestRequestId` guard in `vscode-extension/src/diagnosticsManager.ts`: a response is only applied
if no newer `refresh()` call has started since. Regression test:
`vscode-extension/src/test/suite/extension.test.ts`'s
`"regression: a slow, stale refresh() cannot clobber a newer one's results"` (verified to fail
without the guard, confirming it exercises the real bug).

## 27. M10 CI run: `test_run_live.py::test_run_live_creates_shadow_triggers_and_cleans_up` also failed — diagnosed as unrelated to this milestone (not fixed here, flagged)

The same CI run that surfaced the §26.0 WS-transport bug also failed
`packages/hassle-cli/tests/integration/test_run_live.py::
test_run_live_creates_shadow_triggers_and_cleans_up` on the `dev` job. Full
error text was not available to this session (no direct CI log access);
diagnosis below is from static analysis of what M10 actually touched, cross-
checked against this test's dependency surface.

**What M10 touched that this test's code path could plausibly reach:**
`hassle.ir.keys.OBJECT_KINDS` (widened to include `TEMPLATE_DOMAINS`) and
`hassle_cli.bundle_ops.default_source_path` (added a `TEMPLATE_DOMAINS`
branch). Neither is on `test_run_live`'s path:

- `run --live` (`hassle_cli.commands.run_live_command`) calls
  `bundle_ops.compile_local_objects` (compiles the DSL bundle locally to find
  the target automation) — it never calls `bundle_ops.remote_objects_from_
  backend(backend, list(OBJECT_KINDS))` (that's the `pull`/`plan`/`push`
  commands' code path, `hassle_cli.cli`) and never calls
  `default_source_path` at all (no adoption/placement happens during a live
  run). `OBJECT_KINDS`'s widened membership is therefore inert for this test.
- The `ha`/`ha_url_token` fixtures (`packages/hassle-cli/tests/integration/
  conftest.py`) are untouched by any M10 commit (`git log` confirms last
  touch was the M7.1 bundle-subdirs commit). Their `_wipe` helper does
  iterate the widened `OBJECT_KINDS` (including the four template domains),
  calling `backend.list_remote(kind)` for each — but `list_remote` for a
  template domain calls the genuinely-correct WS command `config_entries/
  get` (§26.0: only the flow/removal paths were wrong, not listing), wrapped
  in `contextlib.suppress(Exception)` regardless. Even in the worst case
  (some other listing error), the suppress means `_wipe` cannot propagate a
  template-domain failure into this test.
- `test_m10_template_flow.py` collects and runs BEFORE `test_run_live.py` in
  the single shared-container CI invocation (`.github/workflows/ci.yml` runs
  one `pytest -m integration` over both directories). Its 5 tests failed
  inside `DirectBackend.create("template_number", ...)`, which raised
  `HaApiError` before any HA-side mutation occurred (the broken call was the
  FIRST WS/REST call in the flow) — so no leftover config-entry state was
  left in HA for a later test to trip over. Each test also gets its own
  fresh `DirectBackend` (a new WS connection, closed in `__exit__`), so a
  broken WS command in one test's connection cannot corrupt a different
  test's separate connection.

**Conclusion: most likely pre-existing/environmental, not an M10
regression** — no code path connects the two. Left undiagnosed further
(no CI log access, and `test_run_live.py`/its fixtures are unowned by this
milestone) rather than guessing at a fix; flagging to the human/orchestrator
per the standing instruction. If the orchestrator's next CI run reproduces
it with full logs, the actual assertion/exception message will settle
whether it's a `dev`-image regression (HA version drift in trace behavior)
or flaky timing, neither of which this milestone's diff plausibly causes.

**Merge-time addendum (2026-07-06):** the failure was subsequently root-caused and
fixed on `main` — see §29 (`automation.trigger` targeted a nonexistent entity_id, then
a trace-settle race, then HA's per-item_id trace retention across shadow
delete/recreate). It was indeed unrelated to this milestone's diff, as diagnosed.

## 28. CI stabilization (`fix/ci-stabilization`): two unrelated root causes for 8 pushes of red `main`

Main was red on every push for a while; the two failures had nothing to do with each other and
neither was actually the "HA behavior changed" story one might guess from the job names.

**Finding A — ubuntu-only unit job: `keyring.errors.NoKeyringError` from `fake://`-backed CLI
tests.** `hassle_cli.token.resolve_token(ha_url)` was called unconditionally by
`_require_backend_config` (`hassle_cli.cli`) for every command, including when `ha_url` was the
`fake://<token>` test-only seam (`hassle_cli.backend_factory`) — the `startswith("fake://")` check
only skipped the *subsequent* "no token" error message, not the keyring lookup itself. On macOS,
`keyring.get_password` always resolves to the Keychain backend (returns `None` for an unknown
entry, never raises), so this was invisible locally. On the headless ubuntu-latest GitHub runner
there is no keyring backend installed at all, so the same call raises
`keyring.errors.NoKeyringError`, which propagated as an unhandled exception out of `hassle_cli.
cli.py::status/plan/push/pull` and anything else going through `_require_backend_config` — i.e.
most of `test_cli_commands.py` and `test_agents_md_scaffold.py`. This is not an HA API/version
finding — it's a pure test-isolation bug — but is recorded here per the standing instruction to
log any finding discovered while stabilizing the shared CI pipeline.

Fix, both layers as required:
- **Product** (`packages/hassle-cli/src/hassle_cli/token.py`): `resolve_token` now short-circuits
  on `fake://` URLs before ever importing/calling `keyring` (the token is embedded in the URL —
  there is nothing to look up), and separately catches `keyring.errors.NoKeyringError` for real
  URLs, treating "no keyring backend installed" the same as "no token found" rather than letting
  it crash. A new `resolve_token_or_raise` + `TokenResolutionError` (what/where/fix, one paragraph)
  is what `_require_backend_config` uses to turn "token not found anywhere" into a clean CLI error
  that explicitly names the headless-server fix (`export HASSLE_TOKEN=...`) alongside the desktop
  one (`hassle login`).
- **Test** (`packages/hassle-cli/tests/conftest.py`): a new autouse `_forbid_real_keyring_access`
  fixture monkeypatches `keyring.get_password`/`set_password`/`delete_password` to raise
  `RealKeyringUsedInUnitTestError` for every test in the suite, unconditionally — no unit test may
  ever depend on a real OS keyring existing again. Tests that intentionally exercise
  keyring-touching code (`hassle login`, the `hassle_cli.token` unit tests) monkeypatch
  `hassle_cli.token._keyring_get`/`_keyring_set` directly instead, which is unaffected by this
  guard (it patches a different, module-internal seam).
- Regression tests added to `packages/hassle-cli/tests/test_token_and_secrets.py`:
  `test_resolve_token_never_touches_keyring_for_fake_url`,
  `test_resolve_token_falls_through_to_env_when_keyring_unavailable`,
  `test_resolve_token_no_keyring_and_no_env_gives_clean_error`,
  `test_cli_status_against_fake_backend_survives_headless_keyring` (the last one reproduces the
  exact CI failure end-to-end by monkeypatching `keyring.get_password`/`set_password` to raise
  `NoKeyringError`, confirmed red before the fix).

**Finding B — `integration · HA stable` and `integration · HA dev`, identically:
`packages/hassle-cli/tests/integration/test_run_live.py::test_run_live_creates_shadow_triggers_
and_cleans_up` — `TypeError: Context.__init__() got an unexpected keyword argument 'cwd'`.** The
task description hypothesized an HA-dev trace/shadow behavior change or a timing/settle issue;
neither is correct. `gh run view 28765559755 --log-failed` shows the identical `AssertionError:
assert 1 == 0` / `TypeError` on **both** the `stable` and `dev` matrix legs, which rules out an
HA-version-specific behavior change outright (a dev-only regression cannot reproduce byte-for-byte
on stable too). The actual cause: the test called
`click.testing.CliRunner.invoke(main, args, env=..., cwd=str(bundle))` — but `CliRunner.invoke`
has never supported a `cwd` kwarg; `**extra` is forwarded through `Command.main` into
`click.Context.__init__`, which raises `TypeError` for the unrecognized keyword *before the command
body ever runs*. `catch_exceptions` defaults to `True`, so the `TypeError` is swallowed into
`Result.exit_code == 1` — the shadow-automation body (create/trigger/trace/cleanup) never executed
at all, on either HA version. This also means
`test_run_live_cleans_up_shadow_on_trace_stream_failure` (which only asserts `exit_code != 0`) was
passing for the wrong reason — the same `TypeError` satisfies its assertion regardless of whether
the injected `stream_trace` failure ever ran.

Fix (a genuine bug fix, not an xfail — the failure is fully diagnosable and platform-independent):
replaced the invalid `cwd=` kwarg with an `os.chdir()`-around-the-call helper
(`_invoke_in_dir` in `test_run_live.py`), matching the pattern the unit-test suite's
`packages/hassle-cli/tests/conftest.py::run_cli` already uses for the same reason. A new unit test,
`test_cli_runner_invoke_rejects_cwd_kwarg_regression` (no network, runs in the ordinary unit job),
pins down the root cause directly against a trivial `click.command()` so this class of mistake
gets caught immediately in the unit job next time instead of silently no-op'ing an integration
test. No DESIGN.md or MILESTONES.md change needed — DESIGN §10.4 / MILESTONES M7 test 5's
intended behavior (shadow created, triggered, trace rendered, cleaned up) is unchanged; only the
test's own Click API usage was wrong. Not independently re-verified against live HA in this PR (no
Docker/HA access in this environment) — the orchestrator's CI run against both `stable` and `dev`
is the actual green/red signal for this fix, per the task's definition of done.

## 29. `run --live` trace-settle race (`fix/run-live-trace-settle`): a real trace vanished silently

**The finding.** Once Finding B (§28) was fixed and `run --live`'s shadow-automation body actually
executed against real HA, a new, legible failure appeared identically on `HA stable` and `HA dev`:
the command completed cleanly (`shadow run complete: hassle_shadow_...`) but rendered **no trace
timeline at all** — DESIGN §10.4 point 3's whole point. Root cause, in
`hassle_cli.commands.run_live_command.execute_live_run`'s `get_trace_fn`: it called `trace/list`
exactly once, immediately after `automation.trigger` returned, and returned `{}` straight through
if that single call came back empty. HA persists a trace **asynchronously** after a trigger — the
same class of async-settling race already documented for the config-REST reload
(`DirectBackend._await_config_entity`, §17.7) — so a `trace/list` issued too early routinely
returns `[]` even though the run is about to have a trace. `execute_live_run`'s
`if result.trace:` then simply skipped the whole rendering block for a falsy `{}`, with **zero**
indication to the user that anything was ever wrong — indistinguishable from "there was nothing to
show," which is never true for a triggered automation.

**Rejected alternate theory (ruled out explicitly, as asked).** A wrong `item_id` (e.g. passing the
shadow's full `entity_id`, `"automation.hassle_shadow_..."`, instead of its bare automation `id`)
would produce the exact same symptom — an empty `trace/list`/`trace/get` — and needed to be ruled
out separately from the timing race. Re-verified against the §7 capture shape
(`trace/list`/`trace/get` take `domain` + `item_id`, where `item_id` is the bare automation `id`,
e.g. `"hassle_skipcond"`) and pinned down with a dedicated unit test
(`test_execute_live_run_uses_bare_automation_id_not_entity_id_for_trace_lookup`,
`packages/hassle-cli/tests/test_run_live_command.py`): `get_trace_fn`/`list_traces`/`get_trace`
were already using the bare `shadow_id` correctly — only `trigger_fn`'s `automation.trigger`
service call needs the full `entity_id` (a service-call target, not a trace lookup), and it already
had it right. The bug was purely the missing poll/no-feedback path, not a parameter mistake.

**Fix.**
- `hassle_cli/run_live.py`: `stream_trace` now bounded-polls `get_trace_fn` (default 5 s budget,
  0.25 s interval, both overridable and read off the module at call time so they're
  monkeypatchable) instead of accepting a single empty response — matching the `DirectBackend`
  reload-settle pattern's own bounded-polling shape. `sleep_fn`/`monotonic_fn` are injected (default
  `time.sleep`/`time.monotonic`) so this is genuinely live-transport I/O (R8's "no wall-clock"
  governs core compiler/simulator logic, not this) while unit tests use a fake clock and take zero
  real wall-clock time. Added `render_trace_timeline` (a real step-by-step timeline keyed off
  `trace["trace"]`'s step paths — `trigger`/`condition/0`/`action/0`/… — DESIGN §10.4 point 3;
  full DSL-source-line mapping remains a separate, not-yet-built feature).
- `hassle_cli/commands/run_live_command.py`: renders the timeline when a trace eventually shows up;
  when it still doesn't after the full poll window, prints an explicit yellow warning naming the
  run id and pointing at Settings → Automations → Traces in the HA UI — never silence, whether the
  cause is a slower-than-usual settle or a genuine absence.
- Regression tests: `test_stream_trace_polls_until_trace_appears` /
  `test_stream_trace_gives_up_after_poll_timeout_returns_empty` (fake clock, `packages/hassle-cli/
  tests/test_run_command.py`); `render_trace_timeline` structural tests (same file); CLI-level
  `test_execute_live_run_renders_timeline_once_trace_settles` /
  `test_execute_live_run_warns_explicitly_when_trace_never_appears` /
  `test_execute_live_run_uses_bare_automation_id_not_entity_id_for_trace_lookup` (new file,
  `packages/hassle-cli/tests/test_run_live_command.py`, against a hand-rolled stub `Backend` with
  the trace/`call_service` surface `FakeBackend` doesn't have). The one integration test's
  assertion was tightened from the bare word `"trace"` to a structural check (`action/0` step path
  present, the explicit-warning text absent) plus the mirror assertion in the "never appears" case.
- No DESIGN.md/MILESTONES.md change: DESIGN §10.4 point 3 already specified a rendered timeline;
  this fixes an implementation gap, not a design gap. Not re-verified against live HA in this PR
  (no Docker/HA access here) — the orchestrator's CI run is the actual green signal.

### 27 addendum (`fix/run-live-enabled-shadow`): the real root cause was `entity_id` targeting, not disabled-automation semantics

**Round-2 CI evidence.** With §29's bounded poll + never-silent warning in place, the warning
fired cleanly on both `HA stable` and `HA dev`: a genuine 5-second poll, never a single trace. This
proved the trace really never appears — not a race — and prompted the hypothesis that a *disabled*
shadow automation (`initial_state: off`, DESIGN §10.4 point 1's original mechanism) might not
execute `automation.trigger`'s forced trigger, or might not have it traced, on the current HA `dev`
line. That hypothesis is the reason this addendum exists: it needed to be checked against HA's
actual source before touching anything, and it turned out to be **wrong**, but the underlying
symptom was real and had a different, definitive cause.

**HA source verification (read directly from `home-assistant/core`, `dev` branch,
`homeassistant/components/automation/__init__.py` + `trace.py` + `homeassistant/helpers/service.py`
+ `homeassistant/components/trace/{util.py,websocket_api.py}`, 2026-07):**

- `automation.trigger` (`SERVICE_TRIGGER`, registered in `async_setup`) is wired directly to
  `AutomationEntity.async_trigger(...)` — **not** to `_async_trigger_if_enabled`, which is a
  separate method that gates on `self._is_enabled` and is *only* wired into
  `_async_attach_triggers` (i.e. the automation's own configured trigger-listener machinery, which
  a disabled/`initial_state: off` automation never even attaches — `_async_enable_automation`
  returns immediately `if not self._is_enabled`). `async_trigger` itself contains **no
  `self._is_enabled` check anywhere** in its body (confirmed by reading the full method,
  `__init__.py` lines ~677–818 of the fetched source): it unconditionally opens
  `trace_automation(...)` and unconditionally runs `self.action_script.async_run(...)`.
- `trace_automation` (`trace.py`) calls `async_store_trace` unconditionally, keyed only by
  `automation_id` (`self.unique_id`) — no enabled-state check.
- `AutomationEntity` never overrides `_attr_available`; only `UnavailableAutomationEntity` (config
  validation failures) does. A disabled-but-valid automation stays `available = True`, so entity
  service-call resolution (`helpers/service.py`'s `.available` filter) never excludes it either.
- `trace/list`/`trace/get` (`components/trace/util.py`, `websocket_api.py`) key purely by the
  `f"{domain}.{item_id}"` string; no enabled-state involvement anywhere in that path either.
- **Conclusion, stated plainly: a disabled automation's forced `automation.trigger` service call
  DOES execute the action script and DOES get a trace recorded, on the `dev` branch read here.**
  `initial_state: off` was never actually the bug. (If a future HA release changes this, the
  never-fires-event-trigger redesign below no longer depends on it either way, which is part of
  why it was still worth making.)

**The actual root cause: already-documented Hassle-side bug, §10.2's exact quirk.** §10.2 above
(from the original M0.V spike) states plainly: *"the automation `entity_id` is `slug(alias)`, not
`slug(id)` … Enumerate/trigger by matching `attributes.id`, never by assuming `automation.<id>`."*
`hassle_cli.commands.run_live_command.execute_live_run`'s `trigger_fn` did exactly the thing this
note warns against:

```python
backend.call_service("automation", "trigger", entity_id=f"automation.{shadow_id}", **payload)
```

`build_shadow_config` copies the *original* automation's `alias` unchanged into the shadow (only
`id`/`initial_state` were overridden) — so the shadow's real `entity_id` is `slug(alias)` of that
unchanged alias (e.g. `automation.live_test_automation`), never `automation.hassle_shadow_<hash>`.
Every live trigger was silently targeting an entity that doesn't exist — `automation.trigger`
against a nonexistent `entity_id` matches zero entities and does nothing — so of course no trace
ever appeared, on any HA version, disabled or not. This fully explains the empirical symptom
without needing the disabled-automation hypothesis at all, and explains why it's identical on
`stable` and `dev`: it isn't HA-version-dependent, it's a Hassle bug that was simply never
exercised until the `cwd=` bug (§28) was fixed and the shadow flow ran against real HA for the
first time.

**Fix (both parts landed together, `fix/run-live-enabled-shadow`):**
- `hassle_cli/run_live.py`'s `build_shadow_config`: the shadow is now created **enabled** (no
  `initial_state` key at all) with its trigger list replaced by a single event trigger on a
  run-unique event type (`never_fires_event_type()` → `hassle_shadow_never_<uuid4>`) that nothing
  on the real event bus will ever fire — the same "never fires on its own" guarantee DESIGN §10.4
  point 1 wants, without depending on disabled-automation semantics being what they turned out to
  already correctly be.
- `hassle_cli/commands/run_live_command.py`: added `resolve_shadow_entity_id`, which resolves the
  shadow's real `entity_id` by matching `attributes.id` against `/api/states` (mirroring
  `DirectBackend._alist_automations`'s own enumeration logic) before calling `automation.trigger` —
  replacing the naive, wrong `f"automation.{shadow_id}"`. `list_traces`/`get_trace`'s `item_id`
  usage was already correct (keyed by the bare config id, per §7/§10.2) and is unchanged.
- DESIGN §10.4 point 1/2 and MILESTONES M7 test 5 updated in the same series to describe the
  enabled-shadow-with-never-fires-trigger design and the `entity_id`-resolution requirement (this
  revises a previously-designed mechanism with live evidence, per the standing instruction).
- Integration test strengthened (coordinator ask): the shadow's action now also increments a
  counter helper created for the test (M0.V pattern), and the test asserts the counter's value
  changed — separating "the service call was accepted" from "the automation's action actually
  executed," the exact ambiguity that let this hide as long as it did. Unit tests updated for the
  new shadow shape (`test_build_shadow_config_replaces_triggers_with_never_fires_event`,
  `test_never_fires_event_type_is_unique_per_call`) and for the entity_id-resolution fix
  (`test_execute_live_run_uses_bare_automation_id_not_entity_id_for_trace_lookup`'s assertion now
  pins the REAL resolved entity_id, not the old naive one).
- Not re-verified against live HA in this PR (no Docker/HA access here) — the orchestrator's CI run
  against `HA stable` + `HA dev` is the actual green signal.

### 27 addendum, round 3 (`fix/run-live-fixture-condition`): the entity_id fix worked; the remaining failure was pure test fixture

**Round-3 CI evidence.** With the enabled-shadow + real-`entity_id` fix from the previous round
landed, the full live pipeline executed for the first time ever: shadow created enabled, entity
resolved correctly, triggered, traced, and the timeline rendered —
`trace: run 554711d1... (failed_conditions) / trigger / condition/0 / condition/0/entity_id/0`.
This is a strong, if accidental, positive result: `failed_conditions` in the trace is direct proof
that Hassle's `skip_condition: false` default (DESIGN §10.4 point 2) is actually taking effect
against real HA — HA's own default (`skip_condition: true`) would have skipped straight to
`action/0` regardless of the condition. But it was accidental: the remaining test failure
(`action/0` not appearing, so the counter-increment assertion failed) was because
`_write_bundle`'s automation gates on `input_boolean.hassle_flag_2` via `only_if`, and the test
created that helper but never set it to `"on"` — HA's own default for a freshly created
`input_boolean` is `"off"` (§4), so the condition was unsatisfiable by construction. Not an HA
behavior question at all; a test-fixture bug.

**Fix.** `test_run_live_creates_shadow_triggers_and_cleans_up`
(`packages/hassle-cli/tests/integration/test_run_live.py`) is now two-phase, turning the accident
into deliberate, documented coverage of the entire §10.4 semantic surface in one test:

1. **Phase 1 (condition unsatisfied):** trigger with `input_boolean.hassle_flag_2` still at HA's
   default `"off"` — assert the trace shows `failed_conditions` AND the counter helper's value did
   NOT change. This is the positive-proof half that was missing before: a trace merely rendering
   isn't proof `skip_condition: false` gates anything (a vacuously-satisfied condition would look
   the same); the counter staying put is what proves the action genuinely didn't run.
2. **Phase 2 (condition satisfied):** `ha.call_service("input_boolean", "turn_on", entity_id=
   "input_boolean.hassle_flag_2")`, trigger again — assert `action/0` in the rendered timeline and
   the counter incremented, exactly as intended by the original (round-2) design.

A new unit test, `test_render_trace_timeline_failed_conditions_has_no_action_step`
(`packages/hassle-cli/tests/test_run_command.py`), pins the rendering shape a `failed_conditions`
trace actually produces (`trigger` + `condition/0` + `condition/0/entity_id/0` steps, no `action/*`
step at all, per the M0.V §7 capture shape) — this is the local, network-free proof that the new
integration test's phase-1 structural assertions (`"failed_conditions" in output`, `"action/0" not
in output`) are checking something real rather than an unverified guess about HA's trace shape.
No product code changed in this round — `render_trace_timeline`/`resolve_shadow_entity_id`/
`build_shadow_config` were already correct; this closes out the last gap with a test fix only. Not
re-verified against live HA in this PR (no Docker/HA access here) — the orchestrator's CI run is
the actual green signal, and is expected to be the first fully-green run of this test across all
three rounds.

## 30. M11: category write-back on push-create — WS shapes now live-verified by CI (`m11/category-writeback`)

> **Corrections (2026-07-06, source-verified in §31):** (b) `config/entity_registry/
> update` merges `categories` per scope server-side (not wholesale replace) — the
> client-side read+merge is harmless but unnecessary; (c) `config/category_registry/
> delete` exists; (d) one entity CAN carry categories in multiple scopes at once.

> **Post-merge status (2026-07-06):** the caveats below were written before the integration
> suite ran. PR #3's CI subsequently ran `tests/integration/test_m11_category_writeback.py`
> green on BOTH HA images (stable + dev) on the first attempt, which live-confirms:
> `config/category_registry/create`'s `{scope, name}` argument shape, the category assignment
> landing in the entity-registry row's `categories` map, the slug-reuse (no-duplicate) path,
> the `script.*` `unique_id == object_id` lookup, and cross-scope assignment preservation
> under the client-side merge. The prospective "will confirm or refute once CI runs" wording
> below is retained as written for the historical record; read it as confirmed. Still genuinely
> unverified: `config/category_registry/delete`'s existence (teardown suppresses errors, so a
> green run proves nothing either way).

**Scope.** M11 is the reverse of §22's pull-side category placement: when `hassle push` CREATEs a
brand-new automation/script whose source file matches the `automations/<slug>.py` /
`scripts/<slug>.py` shape (and isn't the `misc.py` fallback), Hassle assigns the matching HA UI
category to the new object — creating the category first if none exists yet. Implemented in
`hassle.sync.category_writeback.attempt_category_writeback`, called from `hassle.sync.apply.
apply_plan` immediately after a CREATE succeeds; never for UPDATE/DELETE/REFRESH/ADOPT (MILESTONES
M11 test 4 — existing/adopted objects' categories are never retroactively touched, since this
module is only ever invoked from the CREATE branch).

**Two new WS commands, neither previously used/captured anywhere in this codebase — inferred from
reading HA core's source, NOT re-verified against a live instance in this PR (same caveat class as
§22's own "not live-verified" flag for `category_registry/list`'s `scope` param; no Docker/HA
access in this sandbox):**

- **`config/category_registry/create`** — `{scope, name}` → the created row, same shape as
  `.../list`'s rows: `{category_id, name, icon}`. Inferred from
  `homeassistant/components/config/category_registry.py`'s
  `WebSocketCommandCategoryRegistryCreate` handler (mirrors `.../list`'s already-confirmed `scope`
  convention, §22).
- **`config/entity_registry/update`** — `{entity_id, categories, ...}`. Inferred from
  `homeassistant/components/config/entity_registry.py`'s
  `WebSocketCommandEntityRegistryUpdate` handler: `categories` (like most of that handler's other
  optional fields — `area_id`, `labels`, etc.) is stored via `attr.evolve`, which **replaces the
  whole `categories` dict**, not a per-scope server-side merge. `DirectBackend._aassign_category`
  therefore reads the entity's current `categories` off `config/entity_registry/list` first (the
  same `unique_id == identity` anchor §2/§22 already established), merges in just this call's
  `{scope: category_id}`, and resubmits the merged dict — so assigning an automation's category
  never silently drops an unrelated label/category the object already carries under a different
  scope (I6). If a live capture ever shows `entity_registry/update` merging `categories`
  server-side instead, the client-side merge here is harmless (idempotent) — only the "read first"
  round-trip would become unnecessary, not wrong.

**New category naming.** MILESTONES M11 test 2 only specifies that a missing category is "created
... then assigned" — not what name it gets (there's no way to recover a category's original
mixed-case display name from a bundle filename's slug). Chosen: `hassle.ir.keys.humanize_slug`
(`"automatic_hvac"` → `"Automatic Hvac"`), a best-effort display name, not a round-trip guarantee —
the category's identity from that point on is its HA-assigned `category_id`, matched by
`slugify(name) == slug` on every subsequent push (same anchor `bundle_ops._category_source_path`
already uses in the pull direction, §22). A user is free to rename the category in the HA UI
afterward with no ill effect: Hassle only ever looks it up by `category_id` once created for a
given object, and re-derives the slug match fresh on every push for any *other* file that might
want the same category.

**Failure isolation (MILESTONES M11 test 3).** `attempt_category_writeback` never raises past its
own boundary — any exception from `list_categories`/`create_category`/`assign_category` (backend
unreachable, command rejected, older HA with no category registry, anything) becomes a warning
string on `ApplyResult.category_warnings` (additive field), never an `ApplyOutcome.FAILED`/
`ROLLED_BACK` for the object itself. `hassle push` prints each warning (yellow) after reporting
success — the object was genuinely created; only its HA UI grouping is affected, and re-running
`hassle push` is a safe no-op for the object (nothing local changed) that will retry the category
assignment.

**`FakeBackend`'s model (unit-test-only simplification, flagged per this doc's own convention).**
Real HA's entity-registry lookup is by `unique_id`; `FakeBackend` has no simulated entity_id/
entity-registry-row layer at all for automations/scripts (nothing in this codebase's `FakeBackend`
ever needed one before), so its `assign_category`/`categories_for` key directly by `(kind,
identity)` instead of round-tripping through a fabricated entity row. This is an internal
storage-organization shortcut, exactly like `FakeBackend`'s existing helper-id-from-name-slug
shortcut (module docstring) — it does not change the *shape* `DirectBackend`/real HA use (both
still take `entity_id`-shaped WS payloads, `DirectBackend`'s tests in
`test_direct_backend_category_writeback.py` pin those exact payloads), only how the fake stores
its own bookkeeping.

**Backend surface (additive, NOT part of the frozen `Backend` Protocol F2 — same pattern as
`entry_id_for`/`fetch_registry_snapshot`, docs/backend.md §3.1, probed via `getattr` so a hand-
rolled test `Backend` stub without it simply skips write-back with no warning):**
`list_categories(scope)`, `create_category(scope, name)`, `assign_category(kind, identity, scope,
category_id)`, `categories_for(kind, identity)` (test/CLI-facing lookup, not used by
`attempt_category_writeback` itself).

**No F2/Backend Protocol change.** Per MILESTONES R5, since the additive-method pattern (not a
Protocol change) was sufficient, MILESTONES.md's F2 section is untouched.

**Test coverage:** `packages/hassle-core/tests/test_category_writeback.py` (the four milestone
tests, `FakeBackend`-only, `apply_plan`-level), `packages/hassle-core/tests/
test_direct_backend_category_writeback.py` (WS payload shapes for `create_category`/
`assign_category`, monkeypatched `_client`, no network), `packages/hassle-cli/tests/
test_push_category_writeback.py` (end-to-end `hassle push` against `FakeBackend`, including the
warning text in `hassle push`'s stdout), and — added in the round below —
`packages/hassle-core/tests/integration/test_m11_category_writeback.py` (real Docker HA, both
`stable`/`dev`).

### 30 addendum: integration coverage added, one settle-race fixed pre-emptively (round 2, same PR)

**Why this addendum exists.** MILESTONES M11 test 1's own text ends with "CI integration verifies
live" — the first round of this PR shipped only unit tests (`FakeBackend`-level and
monkeypatched-`_client`-level), which never actually drives `config/category_registry/create` or
`config/entity_registry/update` against a real instance. Given M10's own history (§26.0-§26.10:
six CI rounds where source-inferred flow shapes turned out wrong), shipping M11 without live
coverage of its own two newly-inferred WS commands would repeat exactly that mistake. Flagged by
review before merge; fixed in this same PR/commit rather than a follow-up.

**Added:** `test_m11_category_writeback.py`, four tests (module docstring has the full list) —
create-and-assign with no pre-existing category, reuse of an existing matching category (never
duplicated), the script-scope variant (the specific worry: does a `script.<object_id>` entity's
`unique_id` really equal the script's object id, the same way an automation's does?), and an
other-object/other-scope non-interference check (I6) — real HA's category registry only has the
two scopes DESIGN §7.3 places by, and a single object can only ever be in one of them, so there is
no way to seed a second scope's category on the SAME object; the test instead seeds a script's
category first and confirms it survives a *different* object's (an automation's) category
assignment, which still exercises the same `config/entity_registry/list` read-every-row +
client-side-merge code path a same-object two-scope case would. Documented as a limitation of HA's
actual scope set, not a gap in the test.

Every test owns a globally-unique (`uuid4`-suffixed) category-name slug and object identity, and
best-effort deletes the category in teardown — **`config/category_registry/delete` was not
confirmed to exist while writing this suite** (no HA source access for this specific command
in this pass; `contextlib.suppress` makes teardown a no-op rather than a failure if it doesn't).
This is the one still-open "not live-verified" item from this section: if CI's teardown step
errors loudly (rather than silently no-op'ing), that is itself the live confirmation the command
doesn't exist as named, and should be recorded as a further correction here. The globally-unique
slug is what actually prevents collisions across reruns regardless of whether delete works.

**Pre-emptive fix: `_aassign_category` now bounded-polls for the entity-registry row.**
Re-reading `_await_config_entity` (§17.7) while writing the integration tests surfaced a real gap:
`create()` for an automation/script already waits for the entity to appear in `/api/states` before
returning, but `apply_plan` then immediately calls `attempt_category_writeback` ->
`_aassign_category`, which looks the entity up via a SEPARATE call
(`config/entity_registry/list`). "Visible in `/api/states`" and "visible in
`config/entity_registry/list`" are two different HA-internal signals with no guarantee they settle
on the same tick — exactly the async-settling class §17.7/§29 already document for other
HA-internal transitions. Rather than wait for CI to discover this as a flaky `LookupError` (the
same way §29's trace-settle race was originally discovered by symptom), `_aassign_category` now
bounded-polls (`self._reload_timeout`/`self._reload_interval`, the same knobs `_await_config_entity`
uses — no new wait budget invented) until the row appears or the deadline passes, at which point it
raises the same `LookupError` as before (still just a warning at the `attempt_category_writeback`
call site, I6). Unit-tested (`test_assign_category_polls_until_entity_registry_row_appears`, a fake
client whose `config/entity_registry/list` response starts empty and "appears" after N calls) —
this is a pre-emptive hardening based on the documented pattern, not something CI actually caught
failing yet; if live CI shows the row is always immediately visible (no settling needed at all),
the poll is harmless (succeeds on its first iteration) and this note should be updated to say so.

**Still not live-verified as of this addendum** (both flagged in the original §30 text above, both
now covered by tests that will confirm or refute them once CI runs): whether
`config/category_registry/create`'s exact `{scope, name}` argument shape and
`config/entity_registry/update`'s wholesale-replace-vs-merge `categories` semantics match what
this section infers. If CI finds either wrong, fix `DirectBackend` + this section in the same PR
as §26 did, and downgrade the corresponding unit test's docstring claim accordingly.

## 31. M15 research: HA UI categories — which object kinds, which scopes, and can helpers round-trip? (source-verified, core `dev` + `2026.7.1` + `2026.2.3`, frontend `dev` + `20260624.4` + `20260226.0`)

> **Verification method.** All claims below were read directly from GitHub source
> (`gh api .../contents/... -H "Accept: application/vnd.github.raw"`) of
> `home-assistant/core` (branch `dev`, tags `2026.7.1` and `2026.2.3`) and
> `home-assistant/frontend` (branch `dev`, tags `20260624.4` and `20260226.0`) on
> 2026-07-06. Nothing here is from memory. Line numbers are for the `dev` branch
> unless tagged otherwise; the tagged versions were diff-checked for the load-bearing
> claims and are identical unless noted.

### 31.1 Q1 — `scope` is an arbitrary caller-chosen string; core defines NO scope enum

`homeassistant/helpers/category_registry.py` (dev):

- `CategoryRegistry.categories: dict[str, dict[str, CategoryEntry]]` — outer key is the
  scope, a plain `str` (line ~96). Storage (`core.category_registry`, version 1.2) is
  `{"categories": {<scope>: [<entry>, ...]}}`.
- `async_create(*, name: str, scope: str, icon: str | None = None)` (line ~124): `scope`
  is typed `str`, never validated against any set — an unknown scope is simply created
  on first use (`if scope not in self.categories: self.categories[scope] = {}`).
- Category names are unique **per scope**, case-insensitively
  (`_async_ensure_name_is_available`, raises `ValueError "The name '...' is already in use"`).
- `CategoryEntry` = `{category_id (ULID), name, icon, created_at, modified_at}`.

`homeassistant/components/config/category_registry.py` (dev, identical schema at 2026.7.1):
all four WS commands take `vol.Required("scope"): str` — plain string, no enum
(`list` line 26, `create` line 47, `delete` line 75, `update` line 100). So the WS layer
also accepts any scope string.

**Core itself writes no scopes.** A code search for category-registry `scope=` usage in
`home-assistant/core` hits only `homeassistant/helpers/category_registry.py`,
`homeassistant/components/config/category_registry.py`,
`homeassistant/helpers/entity_registry.py` (generic cleanup, §31.3), and tests. Every
real scope string in existence is a **frontend convention**, not a backend contract.

### 31.2 Q2 — which frontend tables use categories, and their scope strings

Code search over `home-assistant/frontend` for `category_registry` /
`ha-filter-categories` importers finds exactly four config tables (plus the shared
category dialogs/picker and `suggest-metadata-helpers.ts`, which reuses the same scope
strings for AI metadata suggestions). **Devices and entities tables have NO category
support** — neither imports `ha-filter-categories` nor touches `categories` on update.

Scopes that exist and who writes them:

| scope string | written by (frontend file) | filter / assign evidence (dev) | present in 20260226.0 (HA ~2026.2)? |
|---|---|---|---|
| `automation` | `src/panels/config/automation/ha-automation-picker.ts` | `scope="automation"` (line 534), bulk write `categories: { automation: category }` (line 1214), read `entityRegEntry?.categories.automation` (line 269) | yes |
| `script` | `src/panels/config/script/ha-script-picker.ts` | `scope="script"` (line 524), `categories: { script: category }` (line 943) | yes |
| `scene` | `src/panels/config/scene/ha-scene-dashboard.ts` | `scope="scene"` (line 553), `categories: { scene: category }` (line 892) | yes |
| `helpers` (**plural!**) | `src/panels/config/helpers/ha-config-helpers.ts` | `scope="helpers"` (line 721), assign dialog `scope: "helpers"` (line 1048), bulk write `categories: { helpers: category }` (line ~1055 region), read `entityRegEntry?.categories.helpers` (line 578) | **yes** (grep at tag 20260226.0: 4 hits) |
| *(anything else)* | nobody in core/frontend | backend accepts it; nothing displays it | — |

Note the asymmetry: three singular scopes matching the HA domain (`automation`,
`script`, `scene`) and one plural umbrella scope `helpers` shared by ALL helper
domains. There is no per-helper-domain scope (`input_boolean` etc. do not get their
own); one category namespace covers every helper on the page.

**Helpers page mechanics** (`ha-config-helpers.ts`, dev): the table's rows are (a) every
state whose domain satisfies `isHelperDomain` (the storage-collection domains) plus (b)
every entity whose entity-source integration is a helper-type config-flow integration
(this is how config-entry helpers — template, derivative, etc. — appear), plus (c) bare
config-entry rows for entries whose entity failed to load (`entity: undefined`,
`selectable: false`). Category assignment (`_editCategory`, line ~1032) resolves the row's
`entity_id` in the **entity registry** and refuses with an alert
(`no_category_support` / `no_category_entity_reg`) only if there is no registry entry —
i.e. case (c), a broken/not-yet-loaded config entry. For every normally loaded helper,
storage-collection **and** config-entry-backed alike, assignment works and is written
via `config/entity_registry/update` with `categories: { helpers: <id | null> }`.

### 31.3 Q3 — `config/entity_registry/update` `categories` is `{scope: category_id}` per entity, and it MERGES server-side

`homeassistant/helpers/entity_registry.py` (dev): `RegistryEntry.categories:
dict[str, str] = attr.ib(factory=dict)` (line 203) — scope → category_id, at most one
category per scope per entity. Deleted entities retain their categories and restore them
on re-registration (lines ~1418/1496). When a category is deleted from the registry,
`async_clear_category_id(scope, category_id)` (line ~2183) strips it from live AND
deleted entities. `async_entries_for_category(registry, scope, category_id)`
(line ~2326) is the reverse lookup.

`homeassistant/components/config/entity_registry.py` — **identical at dev, 2026.7.1,
and 2026.2.3**:

- Schema (dev line 166): `vol.Optional("categories"): cv.schema_with_slug_keys(vol.Any(str, None))`
  — scope keys must be slugs; value is a category_id or `None`.
- Handler (dev lines 253–263) with the comment at lines 157–162: *"If passed in, we
  update/adjust only the provided scope(s). Other category scopes in the entity, are
  left as is."* The code copies `entity_entry.categories`, then per submitted scope
  either deletes it (value `None`) or sets it. **This is a per-scope server-side merge,
  not a wholesale replace** — see discrepancy (b) in §31.5.

### 31.4 Q4 — every helper domain gets a categorizable entity-registry row, and the helpers UI exposes it

- The nine storage-collection domains (`input_boolean`, `input_button`,
  `input_datetime`, `input_number`, `input_select`, `input_text`, `counter`, `timer`,
  `schedule`): each helper is one entity with an entity-registry row (this codebase
  already relies on that row's `unique_id == object_id` anchor, §2/§4). Rows carry
  `categories`; the helpers table lists them via `isHelperDomain` and offers
  assign/edit/bulk-move category and category filtering/grouping under scope `helpers`.
- The four config-entry template domains (§26's flows): a loaded config entry registers
  its entity in the entity registry (that is how the helpers page finds it, via entity
  sources + `config_entry_id`), so it too carries `categories` and the UI exposes the
  same assign path. The only excluded case is a config entry in an error state whose
  entity never registered — the UI shows an explanatory alert instead
  (`no_category_entity_reg`).
- Scenes also have a live scope (`scene`) should Hassle ever manage them.

### 31.5 Discrepancies with §22 / §30 (current HA reality vs. what those sections recorded)

(a) **§22 "Helpers are intentionally excluded … HA's category registry only covers
`automation`/`script` scopes" — wrong, and was already wrong when written.** The
backend never had a scope allowlist, and the frontend's `scene` and `helpers` scopes
are present at frontend tag `20260226.0` — i.e. they existed on the very HA 2026.2.3
instance §0 says this document was verified against. The exclusion was inherited from
DESIGN §7.3's wording, not from HA. Same for the §30-derived comment in
`hassle/sync/category_writeback.py` (`_SCOPE_FOR_KIND` header: "Only
automations/scripts have a category-registry scope in HA") and
`bundle_ops._category_source_path`'s docstring ("the only two scopes HA's category
registry covers … Helpers have no category-registry scope") — both restate the same
false premise.

(b) **§30's inference that `config/entity_registry/update` `attr.evolve`-replaces the
whole `categories` dict — wrong (at dev, 2026.7.1, AND 2026.2.3).** The WS handler
merges per scope before `attr.evolve` runs (§31.3), and `None` unsets a single scope.
This is exactly the contingency §30 itself pre-declared: `DirectBackend
._aassign_category`'s read-then-client-side-merge is harmless/idempotent, only the
"read first" round-trip is unnecessary. It could be simplified to send just
`{scope: category_id}`, and gains a free "unset" primitive (`{scope: None}`) if M15
ever needs category *removal*.

(c) **§30 addendum's open item — `config/category_registry/delete` — is now
source-confirmed to exist**: `websocket_delete_category`, args
`{type: "config/category_registry/delete", scope, category_id}` (dev and 2026.7.1).
The integration-teardown `contextlib.suppress` is masking a command that is real.

(d) **§30 addendum's "real HA's category registry only has the two scopes … no way to
seed a second scope's category on the SAME object" — the premise is wrong.** Scopes
are arbitrary; one entity can carry `{"automation": X, "helpers": Y, "anything_sluggy": Z}`
simultaneously (only the slug-key constraint of `cv.schema_with_slug_keys` applies).
The existing cross-object test still exercises the right code path, but a literal
same-object two-scope test IS possible and would be the stronger I6 check.

(e) Minor: §22's guess that the `scope` request parameter follows the
"`entity_category`" convention was directionally right; the real signature is
confirmed at §31.1 (`vol.Required("scope"): str` on all four commands), matching the
2026-07-05 live verification note already appended to §22.

### 31.6 Implications for M15 (category-first bundle layout)

**Helper category grouping CAN round-trip through HA — it does not need to be
source-only metadata.** Every helper Hassle manages (all nine storage-collection
domains and the four config-entry template domains) has an entity-registry row whose
`categories["helpers"]` the real HA helpers UI reads, writes, filters, and groups by —
the same `config/entity_registry/update` + `config/category_registry/*` surface
Hassle already drives for automations/scripts (I1 holds). Concretely: pull-side,
`RegistrySnapshot` already parses the full `categories` dict, so placement only needs
`category_registry/list` called for scope `"helpers"` and a helper-kind branch in
`bundle_ops._category_source_path`; push-side, `_SCOPE_FOR_KIND` extends with each
helper kind → scope `"helpers"` (and tree `"helpers"`). Two design consequences to
plan for: (1) `helpers` is ONE shared scope — category names are unique across all
thirteen helper domains, which conveniently matches a single `helpers/<slug>.py` (or a
cross-kind `<slug>.py`) per category; but (2) a mixed-kind category file
(automation + script + helper sharing category "Plant Care") maps to **three separate
category rows** (scopes `automation`/`script`/`helpers`, three distinct `category_id`s
that merely share a name) — creation on push must happen per scope, and a user
renaming the category in one HA table but not the others makes the three names
diverge, so M15 needs an explicit policy (e.g. slug-match per scope independently, the
same anchor §30 already uses, and surface divergence as a warning rather than guessing).
One residual caveat: a config-entry helper whose entry is in an error state has no
registry row, so category assignment for it fails into the existing
`category_warnings` path (I6-consistent, already handled). Identity lookup for
config-entry helpers goes via `config_entry_id` → registry row rather than the
`unique_id == object_id` anchor used for automations/scripts/storage helpers —
`DirectBackend`'s helper-side assign needs that variant.

### 31.7 M15 work item A: implementation notes (`m15/category-sync`)

Two decisions the binding spec left to the implementer, recorded here per this
doc's own convention:

- **Conflict-surfacing mechanism.** The spec requires a local-move-vs-remote-
  recategorization conflict to be "surfaced as a conflict (I6), never silently
  overwritten" but doesn't mandate *how*. Implemented as an additive
  `ApplyResult.category_conflicts: list[str]` (parallel to M11's
  `category_warnings`), populated by the new `hassle.sync.category_move`
  module and printed by `hassle push` in red — **not** folded into the
  existing `PlanAction.CONFLICT`/`--accept-local`/`--accept-remote` machinery,
  because a category conflict is metadata-only and detected too late for that
  (only known after a live `categories_for` read during `apply_plan`, not at
  `compute_plan` time, since an object's category isn't part of its hashed
  config body). On a conflict the manifest's base `category` is left
  unchanged, so the identical conflict resurfaces on every subsequent
  push/pull until a human resolves it one way or the other (no CLI flag to
  force a side yet — a natural follow-on, not required by work item A's test
  contract).
- **`assign_category`'s signature widens to `category_id: str | None`**
  (`DirectBackend`/`FakeBackend`), with `None` meaning "unset this scope
  entirely" — §31.3 confirms the real per-scope delete-or-set handler
  supports this directly; needed for "move to `misc.py`" (unassign). Real
  HA's unset REMOVES the scope key from `categories` (never leaves a
  lingering `{scope: None}` entry) — `FakeBackend.assign_category` mirrors
  that exactly (`.pop(scope, None)` rather than storing `None`).
- **`delete_category` is a new additive method** (`DirectBackend`/
  `FakeBackend`, same non-Protocol pattern as `list_categories`/
  `assign_category`), added so integration teardown can call the
  now-confirmed `config/category_registry/delete` directly instead of
  reaching into `DirectBackend._client` privately — the pre-M15 teardown
  fixture did the latter specifically because there was no public method for
  it yet.
- **Pull-side manifest advance now also records `category`**
  (`hassle_cli.cli`'s `_do_pull`/REFRESH+ADOPT manifest-update block, not
  `hassle.sync.apply`): a freshly-refreshed/adopted automation/script's base
  category is set from its OWN placement (`local_category_for_source_path`),
  so the very next push's category-move sync starts from the correct base
  instead of `None` (which would otherwise misfire as "moved locally" on the
  very first push after every pull).
