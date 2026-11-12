"""Быстрая проверка разбора по правилам: python tests_extract.py"""
from datetime import datetime

from extract import extract_rules

REF = datetime(2026, 11, 10)   # вторник
CASES = [
    ("""🎷 Джазовый вечер в Ильхоме
15 ноября в 19:00
📍 Театр Ильхом, ул. Пушкина 5
Вход 100 000 сум""", 1),
    ("""Квартирник с группой Shamol!
В эту субботу, начало 20.00
Место: секретная квартира в Мирабаде. Вход свободный""", 1),
    ("""Ko'rgazma "Ranglar" 20-noyabr soat 18:00
Manzil: Toshkent fotografiya uyi. Kirish bepul""", 1),
    ("""Афиша недели:

12.11 — Стендап в Bar 1991, 20:00

14.11 — Выставка Сони Ким, галерея Bonum Factum

16.11 — Концерт оркестра в Консерватории, 19:00""", 3),
    ("Итоги прошедшего концерта 2 ноября, спасибо всем, кто пришёл!", 0),
]

ok = True
for text, expected in CASES:
    evs = extract_rules(text, REF)
    flag = "OK " if len(evs) == expected else "ERR"
    ok &= len(evs) == expected
    print(flag, f"ожидалось {expected}, найдено {len(evs)}")
    for e in evs:
        print("    ", {k: v for k, v in e.items() if k != "description"})
print("ВСЁ ХОРОШО" if ok else "ЕСТЬ ОШИБКИ")
