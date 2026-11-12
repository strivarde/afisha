"""Превращение текста поста в события.

Два режима:
  * rules — правила и регулярные выражения, работают без ключей и интернета;
  * llm   — бесплатная LLM через OpenAI-совместимый API (Gemini, Groq, OpenRouter,
            локальная Ollama). Включается, если в .env задан LLM_MODEL.
Если LLM недоступна или вернула ошибку, автоматически используются правила.
"""
import json
import os
import re
import time
from datetime import date, datetime, timedelta

import requests

# ---------------------------------------------------------------- словари
MONTHS = {
    # русский
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7,
    "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
    # узбекский (латиница)
    "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6, "iyul": 7,
    "avgust": 8, "sentabr": 9, "sentyabr": 9, "oktabr": 10, "oktyabr": 10,
    "noyabr": 11, "dekabr": 12,
    # узбекский (кириллица)
    "сентабр": 9, "октабр": 10, "ноябр ": 11,
    # английский
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_RE = (r"(январ\w*|феврал\w*|март\w*|апрел\w*|ма[яй]|июн\w*|июл\w*|август\w*|"
            r"сентябр\w*|сентабр\w*|октябр\w*|октабр\w*|ноябр\w*|декабр\w*|"
            r"yanvar\w*|fevral\w*|mart\w*|aprel\w*|may\w*|iyun\w*|iyul\w*|avgust\w*|"
            r"sent[y]?abr\w*|okt[y]?abr\w*|noyabr\w*|dekabr\w*|"
            r"january|february|march|april|june|july|august|september|october|"
            r"november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)")

WEEKDAYS = {"понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3, "пятниц": 4,
            "суббот": 5, "воскресень": 6,
            "dushanba": 0, "seshanba": 1, "chorshanba": 2, "payshanba": 3, "juma": 4,
            "shanba": 5, "yakshanba": 6}

CATEGORIES = [
    ("Квартирник", r"квартирник|kvartirnik"),
    ("Игры", r"\bквиз|\bquiz|\bkviz|мафи[яию]\b|\bmafia\b|\bmafiya\b|настольн\w* игр|настолк|board ?game|"
             r"что\?\s*где\?\s*когда|брейн[- ]?ринг|интеллектуальн\w* игр|intellektual|киберспорт|cybersport|"
             r"esports?\b|\bd&d\b|\bdnd\b|подземелья и драконы|ролев\w* игр|скрабл|scrabble|покер|poker|"
             r"шахмат|chess|бинго|bingo|game ?night|игротек|своя игра|\bkahoot"),
    ("Стендап", r"стендап|stand[- ]?up|стенд-ап|открытый микрофон|open mic"),
    ("Театр", r"спектакл|театр|премьер|spektakl|teatr|мюзикл|опер[аы]\b|балет"),
    ("Выставка", r"выставк|экспозиц|вернисаж|ko.?rgazma|кўргазма|exhibition|галере|galereya"),
    ("Кино", r"кинопоказ|показ фильма|кинотеатр|screening|кино\b"),
    ("Лекция", r"\bлекци|воркшоп|мастер[- ]класс|workshop|\btalk\b|дискусси|\bпрезентаци|"
               r"ma.?ruza|master[- ]klass|семинар|книжн"),
    ("Фестиваль", r"фестивал|festival|фест\b|ярмарк|маркет\b|bazaar|базар"),
    ("Вечеринка", r"вечеринк|party|dj\b|диджей|рейв|rave|techno|техно"),
    ("Концерт", r"концерт|konsert|concert|джаз|jazz|live\b|оркестр|рок\b|"
                r"акустик|группа .* выступ|выступлени|sing|певец|певица"),
    # выезды на природу: походы, треккинг, поездки в горы с турклубами
    ("Туризм", r"\bпоход\b|\bпоход[аеуы]\b|походы|треккинг|trekking|\bтрек\b|\bтрек[аеу]?\s+(по|на|к|в)\b|"
               r"хайкинг|hiking|восхождени|ущель|водопад|перевал|в горы|\bгор[аыу]?\b.*выезд|"
               r"экотур|эко-тур|спелео|кемпинг|camping|сплав|\bвершин|\bпик\b|урочищ|"
               r"тур выходного дня|однодневн\w* тур|выезд в|точка выезда|время выезда|"
               r"tog.?(ga|lar)|sayohat|piyoda yurish|sharshara|чимган|chimgan|амирсай|арашан|"
               r"бельдерсай|пальтау|акташ|сукок|чарвак|бостанлык"),
    ("Спорт", r"забег|марафон|турнир|матч\b|йога|yoga|run\b"),
]

# Магазины, скидки, распродажи, новые коллекции — это не мероприятия
COMMERCE_RE = re.compile(
    r"скидк|распродаж|новая коллекци|новые коллекци|новой коллекци|коллекция бренда|"
    r"в магазин|в бутик|бутике|акция до|промокод|кешбэк|кэшбэк|black friday|черная пятница|"
    r"чёрная пятница|\bsale\b|discount|chegirma|aksiya|yangi kolleksiya|do.?kon", re.I)


def is_commerce(text):
    return bool(COMMERCE_RE.search(text or ""))


EVENT_HINTS = re.compile(
    r"концерт|выставк|квартирник|спектакл|стендап|лекци|мастер-класс|мастер класс|"
    r"фестивал|вечеринк|кинопоказ|воркшоп|презентаци|вход|билет|регистрац|"
    r"приглашаем|ждём вас|ждем вас|начало в|начало:|сбор гостей|afisha|афиша|"
    r"konsert|tadbir|chipta|kirish|taklif|ko'rgazma|spektakl|"
    r"квиз|quiz|kviz|мафия|mafia|настольн|турнир|игра|игру|o.?yin|"
    r"tickets|event|show|"
    r"поход|трек|хайкинг|hiking|восхождени|выезд|сложность|маршрут|экотур|в горы|"
    r"sayohat|yurish|qatnashish", re.I)

# --------------------------------------------------------------- утилиты
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]+")


