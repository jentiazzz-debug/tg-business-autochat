"""Зеркала: копии бота, которые любой может поднять за минуту.

Человек создаёт бота (кнопкой Telegram «создать бота» или в @BotFather
и присылает токен) — и бот сразу работает тем же кодом, в том же
процессе, с обязательной подпиской на наш канал. Свой сервер не нужен.

Почему всё в одном процессе и как это держит память:

* **одна HTTP-сессия на всех ботов.** У каждого aiogram.Bot по
  умолчанию своя aiohttp-сессия со своим пулом соединений; сотня
  зеркал — сотня пулов. Токен едет в адресе запроса, поэтому сессия
  может быть общей — это и сделано;
* **свой лёгкий long-polling** на зеркало: один ожидающий getUpdates,
  без отдельного Dispatcher. Апдейты уходят в общий Dispatcher через
  feed_update — роутеры, база и FSM одни на всех;
* зеркала можно добавлять и убирать на ходу — перезапуск не нужен.

Чтобы бот-зеркало показывался в «Автоматизации чатов», его владелец
включает Business Mode в @BotFather. Бот проверяет это при подключении и
говорит прямо, если выключено.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramConflictError,
    TelegramNetworkError,
    TelegramUnauthorizedError,
)
from aiogram.types import BotCommand

import config
import db

log = logging.getLogger("autochat.mirrors")

#: Ставит main.py при запуске.
MAIN: Bot | None = None
DP: Dispatcher | None = None
SESSION: BaseSession | None = None
DEFAULT: DefaultBotProperties | None = None
COMMANDS: list[BotCommand] = []
#: Может ли основной бот создавать ботов кнопкой (Bot Settings →
#: управление ботами в @BotFather).
CAN_MANAGE = False

#: telegram id бота → Bot и задача поллинга.
_bots: dict[int, Bot] = {}
_tasks: dict[int, asyncio.Task] = {}
_inflight: set[asyncio.Task] = set()
#: Сколько апдейтов одного зеркала обрабатываются одновременно. Держит
#: память, если на зеркало налетела волна.
_PARALLEL = 8

POLL_TIMEOUT = 25


def bot_id_of(token: str) -> int:
    head = token.strip().split(":", 1)[0]
    return int(head) if head.isdigit() else 0


def is_main(bot: Bot | None) -> bool:
    return bot is not None and MAIN is not None and bot.id == MAIN.id


def bot_for(bot_id: int | None) -> Bot:
    """Бот, через которого писать: зеркало или основной."""
    assert MAIN is not None
    if not bot_id or bot_id == MAIN.id:
        return MAIN
    return _bots.get(int(bot_id), MAIN)


def running() -> int:
    return len(_bots)


def is_running(bot_id: int) -> bool:
    return int(bot_id) in _bots


# --------------------------------------------------------------------------
# Поллинг
# --------------------------------------------------------------------------


async def _poll(bot: Bot, mirror_id: int) -> None:
    assert DP is not None
    allowed = DP.resolve_used_update_types()
    gate = asyncio.Semaphore(_PARALLEL)
    offset: int | None = None
    pause = 1.0

    async def handle(update) -> None:
        async with gate:
            try:
                await DP.feed_update(bot, update)
            except Exception as err:  # noqa: BLE001 — одно зеркало не роняет остальные
                log.warning("зеркало #%s: апдейт упал: %s", mirror_id, err)

    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except TelegramAPIError:
        pass

    while True:
        try:
            updates = await bot.get_updates(
                offset=offset, timeout=POLL_TIMEOUT, allowed_updates=allowed
            )
            pause = 1.0
        except TelegramUnauthorizedError:
            log.warning("зеркало #%s: токен отозван — останавливаю", mirror_id)
            await db.set_mirror(mirror_id, active=0)
            _bots.pop(bot.id, None)
            _tasks.pop(bot.id, None)
            await _tell_owner(mirror_id, "токен бота отозван в @BotFather — зеркало остановлено. Подключите его заново новым токеном.")
            return
        except TelegramConflictError:
            # Этот же токен опрашивает кто-то ещё (старый сервер).
            await asyncio.sleep(30)
            continue
        except (TelegramNetworkError, TelegramAPIError, asyncio.TimeoutError) as err:
            log.info("зеркало #%s: %s — повтор через %s с", mirror_id, err, pause)
            await asyncio.sleep(pause)
            pause = min(pause * 2, 60)
            continue
        for update in updates:
            offset = update.update_id + 1
            # Ссылку на задачу держим до конца: asyncio хранит задачи
            # слабо, и без неё недоделанный апдейт может собрать GC.
            task = asyncio.create_task(handle(update))
            _inflight.add(task)
            task.add_done_callback(_inflight.discard)


async def _tell_owner(mirror_id: int, text: str) -> None:
    row = await db.mirror_of(mirror_id)
    if row is None or MAIN is None:
        return
    try:
        await MAIN.send_message(
            int(row["owner_id"]), f"Зеркало @{row['username']}: {text}"
        )
    except TelegramAPIError:
        pass


async def start(row: Any) -> str | None:
    """Запустить зеркало. Возвращает текст ошибки или None."""
    bot_id = int(row["bot_id"])
    if bot_id in _bots:
        return None
    bot = Bot(token=row["token"], session=SESSION, default=DEFAULT)
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        return "Telegram не принял токен"
    except TelegramAPIError as err:
        return str(err)
    if me.username != row["username"]:
        await db.set_mirror(int(row["id"]), username=me.username or "", title=me.first_name or "")
    try:
        await bot.set_my_commands(COMMANDS)
    except TelegramAPIError:
        pass
    _bots[bot_id] = bot
    _tasks[bot_id] = asyncio.create_task(_poll(bot, int(row["id"])))
    log.info("зеркало #%s @%s запущено", row["id"], me.username)
    return None


async def stop(bot_id: int) -> None:
    task = _tasks.pop(int(bot_id), None)
    _bots.pop(int(bot_id), None)
    if task is not None:
        task.cancel()


async def boot() -> None:
    """Поднять все активные зеркала при старте."""
    for row in await db.active_mirrors():
        err = await start(row)
        if err:
            log.warning("зеркало #%s не запустилось: %s", row["id"], err)


async def shutdown() -> None:
    for bot_id in list(_tasks):
        await stop(bot_id)


# --------------------------------------------------------------------------
# Подключение
# --------------------------------------------------------------------------


async def add(owner_id: int, token: str) -> tuple[bool, str, int | None]:
    """Подключить бота по токену: (успех, текст для человека, id зеркала)."""
    assert MAIN is not None
    token = token.strip()
    bot_id = bot_id_of(token)
    if not bot_id or len(token) < 40:
        return False, "Это не похоже на токен. Скопируйте его из @BotFather целиком.", None
    if bot_id == MAIN.id:
        return False, "Это токен нашего бота — нужен токен вашего.", None
    if config.MIRRORS_PER_OWNER <= 0:
        return False, "Зеркала сейчас выключены.", None
    taken = await db.mirror_by_bot(bot_id)
    if taken is not None and int(taken["owner_id"]) != owner_id:
        return False, "Этот бот уже подключён другим человеком.", None
    mine = [m for m in await db.mirrors_of(owner_id) if int(m["bot_id"]) != bot_id]
    if len(mine) >= config.MIRRORS_PER_OWNER:
        return False, f"Можно подключить не больше {config.MIRRORS_PER_OWNER} ботов.", None

    probe = Bot(token=token, session=SESSION)
    try:
        me = await probe.get_me()
    except TelegramUnauthorizedError:
        return False, "Telegram не принял токен. Проверьте, что скопировали его целиком.", None
    except TelegramAPIError as err:
        return False, f"Не получилось проверить бота: {err}", None

    await stop(bot_id)
    mirror_id = await db.add_mirror(owner_id, bot_id, token, me.username or "", me.first_name or "")
    err = await start(await db.mirror_of(mirror_id))
    if err:
        await db.set_mirror(mirror_id, active=0)
        return False, f"Бот добавлен, но не запустился: {err}", mirror_id
    note = f"Бот @{me.username} подключён и уже работает."
    if not me.can_connect_to_business:
        note += (
            "\n\nОсталось одно: включите Business Mode — @BotFather → /mybots → "
            f"@{me.username} → Bot Settings → Business Mode → Enable. Без этого "
            "бота не будет видно в «Автоматизации чатов»."
        )
    log.info("зеркало #%s @%s подключил %s", mirror_id, me.username, owner_id)
    return True, note, mirror_id


async def refresh_token(bot_id: int, token: str) -> None:
    """Telegram сменил токен управляемого бота — подхватить без владельца."""
    row = await db.mirror_by_bot(bot_id)
    if row is None or row["token"] == token:
        return
    await db.set_mirror(int(row["id"]), token=token)
    await stop(bot_id)
    if row["active"]:
        await start(await db.mirror_of(int(row["id"])))


async def pause(mirror_id: int, active: bool) -> str | None:
    row = await db.mirror_of(mirror_id)
    if row is None:
        return "зеркала нет"
    await db.set_mirror(mirror_id, active=int(active))
    if active:
        return await start(await db.mirror_of(mirror_id))
    await stop(int(row["bot_id"]))
    return None


async def remove(mirror_id: int) -> None:
    row = await db.mirror_of(mirror_id)
    if row is None:
        return
    await stop(int(row["bot_id"]))
    await db.drop_mirror(mirror_id)
