"""Сборщики с сайтов-афиш. Каждая функция возвращает список событий
dict(title, date, end_date, time, venue, price, category, description, url, image)."""
import base64
import html
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

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


# =================================================================== билетные сервисы
TASHKENT = timezone(timedelta(hours=5))      # в Узбекистане нет перехода на летнее время


def _local(dt):
    """Время сайта → ташкентское. Время с часовым поясом пересчитываем, без пояса оставляем как есть."""
    return dt.astimezone(TASHKENT).replace(tzinfo=None) if dt.tzinfo else dt


def _price(lo, hi=None):
    if lo is None:
        return None
    try:
        lo = int(float(lo))
        hi = int(float(hi)) if hi is not None else None
    except (TypeError, ValueError):
        return None
    if lo <= 0:
        return "Бесплатно"
    fmt = lambda n: f"{n:,}".replace(",", " ")
    return f"{fmt(lo)} сум" if not hi or hi == lo else f"от {fmt(lo)} сум"


# Постоянные развлечения (продаются как «события», но мероприятиями не являются)
ATTRACTION_RE = re.compile(r"mysterium|квест|quest|зоопарк|\bzoo\b|planetari|планетари|chocolate museum|"
                           r"city tour|сити[- ]тур|экскурси|аквапарк|батут|музей шоколада|"
                           r"центр исламской цивилизации|парк\s*[\"«]?toshkent city", re.I)
# события в других городах (Навои не включаем: в Ташкенте есть ГАБТ им. Навои и улица Навои)
OTHER_CITY_RE = re.compile(
    r"самарканд|samarqand|samarkand|maroqand|мароканд|бухар|buxoro|bukhara|наманган|namangan|андижан|andijon|"
    r"ферган|farg.?ona|fergana|нукус|nukus|хив[аеы]\b|xiva|khiva|карши|qarshi|термез|termiz|ургенч|urganch|"
    r"джизак|jizzax|гулистан|guliston|коканд|qo.?qon|kokand|алматы|almaty|бишкек|bishkek", re.I)

# билет «в музей» как в место — не мероприятие; выставка или концерт в музее — мероприятие
MUSEUM_RE = re.compile(r"\bмузей\b|\bmuseum\b|\bmuzey\b|surflab", re.I)
EVENT_WORD_RE = re.compile(r"выстав|концерт|спектакл|лекци|вечер|шоу|фестивал|exhibition|concert|ko.?rgazma", re.I)
YEAR_TAIL = re.compile(r"\s*[|•—–-]\s*20\d\d\s*$")


def _event(title, start, end=None, venue=None, price=None, category=None, description="",
           url=None, image=None, exact_time=True):
    """Единый формат события для всех сайтов (+ ссылка на покупку билета)."""
    title = YEAR_TAIL.sub("", re.sub(r"\s+", " ", html.unescape(title or "")).strip())
    if not title or is_commerce(title) or ATTRACTION_RE.search(f"{title} {venue or ''}"):
        return None
    if MUSEUM_RE.search(title) and not EVENT_WORD_RE.search(title):
        return None
    if OTHER_CITY_RE.search(f"{title} {venue or ''}"):
        return None
    if venue and re.sub(r"\W", "", title.lower()) == re.sub(r"\W", "", venue.lower()):
        return None                                   # «событие» = само место (достопримечательность)
    start = _local(start)
    end = _local(end) if end else None
    category = category or find_category(title + " " + (description or ""))
    # у серии спектаклей/сеансов «дата окончания» — это конец продаж, а не ежедневное событие
    if end and (end - start).days > 3 and category != "Выставка":
        end = None
    return {
        "title": title,
        "date": start.date().isoformat(),
        "end_date": end.date().isoformat() if end and end.date() > start.date() else None,
        "time": start.strftime("%H:%M") if exact_time and (start.hour or start.minute) else None,
        "venue": venue,
        "price": price,
        "category": category,
        "description": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", description or ""))).strip()[:1200],
        "url": url,
        "ticket_url": url,
        "image": image,
    }


def _ld_events(page_html):
    """Все объекты schema.org/Event из разметки LD+JSON страницы."""
    out = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page_html, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                t = x.get("@type")
                if t == "Event" or (isinstance(t, list) and "Event" in t) or str(t).endswith("Event"):
                    out.append(x)
                stack.extend(v for k, v in x.items() if k in ("@graph", "itemListElement", "item"))
    return out


