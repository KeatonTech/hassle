"""Error case: a `@raw_dashboard` body with a forgotten `return`.

Without the return-type guard this compiled clean with `config: null`, and a
push would have replaced the user's real dashboard with an empty config -- a
silently destructive write (I1/I6).
"""

from hassle import raw_dashboard


@raw_dashboard(url_path="forgot-return")
def forgot_return():
    {"views": [{"title": "Home", "cards": []}]}  # noqa: B018 - the bug under test
