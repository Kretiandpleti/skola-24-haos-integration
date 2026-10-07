DOMAIN = "skola24"

CONF_STUDENT_NAME = "student_name"
CONF_ENTITY_ID = "entity_id"
CONF_SELECTION = "selection"
CONF_AVAILABLE_STUDENTS = "available_students"
CONF_SCHEMA_ID = "schema_id"
CONF_WEEKDAY = "week_change_weekday"
CONF_TIME = "week_change_time"
CONF_WEEKS_AHEAD = "weeks_ahead"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_TENANT_URL = "tenant_url"

DEFAULT_WEEKDAY = 7
DEFAULT_TIME = "18:00"
DEFAULT_WEEKS_AHEAD = 2
DEFAULT_UPDATE_INTERVAL = 30

WEEKDAY_NAMES = {
    1: "Måndag", 2: "Tisdag", 3: "Onsdag", 4: "Torsdag",
    5: "Fredag", 6: "Lördag", 7: "Söndag"
}

DEFAULT_TENANT_URL = "https://eskilstuna.skola24.se/"
LOGIN_PATH = "Applications/Authentication/login.aspx"
BASE_URL = "https://web.skola24.se"
VIEWER_PATH = "portal/start/timetable/timetable-viewer/{host}/"

UNIT_GUID = "Mzk3Mjc5OTAtNWU4Yi1kMzNjLWU5NzctMDg0YTkwZTkyM2Rh"
X_SCOPE = "8a22163c-8662-4535-9050-bc5e1923df48"
PERSONAL_SELECTION_TYPE = 4
PUBLIC_SELECTION_TYPE = 5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)
