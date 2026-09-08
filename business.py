"""Бизнес-обновления: команды, антискам, архив, автоответы.

Сюда приходят четыре типа апдейтов Telegram Business:

* business_connection — бота подключили, отключили или сменили права;
* business_message — сообщение в личном чате владельца (в том числе его
  собственное и отправленное этим же ботом);
* edited_business_message — сообщение исправили;
* deleted_business_messages — сообщения удалили; внутри только номера,
  ни текста, ни файлов.

Из последнего пункта растёт архив: показать удалённое можно только
если бот сохранил сообщение в момент получения. Поэтому входящие
складываются в базу сразу, а при удалении достаются оттуда и уходят
владельцу карточкой — с ником, временем и самим файлом.

<b>Порядок разбора входящего важнее любой отдельной функции.</b>
Сообщение проходит по ступеням, и первая сработавшая забирает его себе:

1. свой же ответ (sender_business_bot) — выходим, иначе бот отвечает сам себе;
2. сообщение владельца — команда, ход в игре или просто «человек в диалоге»;
3. глухой режим — сообщение удаляется, текст уходит владельцу;
4. антискам — то же, но с объяснением, почему;
5. ход в партии — «5» посреди крестиков не должно ловиться правилом;
6. автоответ по правилам.

Ступени именно в этом порядке: фильтр должен успеть до автоответа,
иначе бот вежливо ответит спамеру от имени владельца.
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

import cmd_games
import cmdbase
import commands
import config
import db
import engine
import guard
import keyboards
import state
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


def rights_of(conn: BusinessConnection) -> dict[str, bool]:
    """Все права бота в подключении.

    В Bot API 9.0 плоский can_reply заменили объектом rights с десятком
    отдельных разрешений. Поддерживаются оба варианта: на старом aiogram
    поля rights нет, на новом нет can_reply.
    """
    rights = getattr(conn, "rights", None)
    if rights is not None:
        data = {}
        for name in cmdbase.RIGHT_TITLES:
            value = getattr(rights, name, None)
            if value is not None:
                data[name] = bool(value)
        data.setdefault("can_read_messages", True)
        return data
    return {
        "can_reply": bool(getattr(conn, "can_reply", False)),
        "can_read_messages": True,
    }


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
        return (
            "document",
            text or (message.document.file_name or ""),
            message.document.file_id,
        )
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
    """Подключение из базы; если его там нет — спросить у Telegram."""
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
    rights = rights_of(conn)
    await db.save_connection(
        conn.id,
        conn.user.id,
        conn.user_chat_id,
        enabled=bool(conn.is_enabled),
        can_reply=rights.get("can_reply", False),
        can_read=rights.get("can_read_messages", True),
        rights=rights,
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

    rights = rights_of(event)
    await db.save_connection(
        event.id,
        event.user.id,
        event.user_chat_id,
        enabled=bool(event.is_enabled),
        can_reply=rights.get("can_reply", False),
        can_read=rights.get("can_read_messages", True),
        rights=rights,
        username=event.user.username,
        name=event.user.full_name,
    )
    st = await db.settings_of(event.user.id)
    log.info(
        "подключение %s: владелец %s, включено=%s, права=%s",
        event.id,
        event.user.id,
        event.is_enabled,
        sum(1 for v in rights.values() if v),
    )

    if event.is_enabled:
        note = texts.connected(rights, st)
        markup = keyboards.root(st)
    else:
        note, markup = texts.DISCONNECTED, None
    try:
        await bot.send_message(event.user_chat_id, note, reply_markup=markup)
    except TelegramAPIError as err:
        log.warning("не смог написать владельцу %s: %s", event.user.id, err)


@router.business_message()
async def on_business_message(message: Message, bot: Bot) -> None:
    """Главная развилка: сообщение в личном чате владельца."""
    row = await ensure_connection(bot, message.business_connection_id)
    if row is None:
        return
    owner_id = int(row["owner_id"])
    chat_id = message.chat.id
    conn_id = str(message.business_connection_id)

    # Ответ, который этот же бот только что отправил от имени владельца,
    # прилетает обратно обычным business_message.
    if getattr(message, "sender_business_bot", None) is not None:
        return

    user = message.from_user
    if user is None:
        return

    st = await db.settings_of(owner_id)
    owner_name = (row["name"] or "вы").split()[0]

    # ---------------------------------------------------------- владелец
    if user.id == owner_id:
        chat = await db.touch_chat(owner_id, chat_id, from_owner=True)
        peer_name = (chat["title"] or "собеседник").split()[0]

        name = await commands.handle(
            bot=bot,
            conn=row,
            settings=st,
            message=message,
            owner_name=owner_name,
            peer_name=peer_name,
            peer_id=chat_id,
        )
        if name:
            state.remember(owner_id, chat_id, "command", f"команда .{name}")
            return

        _, text, _ = extract(message)
        if await cmd_games.handle_move(
            bot, conn_id, owner_id, chat_id, owner_id, text,
            owner_name=owner_name, peer_name=peer_name,
        ):
            state.remember(owner_id, chat_id, "game", "ваш ход в партии")
        return

    if user.is_bot and not st["filter_on"]:
        return

    # -------------------------------------------------------- собеседник
    peer_name = user.full_name
    chat = await db.touch_chat(
        owner_id, chat_id, title=peer_name, username=user.username
    )
    kind, text, file_id = extract(message)
    rights = cmdbase.rights_from(row)

    if st["spy"]:
        await db.save_message(
            owner_id,
            chat_id,
            message.message_id,
            from_id=user.id,
            from_name=peer_name,
            kind=kind,
            text=text,
            file_id=file_id,
            at=int(message.date.timestamp()),
        )

    # 3. Глухой режим
    if chat["muted"]:
        await _mute_drop(bot, row, message, kind, text, file_id, peer_name)
        state.remember(owner_id, chat_id, "muted", "чат в глухом режиме")
        return

    # 4. Антискам
    if st["filter_on"]:
        established = bool(
            chat["trusted"] or chat["owner_seen"] > 0 or chat["incoming"] > 5
        )
        verdict = guard.inspect(
            guard.snapshot_of(message),
            established=established,
            own_words=st["filter_words"] or "",
            threshold=int(st["filter_score"]),
        )
        if verdict.bad:
            await _filtered(
                bot, row, st, message, verdict, kind, text, file_id, peer_name
            )
            state.remember(
                owner_id, chat_id, "filtered",
                f"{verdict.score} очк.: {verdict.why()}",
            )
            return

    # 5. Уведомление о новом диалоге
    if st["notify_new"] and chat["incoming"] <= 1 and not chat["owner_seen"]:
        await _notify_new(bot, row, message, peer_name, text)

    # 6. Ход в партии
    if await cmd_games.handle_move(
        bot, conn_id, owner_id, chat_id, user.id, text,
        owner_name=owner_name, peer_name=peer_name,
    ):
        state.remember(owner_id, chat_id, "game", "ход собеседника")
        return

    # 7. Автоответ
    if not row["enabled"] or not rights.get("can_reply"):
        return

    key = (owner_id, chat_id)
    if key in _busy:
        return

    rules = await db.rules_of(owner_id, only_enabled=True)
    decision = engine.decide(text=text, settings=st, rules=rules, chat=chat)
    state.remember(owner_id, chat_id, decision.kind, decision.reason)
    if not decision.send:
        return

    answer = engine.render(
        decision.text, name=user.first_name or "", username=user.username or ""
    )
    _busy.add(key)
    try:
        try:
            await bot.send_chat_action(
                chat_id=chat_id, action="typing", business_connection_id=conn_id
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
                business_connection_id=conn_id,
                parse_mode=None,
            )
        except TelegramAPIError as err:
            log.warning("не отправил ответ в %s: %s", chat_id, err)
            if "BUSINESS_CONNECTION" in str(err).upper():
                await db.disable_connection(conn_id)
            return
    finally:
        _busy.discard(key)

    await db.mark_reply(owner_id, chat_id, decision.rule_id)
    await db.log_reply(owner_id, chat_id, decision.kind, decision.rule_id, text, answer)
    if decision.rule_id:
        await db.bump_rule(decision.rule_id)


# --------------------------------------------------------------------------
# Глухой режим и антискам
# --------------------------------------------------------------------------


async def _drop_incoming(bot: Bot, conn_id: str, message: Message) -> bool:
    try:
        await bot.delete_business_messages(
            business_connection_id=conn_id, message_ids=[message.message_id]
        )
        return True
    except TelegramAPIError as err:
        log.info("не удалил входящее: %s", err)
        return False


async def _mute_drop(
    bot: Bot,
    row: Any,
    message: Message,
    kind: str,
    text: str,
    file_id: str | None,
    peer_name: str,
) -> None:
    """Убрать сообщение из чата и переслать владельцу."""
    conn_id = str(message.business_connection_id)
    gone = await _drop_incoming(bot, conn_id, message)
    card = texts.muted_card(
        name=peer_name,
        username=message.from_user.username if message.from_user else None,
        user_id=message.chat.id,
        kind=kind,
        text=text,
        removed=gone,
    )
    try:
        await bot.send_message(
            row["user_chat_id"], card, reply_markup=keyboards.muted(message.chat.id)
        )
    except TelegramAPIError:
        return
    if file_id:
        await resend(bot, int(row["user_chat_id"]), kind, file_id)


async def _filtered(
    bot: Bot,
    row: Any,
    st: Any,
    message: Message,
    verdict: guard.Verdict,
    kind: str,
    text: str,
    file_id: str | None,
    peer_name: str,
) -> None:
    """Сработал антискам: убрать (если велено) и объяснить владельцу."""
    owner_id = int(row["owner_id"])
    chat_id = message.chat.id
    conn_id = str(message.business_connection_id)

    removed = False
    if st["filter_delete"]:
        removed = await _drop_incoming(bot, conn_id, message)
    await db.bump_chat(owner_id, chat_id, "flagged")

    card = texts.filtered_card(
        name=peer_name,
        username=message.from_user.username if message.from_user else None,
        user_id=chat_id,
        kind=kind,
        text=text,
        verdict=verdict,
        removed=removed,
    )
    try:
        await bot.send_message(
            row["user_chat_id"], card, reply_markup=keyboards.filtered(chat_id)
        )
    except TelegramAPIError as err:
        log.warning("не отправил карточку антискама: %s", err)
        return
    if file_id and kind != "document":
        # Документ намеренно не пересылаем: именно исполняемый файл и
        # мог быть причиной срабатывания, и подсовывать его владельцу
        # в личку — последнее, что стоит делать.
        await resend(bot, int(row["user_chat_id"]), kind, file_id)


async def _notify_new(
    bot: Bot, row: Any, message: Message, peer_name: str, text: str
) -> None:
    card = texts.new_dialog_card(
        name=peer_name,
        username=message.from_user.username if message.from_user else None,
        user_id=message.chat.id,
        text=text,
    )
    try:
        await bot.send_message(
            row["user_chat_id"], card, reply_markup=keyboards.new_dialog(message.chat.id)
        )
    except TelegramAPIError:
        pass


# --------------------------------------------------------------------------
# Правки и удаления
# --------------------------------------------------------------------------


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
    if before == text:
        return
    await db.bump_chat(owner_id, message.chat.id, "edited")
    if not st["spy_edits"]:
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
        await bot.send_message(row["user_chat_id"], card)
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

    await db.bump_chat(owner_id, event.chat.id, "deleted", len(rows))
    chat = await db.chat_of(owner_id, event.chat.id)
    name = (
        getattr(event.chat, "full_name", None)
        or chat["title"]
        or rows[-1]["from_name"]
    )
    username = event.chat.username or chat["username"]

    shown = rows[-MAX_IN_REPORT:]
    card = texts.deleted_card(
        name=name,
        username=username,
        user_id=event.chat.id,
        rows=shown,
        extra=len(rows) - len(shown),
        total_deleted=int(chat["deleted"] or 0),
    )
    try:
        await bot.send_message(
            row["user_chat_id"], card, reply_markup=keyboards.deleted(event.chat.id)
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
    самоуничтожающиеся фото так не достать. Поэтому ошибка здесь не
    считается сбоем: текстовая карточка уже ушла, и владелец знает,
    что именно удалили.
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
