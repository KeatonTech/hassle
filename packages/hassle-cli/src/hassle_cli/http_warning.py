"""Plain-HTTP-to-a-non-private-address warning (DESIGN §14; SECURITY.md "Use
HTTPS").

A long-lived HA access token is sent as a bearer credential on every request.
Over plain `http://` to an address that isn't recognizably private/local,
that token crosses the network in cleartext to anyone positioned to observe
it. This module is the pure classifier; callers (`hassle_cli.cli`'s `login`
and `_require_backend_config`, the single choke point behind
`pull`/`plan`/`status`/`push`/`stubs --refresh`/`run --live`) decide when to
print the message it returns.

Fired on **every command invocation** that builds a backend or runs `login`
against a matching URL -- not "once ever" (DESIGN.md previously said "warns
once", which has no meaningful definition across separate CLI process
invocations with no shared state; DESIGN.md has been corrected to describe
this per-invocation behavior instead of silently drifting from it).
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_PRIVATE_HOST_SUFFIXES = (".local", ".lan")
_PRIVATE_HOST_NAMES = frozenset({"localhost"})


def _is_private_host(host: str) -> bool:
    """Best-effort "this looks like a local/private address" check. Not a
    security boundary -- it only decides whether the warning fires, and
    erring toward NOT warning (a false negative) is the safe failure mode
    here, not the other way around."""
    if not host:
        return True
    if host in _PRIVATE_HOST_NAMES or host.endswith(_PRIVATE_HOST_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # not a literal IP and not a recognized private suffix
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified
    )


def plaintext_http_warning(url: str) -> str | None:
    """Return a what/where/fix warning if `url` is plain `http://` to a host
    that doesn't look private/loopback, else `None`.

    What: the long-lived HA token this command sends crosses the network in
    cleartext on every request. Where: `url` (embedded verbatim in the
    message). Fix: use https.
    """
    parsed = urlparse(url)
    if parsed.scheme != "http":
        return None
    host = (parsed.hostname or "").lower()
    if _is_private_host(host):
        return None
    return (
        f"hassle: {url} uses plain http, and {parsed.hostname!r} doesn't look like a "
        "private/local address. Your Home Assistant long-lived access token is sent on "
        "every request and would cross the network in cleartext to anyone positioned to "
        "see it. Fix: put this instance behind https (a reverse proxy or Nabu Casa), or "
        "only use http for genuinely local/private addresses."
    )
