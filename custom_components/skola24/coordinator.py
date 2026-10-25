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

        # Manual week navigation. None means use the automatically selected
        # week. The manual selection resets when Home Assistant restarts.
        self.manual_week = None

        # Cache lessons by ISO year/week. A cached week can be displayed
        # immediately when navigating back and forth, without another API call.
        # The normal coordinator refresh still refreshes the selected week and
        # configured future weeks in the background/at the normal interval.
        self._week_cache: dict[tuple[int, int], tuple[list, datetime]] = {}
        self._manual_navigation_pending = False

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
        """Change the displayed week, using cached data when available."""
        current_year, current_week = self.target_week()
        monday = date.fromisocalendar(current_year, current_week, 1)
        target = monday + timedelta(weeks=int(delta))
        iso = target.isocalendar()
        self.manual_week = (iso.year, iso.week)

        # If this week is already cached, update the entity immediately. This
        # avoids waiting for a network request just to display known data.
        cache_key = (iso.year, iso.week)
        if cache_key in self._week_cache:
            now = dt_util.now()
            weeks = self._weeks_payload(iso.year, iso.week)
            self.async_set_updated_data(
                self._make_data(iso.year, iso.week, weeks, [], now)
            )
            return

        # On a cache miss, fetch only the requested week. Fetching all future
        # weeks sequentially made the week-navigation buttons unnecessarily slow.
        self._manual_navigation_pending = True
        await self.async_request_refresh()

    async def async_reset_week(self) -> None:
        """Return to the automatically selected week."""
        self.manual_week = None
        target_year, target_week = self.target_week()
        cache_key = (target_year, target_week)

        if cache_key in self._week_cache:
            now = dt_util.now()
            self.async_set_updated_data(
                self._make_data(
                    target_year,
                    target_week,
                    self._weeks_payload(target_year, target_week),
                    [],
                    now,
                )
            )
            return

        self._manual_navigation_pending = True
        await self.async_request_refresh()

    @staticmethod
    def _next_lesson(lessons, now, selected_year, selected_week):
        """Find the next lesson in the selected/display week."""
        actual = now.isocalendar()
        selected_is_future = (selected_year, selected_week) != (actual.year, actual.week)

        # If a future week is selected, return the first lesson in that week.
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

    def _weeks_payload(self, year: int, week: int) -> dict:
        """Return cached lessons for the selected week and configured weeks ahead."""
        weeks = {}
        first = date.fromisocalendar(year, week, 1)

        for offset in range(self.weeks_ahead + 1):
            iso = (first + timedelta(weeks=offset)).isocalendar()
            cached = self._week_cache.get((iso.year, iso.week))
            if cached is not None:
                # Keep the existing public data shape expected by sensors/cards.
                weeks[str(iso.week)] = cached[0]

        return weeks

    def _make_data(
        self,
        year: int,
        week: int,
        weeks: dict,
        failed: list,
        now: datetime,
    ) -> dict:
        """Build coordinator data using the same attributes as previous versions."""
        current = weeks.get(str(week))
        cache_entry = self._week_cache.get((year, week))

        if current is None and cache_entry is not None:
            current = cache_entry[0]

        if current is None:
            raise UpdateFailed(f"Kunde inte hämta vald vecka {week}/{year}.")

        # Report when this week's timetable was actually fetched, not when a
        # cached week was merely selected in the UI.
        updated = cache_entry[1] if cache_entry is not None else now

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
            "updated": updated.isoformat(),
            "last_update": updated.isoformat(),
            "manual_week": self.manual_week is not None,
        }

    async def _async_update_data(self):
        year, week = self.target_week()
        first = date.fromisocalendar(year, week, 1)

        # A week-button cache miss only fetches the selected week. During normal
        # scheduled refreshes, keep refreshing the selected week plus weeks ahead.
        navigation_only = self._manual_navigation_pending
        self._manual_navigation_pending = False
        offsets = range(1) if navigation_only else range(self.weeks_ahead + 1)

        failed = []
        now = dt_util.now()

        for offset in offsets:
            d = first + timedelta(weeks=offset)
            iso = d.isocalendar()
            cache_key = (iso.year, iso.week)

            try:
                lessons = await self.hass.async_add_executor_job(
                    self.client.render_week,
                    iso.week,
                    iso.year,
                    self.schema_id,
                    self.selection,
                    self.selection_type,
                )
                fetched_at = dt_util.now()
                self._week_cache[cache_key] = (lessons, fetched_at)
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

        # Keep cached weeks in the output even when a navigation refresh only
        # fetched one week or an optional future week failed.
        weeks = self._weeks_payload(year, week)

        if (year, week) not in self._week_cache:
            raise UpdateFailed(
                f"Kunde inte hämta vald vecka {week}/{year}."
            )

        now = dt_util.now()
        return self._make_data(year, week, weeks, failed, now)
