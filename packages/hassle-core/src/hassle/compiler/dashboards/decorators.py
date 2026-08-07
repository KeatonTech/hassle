"""``@dashboard`` / ``@raw_dashboard`` and the §3.2 envelope builder.

Both decorators register a :class:`~hassle.compiler.registry.RegisteredObject`
with ``kind="dashboard"`` — the same path ``@automation``/``@script`` take — so
duplicate-identity detection, the span map, and the ``CompileResult`` all work
unchanged. ``hassle.compiler.bundle._build_dashboard`` drains them: it opens a
:class:`~hassle.compiler.dashboards.recorder.DashboardRecorder` (rather than an
automation ``Recorder``) for a traced body, or simply calls the function for a
``@raw_dashboard`` one, and assembles the two-store envelope::

    {"meta": {"url_path": ..., "title": ..., "icon": ...,
              "show_in_sidebar": ..., "require_admin": ...} | None,
     "config": {"views": [...]}}

``meta`` is the HA dashboard-registry item minus ``id`` (HA-assigned,
transport-only) and minus ``mode`` (always ``"storage"``); it is ``None`` for
THE default dashboard, which has no registry item at all.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar, cast

from hassle.compiler.dashboards.errors import (
    DASHBOARD_METADATA_KWARGS,
    DashboardUrlPathError,
    DefaultDashboardMetadataError,
    RawDashboardReturnTypeError,
)
from hassle.compiler.spans import SourceSpan, capture_span

#: A `@raw_dashboard` body: zero arguments, returns the envelope or config dict.
#: Bound exactly like `raw_automation.py`'s `F`, so pyright flags a body that
#: returns anything else (a forgotten `return`, a YAML string) at EDIT time --
#: the compile-time :class:`RawDashboardReturnTypeError` is the runtime backstop
#: for an un-type-checked bundle file.
F = TypeVar("F", bound=Callable[[], dict[str, Any]])

#: The identity sentinel for THE default dashboard (§3.1), used when it has no
#: registry item of its own and is reachable only as `url_path = null`.
#:
#: NOT collision-free by construction -- that claim was retired by DB0
#: (docs/internals/ha-api-notes.md §39.3): HA's hyphen rule is bypassable via
#: `allow_single_word: true` on `lovelace/dashboards/create`, so a real
#: dashboard at the literal `url_path: "default"` is creatable.
#: `DirectBackend._alist_dashboards` raises on that collision rather than
#: letting two dashboards share one object key.
DEFAULT_IDENTITY = "default"


#: `@dashboard`/`@raw_dashboard` option names, in `meta` emission order.
DASHBOARD_OPTIONS: tuple[str, ...] = ("url_path", *DASHBOARD_METADATA_KWARGS)

#: Every process-wide-declared dashboard envelope, in declaration order --
#: this module's unit-test seam, cleared per compile (mirrors
#: `raw_automation._DECLARED`).
_DECLARED: list[dict[str, Any]] = []


def declared_dashboards() -> list[dict[str, Any]]:
    """Every dashboard envelope built so far, in declaration order."""
    return [dict(envelope) for envelope in _DECLARED]


def reset_declared_dashboards() -> None:
    """Clear this module's process-wide state (repeated compiles / tests).

    Also drops any leftover recorder stack, so a compile that raised inside a
    dashboard body can never bleed a half-open container into the next one.
    """
    from hassle.compiler.dashboards.recorder import reset_dashboard_context

    _DECLARED.clear()
    reset_dashboard_context()


def _check_identity(
    *,
    decorator: str,
    url_path: str | None,
    default: bool,
    metadata: dict[str, Any],
    span: SourceSpan | None,
) -> str:
    """Validate the identity kwargs and return the declared identity (§5.2/§3.1)."""
    if url_path is not None and default:
        raise DashboardUrlPathError("both", span, decorator=decorator, url_path=url_path)
    if url_path is None and not default:
        raise DashboardUrlPathError("missing", span, decorator=decorator)
    if default:
        given = [name for name in DASHBOARD_METADATA_KWARGS if metadata.get(name) is not None]
        if given:
            raise DefaultDashboardMetadataError(given, span)
        return DEFAULT_IDENTITY
    assert url_path is not None
    # NO hyphen check here, deliberately (docs/internals/ha-api-notes.md
    # §39.12). HA's hyphen rule is CREATE-time validation on the dashboards
    # collection, not a property of a valid dashboard -- HA bypasses it for
    # its own (`map`, created at onboarding; `lovelace`, created by the
    # default-dashboard migration), and both are ordinary `mode: "storage"`
    # dashboards a real instance genuinely has. Rejecting them at compile time
    # broke `hassle pull` outright on a real household: the decompiler emitted
    # `@dashboard(url_path="map")` and the compiler then refused its own
    # output, violating I3 (`compile(decompile(x)) == x` for ANY config).
    #
    # The rule is enforced where it actually applies -- CREATE, in
    # `DirectBackend._acreate_dashboard`/`FakeBackend._create_dashboard`,
    # mirroring the error real HA returns. A hand-authored NEW dashboard with
    # a hyphen-less url_path therefore fails at push with HA's own reason,
    # instead of being rejected offline on a rule that does not hold.
    return url_path


def _register_dashboard(
    *,
    func: Callable[..., Any],
    identity: str,
    options: dict[str, Any],
    span: SourceSpan | None,
    raw: bool,
) -> None:
    from hassle.compiler.registry import register_dashboard

    register_dashboard(func=func, identity=identity, options=options, span=span, raw=raw)


def dashboard(
    *,
    url_path: str | None = None,
    default: bool = False,
    title: Any = None,
    icon: Any = None,
    show_in_sidebar: Any = None,
    require_admin: Any = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a Lovelace storage-mode dashboard (§5.2).

    Exactly one of ``url_path=`` (a sidebar dashboard, whose slug HA requires to
    contain a hyphen) or ``default=True`` (THE default dashboard, served at
    ``/lovelace``) must be given — omitting both, or giving both, is a
    compile-time :class:`DashboardUrlPathError` that teaches the choice rather
    than silently targeting the default dashboard.

    ``title``/``icon``/``show_in_sidebar``/``require_admin`` are the HA
    dashboard-REGISTRY fields. ``default=True`` **forbids** them
    (:class:`DefaultDashboardMetadataError`): the default dashboard has no
    registry item to hold them.

    The undecorated function is returned unchanged, so a bundle can still call
    it directly; compilation runs it inside a dashboard recorder.
    """
    span = capture_span(depth=0)
    metadata: dict[str, Any] = {
        "title": title,
        "icon": icon,
        "show_in_sidebar": show_in_sidebar,
        "require_admin": require_admin,
    }
    identity = _check_identity(
        decorator="@dashboard",
        url_path=url_path,
        default=default,
        metadata=metadata,
        span=span,
    )

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        _register_dashboard(
            func=func,
            identity=identity,
            options={"url_path": url_path, "default": default, **metadata},
            span=span,
            raw=False,
        )
        return func

    return decorate