def _month_num(word):
    w = word.lower()
    if w in ("мая", "май"):
        return 5
    for k, v in MONTHS.items():
        if w.startswith(k.strip()) and not (k == "ма" and w not in ("мая", "май")):
            return v
    return None


def _with_year(day, month, ref):
    """Подбирает год: если дата сильно в прошлом относительно поста — следующий год."""
    try:
        d = date(ref.year, month, day)
    except ValueError:
        return None
    if (ref - d).days > 60:
        try:
            d = date(ref.year + 1, month, day)
        except ValueError:
            return None
    return d


URL_RE = re.compile(r"https?://\S+|t\.me/\S+|www\.\S+|@\w+")


def find_dates(text, ref):
    """Все даты в тексте → список date. ref — дата публикации поста."""
    out, t = [], URL_RE.sub(" ", text.lower())

    # «15 ноября», «15-17 ноября», «с 10 по 20 ноября», «15-noyabr»
    for m in re.finditer(r"(\d{1,2})(?:\s*[-–—]\s*(\d{1,2}))?[\s\-]*(?:го\s+)?" + MONTH_RE + r"\b", t):
        mon = _month_num(m.group(3))
        if mon:
            d = _with_year(int(m.group(1)), mon, ref)
            if d:
                out.append(d)
    for m in re.finditer(r"с\s+(\d{1,2})\s+по\s+(\d{1,2})\s+" + MONTH_RE, t):
        mon = _month_num(m.group(3))
        d = mon and _with_year(int(m.group(1)), mon, ref)
        if d:
            out.append(d)
    # «November 15»
    for m in re.finditer(r"\b(january|february|march|april|may|june|july|august|september|"
                         r"october|november|december)\s+(\d{1,2})\b", t):
        d = _with_year(int(m.group(2)), _month_num(m.group(1)[:3]), ref)
        if d:
            out.append(d)
    # «15.11», «15.11.2026», «15/11»
    for m in re.finditer(r"(?<![\d:.])(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?![\d:])", t):
        dd, mm, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= dd <= 31 and 1 <= mm <= 12):
            continue
        # «19.00» — это время, а не дата
        after = t[m.end():m.end() + 1]
        if mm == 0 or (dd <= 23 and m.group(2) in ("00", "30") and not yy):
            continue
        try:
            if yy:
                y = int(yy) + (2000 if len(yy) == 2 else 0)
                out.append(date(y, mm, dd))
            else:
                d = _with_year(dd, mm, ref)
                if d:
                    out.append(d)
        except ValueError:
            pass
    # «сегодня», «завтра», «в субботу»
    if re.search(r"\bсегодня\b|\bbugun\b|\btonight\b|\btoday\b", t):
        out.append(ref)
    if re.search(r"\bзавтра\b|\bertaga\b|\btomorrow\b", t):
        out.append(ref + timedelta(days=1))
    for word, wd in WEEKDAYS.items():
        if re.search(r"(?:\bв[о]?\s+|\bэт[уо][тй]?\s+|\b)" + word, t) and not out:
            delta = (wd - ref.weekday()) % 7
            out.append(ref + timedelta(days=delta))
            break
    # уникальные, по порядку появления
    seen, res = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            res.append(d)
    return res


