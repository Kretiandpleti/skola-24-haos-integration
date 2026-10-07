from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_AVAILABLE_STUDENTS, CONF_SCHEMA_ID, CONF_SELECTION, CONF_STUDENT_NAME, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        Skola24RefreshButton(coordinator, entry),
        Skola24DiscoverStudentsButton(coordinator, entry),
        Skola24PreviousWeekButton(coordinator, entry),
        Skola24NextWeekButton(coordinator, entry),
    ])


class Skola24RefreshButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Hämta schema nu"
    _attr_icon = "mdi:calendar-refresh"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_refresh"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry.entry_id)}}

    async def async_press(self):
        await self.coordinator.async_request_refresh()


class Skola24DiscoverStudentsButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Hämta elever"
    _attr_icon = "mdi:account-search"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_discover_students"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry.entry_id)}}

    async def async_press(self):
        result = await self.hass.async_add_executor_job(
            self.coordinator.client.discover_students
        )
        students = result.get("students", [])
        options = dict(self._entry.options)
        options[CONF_AVAILABLE_STUDENTS] = students

        # If there is exactly one student, select it automatically.
        # For multiple students we leave the current selection untouched and
        # let the Options Flow present the discovered list as a dropdown.
        if len(students) == 1:
            self.coordinator.schema_id = students[0].get("schema_id")
            self.coordinator.selection = students[0].get("selection")
            self.coordinator.selection_type = int(students[0].get("selection_type", 4))
            options[CONF_SCHEMA_ID] = self.coordinator.schema_id
            options[CONF_SELECTION] = self.coordinator.selection
            options[CONF_STUDENT_NAME] = students[0]["name"]
            options["selection_type"] = self.coordinator.selection_type

        # available_students is mutable account metadata, so keep it in options.
        # This is also what the OptionsFlow reads when it builds the dropdown.
        self.hass.config_entries.async_update_entry(self._entry, options=options)

        if len(students) == 1:
            await self.coordinator.async_request_refresh()


class Skola24PreviousWeekButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Förra veckan"
    _attr_icon = "mdi:chevron-left"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_previous_week"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry.entry_id)}}

    async def async_press(self):
        await self.coordinator.async_change_week(-1)


class Skola24NextWeekButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Nästa vecka"
    _attr_icon = "mdi:chevron-right"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_next_week"

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._entry.entry_id)}}

    async def async_press(self):
        await self.coordinator.async_change_week(1)
