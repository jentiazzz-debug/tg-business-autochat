"""Бизнес-обновления: ответы от имени владельца, удалённые и правки.

Сюда приходят четыре типа апдейтов Telegram Business:

* business_connection — бота подключили, отключили или поменяли ему права;
* business_message — сообщение в личном чате владельца (в том числе его
  собственное и отправленное этим же ботом);
* edited_business_message — сообщение исправили;
* deleted_business_messages — сообщения удалили; внутри только номера,
  ни текста, ни файлов.

Из последнего пункта растёт вся конструкция с архивом: показать
удалённое можно, только если бот сохранил сообщение в момент получения.
Поэтому входящие складываются в базу сразу, а при удалении достаются
оттуда и уходят владельцу в личку карточкой — с ником, временем и самим
файлом, если он был.

Три вещи, на которых такой бот ломается чаще всего, и как они решены:

1. Собственные ответы возвращаются апдейтом business_message от имени
   владельца. Без проверки sender_business_bot бот отвечал бы сам себе.
2. Сообщения владельца — сигнал «человек в диалоге», а не повод
   ответить: они только продлевают паузу.
3. Пока бот «печатает» перед ответом, в чат успевают прилететь ещё
   сообщения. Чат на это время помечается занятым, иначе на три строки
   подряд уйдут три одинаковых ответа.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BusinessConnection, BusinessMessagesDeleted, Message

import config
import db
import engine
import keyboards
import texts

log = logging.getLogger("autochat.business")
router = Router(name="business")

#: Сколько удалённых сообщений разворачивать в одной карточке. Если
#: собеседник снёс всю переписку, владельцу не нужен её полный текст
#: сотней сообщений — нужен факт и последние несколько.
MAX_IN_REPORT = 8

#: Чаты, в которых прямо сейчас готовится ответ.
_busy: set[tuple[int, int]] = set()

#: Как переотправить сохранённое вложение: метод бота и имя аргумента.
SENDERS: dict[str, tuple[str, str]] = {
    "photo": ("send_photo", "photo"),
    "video": ("send_video", "video"),
    "animation": ("send_animation", "animation"),
    "voice": ("send_voice", "voice"),
    "video_note": ("send_video_note", "video_note"),
    "audio": ("send_audio", "audio"),
    "document": ("send_document", "document"),
    "sticker": ("send_sticker", "sticker"),
}


def rights_of(conn: BusinessConnection) -> tuple[bool, bool]:
    """Права бота в подключении: (отвечать, читать).

    В Bot API 9.0 плоский can_reply заменили объектом rights с десятком
    отдельных разрешений. Поддерживаются оба варианта: на старом
    aiogram поля rights просто нет, на новом нет can_reply.
    """
    rights = getattr(conn, "rights", None)
    if rights is not None:
        return (
            bool(getattr(rights, "can_reply", False)),
            bool(getattr(rights, "can_read_messages", True)),
        )
    return bool(getattr(conn, "can_reply", False)), True


def extract(message: Message) -> tuple[str, str, str | None]:
    """Тип сообщения, его текст и file_id вложения.

    Порядок проверок не случаен: у GIF заполнены сразу animation и
    document, у кружка — video_note и video. Сначала более узкий тип,
    иначе гифка уедет в архив как безымянный файл.
    """
    text = message.text or message.caption or ""
    if message.animation:
        return "animation", text, message.animation.file_id
    if message.photo:
        return "photo", text, message.photo[-1].file_id
    if message.video_note:
        return "video_note", text, message.video_note.file_id
    if message.video:
        return "video", text, message.video.file_id
    if message.voice:
        return "voice", text, message.voice.file_id
    if message.audio:
        return "audio", text, message.audio.file_id
    if message.sticker:
        emoji = message.sticker.emoji or ""
        return "sticker", text or emoji, message.sticker.file_id
    if message.document:
        return "document", text or (message.document.file_name or ""), message.document.file_id
    if message.contact:
        contact = message.contact
        who = " ".join(filter(None, (contact.first_name, contact.last_name)))
        return "contact", f"{who} · {contact.phone_number}", None
    if message.location:
        loc = message.location
        return "location", f"{loc.latitude}, {loc.longitude}", None
    if message.poll:
        return "poll", message.poll.question, None
    if message.dice:
        return "dice", message.dice.emoji or "", None
    if getattr(message, "story", None):
        return "story", "", None
    if text:
        return "text", text, None
    return "other", text, None


async def ensure_connection(bot: Bot, conn_id: str | None) -> Any | None:
    """Подключение из базы; если его там нет — спросить у Telegram.

    Нужно после переезда или чистой базы: подключение уже существует на
    стороне Telegram, апдейты идут, а бот про него ничего не знает.
    """
    if not conn_id:
        return None
    row = await db.connection_by_id(conn_id)
    if row is not None:
        return row
    try:
        conn = await bot.get_business_connection(business_connection_id=conn_id)
    except TelegramAPIError as err:
        log.warning("не удалось получить подключение %s: %s", conn_id, err)
        return None
    if config.ALLOWED_IDS and conn.user.id not in config.ALLOWED_IDS:
        return None
    can_reply, can_read = rights_of(conn)
    await db.save_connection(
        conn.id,
        conn.user.id,
        conn.user_chat_id,
        enabled=bool(conn.is_enabled),
        can_reply=can_reply,
        can_read=can_read,
        username=conn.user.username,
        name=conn.user.full_name,
    )
    return await db.connection_by_id(conn_id)


@router.business_connection()
async def on_connection(event: BusinessConnection, bot: Bot) -> None:
    """Бота подключили к Telegram Business, отключили или сменили права."""
    if config.ALLOWED_IDS and event.user.id not in config.ALLOWED_IDS:
        log.warning("чужое подключение от %s — отклонено", event.user.id)
        try:
            await bot.send_message(event.user_chat_id, texts.NOT_ALLOWED)
        except TelegramAPIError:
            pass
        return

    can_reply, can_read = rights_of(event)
    await db.save_connection(
        event.id,
        event.user.id,
        event.user_chat_id,
        enabled=bool(event.is_enabled),
        can_reply=can_reply,
        can_read=can_read,
        username=event.user.username,
        name=event.user.full_name,
    )
    await db.settings_of(event.user.id)
    log.info(
        "подключение %s: владелец %s, включено=%s, ответы=%s",
        event.id,
        event.user.id,
        event.is_enabled,
        can_reply,
    )

    if event.is_enabled:
        note = texts.CONNECTED
        if not can_reply:
            note += "\n\n" + texts.NO_REPLY_RIGHT
        markup = keyboards.root(await db.settings_of(event.user.id))
    else:
        note, markup = texts.DISCONNECTED, None
    try:
        await bot.send_message(event.user_chat_id, note, reply_markup=markup)
    except TelegramAPIError as err:
        log.warning("не смог написать владельцу %s: %s", event.user.id, err)


@router.business_message()
async def on_business_message(message: Message, bot: Bot) -> None:
    """Сообщение в личном чате владельца: архив плюс, может быть, ответ."""
    row = await ensure_connection(bot, message.business_connection_id)
    if row is None:
        return
    owner_id = int(row["owner_id"])
    chat_id = message.chat.id

    # Ответ, который этот же бот только что отправил от имени владельца,
    # прилетает обратно обычным business_message. Без этой проверки бот
    # отвечает сам себе и заодно сам себе продлевает паузу.
    if getattr(message, "sender_business_bot", None) is not None:
        return

    user = message.from_user
    if user is None:
        return

    if user.id == owner_id:
        # Владелец пишет сам — значит, он в диалоге. Только продлеваем
        # паузу и уходим.
        await db.touch_chat(owner_id, chat_id, from_owner=True)
        return
    if user.is_bot:
        return

    name = user.full_name
    chat = await db.touch_chat(owner_id, chat_id, title=name, username=user.username)
    st = await db.settings_of(owner_id)
    kind, text, file_id = extract(message)

    if st["spy"]:
        await db.save_message(
            owner_id,
            chat_id,
            message.message_id,
            from_id=user.id,
            from_name=name,
            kind=kind,
            text=text,
            file_id=file_id,
            at=int(message.date.timestamp()),
        )

    if not row["enabled"] or not row["can_reply"]:
        return

    key = (owner_id, chat_id)
    if key in _busy:
        return

    rules = await db.rules_of(owner_id, only_enabled=True)
    decision = engine.decide(text=text, settings=st, rules=rules, chat=chat)
    if not decision.send:
        return

    answer = engine.render(
        decision.text, name=user.first_name or "", username=user.username or ""
    )
    _busy.add(key)
    try:
        try:
            await bot.send_chat_action(
                chat_id=chat_id,
                action="typing",
                business_connection_id=message.business_connection_id,
            )
        except TelegramAPIError:
            # Индикатор «печатает» — украшение; молчать из-за него не повод.
            pass
        await asyncio.sleep(random.uniform(config.DELAY_MIN, config.DELAY_MAX))
        try:
            # parse_mode=None намеренно: текст ответа писал человек, и
            # знак «<» в нём не должен ронять отправку.
            await bot.send_message(
                chat_id=chat_id,
                text=answer,
                business_connection_id=message.business_connection_id,
                parse_mode=None,
            )
        except TelegramAPIError as err:
            log.warning("не отправил ответ в %s: %s", chat_id, err)
            if "BUSINESS_CONNECTION" in str(err).upper():
                await db.disable_connection(str(message.business_connection_id))
            return
    finally:
        _busy.discard(key)

    await db.mark_reply(owner_id, chat_id, decision.rule_id)
    await db.log_reply(owner_id, chat_id, decision.kind, decision.rule_id, text, answer)
    if decision.rule_id:
        await db.bump_rule(decision.rule_id)


@router.edited_business_message()
async def on_edited(message: Message, bot: Bot) -> None:
    """Собеседник поправил сообщение — показать, что было и что стало."""
    row = await ensure_connection(bot, message.business_connection_id)
    if row is None:
        return
    owner_id = int(row["owner_id"])
    if getattr(message, "sender_business_bot", None) is not None:
        return
    user = message.from_user
    if user is None or user.id == owner_id:
        return

    old = await db.message_of(owner_id, message.chat.id, message.message_id)
    if old is None:
        # Сообщения нет в архиве: пришло до подключения бота или уже
        # выпало по сроку хранения. Сравнивать не с чем.
        return

    st = await db.settings_of(owner_id)
    _, text, _ = extract(message)
    before = old["text"] or ""
    await db.replace_text(owner_id, message.chat.id, message.message_id, text)
    if not st["spy_edits"] or before == text:
        return

    card = texts.edited_card(
        name=user.full_name,
        username=user.username,
        user_id=user.id,
        before=before,
        after=text,
        ts=int(time.time()),
    )
    try:
        await bot.send_message(
            row["user_chat_id"], card
        )
    except TelegramAPIError as err:
        log.warning("не отправил карточку правки: %s", err)


@router.deleted_business_messages()
async def on_deleted(event: BusinessMessagesDeleted, bot: Bot) -> None:
    """Сообщения удалили — достать их из архива и показать владельцу."""
    row = await ensure_connection(bot, event.business_connection_id)
    if row is None:
        return
    owner_id = int(row["owner_id"])
    st = await db.settings_of(owner_id)
    if not st["spy"]:
        return

    rows = await db.find_messages(owner_id, event.chat.id, event.message_ids)
    if not rows:
        # В архиве ничего нет: удалили сообщения самого владельца
        # (их бот не хранит) или что-то из времён до подключения.
        return

    chat = await db.chat_of(owner_id, event.chat.id)
    name = getattr(event.chat, "full_name", None) or chat["title"] or rows[-1]["from_name"]
    username = event.chat.username or chat["username"]

    shown = rows[-MAX_IN_REPORT:]
    card = texts.deleted_card(
        name=name,
        username=username,
        user_id=event.chat.id,
        rows=shown,
        extra=len(rows) - len(shown),
    )
    try:
        await bot.send_message(
            row["user_chat_id"],
            card,
            reply_markup=keyboards.deleted(event.chat.id),
        )
    except TelegramAPIError as err:
        log.warning("не отправил карточку удаления: %s", err)
        return

    await db.forget_messages(owner_id, event.chat.id, [r["message_id"] for r in rows])
    for item in shown:
        if item["file_id"]:
            await resend(bot, int(row["user_chat_id"]), item["kind"], item["file_id"])


async def resend(bot: Bot, chat_id: int, kind: str, file_id: str) -> None:
    """Переслать сохранённое вложение владельцу.

    file_id остаётся рабочим и после удаления сообщения: файл лежит на
    серверах Telegram отдельно от переписки. Но это не гарантия —
    самоуничтожающиеся фото и файлы, которые Telegram уже выгрузил, так
    не достать. Поэтому ошибка здесь не считается сбоем: текстовая
    карточка уже ушла, и владелец знает, что именно удалили.
    """
    sender = SENDERS.get(kind)
    if sender is None:
        return
    method, arg = sender
    try:
        await getattr(bot, method)(chat_id=chat_id, **{arg: file_id})
    except TelegramAPIError as err:
        log.info("вложение %s недоступно: %s", kind, err)
        try:
            await bot.send_message(
                chat_id,
                f"⚠️ {texts.KINDS.get(kind, kind)} уже недоступно на серверах Telegram.",
            )
        except TelegramAPIError:
            pass
