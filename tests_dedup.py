"""Проверка склейки дублей: python tests_dedup.py"""
from db import _similar, is_duplicate

T = "https://t.me/"


def ev(title, time, venue, cat="Игры"):
    return {"title": title, "time": time, "venue": venue, "category": cat}


CASES = [
    # (событие A, источники A, событие B, источники B, должны ли склеиться)
    (ev("Квиз по трагедиям У. Шекспира", "19:15", "Театр «Другие звери», 1-й проезд"), [T + "drugiezveri/101"],
     ev("Квиз: Нет повести печальнее на свете...", "19:00", "Театр-студия «Другие Звери»"), [T + "drugiezveri/99"], True),
    (ev("Музыкальный квиз «Разумбой»", "18:30", "Peggy’s Pub, Яшнабадский район"), [T + "aydatuda/5"],
     ev("RAZUMBOY: СТРЕЛЯЙ И ПОЙ! ВСЕ ХИТЫ!", "19:00", "Peggy's Pub, 123a, Sultonali"), [T + "voyrazumboy/7"], True),
    # разные франшизы в одном баре в один вечер — НЕ дубль
    (ev("Квиз по сериалу «Отчаянные домохозяйки»", "19:00", "Terrace 100 / ул. Мукими"), [T + "mzgb_tash/1"],
     ev("Квиз «Смузи»: Футбол №24", "19:15", "Ресторан «Terrace100»"), ["https://tashkent.smuzi-quiz.com/games/x"], False),
    (ev("Мозгобойня: Лига Чемпионов", "19:00", "Terrace 100"), [T + "mzgb_tash/2"],
     ev("Квиз Albert Party: Микс №2", "19:00", "Terrace 100 (2 этаж)"), ["https://tash.albertparty.com/"], False),
    # два сеанса одного спектакля на одном сайте — НЕ дубль
    (ev("Ханума", "17:00", "Театр Мукими", "Театр"), ["https://iticket.uz/ru/events/theaters/hanuma-1"],
     ev("Ханума", "19:00", "Театр Мукими", "Театр"), ["https://iticket.uz/ru/events/theaters/hanuma-2"], False),
    # одно событие на разных сайтах с разным временем (сбор гостей / начало) — дубль
    (ev("Tehnikum Bloggers Awards 2026", "16:00", "CAEx", "Другое"), ["https://www.afisha.uz/ru/x"],
     ev("TEHNIKUM BLOGGERS AWARDS 2026", "18:00", "CAEx Uzbekistan", "Другое"), ["https://showgo.uz/ru/session/y"], True),
    # кириллица и латиница
    (ev("Концерт Филиппа Киркорова", "19:00", "Humo Arena", "Концерт"), ["https://www.afisha.uz/ru/a"],
     ev("FILIPP KIRKOROV", "19:00", "Humo Arena", "Концерт"), ["https://showgo.uz/ru/session/b"], True),
    (ev("Концерт Вани Дмитриенко", "19:00", "Humo Arena", "Концерт"), ["https://www.afisha.uz/ru/a"],
     ev("Концерт Филиппа Киркорова", "19:00", "Humo Arena", "Концерт"), ["https://showgo.uz/ru/session/b"], True),
    # выезды: один клуб, анонс на двух языках — дубль
    (ev("Восхождение на вершину Кунбурбука 1981 м", None, "Корзинка «Салом»", "Туризм"), [T + "salom_hiking/1"],
     ev("Kunburbuka cho‘qqisiga (1981 m) ko‘tarilish", None, "«Salom» Korzinka", "Туризм"), [T + "salom_hiking/2"], True),
    # разные клубы едут в одно место — НЕ дубль
    (ev("Круговой поход из Булоксу в Чиноркент", "07:00", "Булоксу", "Туризм"), [T + "trekkingclubnews/1"],
     ev("Buloqsuda piknik", None, "Buloqsu", "Туризм"), [T + "salom_hiking/3"], False),
    # один дайджест, разные маршруты в один день — НЕ дубль
    (ev("Трек по хребту Урикбель", None, "Хребет Урикбель", "Туризм"), [T + "MysteriousUZB/1"],
     ev("Трек на пик Пионерский", None, "Пик Пионерский", "Туризм"), [T + "MysteriousUZB/1"], False),
    # перепост между каналами клуба — дубль
    (ev("Осенние пейзажи ущелья Кок-су", "07:00", "Steam bar (м.Минор)", "Туризм"), [T + "chimganclub/1"],
     ev("Осенние пейзажи ущелья Кок-су🍁", "07:00", "Минор", "Туризм"), [T + "trekkingclubnews/2"], True),
]
# последний случай: одна арена и ровно одно время для двух разных концертов невозможны — это
# правило «то же место, то же время» (для не-игр); оставляем как есть, ожидаем склейку.

ok = True
for a, sa, b, sb, want in CASES:
    got = is_duplicate(a, b, sa, sb)
    ok &= got == want
    print("OK " if got == want else "ERR", got, "|", a["title"][:40], "<>", b["title"][:40])
for x, y, want in [("Спектакль «Сын»", "Спектакль «Семь лун»", False),
                   ("Новая коллекция в магазине Wonderland", "Новая коллекция в Gerry Weber", False)]:
    got = _similar(x, y)
    ok &= got == want
    print("OK " if got == want else "ERR", got, "|", x, "<>", y)
print("ВСЁ ХОРОШО" if ok else "ЕСТЬ ОШИБКИ")
