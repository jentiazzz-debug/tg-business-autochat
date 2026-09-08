"""Решение: отвечать ли на сообщение и что именно.

Модуль сознательно не знает ни про Telegram, ни про базу — на вход
приходят настройки, правила и состояние чата, на выходе одно решение.
Так логику видно целиком в одном месте и её можно прогнать без сети:
selfcheck.py гоняет через decide() десяток ситуаций и печатает, что бы
бот ответил.

Порядок проверок важнее самих правил. Автоответчик пишет от имени
живого человека, поэтому сначала идут четыре причины промолчать —
выключен, чат в игноре, владелец сам в диалоге, недавно уже отвечали, —
и только потом подбор текста.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Iterable, Mapping, Sequence

#: Разделитель триггеров в одном правиле.
SEP = "|"

#: Префикс точного совпадения: «=да» сработает на сообщении «да» и не
#: сработает на «да, давай». Обычный триггер ищется как начало слова.
EXACT = "="


@dataclass(slots=True)
class Decision:
    """Что делать с сообщением.

    kind: rule | greet | away | fallback | skip
    reason заполняется только у skip — он идёт в /why и в самопроверку.
    """

    kind: str
    text: str = ""
    rule_id: int | None = None
    reason: str = ""

    @property
    def send(self) -> bool:
        return self.kind != "skip" and bool(self.text)


def norm(text: str) -> str:
    """Нормализация для сравнения: регистр, ё и лишние пробелы.

    Ё приводится к Е намеренно: половина людей её не печатает, и
    правило на «ещё» иначе молчит на «еще».
    """
    return re.sub(r"\s+", " ", text.replace("ё", "е").replace("Ё", "Е").lower()).strip()


@lru_cache(maxsize=512)
def _pattern(trigger: str) -> re.Pattern[str]:
    """Триггер ищется с начала слова.

    Простое вхождение подстроки — главная ловушка автоответчиков:
    триггер «да» срабатывает на «правда» и «неудачно». Граница слова
    слева это чинит, а справа её нет намеренно — «прив» должно ловить
    «привет», а «цен» — «цена», «цену» и «ценник». Для русского языка
    это заменяет морфологию.
    """
    return re.compile(r"(?<!\w)" + re.escape(trigger))


def triggers_of(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(SEP) if t.strip()]


def matches(text: str, raw_triggers: str) -> str | None:
    """Первый сработавший триггер правила или None."""
    clean = norm(text)
    if not clean:
        return None
    for trigger in triggers_of(raw_triggers):
        low = norm(trigger)
        if not low:
            continue
        if low.startswith(EXACT):
            if clean == low[len(EXACT) :].strip():
                return trigger
        elif _pattern(low).search(clean):
            return trigger
    return None


def pick_rule(text: str, rules: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Первое подходящее правило по порядку добавления.

    Порядок — это приоритет: правила листаются сверху вниз, и владелец
    видит их в админке ровно в этом же порядке.
    """
    for rule in rules:
        if not rule["enabled"]:
            continue
        if matches(text, rule["triggers"]):
            return rule
    return None


def decide(
    *,
    text: str,
    settings: Mapping[str, Any],
    rules: Sequence[Mapping[str, Any]],
    chat: Mapping[str, Any],
    now: int | None = None,
) -> Decision:
    """Главная развилка автоответчика."""
    now = int(now if now is not None else time.time())

    if not settings["active"]:
        return Decision("skip", reason="автоответы выключены")
    if chat["ignored"]:
        return Decision("skip", reason="чат в списке исключений")

    pause = int(settings["pause_minutes"]) * 60
    if pause and now - int(chat["owner_seen"]) < pause:
        left = pause - (now - int(chat["owner_seen"]))
        return Decision("skip", reason=f"вы сами писали в этот чат, пауза ещё {left} с")

    if settings["away"]:
        candidate = Decision("away", settings["away_text"] or "")
    else:
        rule = pick_rule(text, rules)
        if rule is not None:
            candidate = Decision("rule", rule["reply"], int(rule["id"]))
        elif settings["greet"] and not chat["greeted"]:
            candidate = Decision("greet", settings["greet_text"] or "")
        elif settings["fallback"]:
            candidate = Decision("fallback", settings["fallback_text"] or "")
        else:
            return Decision("skip", reason="ни одно правило не подошло")

    if not candidate.text:
        return Decision("skip", reason="текст ответа пуст")

    # Кулдаун держит бота от очереди одинаковых ответов, когда человек
    # пишет мысль в три сообщения подряд. Другое правило его обходит:
    # спросили про цену, а через минуту про сроки — это два разных
    # вопроса, и молчать на второй неправильно.
    cooldown = int(settings["cooldown"])
    fresh_rule = candidate.kind == "rule" and candidate.rule_id != int(chat["last_rule"])
    if cooldown and not fresh_rule:
        since = now - int(chat["last_reply"])
        if since < cooldown:
            return Decision("skip", reason=f"пауза между ответами, ещё {cooldown - since} с")

    return candidate


def render(template: str, *, name: str = "", username: str = "") -> str:
    """Подстановки в тексте ответа.

    Через str.format нельзя: в тексте владельца легко встретится
    одинокая фигурная скобка, и бот молча упадёт на отправке ответа
    вместо того, чтобы отправить текст как есть.
    """
    now = datetime.now()
    values = {
        "{name}": name or "друг",
        "{first_name}": name or "друг",
        "{username}": f"@{username}" if username else (name or "друг"),
        "{time}": now.strftime("%H:%M"),
        "{date}": now.strftime("%d.%m.%Y"),
    }
    for key, value in values.items():
        template = template.replace(key, value)
    return template
