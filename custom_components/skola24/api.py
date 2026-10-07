from __future__ import annotations

import html
import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
import requests
import base64
import re

from .const import (
    BASE_URL, PERSONAL_SELECTION_TYPE, PUBLIC_SELECTION_TYPE,
    DEFAULT_TENANT_URL, LOGIN_PATH, UNIT_GUID, USER_AGENT, VIEWER_PATH, X_SCOPE
)


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms, self.current = [], None
        self.current_select, self.current_option = None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs); tag = tag.lower()
        if tag == "form":
            self.current = {"action": a.get("action", ""), "inputs": [], "selects": []}
            self.forms.append(self.current)
        elif tag == "input" and self.current is not None:
            self.current["inputs"].append(a)
        elif tag == "select" and self.current is not None:
            self.current_select = {"name": a.get("name", ""), "options": []}
        elif tag == "option" and self.current_select is not None:
            self.current_option = a
            self.current_select["options"].append({
                "value": a.get("value", ""), "text": "", "selected": "selected" in a
            })

    def handle_data(self, data):
        if self.current_select is not None and self.current_option is not None:
            self.current_select["options"][-1]["text"] += data.strip()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "option":
            self.current_option = None
        elif tag == "select":
            self.current["selects"].append(self.current_select)
            self.current_select = None
        elif tag == "form":
            self.current = None


class Skola24Error(Exception):
    pass