def find_time(text):
    # «19:00» — надёжно; «19.00» — только после слов «в», «начало», «soat» и т.п.
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if not m:
        m = re.search(r"(?:\bв|начало|начало в|start|boshlanish|soat|at|сбор гостей)\s*[:—-]?\s*"
                      r"\b([01]?\d|2[0-3])\.([0-5]\d)\b", text, re.I)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def find_price(text):
    t = text.lower()
    if re.search(r"вход свободный|вход бесплатн|бесплатно|free entry|bepul|kirish bepul|"
                 r"свободный вход|вход free", t):
        return "Бесплатно"
    m = re.search(r"(\d[\d\s.,]*\d|\d+)\s*(тыс\.?|k\b|000)?\s*(сум|so['‘’]?m|uzs|сўм)", t)
    if m:
        return m.group(0).strip()
    m = re.search(r"(?:вход|билет\w*|цена|стоимость|chipta)[:\s—-]+([^\n]{1,40})", t)
    return m.group(1).strip() if m else None


def find_venue(text):
    m = re.search(r"(?:📍|🏛|🗺|📌)\s*([^\n]{3,100})", text)
    if m:
        return m.group(1).strip(" :—-")
    m = re.search(r"(?:место|адрес|где|локация|manzil|joy|venue|location|where)\s*[:—-]\s*([^\n]{3,100})",
                  text, re.I)
    return m.group(1).strip() if m else None


def find_category(text):
    """Сначала ищем категорию в заголовке, потом во всём тексте."""
    for chunk in (make_title(text), text):
        for name, rx in CATEGORIES:
            if re.search(rx, chunk, re.I):
                return name
    return "Другое"


LEADING_DATE = re.compile(r"^\s*(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|\d{1,2}\s+" + MONTH_RE + r")\s*[—–:\-|,]*\s*",
                          re.I)


JUNK_TITLE = re.compile(
    r"^(#\S+\s*)+$|^(анонс|anons|announcement|внимание|diqqat|уважаемые|hurmatli|dear|"
    r"дата|sana|date|время|vaqt|time|место|manzil|адрес|ждём вас|ждем вас|приглашаем|"
    r"taklif qilamiz|друзья|do.?stlar)\b[^\n]{0,25}$", re.I)


def make_title(text):
    first = None
    for line in text.splitlines():
        line = EMOJI_RE.sub("", line).strip(" *_-—|•·:!‼")
        line = LEADING_DATE.sub("", line).strip(" *_-—|•·:!‼")
        if len(line) < 4:
            continue
        first = first or line
        if not JUNK_TITLE.search(line):
            return line[:140]
    return (first or text)[:140]


