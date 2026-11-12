"""Автопоиск новых источников.

Откуда берутся кандидаты:
  1) из постов уже подключённых каналов: пересылки, ссылки t.me/..., @упоминания;
  2) со страниц площадок afisha.uz (у многих указан их Telegram и Instagram).
Каждый кандидат проверяется: публичный ли это канал, живой ли он, и (нейросетью)
публикует ли он мероприятия в Ташкенте. Подходящие добавляются в источники автоматически.

Запуск:
  .venv\\Scripts\\python discover.py               — кандидаты из постов + проверка
  .venv\\Scripts\\python discover.py --venues      — плюс страницы площадок afisha.uz (культура)
  .venv\\Scripts\\python discover.py --all-venues  — плюс рестораны и кафе (долго)
"""
import html
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

import db  # noqa: E402
import extract  # noqa: E402
import tgscrape  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}
AFISHA = "https://www.afisha.uz"
VENUE_TYPES = ["clubs", "theatres", "museums", "concert-exh-hall", "entertainment", "kovorking",
               "books", "organization", "parks", "dance", "misc"]
VENUE_TYPES_ALL = VENUE_TYPES + ["restaurants"]
MIN_SCORE = 7            # с какой оценки нейросети канал добавляется автоматически
INACTIVE_DAYS = 120      # канал без постов дольше — считаем заброшенным


def known_sources():
    cfg = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    return {c.lower() for c in cfg.get("telegram", [])}


def added_channels(con):
    return [r["username"] for r in con.execute("SELECT username FROM candidates WHERE status='added'")]


def _add_candidate(con, username, via, mentions=1):
    row = con.execute("SELECT found_via, mentions FROM candidates WHERE username=?", (username,)).fetchone()
    if row:
        vias = set(json.loads(row["found_via"] or "[]")) | {via}
        con.execute("UPDATE candidates SET found_via=?, mentions=? WHERE username=?",
                    (json.dumps(sorted(vias), ensure_ascii=False), len(vias), username))
        return False
    con.execute("INSERT INTO candidates(username, found_via, mentions) VALUES (?,?,?)",
                (username, json.dumps([via], ensure_ascii=False), mentions))
    return True


# ------------------------------------------------------------ 1. из постов
def gather_from_posts(con):
    known = known_sources()
    mentioned = defaultdict(set)
    for r in con.execute("SELECT source, refs FROM posts WHERE refs IS NOT NULL AND refs != '[]'"):
        for u in json.loads(r["refs"]):
            if u.lower() not in known:
                mentioned[u].add(r["source"])
    new = 0
    for u, vias in mentioned.items():
        for v in vias:
            new += _add_candidate(con, u, v)
    con.commit()
    return len(mentioned), new


# --------------------------------------------------- 2. площадки afisha.uz
def _places_of_type(t):
    url, out = f"/api/places?types.slug={t}&city=/api/cities/1&page=1", []
    while url:
        r = requests.get(AFISHA + url, headers={**UA, "Accept": "application/ld+json"}, timeout=30)
        r.raise_for_status()
        d = r.json()
        out += [(p["slug"], p["name"]) for p in d.get("hydra:member", []) if p.get("status") == "ACTIVE"]
        url = (d.get("hydra:view") or {}).get("hydra:next")
        time.sleep(0.3)
    return out


def scan_venues(con, types):
    known = known_sources()
    done = {r["slug"] for r in con.execute("SELECT slug FROM venues")}
    found_tg = 0
    for t in types:
        places = [p for p in _places_of_type(t) if p[0] not in done]
        print(f"  тип «{t}»: новых площадок {len(places)}")
        for slug, name in places:
            try:
                page = requests.get(f"{AFISHA}/ru/places/{slug}", headers=UA, timeout=30).text
            except requests.RequestException:
                continue
            # ссылки самой afisha.uz (в подвале сайта) отбрасываем
            tg = sorted({u for u in (tgscrape._username(m) for m in
                         re.findall(r"(?:t\.me|telegram\.me)/[A-Za-z0-9_]+", page))
                         if u and not u.lower().startswith("afisha")})
            ig = sorted({m for m in re.findall(r"instagram\.com/([A-Za-z0-9_.]{2,30})", page)
                         if not m.lower().startswith("afisha") and m not in ("p", "explore", "reel")})
            con.execute("INSERT OR REPLACE INTO venues VALUES (?,?,?,?,?,?)",
                        (slug, name, t, json.dumps(tg), json.dumps(ig), datetime.now().isoformat()))
            for u in tg:
                if u.lower() not in known:
                    found_tg += _add_candidate(con, u, f"afisha.uz: {name}")
            done.add(slug)
            time.sleep(0.4)
        con.commit()
    return found_tg


