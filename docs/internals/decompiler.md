# Decompiler internals

Design rationale that's too long to keep inline in the source. See DESIGN.md §7.3 for the
user-facing decompile semantics; this file is for maintainers of `hassle.decompiler`.

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
