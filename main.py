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

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BotCommand

import business
import config
import db
import handlers

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


async def cleanup() -> None:
    """Фоновая уборка архива и журнала.

    Архив чужих сообщений не должен жить дольше, чем нужно для показа
    удалённого: это чужая переписка, и хранить её месяцами незачем.
    """
    while True:
        try:
            gone = await db.prune_messages()
            logs = await db.prune_log(config.LOG_KEEP_DAYS)
            if gone or logs:
                log.info("уборка: архив -%s, журнал -%s", gone, logs)
        except Exception as err:  # noqa: BLE001 — фоновой задаче нельзя падать
            log.warning("уборка не удалась: %s", err)
        await asyncio.sleep(config.CLEANUP_INTERVAL)


async def run() -> None:
    config.check()
    await db.connect()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML, link_preview_is_disabled=True
        ),
    )
    bot.session.middleware(RetryAfter())
    dispatcher = Dispatcher()

    # Бизнес-роутер идёт первым: он обслуживает свои типы апдейтов и с
    # панелью не пересекается, но так порядок читается сверху вниз —
    # сначала работа, потом настройки.
    dispatcher.include_router(business.router)
    dispatcher.include_router(handlers.router)
    if config.ALLOWED_IDS:
        # Последним: сюда попадают только те, кого отсеял фильтр панели.
        dispatcher.include_router(handlers.strangers)

    me = await bot.me()
    log.info("бот @%s (%s)", me.username, me.id)
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

    janitor = asyncio.create_task(cleanup())
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        janitor.cancel()
        await db.close()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("остановлен")


if __name__ == "__main__":
    main()
