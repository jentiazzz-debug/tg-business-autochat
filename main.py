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
from aiogram.enums import ParseMode
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
    ("stats", "Статистика"),
    ("log", "Последние ответы"),
    ("help", "Справка"),
)


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
    if not config.ALLOWED_IDS:
        log.warning(
            "ALLOWED_IDS пуст: подключить бота к своим чатам сможет любой, "
            "кто его найдёт. Для личного автоответчика впиши свой id в .env."
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