def raw_dashboard(*, url_path: str | None = None, default: bool = False) -> Callable[[F], F]:
    """The top rung of the raw ladder: a whole verbatim dashboard (§5.5).

    The decorated zero-argument function returns either the full §3.2 envelope
    (a dict with a ``config`` key, optionally a ``meta`` one) or just the
    Lovelace config itself (anything else — a ``views``/``strategy``/… dict), in
    which case the decorator's own ``url_path=`` supplies the registry metadata.

    The body's return type is part of the contract, enforced twice: statically
    (:data:`F` is bound to ``Callable[[], dict[str, Any]]``, so pyright rejects
    a body that returns anything else) and at compile time
    (:class:`RawDashboardReturnTypeError`, the backstop for an un-type-checked
    bundle). A forgotten ``return`` is the case that matters — it would
    otherwise store ``config: null`` and a push would blank the real dashboard.

    §3.4's identity-sentinel guard: a returned ``meta`` dict MUST carry
    ``url_path``. The IR keeps a permissive fallback to the ``default``
    sentinel (parse must accept anything, I3), but the COMPILE path rejects a
    ``url_path``-less ``meta`` loudly — otherwise a malformed dashboard would
    silently key as, and overwrite, the default dashboard.
    """
    span = capture_span(depth=0)
    identity = _check_identity(
        decorator="@raw_dashboard",
        url_path=url_path,
        default=default,
        metadata={},
        span=span,
    )

    def decorate(func: F) -> F:
        _register_dashboard(
            func=func,
            identity=identity,
            options={"url_path": url_path, "default": default},
            span=span,
            raw=True,
        )
        return func

    return decorate


# ---------------------------------------------------------------------------
# Envelope assembly (driven by `hassle.compiler.bundle._build_dashboard`)
# ---------------------------------------------------------------------------
def build_meta(options: dict[str, Any]) -> dict[str, Any] | None:
    """The envelope's ``meta`` half from the decorator's own options.

    ``None`` for the default dashboard (no registry item); otherwise the
    registry fields that were actually declared, in a stable order. Nothing is
    materialized that the author did not ask for.
    """
    if options.get("default"):
        return None
    meta: dict[str, Any] = {}
    for name in DASHBOARD_OPTIONS:
        value = options.get(name)
        if value is not None:
            meta[name] = value
    return meta


def build_raw_envelope(
    returned: Any, options: dict[str, Any], span: SourceSpan | None
) -> dict[str, Any]:
    """Normalize a ``@raw_dashboard`` body's return value into the §3.2 envelope.

    A non-``dict`` return is rejected outright
    (:class:`RawDashboardReturnTypeError`): it would otherwise be stored as the
    dashboard's config verbatim, so a forgotten ``return`` would compile to
    ``config: null`` and the next push would blank the real dashboard.
    """
    if not isinstance(returned, dict):
        identity = str(options.get("url_path") or DEFAULT_IDENTITY)
        raise RawDashboardReturnTypeError(identity, returned, span)
    body: dict[str, Any] = dict(cast("dict[str, Any]", returned))
    # A dict with a `config` key is the whole envelope; anything else IS the
    # Lovelace config (a `views`/`strategy`/... dict), which never has a
    # top-level `config` key of its own.
    is_envelope = "config" in body
    config: Any = body["config"] if is_envelope else body
    declared_default = bool(options.get("default"))

    if is_envelope and "meta" in body:
        meta: Any = body["meta"]
        if meta is None:
            if not declared_default:
                raise DashboardUrlPathError(
                    "meta_without_url_path", span, decorator="@raw_dashboard"
                )
        elif isinstance(meta, dict):
            found: Any = cast("dict[str, Any]", meta).get("url_path")
            if declared_default:
                raise DefaultDashboardMetadataError(["meta"], span, raw=True)
            if found is None:
                raise DashboardUrlPathError(
                    "meta_without_url_path", span, decorator="@raw_dashboard"
                )
            if found != options.get("url_path"):
                raise DashboardUrlPathError(
                    "meta_mismatch",
                    span,
                    decorator="@raw_dashboard",
                    declared=options.get("url_path"),
                    url_path=found,
                )
        return {"meta": meta, "config": config}

    return {"meta": build_meta(options), "config": config}


def record_declared(envelope: dict[str, Any]) -> None:
    """Append to this module's process-wide declared list (test seam)."""
    _DECLARED.append(envelope)
