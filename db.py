"""Хранилище SQLite: сырые посты и найденные события (с удалением дублей)."""
import json
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "events.db"


def connect():
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS posts (
        id TEXT PRIMARY KEY, source TEXT, url TEXT, posted_at TEXT,
        text TEXT, image TEXT, processed INTEGER DEFAULT 0, method TEXT);
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, date TEXT, end_date TEXT, time TEXT, venue TEXT, price TEXT,
        category TEXT, description TEXT, image TEXT,
        sources TEXT,               -- JSON-список ссылок на посты
        first_seen TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE INDEX IF NOT EXISTS ev_date ON events(date);
    -- найденные кандидаты в источники (автопоиск)
    CREATE TABLE IF NOT EXISTS candidates (
        username TEXT PRIMARY KEY COLLATE NOCASE,
        found_via TEXT,             -- JSON: откуда узнали (@канал или площадка afisha.uz)
        mentions INTEGER DEFAULT 0,
        status TEXT DEFAULT 'new',  -- new / added / rejected / not_channel / inactive / removed
        score INTEGER, kind TEXT, reason TEXT,
        title TEXT, subscribers TEXT, last_post TEXT,
        checked_at TEXT, first_seen TEXT DEFAULT CURRENT_TIMESTAMP);
    -- площадки afisha.uz, чьи страницы уже просмотрены
    CREATE TABLE IF NOT EXISTS venues (
        slug TEXT PRIMARY KEY, name TEXT, type TEXT,
        telegram TEXT, instagram TEXT, scanned_at TEXT);
    """)
    cols = {r[1] for r in con.execute("PRAGMA table_info(posts)")}
    if "refs" not in cols:
        con.execute("ALTER TABLE posts ADD COLUMN refs TEXT")
    ecols = {r[1] for r in con.execute("PRAGMA table_info(events)")}
    if "ticket_url" not in ecols:
        con.execute("ALTER TABLE events ADD COLUMN ticket_url TEXT")    # ссылка на покупку билета
    return con


def save_post(con, p):
    """True, если пост новый. Ссылки на другие каналы обновляются и у старых постов."""
    exists = con.execute("SELECT 1 FROM posts WHERE id=?", (p["id"],)).fetchone()
    refs = json.dumps(p.get("refs") or [])
    if exists:
        con.execute("UPDATE posts SET refs=? WHERE id=?", (refs, p["id"]))
        return False
    con.execute(
        "INSERT INTO posts(id, source, url, posted_at, text, image, refs) VALUES (?,?,?,?,?,?,?)",
        (p["id"], p["source"], p["url"], p["posted_at"].isoformat() if p.get("posted_at") else None,
         p["text"], p.get("image"), refs))
    return True


def _norm(s):
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


STOP = {"концерт", "выставка", "спектакль", "шоу", "в", "на", "и", "с", "новая", "коллекция",
         "магазине", "ташкенте", "ташкент", "toshkent", "toshkentda", "konserti", "the", "show",
         "стендап", "stand", "up", "балет", "лекция", "мастер", "класс", "фестиваль", "вечер",
         "квиз", "quiz", "kviz", "игра", "игры", "игру"}


TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "j", "з": "z", "и": "i",
    "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
    "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "ў": "o", "қ": "k", "ғ": "g", "ҳ": "h"})


def _latin(w):
    """Одна запись для кириллицы и латиницы: «Разумбой» и «RAZUMBOY» → «razumboi»."""
    w = w.lower().translate(TRANSLIT)
    for a, b in (("dzh", "j"), ("zh", "j"), ("kh", "h"), ("x", "h"), ("y", "i"), ("w", "v"),
                 ("q", "k"), ("ck", "k"), ("o'", "o"), ("g'", "g")):
        w = w.replace(a, b)
    return w


def _key_words(s):
    # первые 5 букв (после перевода в латиницу) — грубо отбрасываем падежные окончания
    return {_latin(w)[:5] for w in _norm(s).split() if w not in STOP and len(w) > 2}


def _similar(a, b):
    """Похожи ли названия: совпадает ли «смысловая» часть, а не общие слова вроде «Концерт»."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    ka, kb = _key_words(a), _key_words(b)
    if ka and kb:
        common = len(ka & kb) / min(len(ka), len(kb))
        if common >= 0.6:
            return True
        if common == 0:
            return False
    return SequenceMatcher(None, na, nb).ratio() > 0.85


def _origin(url):
    """Откуда источник: «t.me/канал» или домен сайта."""
    parts = url.split("/")
    return f"t.me/{parts[3].lower()}" if "t.me" in parts[2] and len(parts) > 3 else parts[2]


