"""Error case: a dashboard verb called outside any `@dashboard` body."""

from hassle import raw_card

raw_card({"type": "markdown", "content": "hi"})
