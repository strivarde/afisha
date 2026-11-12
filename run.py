"""Полный цикл: собрать посты → извлечь события → сохранить → сделать страницу.

Запуск:  .venv\\Scripts\\python run.py            (обычный)
         .venv\\Scripts\\python run.py --reparse  (переразобрать все сохранённые посты)
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

import db  # noqa: E402
import discover  # noqa: E402
import extract  # noqa: E402
import render  # noqa: E402
import sites  # noqa: E402
import tgscrape  # noqa: E402


def collect(con, cfg):
    new = 0
    channels = list(cfg.get("telegram", []))
    known = {c.lower() for c in channels}
    channels += [c for c in discover.added_channels(con) if c.lower() not in known]   # найденные автопоиском
    for ch in channels:
        try:
            posts = tgscrape.fetch_channel(ch, pages=cfg.get("pages_per_channel", 2))
        except Exception as ex:
            print(f"  ! @{ch}: {ex}")
            continue
        n = sum(db.save_post(con, {**p, "source": "@" + ch}) for p in posts)
        new += n
        print(f"  @{ch}: постов {len(posts)}, новых {n}")
        time.sleep(1)
    for name in cfg.get("sites", []):
        try:
            evs = sites.SCRAPERS[name]()
        except Exception as ex:
            print(f"  ! сайт {name}: {ex}")
            continue
        added = sum(db.save_event(con, e, e["url"], e.get("image")) for e in evs)
        print(f"  сайт {name}: событий {len(evs)}, новых {added}")
    con.commit()
    return new


def process(con, reparse=False):
    if reparse:
        # удаляем только события, найденные исключительно в Telegram (сайтовые не трогаем)
        con.execute("DELETE FROM events WHERE sources NOT LIKE '%afisha.uz/ru%'")
        con.execute("UPDATE posts SET processed=0")
    rows = con.execute("SELECT * FROM posts WHERE processed=0").fetchall()
    found, used_llm = 0, 0
    cand = []
    for r in rows:
        posted = datetime.fromisoformat(r["posted_at"]) if r["posted_at"] else None
        if extract.prefilter(r["text"], posted):
            cand.append((r, posted))
        else:
            con.execute("UPDATE posts SET processed=1, method='skip' WHERE id=?", (r["id"],))
    print(f"    похожих на анонсы: {len(cand)} из {len(rows)}")

    def save(r, events, method):
        nonlocal found
        for e in events:
            found += db.save_event(con, e, r["url"], r["image"])
        con.execute("UPDATE posts SET processed=1, method=? WHERE id=?", (method, r["id"]))

    llm_on, batch = extract.llm_enabled(), int(extract.os.getenv("LLM_BATCH", "8"))
    i, fails = 0, 0
    while llm_on and i < len(cand):
        chunk = cand[i:i + batch]
        try:
            res = extract.extract_llm_batch([(r["id"], r["text"], p) for r, p in chunk])
            for r, _ in chunk:
                save(r, res.get(r["id"], []), "llm")
            used_llm += len(chunk)
            fails = 0
            print(f"    нейросеть: {min(i + batch, len(cand))}/{len(cand)}")
        except extract.QuotaError as ex:
            print(f"  ! {ex}. Остальное — по правилам.")
            break
        except Exception as ex:
            fails += 1
            print(f"  ! нейросеть: {str(ex)[:160]} — эта пачка по правилам")
            for r, p in chunk:
                save(r, extract.extract_rules(r["text"], p), "rules")
            if fails >= 3:
                print("  ! три сбоя подряд — остальное по правилам")
                i += batch
                break
        i += batch
        con.commit()
        time.sleep(int(extract.os.getenv("LLM_PAUSE", "5")))   # бережём лимит в минуту
    for r, p in cand[i:]:
        save(r, extract.extract_rules(r["text"], p), "rules")
    con.commit()
    return len(rows), found, used_llm


def main():
    if "--check-llm" in sys.argv:
        if not extract.llm_enabled():
            print("Нейросеть не настроена: в файле .env нет LLM_API_KEY.")
            return
        try:
            print("Ключ работает, ответ:", extract.check_llm())
        except Exception as ex:
            print("Ошибка:", ex)
        return
    cfg = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    con = db.connect()
    print("1/3 Сбор постов…")
    new = collect(con, cfg)
    print(f"    новых постов: {new}")
    print("2/3 Разбор постов" + (" (LLM: " + extract.os.getenv("LLM_MODEL") + ")" if extract.llm_enabled() else " (правила)") + "…")
    n, found, llm = process(con, reparse="--reparse" in sys.argv)
    print(f"    разобрано {n} (нейросетью {llm}), новых событий {found}")
    if "--no-discover" not in sys.argv:
        try:
            discover.run(con, limit=10)        # понемногу проверяем новых кандидатов
        except Exception as ex:
            print(f"  ! автопоиск: {ex}")
    # события, сохранённые до появления категории «Игры» (квизы, мафия…), переносим в неё
    for r in con.execute("SELECT id, title FROM events WHERE category='Другое'").fetchall():
        if extract.find_category(r["title"]) == "Игры":
            con.execute("UPDATE events SET category='Игры' WHERE id=?", (r["id"],))
    con.commit()
    print("3/3 Страница…")
    path, total = render.render(con)
    print(f"    готово: {path}  (предстоящих событий: {total})")


if __name__ == "__main__":
    main()
