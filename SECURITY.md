# Security policy

Hassle holds a credential that controls someone's home, and it writes
executable Python onto their machine. This document says what it protects,
what it deliberately trusts, and how to report a problem.

## Reporting a vulnerability

Please report privately, **not** as a public issue:

- [Open a draft security advisory](https://github.com/KeatonTech/hassle/security/advisories/new)
  (preferred — it gives us a private thread and a CVE path if warranted), or
- email the maintainer listed in the repository profile.

Please include what you were running (`hassle --version`), what an attacker
would need to control to trigger it, and a reproduction if you have one. This
is a small volunteer project, so expect an acknowledgement within about a
week. Please give us a reasonable window to ship a fix before disclosing
publicly; we'll credit you in the advisory and the changelog unless you'd
rather stay anonymous.

**In scope:** anything that lets a party who is *not* already trusted (see the
trust boundaries below) read the HA token, run code on the user's machine, or
write to Home Assistant. **Out of scope:** anything that requires the user to
already be running an untrusted bundle (that is documented below as
equivalent to running untrusted code), or that requires an already-compromised
local machine.

## Supported versions

Pre-1.0, only the latest release gets fixes. There are no backports.

| Version | Supported |
|---|---|
| 0.1.x | ✅ |
| < 0.1 | ❌ |

## Trust boundaries

Three things are inside Hassle's trust boundary. Anything outside them should
not be able to hurt you; if it can, that's a vulnerability worth reporting.

### 1. Your bundle is a program, not a document

A Hassle bundle is real Python. `compile_bundle` imports and executes your
bundle's modules — that is how the DSL works, and there is no sandbox.
Module bodies run at import, and decorated function bodies run during
compilation.

**Running any of these commands against a bundle executes that bundle's
code:** `validate`, `plan`, `status`, `push`, `pull`, `test`, `run`, `explain`.
Only `init`, `login`, `fmt`, `stubs`, and `render` do not.

So **cloning someone else's bundle repo and running `hassle validate` is
equivalent to running their code** — the same risk as `pytest` in a repo with
a `conftest.py`, or opening a project in an editor that auto-imports it. Treat
untrusted bundles the way you'd treat any untrusted source tree.

`compile_bundle` does refuse to follow symlinks out of the bundle and cleans
up `sys.modules` afterwards, but those are correctness and hygiene measures.
They are not a security boundary, and the internal `_sandboxed_import` name
does not imply one.

### 2. Your Home Assistant instance is trusted input

`hassle pull` turns config fetched from HA into Python source on your disk,
and compiles it. Hassle treats every value HA returns — aliases, entity ids,
templates, blueprint paths, service-call fields — as data, and escapes it into
literals so it can never become code. That escaping is enforced by regression
tests ([`test_decompile_injection.py`](packages/hassle-core/tests/test_decompile_injection.py))
covering hostile values *and* hostile field names, and templates render in a
`jinja2.sandbox.SandboxedEnvironment`
([`test_simulator_template_sandbox.py`](packages/hassle-core/tests/test_simulator_template_sandbox.py)),
the same posture Home Assistant itself uses.

That said, a compromised HA instance still controls the *content* of your
automations, and pushing gives Hassle full control of the instance. If your HA
is compromised, Hassle is not your line of defense.

### 3. Your local machine and your git remote

Hassle stores no secrets in the bundle, but the bundle is not free of
sensitive data — see "What ends up in your repository" below.

## Your Home Assistant token

Hassle authenticates with a **long-lived access token, which is equivalent to
full admin control of your Home Assistant** — it can read every entity and
call every service. Treat it like a root password.

- **Where it's stored:** your OS keyring (`keyring` — Keychain on macOS,
  Credential Manager on Windows, Secret Service on Linux), keyed by HA URL.
  It is never written to `hassle.toml`, `manifest.lock`, `.hassle/`, generated
  files, or any temp file, and it never appears in error messages, logs, or
  tracebacks. Regression tests pin this.
