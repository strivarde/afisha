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


def _key_words(s):
    # первые 5 букв — грубо отбрасываем падежные окончания (Киркорова = Киркоров)
    return {w[:5] for w in _norm(s).split() if w not in STOP and len(w) > 2}


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


def save_event(con, e, source_url, image=None):
    """Добавляет событие или приклеивает источник к уже существующему дублю."""
    for row in con.execute("SELECT * FROM events WHERE date = ?", (e["date"],)):
        if row["time"] and e.get("time") and row["time"] != e["time"]:
            # один сайт, разное время в один день — разные сеансы (у разных сайтов время может
            # отличаться для одного события: «сбор гостей» и «начало»)
            site = source_url.split("/")[2]
            if any(s.split("/")[2] == site for s in json.loads(row["sources"])):
                continue
        if _similar(row["title"], e["title"]) or (
                e.get("venue") and row["venue"] and _similar(row["venue"], e["venue"])
                and e.get("time") and row["time"] == e.get("time")
                and row["category"] == e.get("category")
                and e.get("category") != "Игры"):     # разные квизы часто идут в одном баре в одно время
            srcs = json.loads(row["sources"])
            if source_url not in srcs:
                srcs.append(source_url)
            con.execute("""UPDATE events SET sources=?,
                           time=COALESCE(time, ?), venue=COALESCE(venue, ?),
                           price=COALESCE(price, ?), image=COALESCE(image, ?),
                           ticket_url=COALESCE(ticket_url, ?) WHERE id=?""",
                        (json.dumps(srcs), e.get("time"), e.get("venue"), e.get("price"),
                         image, e.get("ticket_url"), row["id"]))
            return False
    con.execute("""INSERT INTO events(title, date, end_date, time, venue, price, category,
                   description, image, sources, ticket_url) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (e["title"], e["date"], e.get("end_date"), e.get("time"), e.get("venue"),
                 e.get("price"), e.get("category") or "Другое", e.get("description"), image,
                 json.dumps([source_url]), e.get("ticket_url")))
    return True
