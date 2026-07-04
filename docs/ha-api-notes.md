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
