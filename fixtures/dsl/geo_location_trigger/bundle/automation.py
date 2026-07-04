"""Golden case: `geo_location` trigger builder.

Mirrors fixtures/configs/automation_geo_location_trigger.json.
"""

from hassle import automation, geo_location, service, when


@automation(id="geo_location_trigger", alias="Geo Location Trigger")
def geo_location_trigger():
    when(geo_location(source="nsw_rural_fire_service_feed", zone="zone.home", event="enter"))
    service("notify.mobile_app", message="Geolocation event")
