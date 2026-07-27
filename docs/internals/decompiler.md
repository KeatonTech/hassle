# Decompiler internals

Design rationale that's too long to keep inline in the source. See DESIGN.md §7.3 for the
user-facing decompile semantics; this file is for maintainers of `hassle.decompiler`.

## The dashboard decompiler (`hassle.decompiler.dashboards`, workstream DB4)

`DashboardConfig` -> DSL source (docs/internals/dashboards-design.md §6.2)
lives in its own module rather than `codegen.py` because the card-tree walk
is substantially bigger than an automation/script's flat trigger/condition/
action lists. A few decisions worth recording here rather than only in the
module's own docstring:

- **Card emission never hardcodes a card type.** It looks a stored card's
  `type` up in `CARD_REGISTRY` (docs/internals/dashboards-design.md §6.1.1),
  resolves the row's `builder` name to the real callable, and drives the
  call generically off `inspect.signature`. `CardSpec.declared` (an
  optional, additive field a later registry-backfill workstream may
  populate) is read via `getattr(spec, "declared", frozenset())` so this
  module works unchanged whether or not that field exists yet — when it's
  absent/empty, every REQUIRED (no-default) parameter is still resolved by
  name (a call can't omit one) and every OPTIONAL leftover key routes
  through `extra=` wholesale; when populated, `declared` is the
  authoritative known-kwarg set instead. On the base this was written
  against, `CARD_REGISTRY` is empty (no card-builder family has merged), so
  every leaf/container card currently decompiles to `raw_card` — expected,
  and the tracked coverage signal that a family is still pending, not a bug.
- **`section()` and `view()` are deliberately asymmetric** in how they treat
  an unmodeled key: a view's stray key round-trips through its `extra=`
  valve, but ANY key `section()` doesn't itself model forces the whole
  section to `raw_section`. This matches §5.5's own wording ("a
  section/view whose OWN keys are unmodeled..."), read literally for
  sections; both builders support `extra=` at the compiler level, so this
  is a decompiler-side policy choice, not a builder limitation.
- **A container never goes raw merely because a descendant did** (the
  `ha-api-notes.md` §20.4 precedent, restated for dashboards): an unknown
  card wrapped inside an otherwise well-formed container/section/view stays
  `raw_card`, with everything above it staying typed. Every `_try_emit_*`
  function in this module returns `None` (never raises, never partially
  emits) exactly when ITS OWN shape can't be modeled, letting the caller
  degrade at the narrowest possible scope.
- **`badge()` cannot reproduce a legacy bare-string badge entry** — see
  `ha-api-notes.md` §39 for the full finding. The decompiler resolves it by
  escalating the whole enclosing view to `raw_view` (a legitimate use of the
  existing ladder, `badges` being an own-structure key of the view), not by
  inventing a `raw_badge` verb outside the frozen F5 ladder.
- **Import-line detection is a plain substring/regex check** on the already
  assembled decompiled source (`from hassle import cards as c` / `from
  hassle.cards import cond`, emitted only when actually used) — the same
  convention `decompile_bundle` already uses for `TemplateExpr`, chosen for
  the same reason: `c`/`cond` are never emitted as any other kind of
  identifier by this decompiler, so a plain regex is exactly as safe as
  threading a used-flag through every emission function, with far less
  plumbing.

## Why a fresh bundle decompile emits a star import

`decompile_bundle` always opens a generated module with `from hassle import *` rather than
an enumerated list of the builder names it actually used. An enumerated list would need a
matching update every time the DSL surface (`hassle.__all__`) gained a new builder, and
that staleness risk isn't worth the marginal readability gain — the star import always
resolves correctly under pyright because `hassle.__all__` is authoritative, and a generated
file is meant to be edited, not audited for its import list.

## ScriptRef and cross-file script calls

`ScriptRef` is how the pull layer tells the decompiler where a MANAGED script's function
actually lives, for scripts that are being called from a *different* file than the one
being decompiled right now. A script in the same `decompile_bundle` call needs no import
(it's just a same-module function call); a `ScriptRef` supplies the cross-file case, where
the decompiler must also emit `from <module> import <function_name>`.

Two fields exist to prevent a caller from being rewritten into a call the callee can't
actually accept:

- `known_fields` is the callee's own declared field names, needed to check "every `data`
  key is a declared field" for a callee this call never actually parses.
- `is_shared_script` records whether the callee decompiled to `@shared_script` (a real
  parameterized call site) or fell back to plain `@script`. The `@script` fallback has no
  call-site parameters at all, regardless of what the raw `fields` block's key names are —
  rewriting a caller to invoke it with kwargs raises `TypeError` at compile time. A script
  whose fields forced the fallback must never resolve a rewrite, so `is_shared_script` is
  checked before `known_fields`, not instead of it.

`calls` is the script's own outgoing call graph (the object_ids of other managed scripts
it calls directly), used only to detect script-to-script call cycles across files: a cycle
must not have both directions rewritten to an import, since neither generated file could
then be imported without a circular import. The edge that would close the cycle falls
back to a plain `service()` call instead.

## Shared-script parameter typing (`TemplateExpr`)

A decompiled `@shared_script` signature annotates every field parameter as `TemplateExpr`
(never a plain Python type inferred from its default) because every field-named parameter
is always a runtime template marker inside the body, never its declared default's Python
type. Annotating e.g. `times: int` would let body composition like `times / 2` type-check
as real arithmetic when it's actually building Jinja text — verified empirically, pyright
raises no error for this "int-field lie" under a plain-type annotation since it trusts the
annotation over the actual runtime type.

`field_default(...)` is the identity function at runtime — `inspect.signature(...)`'s
introspected default (what the generated HA `fields` block actually reads) sees the real
declared value unchanged — but is typed as returning `TemplateExpr`, so a field's default
expression type-checks against its own `TemplateExpr` annotation instead of the
self-inconsistent `tag: TemplateExpr = ""` a bare literal default would be. Caller-side
typing is unaffected by any of this: `@shared_script`'s returned caller wrapper's
signature is `(*args: Any, **kwargs: Any) -> None`, completely decoupled from the
decorated function's own annotations.

Every parameter is emitted keyword-only (a leading `*,`) because a required field (no
default) can legally follow a defaulted one in the stored `fields` dict's own order (HA
imposes no ordering constraint there), but plain positional-or-keyword Python parameters
do (`SyntaxError: parameter without a default follows parameter with a default`). This is
harmless for callers: the compiler always invokes a shared-script body with zero
positional arguments to build its sequence, so nothing ever called these parameters
positionally to begin with.

