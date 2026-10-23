"""Точка входа: база, бот, фоновая уборка, поллинг.

Самая частая причина «бот не появляется в списке» — выключенный
Business Mode у самого бота: @BotFather → /mybots → Bot Settings →
Business Mode → Enable. Telegram сообщает об этом флагом
can_connect_to_business в getMe, поэтому проверка идёт при старте и
пишет в лог человеческим языком, а не оставляет гадать.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BotCommand, BotCommandScopeChat

import admin
import business
import config
import db
import games
import handlers
import mirrors
import mirrorui
import pe
import state
import subs
import timers
from storage import LeanStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("autochat")

COMMANDS = (
    ("menu", "Панель управления"),
    ("on", "Включить автоответы"),
    ("off", "Выключить автоответы"),
    ("away", "Режим «отошёл»"),
    ("back", "Вернуться из режима «отошёл»"),
    ("rules", "Правила автоответов"),
    ("add", "Добавить правило"),
    ("commands", "Команды для чатов"),
    ("mirror", "Своё зеркало бота"),
    ("stats", "Статистика"),
    ("log", "Последние ответы"),
    ("help", "Справка"),
)


#: Сколько раз повторить запрос, упёршийся в лимит Telegram.
RETRIES = 3


class RetryAfter(BaseRequestMiddleware):
    """Переждать лимит Telegram и повторить запрос.

    Открытый бот обслуживает многих владельцев сразу, и при всплеске
    (кто-то удалил переписку целиком — это карточка плюс вложения)
    Telegram отвечает 429 «retry after N». Без этого слоя такой ответ
    просто терялся бы: карточка об удалении не дошла, и владелец даже не
    узнал бы, что она была. Ждать сказанное число секунд — единственный
    правильный способ реакции на 429, наращивать частоту бессмысленно.
    """

    async def __call__(self, make_request, bot, method):
        for attempt in range(RETRIES):
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as err:
                log.warning(
                    "лимит Telegram на %s: ждём %s с (попытка %s из %s)",
                    type(method).__name__,
                    err.retry_after,
                    attempt + 1,
                    RETRIES,
                )
                await asyncio.sleep(err.retry_after + 0.5)
        return await make_request(bot, method)


class SeenUsers(BaseMiddleware):
    """Запомнить, через какого бота человек пишет, — для рассылки и зеркал.

    В базу — один раз на пару (бот, человек) за время жизни процесса:
    множество в памяти сбрасывается, если разрастётся.
    """

    LIMIT = 50_000

    def __init__(self) -> None:
        self._seen: set[tuple[int, int]] = set()

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        chat = data.get("event_chat")
        bot = data.get("bot")
        if user is not None and bot is not None and chat is not None and chat.type == "private":
            key = (bot.id, user.id)
            if key not in self._seen:
                if len(self._seen) > self.LIMIT:
                    self._seen.clear()
                self._seen.add(key)
                try:
                    await db.seen_user(bot.id, user.id)
                except Exception as err:  # noqa: BLE001
                    log.debug("seen_user: %s", err)
        return await handler(event, data)


async def cleanup() -> None:
    """Фоновая уборка архива и журнала.

    Архив чужих сообщений не должен жить дольше, чем нужно для показа
    удалённого: это чужая переписка, и хранить её месяцами незачем.
    """
    while True:
        try:
            gone = await db.prune_messages() + await db.prune_trail()
            logs = await db.prune_log(config.LOG_KEEP_DAYS)
            # Память процесса: подсказки «.почему», брошенные партии и
            # кэш подписок не должны копиться неделями.
            state.prune()
            games.prune()
            subs.prune()
            if gone or logs:
                log.info("уборка: архив -%s, журнал -%s", gone, logs)
        except Exception as err:  # noqa: BLE001 — фоновой задаче нельзя падать
            log.warning("уборка не удалась: %s", err)
        await asyncio.sleep(config.CLEANUP_INTERVAL)


async def run() -> None:
    config.check()
    await db.connect()

    # Одна HTTP-сессия на основной бот и все зеркала: см. mirrors.py.
    session = AiohttpSession()
    session.middleware(RetryAfter())
    session.middleware(pe.PremiumFallback())
    default = DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)
    bot = Bot(token=config.BOT_TOKEN, session=session, default=default)
    dispatcher = Dispatcher(storage=LeanStorage())
    dispatcher.update.outer_middleware(SeenUsers())

    # Бизнес-роутер идёт первым: он обслуживает свои типы апдейтов и с
    # панелью не пересекается, но так порядок читается сверху вниз —
    # сначала работа, потом настройки.
    dispatcher.include_router(business.router)
    # Админский роутер идёт раньше панели: у панели есть широкий
    # обработчик любого текста в личке, и он перехватывал бы то, что
    # админ вводит в мастере рассылки.
    dispatcher.include_router(admin.router)
    # Кабинет зеркал — тоже раньше панели: он ждёт токен текстом.
    dispatcher.include_router(mirrorui.router)
    dispatcher.include_router(handlers.router)
    if config.ALLOWED_IDS:
        # Последним: сюда попадают только те, кого отсеял фильтр панели.
        dispatcher.include_router(handlers.strangers)

    me = await bot.me()
    log.info("бот @%s (%s)", me.username, me.id)
    await db.adopt_legacy(me.id)
    await db.seed_audience(me.id)
    subs.MAIN_BOT = bot
    mirrors.MAIN, mirrors.DP, mirrors.SESSION, mirrors.DEFAULT = bot, dispatcher, session, default
    mirrors.COMMANDS = [
        BotCommand(command=name, description=text)
        for name, text in COMMANDS
        if name != "mirror"
    ]
    mirrors.CAN_MANAGE = bool(getattr(me, "can_manage_bots", False))
    if config.REQUIRED_CHANNEL:
        log.info("обязательная подписка: канал %s", config.REQUIRED_CHANNEL)
    if not getattr(me, "can_connect_to_business", False):
        log.warning(
            "У бота выключен Business Mode — в «Автоматизации чатов» его не "
            "будет видно. Включи: @BotFather → /mybots → @%s → Bot Settings "
            "→ Business Mode → Enable.",
            me.username,
        )
    if config.ALLOWED_IDS:
        log.info("закрытый режим: подключаться могут %s", sorted(config.ALLOWED_IDS))
    else:
        log.info(
            "открытый режим: подключить бота к своим чатам может любой. "
            "У каждого владельца свои правила, тексты, архив и статистика — "
            "они не пересекаются. Чтобы закрыть бота, впиши свой id в "
            "ALLOWED_IDS."
        )

    await bot.set_my_commands(
        [BotCommand(command=name, description=text) for name, text in COMMANDS]
    )
    # Админам /admin виден в меню, остальным его там нет: команда всё
    # равно не сработает, а лишний пункт в списке вызывает вопросы.
    admin_menu = [BotCommand(command=name, description=text) for name, text in COMMANDS]
    admin_menu.insert(0, BotCommand(command="admin", description="Админка бота"))
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(
                admin_menu, scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception as err:  # noqa: BLE001
            log.warning("не выставил меню админу %s: %s", admin_id, err)
    if config.ADMIN_IDS:
        log.info("админы бота: %s", sorted(config.ADMIN_IDS))
    else:
        log.info(
            "ADMIN_IDS пуст — админки нет ни у кого. Впиши свой id, чтобы "
            "открыть /admin: статистику, баннер меню и рассылку."
        )

    janitor = asyncio.create_task(cleanup())
    clock = asyncio.create_task(timers.loop())
    await mirrors.boot()
    log.info(
        "зеркал запущено: %s · создание кнопкой: %s",
        mirrors.running(),
        "да" if mirrors.CAN_MANAGE else "нет (включите управление ботами в @BotFather)",
    )
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        janitor.cancel()
        clock.cancel()
        await mirrors.shutdown()
        await db.close()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("остановлен")


if __name__ == "__main__":
    main()