def _minutes(t):
    try:
        h, m = map(int, t.split(":"))
        return h * 60 + m
    except (AttributeError, ValueError):
        return None


# общие слова в названиях площадок — по ним одну площадку от другой не отличить
VENUE_STOP = {_latin(w)[:5] for w in (
    "театр teatr teatri theatre театр-студия студия studio ресторан restoran рестобар бар bar паб pub "
    "кафе cafe клуб club галерея galereya gallery дворец saroyi palace центр markazi center centre зал "
    "hall концертный государственный davlat академический национальный milliy ташкент toshkent tashkent "
    "кинотеатр kinoteatr ул улица ko'chasi").split()}


def _same_venue(a, b):
    """Площадки сравниваем по названию (до запятой): адреса пишут по-разному."""
    if not a or not b:
        return False
    if _similar(a, b):
        return True
    ka = _key_words(re.split(r"[,/(]", a)[0]) - VENUE_STOP
    kb = _key_words(re.split(r"[,/(]", b)[0]) - VENUE_STOP
    return bool(ka and kb and len(ka & kb) / min(len(ka), len(kb)) >= 0.5)


def is_duplicate(a, b, sources_a, sources_b):
    """Одно ли это событие (a, b — события одного дня; sources_* — их ссылки-источники)."""
    ta, tb = _minutes(a.get("time")), _minutes(b.get("time"))
    gap = abs(ta - tb) if ta is not None and tb is not None else None
    same_origin = bool({_origin(s) for s in sources_a} & {_origin(s) for s in sources_b})
    # один источник, время далеко друг от друга — разные сеансы (два спектакля в один день)
    if gap is not None and gap > 45 and same_origin:
        return False
    if _similar(a["title"], b["title"]):
        return True
    near = gap is not None and gap <= 45
    same_venue = _same_venue(a.get("venue"), b.get("venue"))
    if not (near and same_venue and a.get("category") == b.get("category")):
        return False
    # то же место, почти то же время: дубль, если совпадает организатор — общее слово в
    # названиях (кириллица = латиница) или тот же канал/сайт. Разные квизы в одном баре — не дубль.
    if same_origin or (_key_words(a["title"]) & _key_words(b["title"])):
        return True
    # не игры: та же площадка (строгое сравнение — в Консерватории несколько залов) и ровно
    # то же время — почти наверняка одно и то же
    return gap == 0 and a.get("category") != "Игры" and _similar(a["venue"], b["venue"])


def _merge_into(con, row, e, sources, image=None):
    srcs = json.loads(row["sources"])
    for s in sources:
        if s not in srcs:
            srcs.append(s)
    con.execute("""UPDATE events SET sources=?,
                   time=COALESCE(time, ?), venue=COALESCE(venue, ?),
                   price=COALESCE(price, ?), image=COALESCE(image, ?),
                   ticket_url=COALESCE(ticket_url, ?) WHERE id=?""",
                (json.dumps(srcs), e.get("time"), e.get("venue"), e.get("price"),
                 image or e.get("image"), e.get("ticket_url"), row["id"]))


def dedupe(con):
    """Склеивает дубли, которые уже лежат в базе (например, найденные до улучшения правил)."""
    merged = 0
    for (d,) in con.execute("SELECT DISTINCT date FROM events WHERE date >= date('now','-1 day')").fetchall():
        rows = [dict(r) for r in con.execute("SELECT * FROM events WHERE date=? ORDER BY id", (d,))]
        alive = []
        for r in rows:
            target = next((k for k in alive if is_duplicate(k, r, json.loads(k["sources"]),
                                                             json.loads(r["sources"]))), None)
            if target:
                _merge_into(con, target, r, json.loads(r["sources"]))
                target.update(dict(con.execute("SELECT * FROM events WHERE id=?", (target["id"],)).fetchone()))
                con.execute("DELETE FROM events WHERE id=?", (r["id"],))
                merged += 1
            else:
                alive.append(r)
    con.commit()
    return merged


def save_event(con, e, source_url, image=None):
    """Добавляет событие или приклеивает источник к уже существующему дублю."""
    for row in con.execute("SELECT * FROM events WHERE date = ?", (e["date"],)):
        if is_duplicate(dict(row), e, json.loads(row["sources"]), [source_url]):
            _merge_into(con, row, e, [source_url], image)
            return False
    con.execute("""INSERT INTO events(title, date, end_date, time, venue, price, category,
                   description, image, sources, ticket_url) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (e["title"], e["date"], e.get("end_date"), e.get("time"), e.get("venue"),
                 e.get("price"), e.get("category") or "Другое", e.get("description"), image,
                 json.dumps([source_url]), e.get("ticket_url")))
    return True
