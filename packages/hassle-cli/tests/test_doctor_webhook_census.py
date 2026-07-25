"""`hassle doctor` webhook-ID census (DESIGN §14; SECURITY.md "What ends up
in your repository": "hassle doctor tells you how many [webhook ids] your
bundle contains").

A `webhook_id` is a bearer capability: anyone who knows it can POST to
`/api/webhook/<id>` with no authentication and fire that automation, and
`hassle pull` writes it verbatim into the bundle's committed Python
(`webhook(<id>)`, `hassle.decompiler.exprs._trig_webhook`). Having webhook
triggers is normal and unavoidable -- this is informational, never a doctor
"problem" (never raises `problems`, never affects exit code).
"""

from __future__ import annotations

from pathlib import Path


def test_doctor_reports_zero_webhooks_for_bundle_without_any(bundle_dir: Path, cli) -> None:
    result = cli(["doctor"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert "webhook" in result.output.lower()
    assert "0 webhook" in result.output.lower()


def test_doctor_counts_webhook_triggers_and_stays_informational(bundle_dir: Path, cli) -> None:
    (bundle_dir / "doorbell.py").write_text(
        """
from hassle import automation, service, webhook, when

@automation(id="doorbell_ring", alias="Doorbell ring")
def doorbell_ring():
    when(webhook("abc123def456"))
    service("light.turn_on", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )
    result = cli(["doctor"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output  # informational -- never a failing check
    assert "1 webhook" in result.output.lower()
    # Never printed unmasked as some kind of "problem" list -- the id itself
    # is allowed to appear (it's already public knowledge in the bundle's own
    # committed source, DESIGN §14 -- the warning is about *publishing* the
    # bundle, not about doctor itself leaking anything new), but the count
    # must be presented as informational, not part of the `problems` tally.
    assert "should not be published publicly" in result.output.lower() or (
        "publicly" in result.output.lower()
    )


def test_doctor_counts_multiple_webhook_triggers(bundle_dir: Path, cli) -> None:
    (bundle_dir / "hooks.py").write_text(
        """
from hassle import automation, service, webhook, when

@automation(id="hook_one", alias="Hook One")
def hook_one():
    when(webhook("hook-one-id"))
    service("light.turn_on", target={"entity_id": "light.hallway"})

@automation(id="hook_two", alias="Hook Two")
def hook_two():
    when(webhook("hook-two-id"))
    service("light.turn_off", target={"entity_id": "light.hallway"})
""",
        encoding="utf-8",
    )
    result = cli(["doctor"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert "2 webhook" in result.output.lower()