# ------------------------------------------------------ 3. проверка кандидата
PROMPT = """Мы собираем афишу мероприятий города Ташкент (концерты, выставки, квартирники, театр,
стендап, лекции, кинопоказы, вечеринки, фестивали, мастер-классы, встречи сообществ,
игровые события: квизы, мафия, настольные игры, интеллектуальные игры, турниры;
групповые выезды из Ташкента на природу: походы, треккинг, поездки в горы — турклубы и гиды
с анонсами выездов на конкретные даты тоже полезны, а турагентства с путёвками за границу — нет).
Ниже несколько Telegram-каналов: название, описание и последние посты.
Для КАЖДОГО канала оцени по шкале 0–10, насколько он полезен как источник анонсов мероприятий в Ташкенте:
10 — регулярно анонсирует конкретные мероприятия в Ташкенте (площадка, организатор, афиша);
5 — иногда анонсирует события, но в основном про другое;
0 — не про мероприятия (новости, магазин, личный блог, другой город/страна, реклама, вакансии).
Верни ТОЛЬКО JSON: {{"results": [{{"n": <номер>, "score": 0-10,
 "kind": "площадка" | "организатор" | "афиша" | "СМИ" | "сообщество" | "артист" | "другое",
 "reason": "одна короткая фраза по-русски, почему такая оценка"}}]}}

{channels}"""


def _heuristic(info):
    """Оценка без нейросети: доля постов, похожих на анонсы."""
    posts = info["posts"] or []
    hits = sum(extract.prefilter(p["text"], None) for p in posts)
    tash = bool(re.search(r"ташкент|toshkent|tashkent", json.dumps(info, ensure_ascii=False), re.I))
    score = round(10 * hits / max(len(posts), 1)) if tash else 0
    return {"score": score, "kind": "другое", "reason": f"по правилам: анонсов {hits} из {len(posts)} постов"}


def evaluate(con, limit=40, batch=5):
    rows = con.execute("SELECT username FROM candidates WHERE status='new' "
                       "ORDER BY mentions DESC, first_seen LIMIT ?", (limit,)).fetchall()
    if not rows:
        return 0
    print(f"  проверяю кандидатов: {len(rows)}")
    alive, cutoff = [], (date.today() - timedelta(days=INACTIVE_DAYS)).isoformat()
    for r in rows:
        u = r["username"]
        try:
            info = tgscrape.channel_info(u)
        except requests.RequestException:
            continue
        now = datetime.now().isoformat()
        if not info:
            con.execute("UPDATE candidates SET status='not_channel', checked_at=? WHERE username=?", (now, u))
        elif (info["last_post"] or "") < cutoff:
            con.execute("""UPDATE candidates SET status='inactive', title=?, subscribers=?, last_post=?,
                           checked_at=? WHERE username=?""",
                        (info["title"], info["subscribers"], info["last_post"], now, u))
        else:
            alive.append((u, info))
        time.sleep(1)
    con.commit()

    use_llm = extract.llm_enabled()
    for i in range(0, len(alive), batch):
        chunk = alive[i:i + batch]
        results = {}
        if use_llm:
            blocks = []
            for n, (u, info) in enumerate(chunk, 1):
                posts = "\n".join(f"- [{p['date']}] {p['text'][:300]}" for p in info["posts"][-8:])
                blocks.append(f"### Канал {n}: @{u} «{info['title']}» ({info['subscribers']} подписчиков)\n"
                              f"Описание: {info['description']}\nПосты:\n{posts}")
            try:
                data = extract._call(PROMPT.format(channels="\n\n".join(blocks)))
                for res in data.get("results", []):
                    results[int(res["n"])] = res
                time.sleep(4)
            except Exception as ex:
                print(f"  ! нейросеть: {str(ex)[:150]} — оцениваю по правилам")
                use_llm = False
        for n, (u, info) in enumerate(chunk, 1):
            res = results.get(n) or _heuristic(info)
            score = int(res.get("score") or 0)
            status = "added" if score >= MIN_SCORE else "rejected"
            con.execute("""UPDATE candidates SET status=?, score=?, kind=?, reason=?, title=?, subscribers=?,
                           last_post=?, checked_at=? WHERE username=?""",
                        (status, score, res.get("kind"), res.get("reason"), info["title"],
                         info["subscribers"], info["last_post"], datetime.now().isoformat(), u))
            mark = "+" if status == "added" else "-"
            print(f"    {mark} @{u} [{score}] {info['title'][:40]} — {str(res.get('reason'))[:70]}")
        con.commit()
    return len(alive)


