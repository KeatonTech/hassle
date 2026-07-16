"""Golden case: purpose trigger with a pre-2026.7 renamed key (`battery.low`).

Mirrors fixtures/configs/automation_purpose_trigger_renamed_legacy_key.json.
The `on(...)` builder passes the type string through verbatim — the vocabulary
(including known renames) is validated in M3, not by the compiler. This proves
the compiler neither rejects nor rewrites a legacy purpose-trigger type.
"""

from hassle import automation, on, service, when


@automation(
    id="purpose_trigger_renamed_legacy_key",
    alias="Purpose Trigger Renamed Legacy Key",
    description="Automation with pre-2026.7 purpose trigger key that was renamed without migration",
    mode="single",
)
def purpose_trigger_renamed_legacy_key():
    when(on("battery.low", target="sensor.wireless_device_battery"))
    service("notify.mobile_app_kai", message="Battery low warning")
