"""Golden case: `state_of(...)` string-state vocabulary (M16, DESIGN §5.4
extension) composed through a plain custom function -- the owner's driving
case (MILESTONES M16 test 2): a helper function returning a `state_of(...)
.eq(...)` expression, composed with `|` across two sensors, used as a
`@template_binary_sensor` body.
"""

from hassle import state_of, template_binary_sensor


def check_beacon(sensor: str, area: str):
    return state_of(sensor).eq(area)


@template_binary_sensor(name="Keaton Home Beacon")
def keaton_home_beacon():
    return check_beacon("sensor.keaton_watch_beacon_area", "Living Room") | check_beacon(
        "sensor.keaton_phone_beacon_area", "Living Room"
    )
