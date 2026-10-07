from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ENTITY_ID, CONF_STUDENT_NAME, CONF_AVAILABLE_STUDENTS, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entity = Skola24Sensor(coordinator, entry)
    async_add_entities([entity])

    # Home Assistant may otherwise append the entity name to the configured
    # object_id. Force the entity registry to use the exact object ID entered
    # by the user (for example sensor.skola24_elev).
    desired_object_id = (
        coordinator.entity_object_id or "skola24_schema"
    ).strip().lower()
    registry = er.async_get(hass)
    if entity.entity_id:
        desired_entity_id = f"sensor.{desired_object_id}"
        if entity.entity_id != desired_entity_id:
            try:
                registry.async_update_entity(
                    entity.entity_id,
                    new_entity_id=desired_entity_id,
                )
            except ValueError:
                # Keep the existing entity ID if the requested one is already
                # occupied by another entity. The integration remains usable.
                pass


class Skola24Sensor(CoordinatorEntity, SensorEntity):
    # Keep the configured object_id as the complete entity_id.
    # With has_entity_name=True Home Assistant appends the entity name
    # (for example _elev_schema), which breaks the user-configured ID.
    _attr_has_entity_name = False
    _attr_icon = "mdi:calendar-account"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry

        settings = {**entry.data, **entry.options}
        self._student_name = settings.get(CONF_STUDENT_NAME, "Elev")
        object_id = settings.get(CONF_ENTITY_ID, "skola24_schema")

        self._attr_unique_id = f"{entry.entry_id}_schema"
        self._attr_suggested_object_id = getattr(
            coordinator, "entity_object_id", "skola24_schema"
        )
        self._attr_name = f"{self._student_name} Schema"
        self._attr_suggested_object_id = object_id
        self._attr_native_value = "Laddar..."

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": f"Skola24 – {self._student_name}",
            "manufacturer": "Skola24",
            "model": "Schema",
        }

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return "Laddar..."
        week = data.get("current_week")
        return f"Vecka {week}" if week is not None else "Okänd"

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {
            "student_name": self._student_name,
            "current_week": data.get("current_week"),
            "current_year": data.get("current_year"),
            "requested_week": data.get("requested_week"),
            "requested_year": data.get("requested_year"),
            "weeks_loaded": data.get("weeks_loaded", []),
            "lesson_count": data.get("lesson_count", 0),
            "lessons": data.get("lessons", []),
            "next_lesson": data.get("next_lesson"),
            "weeks": data.get("weeks", {}),
            "weeks_failed": data.get("weeks_failed", []),
            "week_change_weekday": data.get("week_change_weekday"),
            "week_change_time": data.get("week_change_time"),
            "weeks_ahead": data.get("weeks_ahead"),
            "updated": data.get("updated"),
            "last_update": data.get("last_update"),
            "manual_week": data.get("manual_week", False),
            "schema_id": data.get("schema_id"),
            "available_students": self._entry.options.get(CONF_AVAILABLE_STUDENTS, self._entry.data.get(CONF_AVAILABLE_STUDENTS, [])),
        }

    @property
    def available(self):
        return self.coordinator.data is not None

    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data or {}
        week = data.get("current_week")
        self._attr_native_value = (
            f"Vecka {week}" if week is not None else "Okänd"
        )
        super()._handle_coordinator_update()