def is_candidate(text):
    """Похож ли пост на анонс (дёшево, без LLM)."""
    return len(text) > 40 and bool(EVENT_HINTS.search(text)) and not is_commerce(make_title(text))


# --------------------------------------------------------------- правила
def extract_rules(text, posted_at):
    ref = (posted_at or datetime.now()).date()
    if not is_candidate(text):
        return []

    # Пост-дайджест «афиша недели»: несколько абзацев, у каждого своя дата
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    dated = [(b, find_dates(b, ref)) for b in blocks]
    dated = [(b, ds) for b, ds in dated if ds]
    # дайджест — только если даты в абзацах разные (а не один пост на трёх языках)
    if len(dated) >= 3 and len({ds[0] for _, ds in dated}) >= 3:
        parts = dated
    else:
        ds = find_dates(text, ref)
        parts = [(text, ds)] if ds else []

    events = []
    for block, ds in parts:
        start = ds[0]
        if start < ref - timedelta(days=1):       # прошедшее — не анонс
            continue
        if (start - ref).days > 240:              # слишком далеко — скорее ошибка
            continue
        time_, venue, price, cat = find_time(block), find_venue(block) or find_venue(text), \
            find_price(block), find_category(block)
        if not (time_ or venue or price) and cat == "Другое":   # скорее новость, чем анонс
            continue
        if is_commerce(make_title(block)):
            continue
        events.append({
            "title": make_title(block),
            "date": start.isoformat(),
            "end_date": ds[1].isoformat() if len(ds) > 1 and ds[1] > start and (ds[1] - start).days < 120 else None,
            "time": time_,
            "venue": venue,
            "price": price,
            "category": cat,
            "description": block[:1200],
        })
    return events


# ------------------------------------------------------------------- LLM
PROMPT = """Ты извлекаешь анонсы мероприятий в городе Ташкент из постов Telegram. Сегодня: {today}.
Ниже несколько постов, у каждого номер и дата публикации.
Верни ТОЛЬКО JSON: {{"results": [{{"post": <номер>, "events": [ ... ]}}, ...]}} — по элементу на КАЖДЫЙ пост.
Каждое событие:
{{"title": "короткое понятное название (на языке поста)",
  "date": "YYYY-MM-DD — дата начала", "end_date": "YYYY-MM-DD или null",
  "time": "HH:MM или null", "venue": "площадка и адрес или null",
  "price": "цена, 'Бесплатно' или null",
  "category": "одно из: Концерт, Выставка, Квартирник, Театр, Стендап, Лекция, Кино, Фестиваль, Вечеринка, Игры, Туризм, Спорт, Детям, Другое"}}
(«Игры» — квизы, мафия, настольные игры, «Что? Где? Когда?», турниры по шахматам/покеру, киберспорт, D&D.)
(«Туризм» — групповые выезды из Ташкента: походы, треккинг, поездки в горы, к водопадам и озёрам, экотуры,
 восхождения. Для них "venue" — маршрут или место (например «Чимган»), "time" — время выезда.)
Правила:
- "events": [] если пост НЕ анонс конкретного мероприятия: новость, статья, подборка ресторанов, реклама товара, отчёт о прошедшем, вакансия, розыгрыш.
- Магазины, скидки, распродажи, акции, новые коллекции одежды, открытие магазина — это НЕ события, пропускай.
- Только мероприятия в Ташкенте; события в других городах и странах пропускай. Исключение — однодневные
  и короткие групповые выезды из Ташкента на природу (горы, ущелья, озёра) с конкретной датой: это «Туризм».
  Пакетные туры за границу, путёвки, авиабилеты, разрешения и визы — НЕ события. Прайс-лист маршрутов
  «возим каждый день / под заказ» без конкретной даты выезда группы — тоже НЕ событие.
- Относительные даты («в субботу», «завтра», «ertaga») считай от даты публикации поста.
- Если пост — афиша на неделю, верни все события из него.
- Если пост на нескольких языках, это одно событие, не дублируй.

{posts}"""


