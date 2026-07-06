"""Cookbook recipe 10: low-battery alert via a purpose-specific trigger
(2026.7+, DESIGN §5.4).

`battery.became_low` is a purpose trigger type (not a classic numeric_state
threshold) -- the recipe an agent should reach for on a modern HA install.
"""

from hassle import automation, on, service, when


@automation(id="cookbook_low_battery_alert", alias="Cookbook: low battery alert")
def cookbook_low_battery_alert():
    when(on("battery.became_low", target="binary_sensor.laundry_door"))
    service("notify.mobile_app_keaton", message="A sensor's battery is low")
