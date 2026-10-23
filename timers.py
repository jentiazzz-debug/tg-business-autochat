"""Всё, что должно случиться позже: мут на время, напоминания, отложенные.

Одна фоновая задача раз в TICK секунд смотрит в базу. Сроки хранятся
там же, поэтому перезапуск бота ничего не теряет: мут на сутки снимется
через сутки, даже если бот за это время дважды передеплоили.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from aiogram.exceptions import TelegramAPIError

import db
import mirrors
import pe
import texts

log = logging.getLogger("autochat.timers")

TICK = 15

#: Самый долгий срок, который принимают .мут, .напомни и .отложи.
MAX_SPAN = 30 * 86400

_UNITS = {
    "с": 1, "сек": 1, "s": 1,
    "м": 60, "мин": 60, "m": 60, "min": 60,
    "ч": 3600, "час": 3600, "h": 3600,
    "д": 86400, "дн": 86400, "день": 86400, "дня": 86400, "дней": 86400, "d": 86400,
    "н": 604800, "нед": 604800, "w": 604800,
}
_PART = re.compile(r"(\d+)\s*([a-zа-яё]*)", re.I)


def parse_span(raw: str) -> int | None:
    """«10м», «1ч30м», «2д», «45» (минуты) → секунды. None — не срок.

    Строка должна целиком состоять из срока: «10 минут позвонить» сюда
    не попадает — команда сама отрезает первое слово и передаёт его.
    """
    raw = raw.strip().lower()
    if not raw:
        return None
    total, pos = 0, 0
    for match in _PART.finditer(raw):
        if raw[pos:match.start()].strip():
            return None
        number, unit = int(match.group(1)), match.group(2)
        if unit == "":
            unit = "м"
        factor = _UNITS.get(unit)
        if factor is None:
            return None
        total += number * factor
        pos = match.end()
    if pos == 0 or raw[pos:].strip() or total <= 0:
        return None
    return min(total, MAX_SPAN)


def split_span(args: str) -> tuple[int | None, str]:
    """Отделить срок в начале аргументов: «10м позвонить» → (600, «позвонить»)."""
    head, _, tail = args.strip().partition(" ")
    span = parse_span(head)
    if span is None:
        return None, args.strip()
    return span, tail.strip()


def span_words(seconds: int) -> str:
    """600 → «10 мин», 5400 → «1 ч 30 мин», 172800 → «2 дн»."""
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days} дн")
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if secs and not days and not hours:
        parts.append(f"{secs} с")
    return " ".join(parts) or "0 с"


# --------------------------------------------------------------------------
# Фоновая задача
# --------------------------------------------------------------------------


async def _unmute(chat: object) -> None:
    owner_id = int(chat["owner_id"])
    chat_id = int(chat["chat_id"])
    await db.set_muted(owner_id, chat_id, False)
    name = texts.esc(chat["title"] or "Собеседник")
    conn = await db.connection_of(owner_id)
    # Чат обслуживает тот бот, к которому подключён Business, — зеркало
    # или основной. Чужой бот в этот чат написать не сможет.
    bot = mirrors.bot_for(conn["bot_id"] if conn is not None else 0)
    if conn is not None and conn["enabled"] and conn["can_reply"]:
        try:
            await bot.send_message(
                chat_id,
                texts.unmute_public(chat["title"] or "Собеседник", auto=True),
                business_connection_id=conn["id"],
            )
        except TelegramAPIError as err:
            log.info("не объявил конец мута в %s: %s", chat_id, err)
    if conn is not None:
        try:
            await bot.send_message(
                conn["user_chat_id"],
                f"{pe.e('volume')} Срок мута вышел — <b>{name}</b> снова пишет обычно.",
            )
        except TelegramAPIError:
            pass


async def _fire(timer: object) -> None:
    owner_id = int(timer["owner_id"])
    via = await db.connection_by_id(timer["conn_id"]) if timer["conn_id"] else None
    conn = via or await db.connection_of(owner_id)
    owner_chat = int(conn["user_chat_id"]) if conn is not None else owner_id
    bot = mirrors.bot_for(conn["bot_id"] if conn is not None else 0)
    body = texts.esc(timer["text"] or "")

    if timer["action"] == "remind":
        where = f"\n<i>из чата с {texts.esc(timer['title'])}</i>" if timer["title"] else ""
        await bot.send_message(
            owner_chat, f"{pe.e('alarm')} <b>Напоминание</b>{where}\n\n{body}"
        )
        return

    # action == "send": отложенное сообщение от имени владельца.
    try:
        await bot.send_message(
            int(timer["chat_id"]),
            timer["text"] or "",
            business_connection_id=timer["conn_id"],
            parse_mode=None,
        )
        note = f"{pe.e('send')} Отложенное ушло в чат с <b>{texts.esc(timer['title'])}</b>:\n\n{body}"
    except TelegramAPIError as err:
        note = (
            f"{pe.e('warning')} Отложенное в чат с <b>{texts.esc(timer['title'])}</b> "
            f"не ушло: {texts.esc(err)}\n\n{body}"
        )
    await bot.send_message(owner_chat, note)


async def loop() -> None:
    while True:
        try:
            now = int(time.time())
            for chat in await db.expired_mutes(now):
                await _unmute(chat)
            for timer in await db.due_timers(now):
                # Сначала убрать, потом выполнять: упади отправка на
                # середине — повторять её по кругу каждые 15 секунд хуже,
                # чем один раз не доставить.
                await db.drop_timer(int(timer["owner_id"]), int(timer["id"]))
                try:
                    await _fire(timer)
                except TelegramAPIError as err:
                    log.warning("таймер %s не сработал: %s", timer["id"], err)
        except Exception as err:  # noqa: BLE001 — фоновой задаче нельзя падать
            log.warning("таймеры: %s", err)
        await asyncio.sleep(TICK)