class QuotaError(Exception):
    """Закончился бесплатный лимит запросов."""


def llm_enabled():
    return bool(os.getenv("LLM_MODEL")) and bool(os.getenv("LLM_API_KEY") or "localhost" in os.getenv("LLM_BASE_URL", ""))


def _models():
    return [m.strip() for m in os.getenv("LLM_MODEL", "").split(",") if m.strip()]


def _call(prompt):
    """Запрос к OpenAI-совместимому API. Перебирает модели из LLM_MODEL через запятую."""
    base = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
    key = os.getenv("LLM_API_KEY", "")
    last = None
    for model in _models():
        body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}]}
        for attempt in range(3):                       # 5xx — сервер перегружен, ждём и повторяем
            try:
                r = requests.post(f"{base}/chat/completions", json=body, timeout=180,
                                  headers={"Authorization": f"Bearer {key}"} if key else {})
            except requests.RequestException as ex:
                r, last = None, ex
            if r is not None and r.status_code < 500:
                break
            time.sleep(10 * (attempt + 1))
        if r is None or r.status_code >= 500:
            last = RuntimeError(f"{model}: сервер недоступен")
            continue
        if r.status_code == 429:
            last = QuotaError(f"{model}: лимит исчерпан")
            continue                                   # у другой модели может быть свой лимит
        if r.status_code in (400, 404) and "model" in r.text.lower():
            last = RuntimeError(f"{model}: модель недоступна")
            continue
        if r.status_code in (401, 403):
            raise RuntimeError(f"ключ не принят ({r.status_code}): {r.text[:200]}")
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            try:                                       # частая ошибка моделей — лишняя запятая
                return json.loads(re.sub(r",\s*([}\]])", r"\1", content))
            except json.JSONDecodeError as ex:
                last = RuntimeError(f"{model}: кривой JSON ({ex})")
                continue
    raise last or RuntimeError("не задана модель LLM_MODEL")


def check_llm():
    """Короткий тестовый запрос — проверить, что ключ работает."""
    return _call('Верни JSON {"ok": true}')


def extract_llm_batch(posts):
    """posts: список (id, text, posted_at). Возвращает {id: [события]}."""
    blocks = []
    for i, (_, text, posted) in enumerate(posts, 1):
        p = (posted or datetime.now()).date().isoformat()
        blocks.append(f'### Пост {i} (опубликован {p})\n"""{URL_RE.sub("", text)[:2500]}"""')
    data = _call(PROMPT.format(today=date.today().isoformat(), posts="\n\n".join(blocks)))
    out = {pid: [] for pid, _, _ in posts}
    for res in data.get("results", []):
        try:
            pid, text, posted = posts[int(res["post"]) - 1]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        ref = (posted or datetime.now()).date()
        for e in res.get("events") or []:
            try:
                d = date.fromisoformat(e["date"])
            except (KeyError, TypeError, ValueError):
                continue
            if d < ref - timedelta(days=1) or not e.get("title") or is_commerce(e["title"]):
                continue
            if e.get("end_date"):
                try:
                    date.fromisoformat(e["end_date"])
                except (TypeError, ValueError):
                    e["end_date"] = None
            e["description"] = text[:1200]
            e["category"] = e.get("category") or find_category(text)
            out[pid].append(e)
    return out


def prefilter(text, posted_at):
    """Стоит ли вообще разбирать пост: похож на анонс и в нём есть будущая дата."""
    if not is_candidate(text):
        return False
    ref = (posted_at or datetime.now()).date()
    today = date.today()
    # нужна дата, которая ещё не прошла (и относительно поста, и относительно сегодняшнего дня)
    floor = max(ref, today) - timedelta(days=1)
    if any(d >= floor for d in find_dates(text, ref)):
        return True
    # «сегодня/завтра» имеет смысл только в свежем посте
    return (today - ref).days <= 1 and \
        bool(re.search(r"\b(сегодня|завтра|bugun|ertaga|today|tomorrow)\b", text, re.I))
