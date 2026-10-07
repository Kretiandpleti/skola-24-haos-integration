from __future__ import annotations

from datetime import date, datetime, timedelta, time
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Skola24Client
from .const import DEFAULT_TENANT_URL, PUBLIC_SELECTION_TYPE

_LOGGER = logging.getLogger(__name__)


class Skola24Coordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass,
        username,
        password,
        weekday,
        switch_time,
        weeks_ahead,
        update_interval,
        schema_id=None,
        selection=None,
        selection_type=PUBLIC_SELECTION_TYPE,
        tenant_url=DEFAULT_TENANT_URL,
    ):
        self.client = Skola24Client(username, password, tenant_url)
        self.weekday = int(weekday)
        self.switch_time = switch_time
        self.weeks_ahead = int(weeks_ahead)
        self.schema_id = str(schema_id).strip() if schema_id else None
        self.selection = selection
        self.selection_type = int(selection_type or PUBLIC_SELECTION_TYPE)
        # Manual week navigation. None means use the automatic week selected
        # by the configured weekday/time. The manual selection survives normal
        # refreshes and is reset when Home Assistant restarts.
        self.manual_week = None

        super().__init__(
            hass,
            _LOGGER,
            name="Skola24",
            update_interval=timedelta(minutes=int(update_interval)),
        )

    def target_week(self):
        """Return the week selected by manual navigation or schedule."""
        if self.manual_week is not None:
            return self.manual_week

        now = dt_util.now()
        switch = time.fromisoformat(str(self.switch_time)[:5])
        iso = now.isocalendar()

        after_switch = (
            now.isoweekday() > self.weekday
            or (
                now.isoweekday() == self.weekday
                and now.time() >= switch
            )
        )

        if not after_switch:
            return iso.year, iso.week

        next_monday = date.fromisocalendar(iso.year, iso.week, 1) + timedelta(weeks=1)
        nxt = next_monday.isocalendar()
        return nxt.year, nxt.week

    async def async_change_week(self, delta: int) -> None:
        """Move the displayed week backward/forward and refresh the data."""
        current_year, current_week = self.target_week()
        monday = date.fromisocalendar(current_year, current_week, 1)
        target = monday + timedelta(weeks=int(delta))
        iso = target.isocalendar()
        self.manual_week = (iso.year, iso.week)
        await self.async_request_refresh()

    async def async_reset_week(self) -> None:
        """Return to the automatically selected week."""
        self.manual_week = None
        await self.async_request_refresh()

    @staticmethod
    def _next_lesson(lessons, now, selected_year, selected_week):
        """Find the next lesson in the selected/display week."""
        actual = now.isocalendar()
        selected_is_future = (selected_year, selected_week) != (actual.year, actual.week)

        # When the integration is already showing a future week (for example
        # Sunday after the configured week switch), the next lesson is simply
        # the first lesson in that selected week.
        if selected_is_future:
            candidates = list(lessons)
            candidates.sort(
                key=lambda x: (
                    int(x.get("dayOfWeekNumber") or x.get("day_of_week") or 99),
                    x.get("start") or x.get("timeStart") or "",
                )
            )
            return candidates[0] if candidates else None

        candidates = []

        for lesson in lessons:
            try:
                day = int(
                    lesson.get("dayOfWeekNumber")
                    or lesson.get("day_of_week")
                    or 0
                )
            except (TypeError, ValueError):
                day = 0

            if day < now.isoweekday():
                continue

            if day == now.isoweekday():
                start = lesson.get("start") or lesson.get("timeStart") or ""
                try:
                    hhmm = start[:5]
                    hour, minute = [int(x) for x in hhmm.split(":")]
                    if (hour, minute) <= (now.hour, now.minute):
                        continue
                except (ValueError, AttributeError):
                    pass

            candidates.append(lesson)

        candidates.sort(
            key=lambda x: (
                int(
                    x.get("dayOfWeekNumber")
                    or x.get("day_of_week")
                    or 99
                ),
                x.get("start") or x.get("timeStart") or "",
            )
        )

        return candidates[0] if candidates else None

    async def _async_update_data(self):
        year, week = self.target_week()
        first = date.fromisocalendar(year, week, 1)

        weeks = {}
        failed = []

        for offset in range(self.weeks_ahead + 1):
            d = first + timedelta(weeks=offset)
            iso = d.isocalendar()

            try:
                lessons = await self.hass.async_add_executor_job(
                    self.client.render_week,
                    iso.week,
                    iso.year,
                    self.schema_id,
                    self.selection,
                    self.selection_type,
                )
                weeks[str(iso.week)] = lessons
                _LOGGER.debug(
                    "Skola24 vecka %s/%s: %s lektioner",
                    iso.week,
                    iso.year,
                    len(lessons),
                )
            except Exception as err:
                failed.append({
                    "week": iso.week,
                    "year": iso.year,
                    "error": str(err),
                })
                _LOGGER.warning(
                    "Kunde inte hämta Skola24 vecka %s/%s: %s",
                    iso.week,
                    iso.year,
                    err,
                )

        # The selected/display week MUST work. Future weeks are optional.
        current = weeks.get(str(week))
        if current is None:
            raise UpdateFailed(
                f"Kunde inte hämta vald vecka {week}/{year}."
            )

        now = dt_util.now()
        switch = time.fromisoformat(str(self.switch_time)[:5])
        after_switch = (
            now.isoweekday() > self.weekday
            or (now.isoweekday() == self.weekday and now.time() >= switch)
        )
        return {
            "current_week": week,
            "current_year": year,
            "requested_week": week,
            "requested_year": year,
            "weeks_loaded": [int(x) for x in weeks],
            "lesson_count": len(current),
            "lessons": current,
            "next_lesson": self._next_lesson(current, now, year, week),
            "weeks": weeks,
            "weeks_failed": failed,
            "week_change_weekday": self.weekday,
            "week_change_time": str(self.switch_time)[:5],
            "weeks_ahead": self.weeks_ahead,
            "schema_id": self.schema_id,
            "selection": self.selection,
            "selection_type": self.selection_type,
            "updated": now.isoformat(),
            "last_update": now.isoformat(),
            "manual_week": self.manual_week is not None,
        }
