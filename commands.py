"""Сборка команд и точка входа для business.py.

Импорты модулей cmd_* нужны ради их побочного эффекта: декораторы
@command при загрузке наполняют общий реестр. Поэтому линтер будет
считать их неиспользованными — так и есть, они здесь именно для
регистрации, и это единственное место, где такой импорт уместен.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from aiogram import Bot
from aiogram.types import Message

import cmd_chat  # noqa: F401  — регистрация команд
import cmd_games  # noqa: F401
import cmd_media  # noqa: F401
import cmd_profile  # noqa: F401
import cmd_text  # noqa: F401
import cmdbase
from cmdbase import Ctx, RIGHT_TITLES

log = logging.getLogger("autochat.commands")

#: Сколько команд собралось — цифра идёт в справку и в панель.
def count() -> int:
    return len(cmdbase.ORDER)


def names() -> list[str]:
    return sorted(cmdbase.REGISTRY)


def help_pages(prefix: str = ".") -> list[str]:
    return cmdbase.help_pages(prefix)


def looks_like_command(text: str, prefix: str) -> bool:
    """Похоже ли сообщение на команду — без её выполнения."""
    parsed = cmdbase.parse(text, (prefix,))
    return parsed is not None and cmdbase.find(parsed[0]) is not None


async def handle(
    *,
    bot: Bot,
    conn: Mapping[str, Any],
    settings: Mapping[str, Any],
    message: Message,
    owner_name: str,
    peer_name: str,
    peer_id: int,
) -> str | None:
    """Выполнить команду владельца. Возвращает её имя или None.

    None значит «это не команда» — сообщение владельца идёт дальше
    обычным путём и только продлевает паузу автоответчику.
    """
    if not settings["commands"]:
        return None

    text = message.text or message.caption or ""
    prefix = (settings["prefix"] or ".")[0]
    parsed = cmdbase.parse(text, (prefix,))
    if parsed is None:
        return None
    name, args = parsed
    cmd = cmdbase.find(name)
    if cmd is None:
        return None

    rights = cmdbase.rights_from(conn)
    ctx = Ctx(
        bot=bot,
        conn_id=str(message.business_connection_id),
        owner_id=int(conn["owner_id"]),
        owner_chat_id=int(conn["user_chat_id"]),
        chat_id=message.chat.id,
        message=message,
        args=args,
        settings=settings,
        owner_name=owner_name,
        peer_name=peer_name,
        peer_id=peer_id,
        rights=rights,
    )

    missing = cmdbase.missing_rights(cmd, rights)
    if missing:
        titles = ", ".join(f"«{RIGHT_TITLES.get(r, r)}»" for r in missing)
        await ctx.fail(
            f"боту не выдано право {titles}. Настройки Telegram → "
            "Telegram для бизнеса → Автоматизация чатов → права бота."
        )
        return cmd.name

    try:
        await cmd.run(ctx)
    except Exception as err:  # noqa: BLE001
        # Команда не должна ронять обработчик апдейта: у владельца в
        # чате уже может лежать удалённое сообщение, и падение здесь
        # оставит его без ответа и без объяснения.
        log.exception("команда %s упала: %s", cmd.name, err)
        await ctx.to_owner(f"⚠️ команда <code>{cmd.name}</code> сломалась: {err}")
    return cmd.name
