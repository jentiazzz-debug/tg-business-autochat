"""Обязательная подписка: основной канал и спонсоры.

Основной канал (REQUIRED_CHANNEL) обязателен везде — и в основном
боте, и во всех зеркалах. Спонсоров админ добавляет в /admin.

Проверяет всегда **основной бот**: getChatMember в канале работает
только у его администратора, а зеркало, созданное чужим человеком,
админом нашего канала не станет. Основной бот видит подписку любого
пользователя, через какого бы бота тот ни пришёл.

Отказ Telegram (бота сняли с админки, канал удалён) считается «не
мешать»: из-за нашей ошибки в настройке люди не должны упираться в
стену, которую невозможно пройти. Об этом пишется в лог.

Ответ кэшируется: подписанным — на CACHE_OK секунд, чтобы бизнес-
сообщения не дёргали Telegram на каждое входящее; неподписанным — не
кэшируется, чтобы кнопка «Я подписался» срабатывала сразу.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import config
import db

log = logging.getLogger("autochat.subs")

CACHE_OK = 600
#: Как часто напоминать о подписке тому, у кого из-за неё встали
#: бизнес-функции, секунды.
NAG_EVERY = 6 * 3600

#: Кто проверяет подписку — ставит main.py.
MAIN_BOT: Bot | None = None

#: Неподписанным — коротко: входящие в бизнес-чате без подписки иначе
#: дёргали бы getChatMember на каждое сообщение. Кнопка «Я подписался»
#: идёт мимо кэша (fresh=True).
CACHE_BAD = 60

_ok_until: dict[int, float] = {}
_bad: dict[int, tuple[float, list]] = {}
_nagged: dict[int, float] = {}
#: Карточка основного канала: название и ссылка, достаются один раз.
_main_card: dict[str, Any] | None = None

_GOOD = {"creator", "administrator", "member", "restricted"}


async def _main_channel() -> dict[str, Any] | None:
    global _main_card
    if not config.REQUIRED_CHANNEL or MAIN_BOT is None:
        return None
    if _main_card is not None:
        return _main_card
    chat_id = config.REQUIRED_CHANNEL
    url = config.REQUIRED_CHANNEL_URL
    title = "Канал Solutions"
    try:
        chat = await MAIN_BOT.get_chat(chat_id)
        title = chat.title or title
        if not url:
            if chat.username:
                url = f"https://t.me/{chat.username}"
            else:
                url = chat.invite_link or await MAIN_BOT.export_chat_invite_link(chat_id)
    except TelegramAPIError as err:
        log.warning("основной канал %s недоступен боту: %s", chat_id, err)
        if not url:
            return None
    _main_card = {"chat_id": chat_id, "title": title, "url": url}
    return _main_card


async def channels() -> list[dict[str, Any]]:
    """Все каналы, на которые нужна подписка: основной первым."""
    out = []
    main = await _main_channel()
    if main:
        out.append(main)
    for row in await db.sponsors():
        out.append({"chat_id": int(row["chat_id"]), "title": row["title"], "url": row["url"]})
    return out


async def _is_member(chat_id: int, user_id: int) -> bool:
    assert MAIN_BOT is not None
    try:
        member = await MAIN_BOT.get_chat_member(chat_id, user_id)
    except TelegramAPIError as err:
        log.warning("не проверить подписку на %s: %s — пропускаю", chat_id, err)
        return True
    return member.status in _GOOD


async def missing(user_id: int, *, fresh: bool = False) -> list[dict[str, Any]]:
    """Каналы, на которые человек ещё не подписан. Пусто — всё в порядке."""
    if MAIN_BOT is None or user_id in config.ADMIN_IDS:
        return []
    now = time.time()
    if not fresh:
        if _ok_until.get(user_id, 0) > now:
            return []
        cached = _bad.get(user_id)
        if cached is not None and cached[0] > now:
            return cached[1]
    need = [ch for ch in await channels() if not await _is_member(ch["chat_id"], user_id)]
    if need:
        _ok_until.pop(user_id, None)
        _bad[user_id] = (now + CACHE_BAD, need)
    else:
        _bad.pop(user_id, None)
        _ok_until[user_id] = now + CACHE_OK
    return need


def forget(user_id: int) -> None:
    _ok_until.pop(user_id, None)
    _bad.pop(user_id, None)


def should_nag(user_id: int) -> bool:
    now = time.time()
    if _nagged.get(user_id, 0) > now:
        return False
    _nagged[user_id] = now + NAG_EVERY
    return True


def prune() -> None:
    """Выкинуть протухшие записи — словари не должны расти вечно."""
    now = time.time()
    for store in (_ok_until, _nagged):
        for key in [k for k, v in store.items() if v <= now]:
            store.pop(key, None)
    for key in [k for k, v in _bad.items() if v[0] <= now]:
        _bad.pop(key, None)


def reset_cards() -> None:
    """Сбросить карточку канала — после смены спонсоров или ссылки."""
    global _main_card
    _main_card = None
