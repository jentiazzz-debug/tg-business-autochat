"""Кабинет зеркал в основном боте: создать свою копию бота и следить за ней.

Два способа подключить бота:

* **в два касания** — кнопка Telegram «создать бота» (managed bots):
  человек вводит имя и юзернейм, Telegram присылает нам сервисное
  сообщение, и бот забирает токен сам. Работает, если у основного бота
  в @BotFather включено управление ботами (getMe → can_manage_bots);
* **по токену** — создать бота в @BotFather и прислать токен.

Зеркало — тот же бот: панель, след, антискам, команды, с обязательной
подпиской на наш канал. Работает в нашем процессе, свой сервер не нужен.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestManagedBot,
    ManagedBotUpdated,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

import config
import db
import handlers
import mirrors
from keyboards import btn
from pe import e

log = logging.getLogger("autochat.mirrorui")


class MainOnly(Filter):
    """Кабинет зеркал есть только в основном боте — не в самих зеркалах."""

    async def __call__(self, event: object, bot: Bot) -> bool:
        return mirrors.is_main(bot)


router = Router(name="mirrors")
router.message.filter(MainOnly())
router.callback_query.filter(MainOnly())
router.message.middleware(handlers.SubGate())
router.callback_query.middleware(handlers.SubGate())


class Cab(StatesGroup):
    token = State()


CANCEL = "Отмена"


def esc(text: object) -> str:
    return html.escape(str(text or ""), quote=False)


def _kb(*rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


# --------------------------------------------------------------------------
# Главный экран кабинета
# --------------------------------------------------------------------------


async def home_view(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.mirrors_of(user_id)
    lines = [
        f"{e('rocket')} <b>Своё зеркало бота</b>",
        "",
        "Зеркало — ваша копия этого бота под вашим именем и юзернеймом: "
        "сохраняет удалённое, ловит правки, режет спам, понимает все "
        "команды. Работает на наших серверах — вам не нужно ничего "
        "устанавливать.",
        "",
        f"{e('check')} создаётся за минуту",
        f"{e('check')} бесплатно и без сервера",
        f"{e('check')} пользователи бота — ваша аудитория",
        "",
    ]
    if rows:
        lines.append(f"{e('bot')} <b>Ваши боты</b> · {len(rows)} из {config.MIRRORS_PER_OWNER}")
        for row in rows:
            users, _ = await db.users_count(int(row["bot_id"]))
            state = "работает" if mirrors.is_running(int(row["bot_id"])) else "на паузе"
            lines.append(f"{e('dots')} @{esc(row['username'])} — {state}, людей: <b>{users}</b>")
    else:
        lines.append("<i>У вас пока нет зеркал.</i>")

    buttons = [[btn("bot", f"@{r['username']}", callback_data=f"mr:b:{r['id']}")] for r in rows]
    if len(rows) < config.MIRRORS_PER_OWNER:
        if mirrors.CAN_MANAGE:
            buttons.append([btn("plus", "Создать бота в 2 касания", callback_data="mr:new")])
        buttons.append([btn("key", "Подключить по токену", callback_data="mr:tok")])
    buttons.append([btn("back", "В меню", callback_data="m:root")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "mr:home")
async def on_home(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, markup = await home_view(call.from_user.id)
    await handlers._show(call, text, markup)
    await call.answer()


@router.message(Command("mirror", "mirrors"))
async def cmd_mirror(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, markup = await home_view(message.from_user.id)
    await message.answer(text, reply_markup=markup)


# --------------------------------------------------------------------------
# Создание в два касания
# --------------------------------------------------------------------------


def _username_hint(name: str) -> str | None:
    slug = "".join(ch for ch in name.lower() if ch.isascii() and (ch.isalnum() or ch == "_"))
    return f"{slug[:18]}_save_bot" if len(slug) >= 3 else None


@router.callback_query(F.data == "mr:new")
async def on_new(call: CallbackQuery) -> None:
    if not mirrors.CAN_MANAGE:
        await call.answer("Сейчас можно только по токену", show_alert=True)
        return
    await call.answer()
    name = (call.from_user.first_name or "Мой")[:20]
    await call.message.answer(
        f"{e('chevron_down')} Нажмите кнопку внизу — Telegram предложит имя и "
        "юзернейм бота (юзернейм должен кончаться на <code>bot</code>). "
        "Подтвердите — и бот сразу заработает.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(
                        text="Создать бота",
                        request_managed_bot=KeyboardButtonRequestManagedBot(
                            request_id=call.from_user.id % 2_000_000_000,
                            suggested_name=f"{name} Savemode"[:64],
                            suggested_username=_username_hint(name),
                        ),
                    )
                ],
                [KeyboardButton(text=CANCEL)],
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@router.message(F.text == CANCEL)
async def on_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=ReplyKeyboardRemove())


@router.message(F.managed_bot_created)
async def on_created(message: Message, bot: Bot) -> None:
    created = message.managed_bot_created.bot
    try:
        token = await bot.get_managed_bot_token(user_id=created.id)
    except TelegramAPIError as err:
        log.warning("токен управляемого бота %s не получен: %s", created.id, err)
        await message.answer(
            f"{e('warning')} Telegram не отдал токен: {esc(err)}. Попробуйте "
            "подключить по токену из @BotFather.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    ok, note, mirror_id = await mirrors.add(message.from_user.id, token)
    await message.answer(
        f"{e('check')} Бот создан" if ok else f"{e('cross')} Не получилось подключить",
        reply_markup=ReplyKeyboardRemove(),
    )
    await _added(message, ok, note, mirror_id)


@router.managed_bot()
async def on_managed_update(update: ManagedBotUpdated, bot: Bot) -> None:
    """Владелец перевыпустил токен управляемого бота — подхватить."""
    try:
        token = await bot.get_managed_bot_token(user_id=update.bot.id)
    except TelegramAPIError:
        return
    await mirrors.refresh_token(update.bot.id, token)


# --------------------------------------------------------------------------
# По токену
# --------------------------------------------------------------------------


@router.callback_query(F.data == "mr:tok")
async def on_token(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Cab.token)
    await handlers._show(
        call,
        f"{e('key')} <b>Подключение по токену</b>\n\n"
        f"{e('num1')} Откройте @BotFather и отправьте /newbot\n"
        f"{e('num2')} Придумайте имя и юзернейм (кончается на <code>bot</code>)\n"
        f"{e('num3')} Включите Business Mode: /mybots → бот → Bot Settings → "
        "Business Mode → Enable\n"
        f"{e('num4')} Пришлите сюда токен — строку вида <code>123456:ABC-DEF…</code>\n\n"
        f"{e('lock')} <i>Сообщение с токеном бот сразу удалит из чата.</i>",
        _kb([btn("back", "Назад", callback_data="mr:home")]),
    )
    await call.answer()


@router.message(Cab.token, F.text, ~F.text.startswith("/"))
async def got_token(message: Message, state: FSMContext) -> None:
    await state.clear()
    token = message.text.strip()
    try:
        await message.delete()
    except TelegramAPIError:
        pass
    ok, note, mirror_id = await mirrors.add(message.from_user.id, token)
    await _added(message, ok, note, mirror_id)


async def _added(message: Message, ok: bool, note: str, mirror_id: int | None) -> None:
    if ok:
        await message.answer(
            f"{e('rocket')} <b>{esc(note)}</b>\n\n"
            "В нём всё как здесь, плюс обязательная подписка на наш канал. "
            "Делитесь ссылкой на бота — все, кто его подключит, станут вашей "
            "аудиторией.",
            reply_markup=_kb(
                [btn("gear", "Мой бот", callback_data=f"mr:b:{mirror_id}")],
                [btn("back", "К зеркалам", callback_data="mr:home")],
            ),
        )
        return
    await message.answer(
        f"{e('cross')} {esc(note)}",
        reply_markup=_kb(
            [btn("refresh", "Попробовать снова", callback_data="mr:tok")],
            [btn("back", "К зеркалам", callback_data="mr:home")],
        ),
    )


# --------------------------------------------------------------------------
# Экран одного зеркала
# --------------------------------------------------------------------------


async def _mine(call: CallbackQuery) -> object | None:
    try:
        mirror_id = int((call.data or "").split(":")[2])
    except (IndexError, ValueError):
        return None
    row = await db.mirror_of(mirror_id)
    if row is None or int(row["owner_id"]) != call.from_user.id:
        await call.answer("Это не ваш бот", show_alert=True)
        return None
    return row


@router.callback_query(F.data.startswith("mr:b:"))
async def on_bot(call: CallbackQuery) -> None:
    row = await _mine(call)
    if row is None:
        return
    await _bot_screen(call, row)
    await call.answer()


async def _bot_screen(call: CallbackQuery, row: object) -> None:
    bot_id = int(row["bot_id"])
    users, week = await db.users_count(bot_id)
    conns = await db.connections_count(bot_id)
    running = mirrors.is_running(bot_id)
    text = (
        f"{e('bot')} <b>@{esc(row['username'])}</b>\n"
        f"<i>{'работает' if running else 'на паузе'}</i>\n\n"
        f"{e('users')} людей в боте: <b>{users}</b> · за неделю +{week}\n"
        f"{e('link')} подключили к Business: <b>{conns}</b>\n\n"
        f"{e('share')} Ссылка: t.me/{esc(row['username'])}"
    )
    markup = _kb(
        [btn("external", "Открыть бота", url=f"https://t.me/{row['username']}")],
        [
            btn(
                "pause" if running else "play",
                "Пауза" if running else "Запустить",
                callback_data=f"mr:p:{row['id']}",
            )
        ],
        [btn("trash", "Отключить", callback_data=f"mr:d:{row['id']}")],
        [btn("back", "К зеркалам", callback_data="mr:home")],
    )
    await handlers._show(call, text, markup)


@router.callback_query(F.data.startswith("mr:p:"))
async def on_pause(call: CallbackQuery) -> None:
    row = await _mine(call)
    if row is None:
        return
    running = mirrors.is_running(int(row["bot_id"]))
    err = await mirrors.pause(int(row["id"]), not running)
    if err:
        await call.answer(f"Не запустился: {err}", show_alert=True)
        return
    await call.answer("Пауза" if running else "Запущен")
    await _bot_screen(call, row)


@router.callback_query(F.data.startswith("mr:d:"))
async def on_drop(call: CallbackQuery) -> None:
    row = await _mine(call)
    if row is None:
        return
    await handlers._show(
        call,
        f"{e('warning')} Отключить @{esc(row['username'])}?\n\n"
        "Бот перестанет отвечать. Сам бот в Telegram останется у вас — его "
        "можно подключить снова.",
        _kb(
            [btn("trash", "Да, отключить", callback_data=f"mr:D:{row['id']}")],
            [btn("back", "Отмена", callback_data=f"mr:b:{row['id']}")],
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("mr:D:"))
async def on_drop_yes(call: CallbackQuery, state: FSMContext) -> None:
    row = await _mine(call)
    if row is None:
        return
    await mirrors.remove(int(row["id"]))
    await call.answer("Отключено")
    await on_home(call, state)
