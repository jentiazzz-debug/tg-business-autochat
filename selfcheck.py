"""Самопроверка логики автоответчика без Telegram и без базы.

Запуск: python selfcheck.py

Проверяется ровно то, за что бота ругают в реальной переписке: ответил,
когда должен был молчать, промолчал на второй вопрос, поймал триггер
внутри чужого слова. Ни сети, ни зависимостей — только engine.py,
поэтому гонять можно прямо на машине, где даже aiogram не установлен.
"""

from __future__ import annotations

import sys

import engine

NOW = 1_700_000_000

BASE_SETTINGS = {
    "active": 1,
    "away": 0,
    "greet": 0,
    "fallback": 0,
    "away_text": "Я отошёл, вернусь позже.",
    "greet_text": "Привет, {name}!",
    "fallback_text": "Отвечу позже.",
    "cooldown": 120,
    "pause_minutes": 30,
}

BASE_CHAT = {
    "ignored": 0,
    "greeted": 1,
    "last_reply": 0,
    "last_rule": 0,
    "owner_seen": 0,
}

RULES = [
    {"id": 1, "enabled": 1, "triggers": "цена|сколько стоит", "reply": "Прайс скину."},
    {"id": 2, "enabled": 1, "triggers": "сроки|когда будет", "reply": "На неделе."},
    {"id": 3, "enabled": 0, "triggers": "скидка", "reply": "Скидок нет."},
    {"id": 4, "enabled": 1, "triggers": "=да", "reply": "Отлично!"},
]


def case(name: str, expect: str, *, text: str, settings=None, chat=None, now=NOW):
    st = {**BASE_SETTINGS, **(settings or {})}
    ch = {**BASE_CHAT, **(chat or {})}
    got = engine.decide(text=text, settings=st, rules=RULES, chat=ch, now=now)
    ok = got.kind == expect
    mark = "ok  " if ok else "ФЕЙЛ"
    tail = got.reason if got.kind == "skip" else engine.render(got.text, name="Аня")
    print(f"[{mark}] {name}\n       ждали {expect}, получили {got.kind}: {tail}")
    return ok


def main() -> int:
    results = [
        case("правило сработало", "rule", text="а какая цена?"),
        case("триггер внутри слова не ловится", "skip", text="это правда оценка"),
        case("точное совпадение =да", "rule", text="да"),
        case("=да не ловит «да, конечно»", "skip", text="да, конечно"),
        case("выключенное правило молчит", "skip", text="а скидка будет?"),
        case(
            "владелец сам в диалоге",
            "skip",
            text="цена?",
            chat={"owner_seen": NOW - 60},
        ),
        case(
            "пауза владельца истекла",
            "rule",
            text="цена?",
            chat={"owner_seen": NOW - 3600},
        ),
        case(
            "кулдаун после того же правила",
            "skip",
            text="а цена точно такая?",
            chat={"last_reply": NOW - 30, "last_rule": 1},
        ),
        case(
            "другое правило кулдаун обходит",
            "rule",
            text="а сроки какие?",
            chat={"last_reply": NOW - 30, "last_rule": 1},
        ),
        case("чат в исключениях", "skip", text="цена?", chat={"ignored": 1}),
        case("автоответы выключены", "skip", text="цена?", settings={"active": 0}),
        case("режим «отошёл» отвечает на всё", "away", text="привет", settings={"away": 1}),
        case(
            "приветствие новому чату",
            "greet",
            text="привет",
            settings={"greet": 1},
            chat={"greeted": 0},
        ),
        case(
            "правило важнее приветствия",
            "rule",
            text="привет, сколько стоит?",
            settings={"greet": 1},
            chat={"greeted": 0},
        ),
        case("без правил и без запасного текста — тишина", "skip", text="как дела?"),
        case(
            "ответ по умолчанию включён",
            "fallback",
            text="как дела?",
            settings={"fallback": 1},
        ),
        case("пустой текст ответа не отправляется", "skip", text="привет",
             settings={"away": 1, "away_text": ""}),
    ]

    print()
    print("подстановки:", engine.render("Привет, {name}! Сейчас {time}.", name="Аня"))
    print("фигурная скобка не ломает:", engine.render("Скидка {50%} для {name}", name="Аня"))

    bad = results.count(False)
    print()
    print(f"проверок: {len(results)}, провалено: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