def _from_ld(e, url, category):
    loc = e.get("location") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    venue = loc.get("name")
    addr = loc.get("address")
    if isinstance(addr, dict):
        addr = addr.get("streetAddress") or addr.get("addressLocality")
    if venue and addr:
        venue = f"{venue.strip()}, {addr}"
    offers = e.get("offers") or []
    offers = offers if isinstance(offers, list) else [offers]
    prices = [float(o["price"]) for o in offers if isinstance(o, dict) and str(o.get("price", "")).replace(".", "").isdigit()]
    img = e.get("image")
    img = img[0] if isinstance(img, list) and img else img if isinstance(img, str) else None
    try:
        start = datetime.fromisoformat(e["startDate"].replace("Z", "+00:00"))
    except (KeyError, ValueError, AttributeError):
        return None
    end = None
    if e.get("endDate"):
        try:
            end = datetime.fromisoformat(e["endDate"].replace("Z", "+00:00"))
        except ValueError:
            pass
    return _event(e.get("name"), start, end, venue, _price(min(prices), max(prices)) if prices else None,
                  category, e.get("description") or "", url, img)


def _future(events):
    today = date.today().isoformat()
    out, seen = [], set()
    for e in events:
        if not e or (e["end_date"] or e["date"]) < today:
            continue
        key = (e["title"].lower(), e["date"], e["time"])
        if key not in seen:                       # один и тот же сеанс из разных разделов сайта
            seen.add(key)
            out.append(e)
    return out


# ---------------------------------------------------------------- Olbilet
OLBILET_CATS = {"concerts": "Концерт", "festivals": "Фестиваль", "sports": "Спорт", "theatres": "Театр",
                "theatre": "Театр", "kids": "Детям", "standup": "Стендап", "stand-up": "Стендап",
                "exhibitions": "Выставка", "shows": None}
OLBILET_SKIP = {"event", "movies", "amusement-parks", "sky-park", "about", "news", "en", "uz", "ru"}  # event/ — это кино


def olbilet():
    base, links = "https://olbilet.uz", set()
    for path in ["/"] + [f"/{c}" for c in OLBILET_CATS]:
        try:
            page = requests.get(base + path, headers=UA, timeout=30).text
        except requests.RequestException:
            continue
        for seg, slug in re.findall(r'href="/([a-z\-]+)/([a-z0-9\-]+)"', page):
            if seg not in OLBILET_SKIP:
                links.add((seg, slug))
        time.sleep(0.4)
    events = []
    for seg, slug in sorted(links):
        url = f"{base}/{seg}/{slug}"
        try:
            page = requests.get(url, headers=UA, timeout=30).text
        except requests.RequestException:
            continue
        for e in _ld_events(page):
            events.append(_from_ld(e, url, OLBILET_CATS.get(seg)))
        time.sleep(0.4)
    return _future(events)


# ---------------------------------------------------------------- Ticketon
TICKETON_CATS = {"concerts": "Концерт", "theatres": "Театр", "stand-up": "Стендап", "children": "Детям",
                 "museums": "Выставка", "sports": "Спорт", "knowledge-skills": "Лекция", "shows": None,
                 "entertainment": None}                       # cinema не берём — это обычные киносеансы


def ticketon():
    base, links = "https://ticketon.uz", {}
    for cat in TICKETON_CATS:
        try:
            page = requests.get(f"{base}/tashkent/{cat}", headers=UA, timeout=30).text
        except requests.RequestException:
            continue
        for path in re.findall(r'href="(/(?:[a-z\-]+/)?event/[a-z0-9\-]+)"', page):
            if not path.startswith("/cinema"):
                links.setdefault(path, TICKETON_CATS[cat])
        time.sleep(0.4)
    events = []
    for path, cat in sorted(links.items()):
        url = base + path
        try:
            page = requests.get(url, headers=UA, timeout=30).text
        except requests.RequestException:
            continue
        for e in _ld_events(page):
            events.append(_from_ld(e, url, cat))
        time.sleep(0.4)
    return _future(events)


# ---------------------------------------------------------------- iTicket
ITICKET_SKIP = {"samarkand"}