## Template helper decompilation: inversion vs. raw fallback

A template helper's `state=`/`options=` Jinja string decompiles through the bounded
inverter (`hassle.decompiler.template_invert`) first. When the inverter can produce an
expression that reproduces the stored text byte-for-byte, that expression is used as the
decorator body's `return` value; otherwise the fallback embeds the Jinja text verbatim as
a string literal return. Both branches share the same decorator-kwargs rendering and the
same computed identifier, so a helper never changes its function name depending on which
branch it took.

The acceptance rule is enforced inside `invert_template` itself: it returns `None` (never
partial output) unless re-rendering the inverted expression reproduces the original text
byte-for-byte, so choosing the invertible branch here is safe by construction. The
fallback branch is safe by construction too — it never re-renders or normalizes the
original text, just embeds it verbatim, so `compile(decompile(x)) == x` holds trivially
(this is the "raw" escape hatch described in DESIGN.md §2).

### Escaping a raw template's text as a Python string literal

The raw fallback (`_raw_template_return_source`) must parse back to exactly the original
text, whatever it contains — embedded quote runs, backslashes, leading/trailing newlines,
CR bytes. Single-line text (no `\n`) uses a plain `repr()`, since `ruff format` normalizes
quote-character choice/escaping deterministically for any string content. Multi-line text
uses a triple-double-quoted string, escaping only backslash, the double-quote character,
and `\r`, character-by-character rather than with a whole-string `.replace` (a whole-string
replace can corrupt overlapping matches, e.g. text ending in a double-quote character).
Escaping every double-quote individually means a run of them can never produce an
unescaped close-delimiter sequence. `\r` is escaped rather than emitted literally because
`ruff format`'s own line-ending normalization silently rewrites a bare CR byte inside a
multi-line string, which would break byte-stability.

## Cross-file script-call resolution (`_build_resolver`)

Same-batch scripts (defined in the same `decompile_bundle` call) always win over the
externally supplied `script_refs` table — they need no import, being plain functions in
the same module. A `script_refs` entry for a script not in this batch resolves to a
cross-file call, contributing one deduplicated, sorted `from <module> import <fn>` line.

Only `script_refs` entries actually referenced by an object in this batch ever contribute
a target or an import — an unused table entry must never surface as a dangling unused
import. A script that fell back to plain `@script` has no call-site parameters at all,
whatever its `fields` block's key names are, so it must never get a resolvable call
target on either side (same-batch or cross-file); otherwise a caller could be rewritten to
invoke a function with kwargs it does not accept, raising `TypeError` at compile time.
