from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENTITY_ID,
    CONF_SELECTION,
    CONF_SCHEMA_ID,
    CONF_STUDENT_NAME,
    CONF_TIME,
    CONF_TENANT_URL,
    CONF_UPDATE_INTERVAL,
    CONF_WEEKDAY,
    CONF_WEEKS_AHEAD,
    DEFAULT_TIME,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WEEKDAY,
    DEFAULT_WEEKS_AHEAD,
    DOMAIN,
)
from .coordinator import Skola24Coordinator

PLATFORMS = ["sensor", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    settings = {**entry.data, **entry.options}

    coordinator = Skola24Coordinator(
        hass,
        settings[CONF_USERNAME],
        settings[CONF_PASSWORD],
        settings.get(CONF_WEEKDAY, DEFAULT_WEEKDAY),
        settings.get(CONF_TIME, DEFAULT_TIME),
        settings.get(CONF_WEEKS_AHEAD, DEFAULT_WEEKS_AHEAD),
        settings.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        settings.get(CONF_SCHEMA_ID),
        settings.get(CONF_SELECTION),
        settings.get("selection_type", 5),
        settings.get(CONF_TENANT_URL),
    )

    coordinator.student_name = settings.get(CONF_STUDENT_NAME, "Elev")
    coordinator.entity_object_id = settings.get(CONF_ENTITY_ID, "skola24_schema")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return ok