class Skola24Client:
    def __init__(self, username, password, tenant_url=DEFAULT_TENANT_URL):
        self.username, self.password = username, password
        self.tenant_url = str(tenant_url or DEFAULT_TENANT_URL).strip()
        if not self.tenant_url.endswith("/"):
            self.tenant_url += "/"
        self.host = (urlparse(self.tenant_url).hostname or "").lower()
        if not self.host:
            raise Skola24Error("Ogiltig Skola24-domän.")
        self.login_url = urljoin(self.tenant_url, LOGIN_PATH)
        self.viewer_url = "https://web.skola24.se/portal/start/timetable/timetable-viewer/" + self.host + "/"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def login(self):
        self.session.get(self.tenant_url, timeout=30).raise_for_status()
        page = self.session.get(self.login_url, timeout=30)
        page.raise_for_status()

        parser = FormParser(); parser.feed(page.text)
        form = next((f for f in parser.forms if any(
            (x.get("type") or "").lower() == "password" for x in f["inputs"]
        )), None)
        if not form:
            raise Skola24Error("Hittade inget Skola24-loginformulär.")

        pw = next(x for x in form["inputs"] if (x.get("type") or "").lower() == "password")
        idx = form["inputs"].index(pw)
        user = next((x for x in reversed(form["inputs"][:idx])
                     if x.get("name") and (x.get("type") or "text").lower() in ("text","email")), None)
        if not user:
            raise Skola24Error("Hittade inget användarnamnsfält.")

        data = {}
        for x in form["inputs"]:
            if x.get("name") and (x.get("type") or "").lower() == "hidden":
                data[x["name"]] = html.unescape(x.get("value", ""))

        for sel in form["selects"]:
            chosen = next((o for o in sel["options"]
                           if self.host in o["text"].lower()), None)
            if chosen is None:
                chosen = next((o for o in sel["options"] if o["selected"]), None)
            if chosen:
                data[sel["name"]] = chosen["value"]

        data[user["name"]] = self.username
        data[pw["name"]] = self.password

        submit = next((x for x in form["inputs"]
                       if (x.get("type") or "").lower() == "submit" and x.get("name")), None)
        if submit:
            data[submit["name"]] = submit.get("value", "")

        action = urljoin(page.url, form["action"] or page.url)
        r = self.session.post(action, data=data, allow_redirects=True, timeout=30)
        r.raise_for_status()

        if "login.aspx" in r.url.lower() or "defaulterrorpage.aspx" in r.url.lower():
            raise Skola24Error("Skola24-inloggningen misslyckades.")

    @staticmethod
    def _selection_token(value):
        """Normalize a selection value to Skola24's base64 string form."""
        if not value:
            return ""
        value = str(value).strip()
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8")
            if len(decoded) >= 20 and "-" in decoded:
                return value
        except Exception:
            pass
        if len(value) >= 20 and "-" in value:
            return base64.b64encode(value.encode("utf-8")).decode("ascii")
        return value

    @staticmethod
    def _student_from_obj(obj, context_key=""):
        """Extract a student from a Skola24 selection object.

        The public viewer endpoint commonly returns students as objects with
        only guid/firstName/lastName fields, so the surrounding collection
        name (for example ``students``) is also used as a strong hint.
        """
        if not isinstance(obj, dict):
            return None
        lower = {str(k).lower(): v for k, v in obj.items()}
        name = None
        for key in ("name", "displayname", "studentname", "fullname", "text", "label"):
            if lower.get(key):
                name = str(lower[key]).strip()
                break
        if not name:
            first = lower.get("firstname") or lower.get("first_name") or ""
            last = lower.get("lastname") or lower.get("last_name") or ""
            name = f"{first} {last}".strip()

        selection = None
        for key in (
            "selection", "selectionguid", "selectionid", "studentguid",
            "studentid", "personguid", "personid", "guid", "id"
        ):
            if lower.get(key) not in (None, ""):
                selection = lower[key]
                break
        if not name or selection in (None, ""):
            return None

        hints = " ".join(str(k) for k in lower.keys()) + " " + str(context_key).lower()
        if not any(x in hints for x in ("student", "selection", "person", "child", "pupil")):
            return None

        token = Skola24Client._selection_token(selection)
        if not token:
            return None
        try:
            selection_type = int(
                lower.get("selectiontype")
                or lower.get("selection_type")
                or 5
            )
        except (TypeError, ValueError):
            selection_type = 5
        return {"name": name, "selection": token, "selection_type": selection_type}

    @classmethod
    def _extract_students(cls, obj):
        found = []

        def walk(v, context_key=""):
            if isinstance(v, dict):
                item = cls._student_from_obj(v, context_key)
                if item:
                    found.append(item)
                for key, child in v.items():
                    walk(child, str(key))
            elif isinstance(v, list):
                for child in v:
                    walk(child, context_key)

        walk(obj)
        unique = {}
        for item in found:
            unique[(item["name"].casefold(), item["selection"])] = item
        return list(unique.values())

    @staticmethod
    def _safe_endpoint(url):
        """Return only the path/query-free endpoint for diagnostics."""
        try:
            from urllib.parse import urlsplit
            return urlsplit(url).path
        except Exception:
            return str(url).split("?")[0]

    @classmethod
    def _extract_html_students(cls, text):
        """Best-effort extraction from authenticated HTML/inline JSON.

        Skola24 has changed its web frontend several times.  Rather than
        depending on one undocumented endpoint, inspect the authenticated
        pages/scripts for the same student objects the browser receives.
        """
        found = []

        # JSON-ish objects containing guid + first/last name.
        patterns = [
            re.compile(
                r'\{[^{}]{0,2500}?(?:"|\')?(?:guid|studentGuid|personGuid)(?:"|\')?\s*:\s*(?:"|\')([^"\']+)(?:"|\')[^{}]{0,2500}?(?:"|\')?(?:firstName|firstname)(?:"|\')?\s*:\s*(?:"|\')([^"\']+)(?:"|\')[^{}]{0,1500}?(?:"|\')?(?:lastName|lastname)(?:"|\')?\s*:\s*(?:"|\')([^"\']*)(?:"|\')',
                re.I | re.S,
            ),
            re.compile(
                r'\{[^{}]{0,2500}?(?:"|\')?(?:studentName|displayName|fullName)(?:"|\')?\s*:\s*(?:"|\')([^"\']+)(?:"|\')[^{}]{0,2500}?(?:"|\')?(?:selection|selectionGuid|studentId|personId|guid)(?:"|\')?\s*:\s*(?:"|\')([^"\']+)(?:"|\')',
                re.I | re.S,
            ),
        ]
        for m in patterns[0].finditer(text):
            guid, first, last = m.groups()
            name = f"{first} {last}".strip()
            if name and guid:
                found.append({"name": name, "selection": cls._selection_token(guid), "selection_type": 5})
        for m in patterns[1].finditer(text):
            name, guid = m.groups()
            if name and guid:
                found.append({"name": name.strip(), "selection": cls._selection_token(guid), "selection_type": 5})

        unique = {}
        for item in found:
            if item["selection"]:
                unique[(item["name"].casefold(), item["selection"])] = item
        return list(unique.values())

    @staticmethod
    def _script_sources(html_text, base_url):
        sources = []
        for match in re.finditer(r'<script[^>]+src=["\']([^"\']+)', html_text, re.I):
            sources.append(urljoin(base_url, html.unescape(match.group(1))))
        return list(dict.fromkeys(sources))

    @staticmethod
    def _strip_html(text):
        """Turn authenticated settings HTML into compact visible text."""
        try:
            from html.parser import HTMLParser

            class _Text(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.parts = []
                def handle_data(self, data):
                    if data and data.strip():
                        self.parts.append(data.strip())

            parser = _Text()
            parser.feed(text)
            return " ".join(parser.parts)
        except Exception:
            return re.sub(r"<[^>]+>", " ", text)

    @staticmethod
    def _extract_schema_ids(text):
        """Extract child names + SchemaID values from the authenticated settings page."""
        visible = Skola24Client._strip_html(text)
        found = []

        # The settings page displays rows similar to:
        #   Exempel Elevnamn  SchemaID: BA26BEbRy
        # Keep this deliberately broad because the legacy ASP.NET frontend
        # has changed markup between Skola24 releases.
        patterns = [
            re.compile(
                r"([A-ZÅÄÖ][A-Za-zÅÄÖåäöÉé'’.-]*(?:\s+[A-ZÅÄÖ][A-Za-zÅÄÖåäöÉé'’.-]*){1,4})\s+SchemaID\s*:\s*([A-Za-z0-9_-]{4,64})",
                re.I,
            ),
            re.compile(
                r"SchemaID\s*:\s*([A-Za-z0-9_-]{4,64})\s+([A-ZÅÄÖ][A-Za-zÅÄÖåäöÉé'’.-]*(?:\s+[A-ZÅÄÖ][A-Za-zÅÄÖåäöÉé'’.-]*){1,4})",
                re.I,
            ),
        ]
        for pat in patterns:
            for match in pat.finditer(visible):
                if len(match.groups()) == 2:
                    if pat is patterns[0]:
                        name, schema_id = match.groups()
                    else:
                        schema_id, name = match.groups()
                    name = re.sub(r"\s+", " ", name).strip(" :,-")
                    schema_id = schema_id.strip()
                    if name and schema_id:
                        found.append({"name": name, "schema_id": schema_id})

        # Fallback: if the name is separated from SchemaID by markup/text,
        # take a short window around each SchemaID and choose the nearest
        # plausible person's name.
        for m in re.finditer(r"SchemaID\s*:\s*([A-Za-z0-9_-]{4,64})", visible, re.I):
            schema_id = m.group(1).strip()
            before = visible[max(0, m.start() - 120):m.start()]
            before = re.sub(r"\s+", " ", before).strip()
            # Prefer the last 2-5 title-cased words immediately before SchemaID.
            words = re.findall(r"[A-ZÅÄÖ][A-Za-zÅÄÖåäöÉé'’.-]*", before)
            if words:
                for count in range(min(5, len(words)), 1, -1):
                    name = " ".join(words[-count:]).strip()
                    if name.lower() not in {"mina barn", "schemaid"}:
                        found.append({"name": name, "schema_id": schema_id})
                        break

        unique = {}
        for item in found:
            unique[(item["name"].casefold(), item["schema_id"])] = item
        return list(unique.values())

    def _schema_signature(self, schema_id):
        """Convert a child's SchemaID to the selection signature used by render/timetable."""
        r = self.session.post(
            f"{BASE_URL}/api/encrypt/signature",
            json={"signature": schema_id},
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "X-Scope": X_SCOPE,
                "Referer": self.tenant_url,
                "Origin": BASE_URL,
                "User-Agent": USER_AGENT,
            },
            timeout=20,
        )
        r.raise_for_status()
        payload = r.json()
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if isinstance(data, str):
            signature = data
        else:
            signature = data.get("signature") if isinstance(data, dict) else None
        signature = signature or (payload.get("signature") if isinstance(payload, dict) else None)
        if not signature:
            raise Skola24Error("Skola24 returnerade ingen signature för SchemaID.")
        return str(signature)

    def discover_students(self):
        """Discover children from authenticated Skola24 pages when available."""
        self.login()
        students = []

        pages = [
            self.tenant_url,
            urljoin(self.tenant_url, "Applications/Start/Default.aspx"),
            urljoin(self.tenant_url, "Applications/Settings/MySettings.aspx"),
            self.viewer_url,
            urljoin(self.tenant_url, "portal/start/"),
            urljoin(self.tenant_url, "portal/start/timetable/"),
        ]

        for url in pages:
            try:
                r = self.session.get(url, timeout=20)
                if not r.ok or not r.text:
                    continue
                for child in self._extract_schema_ids(r.text):
                    try:
                        signature = self._schema_signature(child["schema_id"])
                    except Exception:
                        continue
                    students.append({
                        "name": child["name"],
                        "schema_id": child["schema_id"],
                        "selection": signature,
                        "selection_type": PERSONAL_SELECTION_TYPE,
                    })
            except requests.RequestException:
                continue

        unique = {}
        for item in students:
            unique[(item["name"].casefold(), item["schema_id"])] = item
        students = list(unique.values())
        if not students:
            raise Skola24Error(
                "Kunde inte hitta barnens SchemaID automatiskt. "
                "Ange SchemaID från Skola24 → Mina inställningar → Mina barn."
            )
        return {"students": students}

    def _active_school_year(self):
        r = self.session.post(
            f"{BASE_URL}/api/get/active/school/years",
            json={"hostName": self.host, "checkSchoolYearsFeatures": False},
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/json",
                "X-Scope": X_SCOPE,
                "X-Requested-With": "XMLHttpRequest",
                "Origin": BASE_URL,
                "Referer": self.viewer_url,
                "User-Agent": USER_AGENT,
            },
            timeout=20,
        )
        r.raise_for_status()
        payload = r.json()
        years = ((payload.get("data") or {}).get("activeSchoolYears")
                 if isinstance(payload, dict) else None)
        if not years:
            raise Skola24Error("Kunde inte hämta aktuellt läsår från Skola24.")
        guid = years[0].get("guid") if isinstance(years[0], dict) else None
        if not guid:
            raise Skola24Error("Skola24 returnerade inget aktuellt schoolYear-guid.")
        return str(guid)

    def render_week(self, week, year, schema_id=None, selection=None, selection_type=None):
        """Render one week for a personal SchemaID or a legacy selection."""
        self.login()
        self.session.get(
            self.viewer_url,
            headers={"Referer": self.tenant_url, "User-Agent": USER_AGENT},
            timeout=30,
        ).raise_for_status()

        r = self.session.post(
            f"{BASE_URL}/api/get/timetable/render/key",
            json={},
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "X-Scope": X_SCOPE,
                "Referer": self.viewer_url,
                "Origin": BASE_URL,
                "User-Agent": USER_AGENT,
            },
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
        key = d.get("data", {}).get("key", "") if isinstance(d, dict) else ""
        if not key and isinstance(d, dict):
            key = d.get("key") or d.get("renderKey") or ""
        if not key:
            raise Skola24Error("Kunde inte hämta render key.")

        if schema_id:
            # Always regenerate the signature from SchemaID. This prevents a
            # stale cached selection from being reused after configuration changes.
            selection = self._schema_signature(schema_id)
            selection_type = PERSONAL_SELECTION_TYPE
        elif selection:
            selection_type = int(selection_type or PUBLIC_SELECTION_TYPE)
        else:
            raise Skola24Error("Ingen SchemaID eller schema-selection är konfigurerad.")

        school_year = self._active_school_year()
        payload = {
            "renderKey": key,
            "host": self.host,
            "unitGuid": UNIT_GUID,
            "schoolYear": school_year,
            "startDate": None,
            "endDate": None,
            "scheduleDay": 0,
            "blackAndWhite": False,
            "width": 125,
            "height": 550,
            "selectionType": int(selection_type),
            "selection": selection,
            "showHeader": False,
            "periodText": "",
            "week": week,
            "year": year,
            "privateFreeTextMode": False,
            "privateSelectionMode": None,
            "customerKey": "",
        }
        r = self.session.post(
            f"{BASE_URL}/api/render/timetable",
            json=payload,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "X-Scope": X_SCOPE,
                "Referer": self.viewer_url,
                "Origin": BASE_URL,
                "User-Agent": USER_AGENT,
            },
            timeout=30,
        )
        r.raise_for_status()
        response_payload = r.json()
        lessons = self.normalize(self.extract(response_payload))
        if not lessons:
            raise Skola24Error(f"Inga lektioner för vecka {week}/{year}.")
        return lessons

    @staticmethod
    def extract(obj):
        found = []
        def walk(v):
            if isinstance(v, dict):
                if isinstance(v.get("lessonInfo"), list):
                    found.extend(x for x in v["lessonInfo"] if isinstance(x, dict))
                if (isinstance(v.get("texts"), list) and "timeStart" in v
                        and "timeEnd" in v and "dayOfWeekNumber" in v):
                    found.append(v)
                for x in v.values(): walk(x)
            elif isinstance(v, list):
                for x in v: walk(x)
        walk(obj)

        unique = {}
        for x in found:
            key = (x.get("guidId"), x.get("dayOfWeekNumber"),
                   x.get("timeStart"), x.get("timeEnd"),
                   json.dumps(x.get("texts") or [], ensure_ascii=False))
            unique[key] = x
        return list(unique.values())

    @staticmethod
    def normalize(lessons):
        result = []
        for x in lessons:
            t = x.get("texts") or []
            result.append({
                "subject": t[0] if len(t) > 0 else "",
                "teacher": t[1] if len(t) > 1 else "",
                "room": t[2] if len(t) > 2 else "",
                "start": x.get("timeStart", ""), "end": x.get("timeEnd", ""),
                "timeStart": x.get("timeStart", ""), "timeEnd": x.get("timeEnd", ""),
                "day_of_week": x.get("dayOfWeekNumber"),
                "dayOfWeekNumber": x.get("dayOfWeekNumber"),
                "guidId": x.get("guidId", ""), "blockName": x.get("blockName", "")
            })
        return result
