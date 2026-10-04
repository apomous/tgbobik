"""Клиент Модеуса ТюмГУ: автоматический вход и получение расписания."""
import base64
import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from playwright.sync_api import sync_playwright

TZ = timezone(timedelta(hours=5))  # Тюмень, UTC+5
BASE = "https://utmn.modeus.org"
START_URL = (BASE + "/schedule-calendar/my"
             "?timeZone=%22Asia%2FTyumen%22&calendar=%7B%22view%22:%22agendaWeek%22%7D")
API = BASE + "/schedule-calendar-v2/api/calendar"
EVENTS_URL = API + "/events/search?tz=Asia/Tyumen"
HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "modeus_state.json"  # сессия браузера, держите в секрете
FAIL_PNG = HERE / "modeus_fail.png"
RAW_JSON = HERE / "modeus_last_raw.json"

_cache = {"token": None, "exp": 0.0, "person_id": None}
_types: dict = {}


def _jwt_payload(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def _login() -> None:
    """Заходит в Модеус headless-браузером и запоминает токен."""
    login, password = os.environ["MODEUS_LOGIN"], os.environ["MODEUS_PASSWORD"]
    found: dict = {}

    def on_request(req):
        if "/schedule-calendar-v2/api/" in req.url:
            auth = req.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                found["bearer"] = auth[7:]

    def on_nav(frame):
        if "id_token=" in frame.url:
            frag = parse_qs(urlparse(frame.url).fragment)
            found["id_token"] = (frag.get("id_token") or [None])[0]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(
                storage_state=str(STATE_FILE) if STATE_FILE.exists() else None)
        except Exception:
            logging.exception("state load")
            ctx = browser.new_context()
        page = ctx.new_page()
        page.on("request", on_request)
        page.on("framenavigated", on_nav)
        try:
            page.goto(START_URL, wait_until="domcontentloaded")
        except Exception:
            logging.exception("goto")

        filled = False
        deadline = time.time() + 60
        while time.time() < deadline and "bearer" not in found:
            if not filled:
                try:
                    pw = page.locator("input[type=password]:visible")
                    if pw.count():
                        user = page.locator(
                            "input[type=text]:visible, input[type=email]:visible,"
                            " input:not([type]):visible")
                        if user.count():
                            user.first.fill(login)
                        pw.first.fill(password)
                        pw.first.press("Enter")
                        filled = True
                except Exception:
                    pass
            page.wait_for_timeout(300)

        if "bearer" not in found:
            page.screenshot(path=str(FAIL_PNG))
            browser.close()
            raise RuntimeError("Не удалось войти в Модеус (скриншот: modeus_fail.png)")

        try:
            ctx.storage_state(path=str(STATE_FILE))
        except Exception:
            logging.exception("state save")
        browser.close()

    token = found["bearer"]
    payload = _jwt_payload(token)
    pid = payload.get("person_id") or _jwt_payload(found.get("id_token") or "").get("person_id")
    _cache.update(
        token=token,
        exp=float(payload["exp"]) - 120 if payload.get("exp") else time.time() + 40 * 60,
        person_id=pid,
    )


def get_token(force: bool = False):
    if force or not _cache["token"] or time.time() > _cache["exp"]:
        _login()
    return _cache["token"], _cache["person_id"]


# ---------- разбор ответа ----------
def _utc(d: date) -> str:
    dt = datetime(d.year, d.month, d.day, tzinfo=TZ).astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_dt(s):
    if not s:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.astimezone(TZ) if dt.tzinfo else dt.replace(tzinfo=TZ)


def _last(href) -> str:
    return (href or "").rstrip("/").split("/")[-1]


def _link(item: dict, name: str) -> str:
    return _last(item.get("_links", {}).get(name, {}).get("href"))


def _person_name(p: dict) -> str:
    return p.get("fullName") or " ".join(
        x for x in (p.get("lastName"), p.get("firstName"), p.get("middleName")) if x)


BUILDING_ADDR = {
    "главный": "ул. Республики, 9",
    "03": "ул. Осипенко, 2",
    "04": "ул. Ленина, 16",
    "05": "ул. Перекопская, 15а",
    "06": "ул. Пирогова, 3",
    "07": "ул. Пржевальского, 37, корпус 1",
    "08": "ул. Пржевальского, 37",
    "09": "ул. Ленина, 6",
    "10": "ул. Ленина, 38",
    "11": "ул. Ленина, 23",
    "12": "ул. Семакова, 18",
    "13": "ул. Барнаульская, 41",
    "14": "ул. Тургенева, 9",
    "15": "ул. Республики, 18",
    "17": "ул. Ленина, 25",
}


def _building_text(bname: str) -> str:
    """'Корпус-04' -> 'Корпус-04 (ул. Ленина, 16)'."""
    if not bname:
        return ""
    low = bname.lower()
    addr = None
    if "главн" in low:
        addr = BUILDING_ADDR["главный"]
    else:
        m = re.search(r"(\d+)", bname)
        if m:
            addr = BUILDING_ADDR.get(f"{int(m.group(1)):02d}")
    return f"{bname} ({addr})" if addr else bname


def _load_types(token: str) -> None:
    """Справочник типов занятий: id -> название."""
    if _types:
        return
    try:
        r = requests.get(API + "/event-types", timeout=20,
                         headers={"Authorization": f"Bearer {token}"})
        data = r.json()
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if "id" in x and "name" in x and isinstance(x["name"], str):
                    _types[x["id"]] = x["name"]
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    except Exception:
        logging.exception("event-types")


def _parse(data: dict) -> list[dict]:
    emb = data.get("_embedded", {})
    rooms = {r.get("id"): r for r in emb.get("rooms", [])}
    persons = {p.get("id"): p for p in emb.get("persons", [])}
    courses = {c.get("id"): c for c in emb.get("course-unit-realizations", [])}

    room_by_event = {}
    for er in emb.get("event-rooms", []):
        ev_id = _link(er, "event") or er.get("eventId")
        room = rooms.get(_link(er, "room") or er.get("roomId"))
        if ev_id and room:
            b = room.get("building") or {}
            bname = _building_text(b.get("name") or b.get("nameShort") or "")
            rname = room.get("name") or room.get("nameShort") or ""
            room_by_event[ev_id] = ", ".join(x for x in (rname, bname) if x)
    for loc in emb.get("event-locations", []):  # онлайн / нестандартное место
        ev_id = loc.get("eventId") or _link(loc, "event")
        if ev_id and ev_id not in room_by_event and loc.get("customLocation"):
            room_by_event[ev_id] = loc["customLocation"]

    teachers = defaultdict(list)
    for a in emb.get("event-attendees", []):
        role = f"{a.get('roleId') or ''} {a.get('roleName') or ''}"
        if "TEACH" in role.upper() or "преподав" in role.lower():
            ev_id = _link(a, "event") or a.get("eventId")
            p = persons.get(_link(a, "person") or a.get("personId"))
            if ev_id and p:
                name = _person_name(p)
                if name and name not in teachers[ev_id]:
                    teachers[ev_id].append(name)

    out = []
    for e in emb.get("events", []):
        start = _parse_dt(e.get("start") or e.get("startsAt"))
        end = _parse_dt(e.get("end") or e.get("endsAt"))
        if not start:
            continue
        course = courses.get(_link(e, "course-unit-realization")
                             or e.get("courseUnitRealizationId")) or {}
        topic = e.get("name") or e.get("nameShort") or ""
        course_name = course.get("name") or course.get("nameShort") or ""
        eid = e.get("id")
        out.append({
            "course": course_name,
            "topic": topic,
            "type": _types.get(e.get("typeId")) or "",
            "start": start,
            "end": end,
            "room": room_by_event.get(eid, ""),
            "teachers": teachers.get(eid, []),
        })
    out.sort(key=lambda x: x["start"])
    return out


def fetch_events(d1: date, d2: date, person_id: str | None = None) -> list[dict]:
    """События с d1 (включительно) по d2 (не включая)."""
    for attempt in (0, 1):
        token, my_id = get_token(force=attempt == 1)
        _load_types(token)
        body = {
            "size": 500,
            "timeMin": _utc(d1),
            "timeMax": _utc(d2),
            "attendeePersonId": [person_id or my_id],
        }
        r = requests.post(EVENTS_URL, json=body, timeout=30,
                          headers={"Authorization": f"Bearer {token}"})
        if r.status_code in (401, 403) and attempt == 0:
            continue  # токен протух — логинимся заново
        r.raise_for_status()
        data = r.json()
        if os.environ.get("MODEUS_DEBUG"):
            RAW_JSON.write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return _parse(data)
    return []


# ---------- оформление ----------
DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def format_event(e: dict) -> str:
    t = f"⏰ {e['start']:%H:%M}"
    if e["end"]:
        t += f" - {e['end']:%H:%M}"
    lines = [t]
    name = " | ".join(x for x in (e["course"], e["topic"]) if x)
    if name:
        lines.append(f"📚 {name}")
    if e["type"]:
        lines.append(f"🧪 {e['type']}")
    if e["room"]:
        lines.append(f"🏫 {e['room']}")
    if e["teachers"]:
        lines.append(f"👨‍🏫 {', '.join(e['teachers'])}")
    return "\n".join(lines)


def format_events(events: list[dict], title: str, by_day: bool = False) -> str:
    if not events:
        return f"{title}\nПар нет 🎉"
    parts = [title]
    cur = None
    for e in events:
        if by_day and e["start"].date() != cur:
            cur = e["start"].date()
            parts.append(f"━━ {DAYS[cur.weekday()]} {cur:%d.%m} ━━")
        parts.append(format_event(e))
    return "\n\n".join(parts)
