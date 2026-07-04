"""Golden case: helper declarations for all nine storage-collection domains.

Each declaration is a whole top-level object (DESIGN §5.7); the compiler must
land every one in CompileResult.objects under "<domain>:<id>". Declaring them
also returns an EntityRef usable elsewhere in the bundle.
"""

from hassle import (
    counter,
    input_boolean,
    input_button,
    input_datetime,
    input_number,
    input_select,
    input_text,
    schedule,
    timer,
)

input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
input_number(id="target_temp", name="Target Temp", min=10, max=30, step=0.5, mode="slider")
input_select(id="house_mode", name="House Mode", options=["home", "away", "night"])
input_text(id="last_message", name="Last Message", max=255)
input_datetime(id="wake_time", name="Wake Time", has_date=False, has_time=True)
input_button(id="run_scene", name="Run Scene")
counter(id="door_opens", name="Door Opens", initial=0, step=1)
timer(id="cooldown", name="Cooldown", duration="00:05:00")
schedule(id="heating", name="Heating Schedule")