def _iticket_cat(slug):
    for key, name in (("theat", "Театр"), ("concert", "Концерт"), ("kid", "Детям"), ("child", "Детям"),
                      ("sport", "Спорт"), ("stand", "Стендап"), ("exhib", "Выставка"), ("museum", "Выставка")):
        if key in slug:
            return name
    return None


def iticket(max_pages=15):
    """Открытый API сайта iticket.uz (тот же, что использует их сайт)."""
    api, events = "https://api.iticket.uz/ru/v5/events", []
    for page in range(1, max_pages + 1):
        r = requests.get(api, params={"client": "web", "page": page},
                         headers={**UA, "Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        block = (r.json().get("response") or {}).get("events") or {}
        for e in block.get("data", []):
            cat = e.get("category_slug") or ""
            if cat in ITICKET_SKIP:
                continue
            try:
                start = datetime.fromisoformat(e["event_starts_at"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(e["event_ends_at"].replace("Z", "+00:00")) if e.get("event_ends_at") else None
            except (KeyError, ValueError):
                continue
            if end and (end - start).days > 90:          # «события» на весь год — это акции, не мероприятия
                continue
            venues = e.get("venues") or []
            events.append(_event(
                e.get("name"), start, end,
                venues[0].get("name") if venues else None,
                _price(e.get("min_price"), e.get("max_price")),
                _iticket_cat(cat), e.get("meta_description") or "",
                f"https://iticket.uz/ru/events/{cat}/{e.get('slug')}", e.get("poster_url")))
        if not block.get("next_page_url"):
            break
        time.sleep(0.5)
    return _future(events)


# ---------------------------------------------------------------- ShowGo
SHOWGO_CATS = {"koserts": "Концерт", "teatrs": "Театр", "detyam": "Детям", "stend-py": "Стендап",
               "razvitie": "Лекция", "orkestr-bravo": "Концерт"}        # cinemas не берём
SHOWGO_RE = re.compile(
    r'\{"date_time":"([^"]+)","event":\{"id":\d+,"image_path":"([^"]*)","is_free":(true|false),'
    r'"is_pinned":(true|false),"title":"((?:[^"\\]|\\.)*)"\}.*?"min_price":(\d+|null),'
    r'"slug":"([^"]+)","theater":\{"id":\d+,"title":"((?:[^"\\]|\\.)*)"\}')


def _next_payload(page_html):
    """Склеивает данные Next.js (self.__next_f.push) в обычный текст."""
    parts = []
    for s in re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', page_html):
        try:
            parts.append(json.loads('"' + s + '"'))
        except ValueError:
            pass
    return "".join(parts)


def showgo():
    base, seen, events = "https://showgo.uz", set(), []
    # сначала разделы (там известна категория), главная — последней
    for path, cat in [(f"/ru/category/{c}", n) for c, n in SHOWGO_CATS.items()] + [("/ru", None)]:
        try:
            payload = _next_payload(requests.get(base + path, headers=UA, timeout=30).text)
        except requests.RequestException:
            continue
        found = SHOWGO_RE.findall(payload)
        for dt, img, free, pinned, title, price, slug, theater in found:
            # закреплённые события показываются в карусели на всех страницах — раздел о них ничего не говорит
            page_cat = None if pinned == "true" else cat
            if slug in seen:
                continue
            if pinned == "true" and path != "/ru":
                continue                              # возьмём его позже — с главной или из своего раздела
            seen.add(slug)
            try:
                # сайт пишет «GMT», но фактически это ташкентское время
                start = parsedate_to_datetime(dt).replace(tzinfo=None)
            except (TypeError, ValueError):
                continue
            title = json.loads(f'"{title}"')
            events.append(_event(
                title, start, venue=json.loads(f'"{theater}"'),
                price="Бесплатно" if free == "true" else _price(None if price == "null" else price, None),
                # разделы сайта показывают все события подряд, поэтому категорию определяем по названию
                category=page_cat or (find_category(title) if find_category(title) != "Другое" else "Концерт"),
                url=f"{base}/ru/session/{slug}"))
        time.sleep(0.4)
    return _future(events)


SCRAPERS = {"afisha.uz": afisha_uz, "iticket.uz": iticket, "showgo.uz": showgo,
            "olbilet.uz": olbilet, "ticketon.uz": ticketon}
