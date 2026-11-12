"""Сборщики с сайтов-афиш. Каждая функция возвращает список событий
dict(title, date, end_date, time, venue, price, category, description, url, image)."""
import base64
import re
import time
from datetime import datetime

import requests

from extract import find_category, is_commerce

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}

AFISHA_SECTIONS = {
    "concerts": "Концерт", "theatres": "Театр", "exhibitions": "Выставка", "standup": "Стендап",
    "cinema": "Кино", "kids": "Детям", "parties": "Вечеринка", "clubs": "Вечеринка",
    "lectures": "Лекция", "education": "Лекция", "znaniya": "Лекция", "festivals": "Фестиваль",
    "sport": "Спорт", "children": "Детям",
}
AFISHA_SKIP = {"shops"}          # магазины, скидки, коллекции — не мероприятия


def afisha_uz(max_pages=10):
    """Открытый JSON API afisha.uz: текущие и предстоящие события."""
    base = "https://www.afisha.uz"
    url = "/api/event_schedules/current_and_upcoming?page=1"
    events, pages = [], 0
    while url and pages < max_pages:
        r = requests.get(base + url, headers={**UA, "Accept": "application/ld+json"}, timeout=30)
        r.raise_for_status()
        data = r.json()
        for it in data.get("hydra:member", []):
            ev, place = it.get("event") or {}, it.get("place") or {}
            if place.get("city") not in (None, "/api/cities/1"):          # только Ташкент
                continue
            start = datetime.fromisoformat(it["startedAt"])
            end = datetime.fromisoformat(it["endedAt"]) if it.get("endedAt") else None
            sections = ev.get("sections") or []
            if any(s["slug"] in AFISHA_SKIP for s in sections) or is_commerce(ev.get("title", "")):
                continue
            slug = sections[0]["slug"] if sections else "gorod"
            category = next((AFISHA_SECTIONS[s["slug"]] for s in sections if s["slug"] in AFISHA_SECTIONS),
                            None) or find_category(ev.get("title", ""))
            try:
                path = base64.b64decode(ev.get("permalink", "")).decode()
            except Exception:
                path = ""
            img = None
            mo = ev.get("mainMediaObject") or {}
            for v in mo.get("variants", []):
                if v.get("type") == "medium":
                    img = base + v["url"]
            venue = place.get("name")
            if venue and place.get("address"):
                venue += ", " + place["address"]
            events.append({
                "title": ev.get("title", "").strip(),
                "date": start.date().isoformat(),
                "end_date": end.date().isoformat() if end and end.date() > start.date() else None,
                "time": start.strftime("%H:%M") if it.get("isExactStartTime") else None,
                "venue": venue,
                "price": None,
                "category": category,
                "description": re.sub(r"\s+", " ", ev.get("intro") or "").strip(),
                "url": f"{base}/ru/{slug}{path}" if path else base,
                "image": img,
            })
        url = (data.get("hydra:view") or {}).get("hydra:next")
        pages += 1
        time.sleep(0.5)
    return events


SCRAPERS = {"afisha.uz": afisha_uz}
