"""Dashboard compile errors (docs/internals/dashboards-design.md §5.6).

Product surface, same rules as :mod:`hassle.compiler.errors`: every message
names *what* went wrong, *where* (``file:line`` where determinable) and *the
fix*, in one paragraph, and is snapshot-tested
(``tests/snapshots/errors/dashboard_*.txt``).

They live in this subpackage rather than in ``hassle/compiler/errors.py``
because the whole dashboard vocabulary is one cohesive family (the same reason
``scripts.py`` and ``raw_automation.py`` own theirs) -- they are re-exported
through :mod:`hassle.compiler` for tooling, exactly like every other compiler
error.
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.errors import CompileError
from hassle.compiler.spans import SourceSpan

# Registry-metadata keywords `@dashboard` accepts -- the ones the DEFAULT
# dashboard has nowhere to store (it has no registry item at all, §3.2).
DASHBOARD_METADATA_KWARGS: tuple[str, ...] = (
    "title",
    "icon",
    "show_in_sidebar",
    "require_admin",
)


def _at(span: SourceSpan | None) -> str:
    return f" at {span.file}:{span.line}" if span is not None else ""


class NoDashboardContextError(CompileError):
    """A card/view/section/badge verb ran outside a ``@dashboard`` body.

    The dashboard mirror of :class:`~hassle.compiler.errors.NoRecordingContextError`:
    these verbs record into the dashboard the compiler is currently tracing, and
    there is none. ``in_automation=`` sharpens the message for the specific
    mix-up of using a dashboard verb inside an ``@automation``/``@script`` body,
    where a recording context IS active -- just the wrong kind.
    """

    def __init__(self, what: str, span: SourceSpan | None, *, in_automation: bool = False) -> None:
        self.what = what
        wrong_context = (
            " This call is inside an `@automation`/`@script` body, which records "
            "triggers, conditions and actions -- not cards."
            if in_automation
            else ""
        )
        super().__init__(
            f"{what} was used outside any `@dashboard` body{_at(span)}. Card, view, section "
            f"and badge verbs record into the dashboard the compiler is currently tracing, "
            f"and no dashboard is being traced here.{wrong_context} Fix: move this call into "
            f'a function decorated with `@dashboard(url_path="my-dashboard")` (or '
            f"`@dashboard(default=True)` for the default dashboard); if you meant to build a "
            f"value rather than record one, assign the dict to a variable instead of calling "
            f"it at module scope."
        )


class DashboardNestingError(CompileError):
    """A structural verb was used at a point in the card tree that cannot hold it.

    The general placement guard, distinct from the two SPECIFIC discipline
    errors below (:class:`SectionRequiredError`, which is about a
    ``sections`` view, and :class:`SectionOutsideSectionsViewError`, which is
    about a section). It covers: a card recorded straight into the
    ``@dashboard`` body (no view open), a ``badge()`` that is not directly
    inside a view, and a ``view()``/``raw_view()`` opened inside another
    container. **Addition to §5.6's enumerated list** -- see the F5 appendix
    (design doc §6.1.1) for why these trigger shapes need their own message.
    """

    def __init__(self, what: str, where: str, explain: str, fix: str, span: SourceSpan | None):
        self.what = what
        super().__init__(f"{what} was recorded {where}{_at(span)}. {explain} Fix: {fix}")


class SectionRequiredError(CompileError):
    """A leaf card was recorded directly under a ``sections`` view."""

    def __init__(self, span: SourceSpan | None) -> None:
        super().__init__(
            f"A card was recorded directly inside a `sections` view{_at(span)}. A `sections` "
            f"view stores only sections -- the cards live inside them -- so a card here has "
            f"nowhere to be stored and would be silently dropped. Fix: wrap it in `with "
            f"section():` (grouping related cards into one grid section), or open the "
            f'enclosing view as `view(type="masonry")`, the free-form column layout that '
            f"does take cards directly."
        )


class SectionOutsideSectionsViewError(CompileError):
    """``section()``/``raw_section()`` used somewhere that has no ``sections`` list."""

    def __init__(self, where: str, span: SourceSpan | None) -> None:
        self.where = where
        super().__init__(
            f"`section()` was used inside {where}{_at(span)}. HA stores a `sections` list "
            f"only on a view whose `type` is `sections`; every other view type stores one "
            f"flat `cards` list, and sections never nest inside each other or inside a card. "
            f'Fix: open the enclosing view as `view(type="sections")` (the authoring '
            f"default) and put the `with section():` directly inside it -- or drop the "
            f"section here and record the cards directly, grouping them with a stack card "
            f"if you wanted the visual box."
        )


class PanelViewArityError(CompileError):
    """A ``panel`` view holds anything other than exactly one card."""

    def __init__(self, count: int, span: SourceSpan | None) -> None:
        self.count = count
        plural = "card" if count == 1 else "cards"
        super().__init__(
            f"The `panel` view opened{_at(span)} contains {count} {plural}. HA's panel view "
            f"renders exactly one card at full width, so any other number cannot be stored "
            f"faithfully -- HA would show only the first card and quietly lose the rest. "
            f"Fix: keep exactly one card in the view (group several inside one stack card), "
            f'or change it to `view(type="sections")`/`view(type="masonry")`, which both '
            f"take any number of cards."
        )


class DashboardUrlPathError(CompileError):
    """A dashboard's identity (``url_path`` / ``default``) is missing or malformed.

    Five trigger shapes, all about the ONE thing that identifies a dashboard
    (§3.1): neither ``url_path=`` nor ``default=True``; both; a ``url_path``
    with no hyphen (HA requires one, §2.2 item 1); a ``@raw_dashboard`` body
    returning a ``meta`` dict with no ``url_path`` (§3.4's identity-sentinel
    guard); and a ``meta`` ``url_path`` that contradicts the decorator's.
    """

    def __init__(self, reason: str, span: SourceSpan | None, **detail: Any) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(self._message(reason, span, detail))

    @staticmethod
    def _message(reason: str, span: SourceSpan | None, detail: dict[str, Any]) -> str:
        where = _at(span)
        decorator = str(detail.get("decorator", "@dashboard"))
        if reason == "missing":
            return (
                f"`{decorator}(...)`{where} declares neither `url_path=` nor `default=True`. "
                f"Every dashboard is identified either by its HA `url_path` (the slug in its "
                f"sidebar link) or by being THE default dashboard, and Hassle never guesses "
                f"which one you meant -- guessing would silently overwrite the default "
                f'dashboard. Fix: pass `url_path="my-dashboard"` for a sidebar dashboard, '
                f"or `default=True` for the one HA serves at `/lovelace`."
            )
        if reason == "both":
            url_path = detail.get("url_path")
            return (
                f"`{decorator}(url_path={url_path!r}, default=True)`{where} sets both "
                f"`url_path=` and `default=True`. THE default dashboard has no `url_path` at "
                f"all -- HA stores it as `null` and gives it no dashboard-registry item -- so "
                f"the two are mutually exclusive identities, not a pair of options. Fix: keep "
                f"exactly one: `url_path={url_path!r}` for a sidebar dashboard, or "
                f"`default=True` for the default one."
            )
        if reason == "hyphen":
            url_path = str(detail.get("url_path", ""))
            return (
                f"`{decorator}(url_path={url_path!r})`{where} has no hyphen in its "
                f"`url_path`. Home Assistant requires a dashboard's `url_path` to contain a "
                f"hyphen (its own frontend and backend both enforce it), and Hassle relies on "
                f"that rule to keep the `default` identity sentinel collision-free. Fix: "
                f'rename it to a hyphenated slug, e.g. `url_path="{url_path}-dashboard"`.'
            )
        if reason == "meta_without_url_path":
            return (
                f"The `@raw_dashboard` body{where} returned a `meta` dict with no `url_path` "
                f"key. `meta` IS the HA dashboard-registry item, and its `url_path` is the "
                f"dashboard's identity -- without it the envelope would fall through to the "
                f"`default` identity sentinel and silently overwrite the default dashboard. "
                f'Fix: add `"url_path": "my-dashboard"` to the `meta` dict, or drop `meta` '
                f"entirely and let the decorator's own `url_path=` supply it, or declare "
                f"`@raw_dashboard(default=True)` if you really do mean the default dashboard."
            )
        if reason == "meta_mismatch":
            declared = detail.get("declared")
            found = detail.get("url_path")
            return (
                f"The `@raw_dashboard(url_path={declared!r})` body{where} returned a `meta` "
                f"dict whose `url_path` is {found!r}. A dashboard has exactly one identity, "
                f"and these two spellings of it disagree -- Hassle would register the object "
                f"under one and push it to the other. Fix: make them the same, or drop the "
                f"`meta` key entirely and let the decorator's `url_path=` supply it."
            )
        raise AssertionError(f"unknown DashboardUrlPathError reason {reason!r}")


class RawDashboardReturnTypeError(CompileError):
    """A ``@raw_dashboard`` body returned something other than a ``dict``.

    The destructive case this exists for: a forgotten ``return`` makes the body
    return ``None``, which -- before this guard -- fell through the
    envelope/config discrimination and became the stored config **verbatim**.
    ``{"meta": ..., "config": null}`` validates, hashes, and compiles clean, and
    the next ``hassle push`` would replace the user's real dashboard with an
    empty one. A wrong-typed return is always an authoring bug, never a shape
    to round-trip (I3's escape hatch is a dict, §5.5).
    """

    def __init__(self, identity: str, returned: object, span: SourceSpan | None) -> None:
        self.identity = identity
        type_name = type(returned).__name__
        hint = (
            " A body that ends in an expression rather than a `return` statement returns "
            "`None` -- check for a missing `return`."
            if returned is None
            else ""
        )
        super().__init__(
            f"The `@raw_dashboard` body for `{identity}`{_at(span)} returned a `{type_name}`, "
            f"not a `dict`.{hint} A raw dashboard's body must return either the whole "
            f'`{{"meta": ..., "config": ...}}` envelope or just the Lovelace config dict; '
            f"anything else would be stored as the dashboard's config as-is, so a push would "
            f"overwrite the real dashboard with it. Fix: `return` a dict from this function "
            f'-- e.g. `return {{"views": [...]}}` for a config, or `return {{"meta": '
            f'{{"url_path": "..."}}, "config": {{...}}}}` for the full envelope. Raw '
            f"bodies take dicts, never YAML strings (§5.5)."
        )


class DefaultDashboardMetadataError(CompileError):
    """The default dashboard was given registry metadata it cannot store.

    Two shapes, because the two decorators fail differently:
    ``@dashboard(default=True, title=...)`` passes metadata as KEYWORDS, while
    ``@raw_dashboard(default=True)`` smuggles it in as a ``meta`` key of the
    dict its body returns. Naming the wrong one leaves the author looking for a
    call site they never wrote (reviewer finding SF-3).
    """

    def __init__(self, options: list[str], span: SourceSpan | None, *, raw: bool = False) -> None:
        self.options = options
        self.raw = raw
        if raw:
            super().__init__(
                f"The `@raw_dashboard(default=True)` body{_at(span)} returned a non-null "
                f"`meta` key. THE default dashboard has no entry in Home Assistant's "
                f"dashboard registry -- that registry is the only thing `meta` describes, "
                f"and it is what stores a dashboard's title, icon, sidebar visibility and "
                f"admin-only flag -- so there is nowhere for it to be written and a push "
                f'would silently drop it. Fix: drop the `"meta"` key from the returned '
                f'dict (return just the config, or `{{"meta": None, "config": {{...}}}}`), '
                f'or replace `default=True` with `@raw_dashboard(url_path="...")` so this '
                f"becomes a real registry-listed dashboard that can carry it."
            )
            return
        named = ", ".join(f"`{o}=`" for o in options)
        super().__init__(
            f"`@dashboard(default=True)`{_at(span)} also sets {named}. THE default dashboard "
            f"has no entry in Home Assistant's dashboard registry -- that registry is what "
            f"stores a dashboard's title, icon, sidebar visibility and admin-only flag -- so "
            f"there is nowhere for these to be written and a push would silently drop them. "
            f"Fix: remove {named} here (the default dashboard's own sidebar name and icon "
            f"are HA settings, changed under Settings -> Dashboards), or give this dashboard "
            f"a `url_path=` so it becomes a real registry-listed dashboard that can carry "
            f"them."
        )


class DashboardConditionTypeError(CompileError):
    """An automation condition builder was passed to a dashboard condition slot."""

    def __init__(self, value_repr: str, suggestion: str, span: SourceSpan | None) -> None:
        self.value_repr = value_repr
        super().__init__(
            f"{value_repr} was passed to a dashboard `visibility=`/conditional-card "
            f"slot{_at(span)}, which needs a Lovelace condition. Lovelace conditions are a "
            f"different schema from automation conditions -- `entity`/`state`/`state_not` "
            f"keys instead of `entity_id`/`condition` shapes, plus the UI-only `screen` and "
            f"`user` kinds -- so HA would store this one and then never evaluate it. Fix: use "
            f"the `cond` vocabulary instead (`from hassle.cards import cond`), e.g. "
            f"`{suggestion}` -- or pass a verbatim `dict` for a condition kind Hassle does "
            f"not model yet."
        )


class DashboardConditionInAutomationError(CompileError):
    """The mirror: a ``cond.*`` Lovelace condition in an automation slot."""

    def __init__(self, value_repr: str, span: SourceSpan | None) -> None:
        self.value_repr = value_repr
        super().__init__(
            f"{value_repr} was passed to an automation condition slot{_at(span)}. The "
            f"`cond.*` builders make Lovelace CARD-VISIBILITY conditions -- a different "
            f"schema from Home Assistant's automation conditions, which HA would never "
            f"evaluate inside an automation, script or `if`/`choose` block. Fix: use the "
            f'automation vocabulary here (`state(entity).is_("on")`, '
            f"`numeric_state(entity, above=...)`, `all_of`/`any_of`/`not_`) and keep "
            f"`cond.*` for `visibility=` and conditional cards inside a `@dashboard` body."
        )


class ExtraShadowsKwargError(CompileError):
    """An ``extra=`` key shadows a declared keyword of the same builder."""

    def __init__(self, builder: str, key: str, span: SourceSpan | None) -> None:
        self.builder = builder
        self.key = key
        super().__init__(
            f"`{builder}(extra={{{key!r}: ...}})`{_at(span)} sets `{key}`, which is already a "
            f"declared keyword of `{builder}`. `extra=` is the forward-compatibility valve "
            f"for card options Hassle does not model yet; letting it also spell a modelled "
            f"option would give that option two spellings, so a decompiled dashboard could "
            f"never be byte-stable. Fix: pass `{key}=` as an ordinary keyword argument and "
            f"remove it from `extra=`."
        )