# ------------------------------------------------------------- 4. отчёт
def report(con):
    e = html.escape
    def rows(q):
        return con.execute(q).fetchall()
    added = rows("SELECT * FROM candidates WHERE status='added' ORDER BY score DESC, mentions DESC")
    rejected = rows("SELECT * FROM candidates WHERE status='rejected' ORDER BY score DESC, mentions DESC")
    pending = con.execute("SELECT COUNT(*) FROM candidates WHERE status='new'").fetchone()[0]
    other = con.execute("SELECT COUNT(*) FROM candidates WHERE status IN ('not_channel','inactive')").fetchone()[0]
    ig = rows("SELECT name, type, instagram FROM venues WHERE instagram != '[]' ORDER BY type, name")

    def table(rs):
        out = []
        for r in rs:
            via = ", ".join(json.loads(r["found_via"] or "[]")[:3])
            out.append(f"<tr><td><a href='https://t.me/{e(r['username'])}' target='_blank'>@{e(r['username'])}</a>"
                       f"<div class='t'>{e(r['title'] or '')}</div></td><td class='n'>{r['score']}</td>"
                       f"<td>{e(r['kind'] or '')}</td><td>{e(r['reason'] or '')}</td>"
                       f"<td class='t'>{e(r['subscribers'] or '')}</td><td class='t'>{e(via)}</td></tr>")
        return ("<table><tr><th>Канал</th><th>Оценка</th><th>Тип</th><th>Почему</th><th>Подписчики</th>"
                "<th>Где нашли</th></tr>" + "".join(out) + "</table>") if out else "<p class='t'>Пока пусто.</p>"

    igs = "".join(f"<li>{e(r['name'])} <span class='t'>({e(r['type'])})</span>: " +
                  ", ".join(f"<a href='https://instagram.com/{e(h)}' target='_blank'>@{e(h)}</a>"
                            for h in json.loads(r["instagram"])) + "</li>" for r in ig)
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Источники афиши</title>
<style>
:root{{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e6e4df;--acc:#c2410c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141416;--card:#1e1e21;--ink:#f1f1f3;--mute:#9a9aa1;--line:#2c2c30;--acc:#fb923c}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px 48px}}
h1{{margin:0 0 4px}} h2{{margin:32px 0 8px;color:var(--acc)}}
.t{{color:var(--mute);font-size:13px}} .n{{text-align:center;font-weight:600}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;background:var(--card);font-size:14px}}
td,th{{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}}
a{{color:var(--acc);text-decoration:none}} li{{margin:3px 0}}
</style></head><body><main>
<h1>Источники афиши</h1>
<div class="t">Обновлено {datetime.now():%d.%m.%Y %H:%M} · добавлено автоматически: {len(added)} ·
отклонено: {len(rejected)} · ждут проверки: {pending} · не каналы или заброшены: {other}</div>
<p class="t">Каналы с оценкой {MIN_SCORE}+ добавляются в афишу сами. Если какой-то канал добавлен зря или
отклонён зря — скажите, я поправлю.</p>
<h2>Добавлены в афишу</h2><div class="wrap">{table(added)}</div>
<h2>Отклонены</h2><div class="wrap">{table(rejected)}</div>
<h2>Instagram площадок (на будущее)</h2><ul>{igs or "<li class='t'>Пока пусто.</li>"}</ul>
</main></body></html>"""
    out = ROOT / "output" / "sources.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def run(con, venues=None, limit=40):
    print("Поиск новых источников…")
    total, new = gather_from_posts(con)
    print(f"  упомянуто каналов в постах: {total}, новых кандидатов: {new}")
    if venues:
        print("  просматриваю площадки afisha.uz…")
        print(f"  каналов площадок найдено: {scan_venues(con, venues)}")
    evaluate(con, limit=limit)
    path = report(con)
    n = len(added_channels(con))
    print(f"  в афише автоматически найденных каналов: {n}. Отчёт: {path}")


if __name__ == "__main__":
    con = db.connect()
    v = VENUE_TYPES_ALL if "--all-venues" in sys.argv else VENUE_TYPES if "--venues" in sys.argv else None
    run(con, venues=v, limit=int(next((a.split("=")[1] for a in sys.argv if a.startswith("--limit=")), 60)))
