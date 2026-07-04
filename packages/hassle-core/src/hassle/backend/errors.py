"""Error types for the real HA transport (M6).

These are the product-surface errors `DirectBackend`/`HaClient` raise. They
follow the same what/where/fix rubric as the compiler's errors and the M3
`Finding` (R6): one paragraph, actionable. `HaAuthError` in particular is the
`hassle login` failure surface (DESIGN §4: a 401 means the token is invalid).
"""

from __future__ import annotations


class HaError(Exception):
    """Base class for every error talking to Home Assistant."""


class HaConnectionError(HaError):
    """The instance was unreachable (DNS/refused/timeout), after retries.

    Distinct from `HaAuthError` (reached HA, but it rejected the credentials):
    this is "couldn't reach HA at all", so the fix is about the URL/network.
    """


class HaAuthError(HaError):
    """HA returned 401 — the long-lived token is missing, expired, or wrong.

    The message is the `hassle login` failure surface (DESIGN §4): long-lived
    tokens have no introspection endpoint, so validity is proven by a call and a
    401 means "invalid".
    """

    def __init__(self, detail: str = "") -> None:
        suffix = f" ({detail})" if detail else ""
        super().__init__(
            "Home Assistant rejected the access token with 401 Unauthorized"
            f"{suffix}. Fix: check HASSLE_TOKEN / your keyring entry and re-run "
            "`hassle login` to store a valid long-lived access token "
            "(Profile -> Security -> Long-lived access tokens in the HA UI)."
        )


class HaApiError(HaError):
    """HA accepted the request but reported an error (non-401 REST status, or a
    WebSocket ``success: false`` result)."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.code = code
        super().__init__(message)
