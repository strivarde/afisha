"""Сбор постов из публичных Telegram-каналов через веб-версию t.me/s/<канал>.
Аккаунт Telegram не нужен."""
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


# служебные адреса t.me, которые не являются каналами
NOT_CHANNELS = {"s", "c", "joinchat", "share", "addstickers", "addemoji", "proxy", "socks", "iv",
                "login", "setlanguage", "boost", "contact", "addlist", "m", "i", "k", "a", "z"}
USER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


def _username(s):
    """'https://t.me/foo/123' или '@foo' → 'foo' (или None)."""
    s = s.strip()
    m = re.search(r"(?:t(?:elegram)?\.me|telegram\.dog)/(?:s/)?([A-Za-z0-9_+]+)", s)
    u = m.group(1) if m else s.lstrip("@")
    if not USER_RE.match(u) or u.lower() in NOT_CHANNELS or u.lower().endswith("bot"):
        return None
    return u


def _refs_of(msg, text_node, own):
    """На какие каналы ссылается пост: пересылка, ссылки t.me, @упоминания."""
    refs = set()
    fwd = msg.select_one("a.tgme_widget_message_forwarded_from_name")
    if fwd and fwd.get("href"):
        refs.add(_username(fwd["href"]))
    if text_node:
        for a in text_node.select("a[href]"):
            if "t.me/" in a["href"] or a.get_text().startswith("@"):
                refs.add(_username(a["href"] if "t.me/" in a["href"] else a.get_text()))
        for m in re.finditer(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_]{3,31})", text_node.get_text()):
            refs.add(_username(m.group(1)))
    refs.discard(None)
    return sorted(r for r in refs if r.lower() != own.lower())


def channel_info(channel):
    """Название, описание и последние посты канала (для оценки кандидата).
    None — если это не публичный канал (личный аккаунт, группа, нет такого)."""
    r = requests.get(f"https://t.me/s/{channel}", headers=HEADERS, timeout=30, allow_redirects=False)
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    msgs = soup.select(".tgme_widget_message[data-post]")
    if not msgs:
        return None
    title = soup.select_one(".tgme_channel_info_header_title")
    desc = soup.select_one(".tgme_channel_info_description")
    subs = soup.select_one(".tgme_channel_info_counter .counter_value")
    posts = []
    for m in msgs[-10:]:
        t = m.select_one(".tgme_widget_message_text")
        tm = m.select_one("time[datetime]")
        if t:
            posts.append({"date": tm["datetime"][:10] if tm else None, "text": _text_of(t)[:400]})
    last = msgs[-1].select_one("time[datetime]")
    return {
        "username": msgs[-1]["data-post"].split("/")[0],     # каноническое написание
        "title": title.get_text(strip=True) if title else channel,
        "description": desc.get_text(" ", strip=True)[:500] if desc else "",
        "subscribers": subs.get_text(strip=True) if subs else "",
        "last_post": last["datetime"][:10] if last else None,
        "posts": posts,
    }


def _text_of(node):
    """Текст поста с сохранением переносов строк."""
    for br in node.find_all("br"):
        br.replace_with("\n")
    return node.get_text().strip()


def fetch_channel(channel, pages=2, pause=1.0):
    """Возвращает список постов: dict(id, channel, url, posted_at, text, image)."""
    posts, url = [], f"https://t.me/s/{channel}"
    for _ in range(pages):
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "lxml")
        msgs = soup.select(".tgme_widget_message[data-post]")
        if not msgs:
            break
        for m in msgs:
            data_post = m["data-post"]                     # "channel/123"
            text_node = m.select_one(".tgme_widget_message_text")
            if not text_node:
                continue
            refs = _refs_of(m, text_node, channel)          # до _text_of: он меняет узел
            t = m.select_one("time[datetime]")
            img = m.select_one(".tgme_widget_message_photo_wrap")
            image = None
            if img and "background-image" in (img.get("style") or ""):
                image = img["style"].split("url('")[-1].split("')")[0]
            posts.append({
                "id": data_post,
                "channel": channel,
                "url": f"https://t.me/{data_post}",
                "posted_at": datetime.fromisoformat(t["datetime"]) if t else None,
                "text": _text_of(text_node),
                "image": image,
                "refs": refs,
            })
        prev = soup.select_one("link[rel=prev]")
        if not prev:
            break
        url = "https://t.me" + prev["href"]
        time.sleep(pause)
    return posts


if __name__ == "__main__":
    import sys
    for p in fetch_channel(sys.argv[1] if len(sys.argv) > 1 else "durov", pages=1)[-3:]:
        print(p["url"], p["posted_at"], p["text"][:100].replace("\n", " | "))
