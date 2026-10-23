"""Админская панель: статистика по всему боту, баннер меню, рассылка.

Доступ — только для id из ADMIN_IDS. Если список пуст, роутер не
срабатывает ни у кого: фильтр `in_(set())` всегда ложный, и это
правильное поведение по умолчанию — открытая админка у бота, которого
может подключить любой, означала бы рассылку от чужого имени.

<b>Про форматирование рассылки.</b> Текст не набирается разметкой
вручную — админ присылает сообщение так, как хочет его видеть, со своим
жирным, курсивом, спойлерами, ссылками и премиум-эмодзи. Бот забирает
из него html_text, то есть ровно те entities, что расставил Telegram, и
отправляет их обратно. Это и надёжнее ручной разметки, и позволяет
использовать premium-эмодзи: их нельзя «написать», они существуют
только как entity.

<b>Чего Telegram не умеет, а спрашивают часто.</b>

* <b>Цвета инлайн-кнопок не существует.</b> В Bot API у
  InlineKeyboardButton нет поля цвета — кнопку рисует клиент по своей
  теме. Единственный честный способ «покрасить» её — кружок в подписи:
  🟢 🔵 🔴. Именно это и делает выбор цвета ниже.
* Премиум-эмодзи бот может отправлять, если у владельца бота есть
  Telegram Premium (или юзернейм бота куплен на Fragment). На кнопке —
  только одна иконка перед текстом (icon_custom_emoji_id), внутри
  подписи кнопки их нет.

<b>Рассылка идёт по всем ботам</b> — основному и зеркалам: каждый
человек получает её от того бота, которым пользуется. file_id фото и
стикера у каждого бота свой, поэтому для зеркала вложение один раз
скачивается основным ботом и загружается заново, дальше идёт по новому
file_id.

<b>Спонсоры</b> — каналы обязательной подписки сверх основного. Основной
бот должен быть в них админом: иначе Telegram не скажет ему, подписан
ли человек.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from dataclasses import dataclass, field

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import commands
import config
import db
import mirrors
import subs
import texts

log = logging.getLogger("autochat.admin")
router = Router(name="admin")

# Пустой ADMIN_IDS означает «админа нет» — фильтр по пустому множеству
# не пропустит никого, и это именно то, что нужно.
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))


def _main_only(event: object, bot: Bot) -> bool:
    """Админка живёт только в основном боте — в зеркалах её нет."""
    return mirrors.is_main(bot)


router.message.filter(_main_only)
router.callback_query.filter(_main_only)

#: Ключ баннера в bot_meta — общий с панелью владельца.
BANNER = db.BANNER_KEY

#: Цвета — на самом деле кружки в подписи кнопки. См. докстрок модуля.
COLORS = {
    "none": ("без кружка", ""),
    "green": ("🟢 зелёный", "🟢 "),
    "blue": ("🔵 синий", "🔵 "),
    "red": ("🔴 красный", "🔴 "),
}

#: Разрешённые схемы ссылок в кнопках. Telegram отклоняет всё
#: остальное, и отклоняет он сразу всю отправку — поэтому проверяем
#: заранее, а не в момент рассылки.
URL_OK = re.compile(r"^(https?://|tg://|t\.me/)", re.I)


class Form(StatesGroup):
    text = State()
    media = State()
    buttons = State()
    banner = State()
    sponsor = State()


@dataclass(slots=True)
class Draft:
    """Черновик рассылки."""

    text: str = ""
    photo_id: str = ""
    sticker_id: str = ""
    rows: list[list[tuple[str, str]]] = field(default_factory=list)
    color: str = "none"
    #: Для зеркал: байты вложения и его file_id в каждом боте.
    blob: bytes | None = None
    ids: dict[int, str] = field(default_factory=dict)

    def markup(self) -> InlineKeyboardMarkup | None:
        if not self.rows:
            return None
        tint = COLORS.get(self.color, ("", ""))[1]
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"{tint}{label}", url=url) for label, url in row]
                for row in self.rows
            ]
        )

    def empty(self) -> bool:
        return not (self.text or self.photo_id or self.sticker_id)


#: Черновики по админу и флаги остановки по id рассылки.
_drafts: dict[int, Draft] = {}
_stop: set[int] = set()
_running: dict[int, int] = {}


def draft(admin_id: int) -> Draft:
    return _drafts.setdefault(admin_id, Draft())


def esc(text: object) -> str:
    return html.escape(str(text or ""), quote=False)


# --------------------------------------------------------------------------
# Экраны
# --------------------------------------------------------------------------


def root_kb(has_banner: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="a:stats"),
                InlineKeyboardButton(text="👑 Владельцы", callback_data="a:owners"),
            ],
            [
                InlineKeyboardButton(
                    text="🖼 Баннер меню" + (" ✓" if has_banner else ""),
                    callback_data="a:banner",
                ),
                InlineKeyboardButton(text="📣 Рассылка", callback_data="a:cast"),
            ],
            [
                InlineKeyboardButton(text="📢 Спонсоры", callback_data="a:sp"),
                InlineKeyboardButton(text="🤖 Зеркала", callback_data="a:mr"),
            ],
            [InlineKeyboardButton(text="🧾 История рассылок", callback_data="a:hist")],
        ]
    )


def back_kb(to: str = "a:root") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="‹ Назад", callback_data=to)]]
    )


async def root_text() -> str:
    stats = await db.global_stats()
    return (
        f"⚙️ <b>{texts.BRAND} · админка</b>\n"
        f"{texts.LINE}\n"
        f"👤 Владельцев: <b>{stats['owners']}</b> "
        f"· подключено <b>{stats['connected']}</b>\n"
        f"🆕 За неделю: <b>+{stats['new_week']}</b>\n"
        f"💬 Автоответов за сутки: <b>{stats['replies_day']}</b>\n"
        f"🛡 Антискам сработал: <b>{stats['flagged']}</b>\n"
        f"🗑 Поймано удалённых: <b>{stats['caught_deleted']}</b>\n"
        f"{texts.LINE}\n"
        f"<i>Команд в боте: {commands.count()}</i>"
    )


async def show(event: Message | CallbackQuery, text: str, markup) -> None:
    if isinstance(event, CallbackQuery) and event.message is not None:
        try:
            await event.message.edit_text(text, reply_markup=markup)
            return
        except TelegramAPIError:
            await event.message.answer(text, reply_markup=markup)
            return
    if isinstance(event, Message):
        await event.answer(text, reply_markup=markup)


@router.message(Command("admin"), StateFilter(None))
async def cmd_admin(message: Message) -> None:
    await show(message, await root_text(), root_kb(bool(await db.meta_get(BANNER))))


@router.callback_query(F.data == "a:root")
async def on_root(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await show(call, await root_text(), root_kb(bool(await db.meta_get(BANNER))))
    await call.answer()


@router.callback_query(F.data == "a:stats")
async def on_stats(call: CallbackQuery) -> None:
    s = await db.global_stats()
    text = (
        "📊 <b>Статистика бота</b>\n\n"
        "<b>Люди</b>\n"
        f"владельцев всего: <b>{s['owners']}</b>\n"
        f"с активным подключением: <b>{s['connected']}</b>\n"
        f"подключений в базе: <b>{s['connections']}</b>\n"
        f"новых за неделю: <b>+{s['new_week']}</b>\n\n"
        "<b>Работа</b>\n"
        f"диалогов на обслуживании: <b>{s['chats']}</b>\n"
        f"правил создано: <b>{s['rules']}</b>\n"
        f"заготовок: <b>{s['snips']}</b>\n"
        f"автоответов: <b>{s['replies_day']}</b> за сутки · "
        f"<b>{s['replies_week']}</b> за неделю · <b>{s['replies_all']}</b> всего\n"
        f"партий в играх: <b>{s['games']}</b>\n\n"
        "<b>Защита и след</b>\n"
        f"антискам сработал: <b>{s['flagged']}</b>\n"
        f"чатов в глухом режиме: <b>{s['muted']}</b>\n"
        f"поймано удалённых: <b>{s['caught_deleted']}</b>\n"
        f"поймано правок: <b>{s['caught_edited']}</b>\n"
        f"сообщений в архиве сейчас: <b>{s['archive']}</b>"
    )
    await show(call, text, back_kb())
    await call.answer()


@router.callback_query(F.data == "a:owners")
async def on_owners(call: CallbackQuery) -> None:
    rows = await db.top_owners(10)
    if not rows:
        text = "👑 <b>Владельцы</b>\n\nПока никто не пользовался ботом."
    else:
        lines = ["👑 <b>Самые активные владельцы</b>", "<i>по числу автоответов</i>", ""]
        for i, row in enumerate(rows, 1):
            name = esc(row["name"] or row["owner_id"])
            lines.append(f"{i}. {name} · <code>{row['owner_id']}</code> — {row['n']}")
        text = "\n".join(lines)
    await show(call, text, back_kb())
    await call.answer()


# --------------------------------------------------------------------------
# Баннер главного меню
# --------------------------------------------------------------------------


def banner_kb(has: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🖼 Загрузить фото", callback_data="a:banner:set")]]
    if has:
        rows.append(
            [InlineKeyboardButton(text="👁 Показать", callback_data="a:banner:show")]
        )
        rows.append(
            [InlineKeyboardButton(text="🗑 Убрать", callback_data="a:banner:del")]
        )
    rows.append([InlineKeyboardButton(text="‹ Назад", callback_data="a:root")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


BANNER_TEXT = (
    "🖼 <b>Баннер главного меню</b>\n\n"
    "Картинка, которую увидит человек, открыв бота: панель приходит "
    "фотографией с текстом под ней.\n\n"
    "Ограничение Telegram: подпись к фото — до 1024 символов. Экраны "
    "длиннее (справка, антискам) всё равно придут текстом — подпись "
    "такой длины Telegram просто не примет.\n\n"
    "Состояние: <b>{state}</b>"
)


@router.callback_query(F.data == "a:banner")
async def on_banner(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    has = bool(await db.meta_get(BANNER))
    await show(
        call,
        BANNER_TEXT.format(state="загружен" if has else "не задан"),
        banner_kb(has),
    )
    await call.answer()


@router.callback_query(F.data == "a:banner:set")
async def on_banner_set(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Form.banner)
    await show(
        call,
        "Пришлите фотографию для главного меню.\n\n"
        "<i>Лучше горизонтальную — она показывается над текстом панели.</i>\n"
        "Отмена: /cancel",
        back_kb("a:banner"),
    )
    await call.answer()


@router.message(Form.banner, F.photo)
async def got_banner(message: Message, state: FSMContext) -> None:
    await db.meta_set(BANNER, message.photo[-1].file_id)
    await state.clear()
    await message.answer(
        "✅ Баннер сохранён. Откройте /menu — панель придёт с картинкой.",
        reply_markup=banner_kb(True),
    )


@router.message(Form.banner)
async def got_banner_wrong(message: Message) -> None:
    await message.answer("Нужна именно фотография. Или /cancel.")


@router.callback_query(F.data == "a:banner:show")
async def on_banner_show(call: CallbackQuery) -> None:
    file_id = await db.meta_get(BANNER)
    if not file_id:
        await call.answer("Баннер не задан", show_alert=True)
        return
    await call.message.answer_photo(file_id, caption="Текущий баннер меню")
    await call.answer()


@router.callback_query(F.data == "a:banner:del")
async def on_banner_del(call: CallbackQuery) -> None:
    await db.meta_set(BANNER, None)
    await show(call, BANNER_TEXT.format(state="не задан"), banner_kb(False))
    await call.answer("Баннер убран")


# --------------------------------------------------------------------------
# Рассылка
# --------------------------------------------------------------------------


def cast_kb(d: Draft) -> InlineKeyboardMarkup:
    media = "фото" if d.photo_id else ("стикер" if d.sticker_id else "нет")
    rows = [
        [InlineKeyboardButton(text="✍️ Текст" + (" ✓" if d.text else ""), callback_data="a:cast:text")],
        [InlineKeyboardButton(text=f"🖼 Вложение: {media}", callback_data="a:cast:media")],
        [
            InlineKeyboardButton(
                text=f"🔗 Кнопки: {sum(len(r) for r in d.rows) or 'нет'}",
                callback_data="a:cast:btn",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🎨 Кружок: {COLORS[d.color][0]}", callback_data="a:cast:color"
            )
        ],
    ]
    if not d.empty():
        rows.append(
            [InlineKeyboardButton(text="👁 Предпросмотр", callback_data="a:cast:preview")]
        )
        rows.append(
            [InlineKeyboardButton(text="🚀 Отправить всем", callback_data="a:cast:go")]
        )
    rows.append([InlineKeyboardButton(text="🧹 Очистить", callback_data="a:cast:clear")])
    rows.append([InlineKeyboardButton(text="‹ Назад", callback_data="a:root")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def cast_text(d: Draft) -> str:
    people = len(await db.owner_chats())
    parts = [
        "📣 <b>Рассылка</b>",
        f"<i>получателей: {people}</i>",
        "",
    ]
    if d.text:
        parts += ["<b>Текст:</b>", texts.short(d.text, 300), ""]
    else:
        parts += ["<i>Текст не задан.</i>", ""]
    if d.photo_id:
        parts.append("🖼 Вложение: фото")
    elif d.sticker_id:
        parts.append("🪄 Вложение: стикер")
    if d.rows:
        listed = " · ".join(
            f"{COLORS[d.color][1]}{esc(b[0])}" for row in d.rows for b in row
        )
        parts.append(f"🔗 Кнопки: {listed}")
    parts += [
        "",
        "<i>Текст присылайте сообщением с готовым форматированием — жирный, "
        "курсив, спойлер, ссылки и премиум-эмодзи сохранятся как есть.</i>",
    ]
    return "\n".join(parts)


@router.callback_query(F.data == "a:cast")
async def on_cast(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    d = draft(call.from_user.id)
    await show(call, await cast_text(d), cast_kb(d))
    await call.answer()


@router.callback_query(F.data == "a:cast:clear")
async def on_cast_clear(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    _drafts[call.from_user.id] = Draft()
    d = draft(call.from_user.id)
    await show(call, await cast_text(d), cast_kb(d))
    await call.answer("Черновик очищен")


@router.callback_query(F.data == "a:cast:text")
async def on_cast_text(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Form.text)
    await show(
        call,
        "Пришлите текст рассылки <b>одним сообщением</b>, оформленным так, "
        "как он должен выглядеть у людей.\n\n"
        "Работает всё, что умеет ваш Telegram: <b>жирный</b>, <i>курсив</i>, "
        "<u>подчёркнутый</u>, <s>зачёркнутый</s>, <tg-spoiler>спойлер</tg-spoiler>, "
        "ссылки, <code>моно</code> и цитаты.\n\n"
        "<b>Премиум-эмодзи</b> тоже сохранятся — но отправить их бот сможет "
        "только если его юзернейм куплен на Fragment: это ограничение "
        "Telegram на custom_emoji для ботов.\n\n"
        "Отмена: /cancel",
        back_kb("a:cast"),
    )
    await call.answer()


@router.message(Form.text, F.text | F.caption)
async def got_cast_text(message: Message, state: FSMContext) -> None:
    d = draft(message.from_user.id)
    # html_text собирает разметку из entities, которые расставил сам
    # Telegram: так сохраняются и премиум-эмодзи, которых «текстом»
    # не существует в принципе.
    try:
        d.text = message.html_text
    except (TypeError, ValueError):
        d.text = message.text or message.caption or ""
    await state.clear()
    await message.answer(await cast_text(d), reply_markup=cast_kb(d))


@router.callback_query(F.data == "a:cast:media")
async def on_cast_media(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Form.media)
    await show(
        call,
        "Пришлите <b>фото</b> или <b>стикер</b> для рассылки.\n\n"
        "Премиум-стикеры подходят: бот отправляет стикер по его file_id, "
        "и анимация с эффектом сохраняется.\n\n"
        "Фото уйдёт вместе с текстом одним сообщением (подпись до 1024 "
        "символов). Стикер — отдельным сообщением перед текстом: подписей "
        "у стикеров в Telegram нет.\n\n"
        "Убрать вложение — /skip. Отмена: /cancel",
        back_kb("a:cast"),
    )
    await call.answer()


@router.message(Form.media, Command("skip"))
async def cast_media_skip(message: Message, state: FSMContext) -> None:
    d = draft(message.from_user.id)
    d.photo_id = d.sticker_id = ""
    await state.clear()
    await message.answer(await cast_text(d), reply_markup=cast_kb(d))


@router.message(Form.media, F.photo | F.sticker)
async def got_cast_media(message: Message, state: FSMContext) -> None:
    d = draft(message.from_user.id)
    if message.photo:
        d.photo_id, d.sticker_id = message.photo[-1].file_id, ""
        note = "🖼 Фото принято."
    else:
        d.sticker_id, d.photo_id = message.sticker.file_id, ""
        note = "🪄 Стикер принят."
    await state.clear()
    await message.answer(note)
    await message.answer(await cast_text(d), reply_markup=cast_kb(d))


@router.message(Form.media)
async def cast_media_wrong(message: Message) -> None:
    await message.answer("Нужно фото или стикер. /skip — без вложения, /cancel — выйти.")


BUTTONS_HELP = (
    "🔗 <b>Кнопки под рассылкой</b>\n\n"
    "Пришлите строки вида:\n"
    "<code>Подписаться - https://t.me/mychannel</code>\n"
    "<code>Открыть бота - https://t.me/mybot</code>\n\n"
    "Две кнопки в один ряд — через <code>|</code>:\n"
    "<code>Да - https://t.me/a | Нет - https://t.me/b</code>\n\n"
    "Ссылка должна начинаться с <code>https://</code>, <code>http://</code> "
    "или <code>tg://</code> — остальное Telegram отклонит вместе со всей "
    "рассылкой, поэтому проверяю сразу.\n\n"
    "Убрать кнопки — /skip. Отмена: /cancel"
)


@router.callback_query(F.data == "a:cast:btn")
async def on_cast_btn(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Form.buttons)
    await show(call, BUTTONS_HELP, back_kb("a:cast"))
    await call.answer()


def parse_buttons(raw: str) -> tuple[list[list[tuple[str, str]]], list[str]]:
    """Разобрать кнопки из текста. Возвращает (ряды, ошибки)."""
    rows: list[list[tuple[str, str]]] = []
    errors: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        row: list[tuple[str, str]] = []
        for chunk in line.split("|"):
            chunk = chunk.strip()
            if not chunk:
                continue
            label, sep, url = chunk.rpartition(" - ")
            if not sep:
                label, sep, url = chunk.rpartition("-")
            label, url = label.strip(), url.strip()
            if not label or not url:
                errors.append(f"«{chunk}» — нет разделителя «текст - ссылка»")
                continue
            if not URL_OK.match(url):
                errors.append(f"«{label}» — ссылка {url} не подходит")
                continue
            if url.lower().startswith("t.me/"):
                url = "https://" + url
            row.append((label[:64], url))
        if row:
            rows.append(row[:3])
    return rows[:8], errors


@router.message(Form.buttons, Command("skip"))
async def cast_btn_skip(message: Message, state: FSMContext) -> None:
    d = draft(message.from_user.id)
    d.rows = []
    await state.clear()
    await message.answer(await cast_text(d), reply_markup=cast_kb(d))


@router.message(Form.buttons, F.text)
async def got_cast_btn(message: Message, state: FSMContext) -> None:
    rows, errors = parse_buttons(message.text)
    if errors:
        await message.answer(
            "⚠️ Не разобрал:\n" + "\n".join(f"· {esc(e)}" for e in errors[:5])
        )
        if not rows:
            return
    d = draft(message.from_user.id)
    d.rows = rows
    await state.clear()
    await message.answer(await cast_text(d), reply_markup=cast_kb(d))


@router.callback_query(F.data == "a:cast:color")
async def on_cast_color(call: CallbackQuery) -> None:
    d = draft(call.from_user.id)
    keys = list(COLORS)
    d.color = keys[(keys.index(d.color) + 1) % len(keys)]
    await show(call, await cast_text(d), cast_kb(d))
    await call.answer(
        f"Кружок: {COLORS[d.color][0]}. Настоящего цвета у кнопок Telegram не даёт."
    )


# --------------------------------------------------------------------------
# Отправка
# --------------------------------------------------------------------------


async def _media(bot: Bot, d: Draft, file_id: str) -> str | BufferedInputFile:
    """Вложение для этого бота: свой file_id или файл заново."""
    if mirrors.is_main(bot):
        return file_id
    if bot.id in d.ids:
        return d.ids[bot.id]
    if d.blob is None:
        main = mirrors.bot_for(0)
        buf = await main.download(file_id)
        d.blob = buf.read() if buf is not None else b""
    name = "sticker.webp" if d.sticker_id else "photo.jpg"
    return BufferedInputFile(d.blob, filename=name)


def _keep(bot: Bot, d: Draft, sent: Message | None) -> None:
    if mirrors.is_main(bot) or sent is None or bot.id in d.ids:
        return
    if sent.photo:
        d.ids[bot.id] = sent.photo[-1].file_id
    elif sent.sticker:
        d.ids[bot.id] = sent.sticker.file_id


async def deliver(bot: Bot, chat_id: int, d: Draft) -> str:
    """Отправить одному человеку. Возвращает sent | blocked | failed."""
    markup = d.markup()
    try:
        if d.sticker_id:
            _keep(bot, d, await bot.send_sticker(chat_id, await _media(bot, d, d.sticker_id)))
        if d.photo_id:
            photo = await _media(bot, d, d.photo_id)
            if d.text and len(d.text) <= 1024:
                _keep(bot, d, await bot.send_photo(
                    chat_id, photo, caption=d.text, reply_markup=markup
                ))
                return "sent"
            _keep(bot, d, await bot.send_photo(chat_id, photo))
        if d.text:
            await bot.send_message(chat_id, d.text, reply_markup=markup)
        elif markup is not None and not d.photo_id and not d.sticker_id:
            await bot.send_message(chat_id, "…", reply_markup=markup)
        return "sent"
    except TelegramForbiddenError:
        # Человек заблокировал бота или удалил аккаунт — это не сбой.
        return "blocked"
    except TelegramAPIError as err:
        log.warning("рассылка %s: %s", chat_id, err)
        return "failed"


@router.callback_query(F.data == "a:cast:preview")
async def on_preview(call: CallbackQuery) -> None:
    d = draft(call.from_user.id)
    if d.empty():
        await call.answer("Черновик пуст", show_alert=True)
        return
    await call.answer("Отправляю вам как получателю")
    result = await deliver(call.bot, call.from_user.id, d)
    if result != "sent":
        await call.message.answer(
            "⚠️ Предпросмотр не ушёл. Если в тексте премиум-эмодзи — "
            "у владельца бота должен быть Telegram Premium. Уберите их или "
            "пришлите текст без них."
        )


@router.callback_query(F.data == "a:cast:go")
async def on_go(call: CallbackQuery) -> None:
    d = draft(call.from_user.id)
    if d.empty():
        await call.answer("Черновик пуст", show_alert=True)
        return
    if _running.get(call.from_user.id):
        await call.answer("Рассылка уже идёт", show_alert=True)
        return
    people = await db.bot_audience()
    bots = len({int(r["bot_id"]) for r in people})
    await show(
        call,
        f"📣 Отправить <b>{len(people)}</b> получателям через {bots} "
        f"{texts.plural(bots, 'бота', 'ботов', 'ботов')}?\n\n"
        "Предпросмотр покажет ровно то, что они увидят. Остановить можно "
        "кнопкой во время отправки — уже отправленное не отзовётся.",
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Да, отправить", callback_data="a:cast:run")],
                [InlineKeyboardButton(text="‹ Отмена", callback_data="a:cast")],
            ]
        ),
    )
    await call.answer()


@router.callback_query(F.data == "a:cast:run")
async def on_run(call: CallbackQuery) -> None:
    admin_id = call.from_user.id
    d = draft(admin_id)
    if d.empty():
        await call.answer("Черновик пуст", show_alert=True)
        return
    people = [(int(r["bot_id"]), int(r["user_id"])) for r in await db.bot_audience()]
    if not people:
        await call.answer("Получателей нет", show_alert=True)
        return

    cast_id = await db.start_broadcast(admin_id, len(people), texts.short(d.text, 200))
    _running[admin_id] = cast_id
    _stop.discard(cast_id)
    await call.answer("Пошла")
    # Копия черновика: пока рассылка идёт, админ может начать править
    # новый — и правки не должны попадать в уже запущенную отправку.
    snapshot = Draft(
        text=d.text,
        photo_id=d.photo_id,
        sticker_id=d.sticker_id,
        rows=[list(r) for r in d.rows],
        color=d.color,
    )
    asyncio.create_task(
        _broadcast(call.bot, admin_id, cast_id, people, snapshot, call.message)
    )


async def _broadcast(
    bot: Bot,
    admin_id: int,
    cast_id: int,
    people: list[tuple[int, int]],
    d: Draft,
    status: Message | None,
) -> None:
    """Сама рассылка: с паузой под лимиты и живым прогрессом."""
    pause = 1 / max(config.BROADCAST_RATE, 1)
    sent = blocked = failed = 0
    started = time.time()

    def progress(done: bool = False) -> str:
        total = len(people)
        passed = sent + blocked + failed
        head = "✅ <b>Рассылка завершена</b>" if done else "📣 <b>Рассылка идёт…</b>"
        speed = passed / max(time.time() - started, 0.1)
        left = (total - passed) / speed if speed and not done else 0
        lines = [
            head,
            "",
            f"Отправлено: <b>{sent}</b> из {total}",
            f"Заблокировали бота: <b>{blocked}</b>",
            f"Ошибок: <b>{failed}</b>",
        ]
        if not done:
            lines.append(f"<i>осталось примерно {int(left)} с</i>")
        return "\n".join(lines)

    stop_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏹ Остановить", callback_data=f"a:cast:stop:{cast_id}")]
        ]
    )

    async def redraw(done: bool = False) -> None:
        if status is None:
            return
        try:
            await status.edit_text(
                progress(done), reply_markup=None if done else stop_kb
            )
        except TelegramAPIError:
            pass

    await redraw()
    for i, (bot_id, chat_id) in enumerate(people, 1):
        if cast_id in _stop:
            break
        via = mirrors.bot_for(bot_id)
        if bot_id and via.id != bot_id:
            # Зеркало сейчас не запущено — писать от чужого бота нельзя:
            # человек его не открывал, Telegram ответит «chat not found».
            failed += 1
            continue
        result = await deliver(via, chat_id, d)
        if result == "sent":
            sent += 1
        elif result == "blocked":
            blocked += 1
            await db.mark_blocked(bot_id, chat_id)
        else:
            failed += 1
        if i % config.BROADCAST_TICK == 0:
            await redraw()
        await asyncio.sleep(pause)

    await db.finish_broadcast(cast_id, sent=sent, failed=failed, blocked=blocked)
    _running.pop(admin_id, None)
    _stop.discard(cast_id)
    await redraw(True)
    log.info(
        "рассылка #%s: отправлено %s, заблокировали %s, ошибок %s",
        cast_id, sent, blocked, failed,
    )


@router.callback_query(F.data.startswith("a:cast:stop:"))
async def on_stop(call: CallbackQuery) -> None:
    cast_id = int(call.data.rsplit(":", 1)[1])
    _stop.add(cast_id)
    await call.answer("Останавливаю — уже отправленное не отзовётся", show_alert=True)


@router.callback_query(F.data == "a:hist")
async def on_hist(call: CallbackQuery) -> None:
    rows = await db.last_broadcasts(8)
    if not rows:
        text = "🧾 <b>История рассылок</b>\n\nРассылок ещё не было."
    else:
        lines = ["🧾 <b>История рассылок</b>", ""]
        for row in rows:
            state = "идёт" if not row["finished_at"] else "готово"
            lines.append(
                f"<code>{texts.when(row['started_at'])}</code> · {state}\n"
                f"отправлено {row['sent']} из {row['total']} · "
                f"блок {row['blocked']} · ошибок {row['failed']}\n"
                f"<i>{esc(texts.short(row['preview'] or '—', 60))}</i>"
            )
            lines.append("")
        text = "\n".join(lines)
    await show(call, text, back_kb())
    await call.answer()


@router.message(Command("cancel"), StateFilter(Form))
async def cast_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    d = draft(message.from_user.id)
    await message.answer(await cast_text(d), reply_markup=cast_kb(d))


# --------------------------------------------------------------------------
# Спонсоры — обязательная подписка сверх основного канала
# --------------------------------------------------------------------------


async def sponsors_view() -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.sponsors()
    main = (await subs.channels())[:1]
    lines = ["📢 <b>Обязательная подписка</b>", ""]
    if config.REQUIRED_CHANNEL:
        title = main[0]["title"] if main else f"канал {config.REQUIRED_CHANNEL}"
        lines.append(f"🔒 Основной: <b>{esc(title)}</b> <i>(всегда, во всех зеркалах)</i>")
    else:
        lines.append("<i>Основной канал выключен (REQUIRED_CHANNEL=0).</i>")
    lines.append("")
    if rows:
        lines.append(f"<b>Спонсоры</b> · {len(rows)}")
        for row in rows:
            lines.append(f"▫️ {esc(row['title'])} · <code>{row['chat_id']}</code>")
    else:
        lines.append("<i>Спонсоров нет.</i>")
    lines += [
        "",
        "<i>Бот должен быть админом в канале спонсора — иначе подписку не "
        "проверить. Подписка обязательна и в основном боте, и в зеркалах.</i>",
    ]
    buttons = [
        [InlineKeyboardButton(text=f"✖️ {texts.short(r['title'], 28)}", callback_data=f"a:sp:x:{r['chat_id']}")]
        for r in rows
    ]
    buttons.append([InlineKeyboardButton(text="＋ Добавить спонсора", callback_data="a:sp:add")])
    buttons.append([InlineKeyboardButton(text="‹ Назад", callback_data="a:root")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "a:sp")
async def on_sponsors(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, markup = await sponsors_view()
    await show(call, text, markup)
    await call.answer()


@router.callback_query(F.data == "a:sp:add")
async def on_sponsor_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Form.sponsor)
    await show(
        call,
        "📢 <b>Новый спонсор</b>\n\n"
        "1. Добавьте бота админом в канал (достаточно права приглашать).\n"
        "2. Пришлите сюда <code>@username</code> канала, его id "
        "(<code>-100…</code>) или перешлите любой пост из канала.\n\n"
        "Можно сразу со ссылкой через пробел: <code>-1001234 https://t.me/+abc</code>\n"
        "Отмена: /cancel",
        back_kb("a:sp"),
    )
    await call.answer()


@router.message(Form.sponsor)
async def got_sponsor(message: Message, state: FSMContext, bot: Bot) -> None:
    url = ""
    if message.forward_from_chat is not None:
        ref: int | str = message.forward_from_chat.id
    else:
        parts = (message.text or "").split()
        if not parts:
            await message.answer("Пришлите @username, id или пересланный пост.")
            return
        raw = parts[0]
        url = parts[1] if len(parts) > 1 else ""
        ref = int(raw) if raw.lstrip("-").isdigit() else raw if raw.startswith("@") else "@" + raw.split("/")[-1]
    try:
        chat = await bot.get_chat(ref)
        me = await bot.me()
        member = await bot.get_chat_member(chat.id, me.id)
    except TelegramAPIError as err:
        await message.answer(f"⚠️ Канал не найден или бот в нём не состоит: {esc(err)}")
        return
    if member.status not in ("administrator", "creator"):
        await message.answer("⚠️ Бот в канале не админ — подписку проверить не получится. Сделайте его админом и пришлите снова.")
        return
    if not url:
        if chat.username:
            url = f"https://t.me/{chat.username}"
        else:
            try:
                url = chat.invite_link or await bot.export_chat_invite_link(chat.id)
            except TelegramAPIError as err:
                await message.answer(f"⚠️ Не вышло получить ссылку-приглашение: {esc(err)}. Пришлите её вторым словом.")
                return
    await db.add_sponsor(chat.id, chat.title or str(chat.id), url)
    await state.clear()
    text, markup = await sponsors_view()
    await message.answer(f"✅ Добавлен: <b>{esc(chat.title)}</b>\n\n" + text, reply_markup=markup)


@router.callback_query(F.data.startswith("a:sp:x:"))
async def on_sponsor_drop(call: CallbackQuery) -> None:
    chat_id = int(call.data.rsplit(":", 1)[1])
    await db.drop_sponsor(chat_id)
    text, markup = await sponsors_view()
    await show(call, text, markup)
    await call.answer("Спонсор убран")


# --------------------------------------------------------------------------
# Зеркала — сводка для админа
# --------------------------------------------------------------------------


@router.callback_query(F.data == "a:mr")
async def on_mirrors(call: CallbackQuery) -> None:
    rows = await db.all_mirrors()
    lines = [
        "🤖 <b>Зеркала</b>",
        f"<i>всего {len(rows)} · работают {mirrors.running()}</i>",
        "",
    ]
    stats = []
    for row in rows:
        users, week = await db.users_count(int(row["bot_id"]))
        stats.append((users, week, row))
    stats.sort(key=lambda x: x[0], reverse=True)
    for users, week, row in stats[:25]:
        mark = "▶️" if mirrors.is_running(int(row["bot_id"])) else "⏸"
        lines.append(
            f"{mark} @{esc(row['username'])} · людей {users} (+{week}) · "
            f'<a href="tg://user?id={row["owner_id"]}">владелец</a>'
        )
    if not rows:
        lines.append("Пока никто не создал зеркало.")
    lines += ["", f"<i>Лимит на человека: {config.MIRRORS_PER_OWNER}.</i>"]
    await show(call, "\n".join(lines), back_kb())
    await call.answer()