- **Headless machines** with no keyring: set `HASSLE_TOKEN` in the
  environment. On Linux, `/proc/<pid>/environ` is readable only by the owning
  user, so this is acceptable — but note that child processes inherit it
  (`hassle test` spawns pytest, so your bundle's own test code can read it).
- **Prefer the interactive prompt** over `hassle login --token <value>`.
  A token passed as a command-line argument is written to your shell history
  and, on Linux, is visible in `ps` to other local users while the command
  runs.
- **Use HTTPS.** With a plain `http://` URL, the token crosses your network in
  cleartext on every command, and Hassle downgrades the WebSocket connection
  to match. Hassle warns when the URL is plain HTTP to a non-private address.
  TLS verification is never disabled, and the token is sent as an
  `Authorization` header — never in a URL or query string.
- **A caveat outside our control:** if your environment has the `keyrings.alt`
  backend installed, `keyring` may select a plaintext or lightly obfuscated
  file backend. Hassle asks `keyring` for storage and does not override the
  backend choice.
- **Rotate** in Home Assistant (Profile → Security → Long-Lived Access Tokens)
  if a token is ever exposed; revoking there is immediate and total.

## What ends up in your repository

Your bundle is designed to be committed to git. Before you make that
repository **public**, know what's in it:

- **Webhook IDs are secrets.** An automation with a webhook trigger stores a
  `webhook_id`, and Hassle writes it into your source verbatim (it has to —
  the id *is* the trigger's identity). Anyone who knows it can `POST` to
  `/api/webhook/<id>` **with no authentication** and fire that automation.
  Publishing a bundle with webhook automations hands over the ability to
  trigger them. `hassle doctor` tells you how many your bundle contains.
- **`.hassle/registry.json` is a map of your home.** It is committed
  deliberately (it's the offline registry snapshot that makes validation and
  stubs work), and it contains every entity id, friendly name, device name,
  area, floor, and label. No credentials — but a complete inventory of your
  house and, often, who lives in it.
- **No token.** `hassle pull` and `hassle doctor` refuse to proceed if they
  find a committed token, and `doctor` scans the bundle for token-shaped
  strings.

**Hassle is not a secret scanner.** `doctor`'s check is a safety net for the
obvious cases, not a guarantee, and it only inspects your working tree — a
token committed earlier and later deleted stays in git history, where `doctor`
will not see it. For a repository you intend to publish, use a real scanner
(gitleaks, `git-secrets`, GitHub push protection) and rotate anything that was
ever committed.

## If your bundle repository is public

`hassle validate` and `hassle test` execute the bundle's Python (see trust
boundary 1). The CI workflow `hassle init` scaffolds therefore runs a pull
request author's code on your runner. It ships with `permissions: contents:
read` and no secrets, which limits the blast radius to the runner itself — but
you should also enable **Settings → Actions → Require approval for all
external contributors**.

## What Hassle does to protect you

Stated plainly so you can check our work, and so a regression is recognizable:

- **Remote config never becomes code.** Values are rendered through `repr`;
  field names that aren't safe Python identifiers are routed into `**{...}`
  literals rather than identifier positions.
- **Templates from HA render sandboxed**, so a stored template cannot reach
  Python builtins during `hassle test`.
- **Writes stay inside the bundle.** Destination paths derived from remote
  data (HA category names) are slugified to `[a-z0-9_]`, which strips
  traversal entirely; the source writer additionally refuses paths that
  resolve outside the bundle root and refuses to write through symlinks.
- **No shell.** Every subprocess call (`ruff`, `git`, `pytest`) uses list-form
  argv with no shell interpretation, and untrusted content is passed on stdin,
  never as an argument.
- **Nothing is deserialized unsafely** — no `pickle`, no `yaml.load`, no
  `eval`/`exec` on data.
- **Push re-verifies before writing**, detects concurrent HA-side changes, and
  rolls back on failure. A bundle that fails to compile never pushes.
- **`pull` requires a clean git tree** by default, so git is always your undo.

## Known limitations

Honest gaps, none of which we consider vulnerabilities, but which you should
know about:

- **`hassle push --yes` will delete whatever the plan says to delete.** There
  is no cap and no extra prompt scaled to the number of deletions, so an empty
  or mis-configured bundle in CI can remove every object Hassle manages.
  Review `hassle plan` before automating `push --yes`.
- **Nothing binds a bundle to one HA instance.** The manifest records no
  instance identity, so pointing `hassle.toml` at a different instance is not
  detected. Push is accidentally survivable (unmatched objects don't write to
  HA), but the next `pull` will rewrite local sources to match the wrong
  instance — recoverable from git, which is why the clean-tree gate exists.
- **Dependency floors are lower bounds** (`aiohttp>=3.9`, `jinja2>=3.1`,
  `pydantic>=2.7`) and the lockfile isn't shipped in the wheel, so a fresh
  install can resolve older versions than we test. Install into a fresh
  environment to get current ones.
- **`ruff` is a runtime dependency** (the decompiler formats generated source
  with it), which puts its release pipeline in the trust boundary, as does
  `git`.
