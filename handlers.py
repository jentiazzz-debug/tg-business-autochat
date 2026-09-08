"""Панель управления в личке владельца.

Панель — одно сообщение, которое перерисовывается на месте: так в
переписке с ботом не растёт лента одинаковых меню. Отсюда правило: на
каждый callback либо перерисовка экрана, либо всплывающий ответ, но
обязательно что-то — иначе у нажавшего висит крутилка.

Обычные сообщения (этот роутер) и бизнес-сообщения (business.py) — два
разных потока апдейтов, они не пересекаются: здесь владелец настраивает
бота, там бот работает от его имени.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import cmdbase
import commands
import config
import db
import engine
import keyboards
import texts

log = logging.getLogger("autochat.panel")
router = Router(name="panel")
#: Второй роутер для чужих: включается последним и отвечает одной фразой.
strangers = Router(name="strangers")

if config.ALLOWED_IDS:
    router.message.filter(F.from_user.id.in_(config.ALLOWED_IDS))
    router.callback_query.filter(F.from_user.id.in_(config.ALLOWED_IDS))

#: Что можно переключать кнопкой. Проверять по SETTING_FIELDS мало:
#: там же лежат тексты и паузы, и «переключение» превратило бы текст
#: приветствия в единицу.
TOGGLEABLE = (
    "active", "away", "greet", "fallback", "spy", "spy_edits",
    "filter_on", "filter_delete", "notify_new", "commands",
)

#: Какие текстовые поля разрешено править из панели.
EDITABLE = ("away_text", "greet_text", "fallback_text", "filter_words")

TOGGLE_HINTS = {
    "active": ("Автоответы включены", "Автоответы выключены"),
    "away": ("Режим «отошёл» включён", "Обычный режим"),
    "greet": ("Приветствие включено", "Приветствие выключено"),
    "fallback": ("Ответ по умолчанию включён", "Ответ по умолчанию выключен"),
    "spy": ("Ловлю удалённые", "Удалённые больше не ловлю"),
    "spy_edits": ("Сообщаю о правках", "О правках молчу"),
    "filter_on": ("Антискам включён", "Антискам выключен"),
    "filter_delete": ("Спам удаляется", "Спам остаётся в чате"),
    "notify_new": ("Сообщаю о новых диалогах", "О новых диалогах молчу"),
    "commands": ("Команды в чатах включены", "Команды в чатах выключены"),
}


class Form(StatesGroup):
    triggers = State()
    reply = State()
    text_field = State()
    rule_reply = State()


# --------------------------------------------------------------------------
# Отрисовка экранов
# --------------------------------------------------------------------------


async def _show(
    event: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup
) -> None:
    """Перерисовать панель на месте или отправить новую."""
    if isinstance(event, CallbackQuery):
        message = event.message
        if message is not None:
            try:
                await message.edit_text(text, reply_markup=markup)
                return
            except TelegramBadRequest as err:
                # «message is not modified» — нормальная ситуация: нажали
                # ту же кнопку дважды. Всё остальное (сообщение слишком
                # старое для правки) лечится новой отправкой.
                if "not modified" in str(err):
                    return
                await message.answer(text, reply_markup=markup)
                return
    if isinstance(event, Message):
        await event.answer(text, reply_markup=markup)


async def root(event: Message | CallbackQuery, bot: Bot, owner_id: int) -> None:
    st = await db.settings_of(owner_id)
    conn = await db.connection_of(owner_id)
    rules = await db.rules_of(owner_id)
    stats = await db.stats_of(owner_id)
    me = await bot.me()
    text = texts.panel(
        bot_username=me.username or "bot",
        conn=conn,
        st=st,
        rules=len(rules),
        active_rules=sum(1 for r in rules if r["enabled"]),
        archive=await db.archive_size(owner_id),
        chats=stats["chats"],
        commands_total=commands.count(),
    )
    if conn is None:
        text += "\n\n" + texts.no_connection(me.username or "bot")
    elif conn["enabled"] and not conn["can_reply"]:
        text += "\n\n" + texts.NO_REPLY_RIGHT
    await _show(event, text, keyboards.root(st))


def _group_counts() -> list[tuple[str, str, int]]:
    """Сколько команд в каждом разделе — для экрана «Команды»."""
    out = []
    for group in cmdbase.GROUPS:
        icon, title, _ = cmdbase.GROUP_TITLES.get(group, ("▫️", group, ""))
        count = sum(1 for c in cmdbase.ORDER if c.group == group)
        if count:
            out.append((icon, title, count))
    return out


# --------------------------------------------------------------------------
# Команды в личке
# --------------------------------------------------------------------------


@router.message(Command("start", "menu"), StateFilter(None))
async def cmd_start(message: Message, bot: Bot) -> None:
    owner_id = message.from_user.id
    conn = await db.connection_of(owner_id)
    if conn is None:
        me = await bot.me()
        await message.answer(
            texts.START.format(bot=me.username or "bot", commands=commands.count())
        )
    await root(message, bot, owner_id)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.how(), reply_markup=keyboards.back())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await root(message, bot, message.from_user.id)


@router.message(Command("on"))
async def cmd_on(message: Message, bot: Bot) -> None:
    await db.set_setting(message.from_user.id, "active", 1)
    await root(message, bot, message.from_user.id)


@router.message(Command("off"))
async def cmd_off(message: Message, bot: Bot) -> None:
    await db.set_setting(message.from_user.id, "active", 0)
    await root(message, bot, message.from_user.id)


@router.message(Command("away"))
async def cmd_away(message: Message, command: CommandObject, bot: Bot) -> None:
    owner_id = message.from_user.id
    if command.args:
        await db.set_setting(
            owner_id, "away_text", command.args.strip()[: config.MAX_TEXT_LEN]
        )
    await db.set_setting(owner_id, "away", 1)
    await root(message, bot, owner_id)


@router.message(Command("back"))
async def cmd_back(message: Message, bot: Bot) -> None:
    await db.set_setting(message.from_user.id, "away", 0)
    await root(message, bot, message.from_user.id)


@router.message(Command("rules"))
async def cmd_rules(message: Message) -> None:
    rules = await db.rules_of(message.from_user.id)
    await message.answer(texts.rules_list(rules), reply_markup=keyboards.rules(rules))


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext) -> None:
    await start_rule(message, state, message.from_user.id)


@router.message(Command("commands"))
async def cmd_commands(message: Message) -> None:
    """Список команд в чатах — тот же, что показывает .помощь."""
    st = await db.settings_of(message.from_user.id)
    for page in commands.help_pages(st["prefix"] or "."):
        await message.answer(page)


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    owner_id = message.from_user.id
    data = await db.stats_of(owner_id)
    await message.answer(
        texts.stats_card(data, await db.archive_size(owner_id)),
        reply_markup=keyboards.back(),
    )


@router.message(Command("log"))
async def cmd_log(message: Message) -> None:
    rows = await db.last_log(message.from_user.id, 10)
    await message.answer(texts.log_card(rows), reply_markup=keyboards.back())


# --------------------------------------------------------------------------
# Переходы по экранам
# --------------------------------------------------------------------------


@router.callback_query(F.data.startswith("m:"))
async def on_menu(call: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    owner_id = call.from_user.id
    screen = call.data.split(":", 1)[1]
    st = await db.settings_of(owner_id)

    if screen == "root":
        await root(call, bot, owner_id)
    elif screen == "rules":
        rules = await db.rules_of(owner_id)
        await _show(call, texts.rules_list(rules), keyboards.rules(rules))
    elif screen == "texts":
        await _show(call, texts.texts_card(st), keyboards.texts_menu(st))
    elif screen == "time":
        await _show(call, texts.timings_card(st), keyboards.timings(st))
    elif screen == "trace":
        archive = await db.archive_size(owner_id)
        await _show(call, texts.trace_card(st, archive), keyboards.trace(st))
    elif screen == "guard":
        await _show(call, texts.guard_card(st), keyboards.guard(st))
    elif screen == "cmds":
        await _show(
            call,
            texts.commands_card(st, commands.count(), _group_counts()),
            keyboards.commands(st),
        )
    elif screen == "chats":
        rows = await db.recent_chats(owner_id, config.CHATS_PAGE)
        await _show(call, texts.chats_card(rows), keyboards.chats(rows))
    elif screen == "stats":
        data = await db.stats_of(owner_id)
        archive = await db.archive_size(owner_id)
        await _show(call, texts.stats_card(data, archive), keyboards.back())
    elif screen == "log":
        rows = await db.last_log(owner_id, 10)
        await _show(call, texts.log_card(rows), keyboards.back())
    elif screen == "how":
        await _show(call, texts.how(), keyboards.back())
    await call.answer()


async def _redraw(call: CallbackQuery, bot: Bot, field: str) -> None:
    """Вернуться на тот экран, с которого нажали переключатель."""
    owner_id = call.from_user.id
    st = await db.settings_of(owner_id)
    if field in ("greet", "fallback"):
        await _show(call, texts.texts_card(st), keyboards.texts_menu(st))
    elif field in ("spy", "spy_edits"):
        archive = await db.archive_size(owner_id)
        await _show(call, texts.trace_card(st, archive), keyboards.trace(st))
    elif field in ("filter_on", "filter_delete", "notify_new"):
        await _show(call, texts.guard_card(st), keyboards.guard(st))
    elif field == "commands":
        await _show(
            call,
            texts.commands_card(st, commands.count(), _group_counts()),
            keyboards.commands(st),
        )
    else:
        await root(call, bot, owner_id)


@router.callback_query(F.data.startswith("t:"))
async def on_toggle(call: CallbackQuery, bot: Bot) -> None:
    field = call.data.split(":", 1)[1]
    if field not in TOGGLEABLE:
        await call.answer("Неизвестная настройка")
        return
    now_on = await db.toggle_setting(call.from_user.id, field)
    await _redraw(call, bot, field)
    hint = TOGGLE_HINTS.get(field)
    await call.answer(hint[0] if now_on else hint[1] if hint else "Готово")


@router.callback_query(F.data.startswith("cd:"))
async def on_cooldown(call: CallbackQuery) -> None:
    value = int(call.data.split(":")[1])
    await db.set_setting(call.from_user.id, "cooldown", value)
    st = await db.settings_of(call.from_user.id)
    await _show(call, texts.timings_card(st), keyboards.timings(st))
    await call.answer("Пауза между ответами: " + texts.secs(value))


@router.callback_query(F.data.startswith("pa:"))
async def on_pause(call: CallbackQuery) -> None:
    value = int(call.data.split(":")[1])
    await db.set_setting(call.from_user.id, "pause_minutes", value)
    st = await db.settings_of(call.from_user.id)
    await _show(call, texts.timings_card(st), keyboards.timings(st))
    await call.answer("Пауза после вашего ответа: " + texts.mins(value))


@router.callback_query(F.data.startswith("kd:"))
async def on_keep(call: CallbackQuery) -> None:
    value = int(call.data.split(":")[1])
    owner_id = call.from_user.id
    await db.set_setting(owner_id, "keep_days", value)
    st = await db.settings_of(owner_id)
    await _show(
        call, texts.trace_card(st, await db.archive_size(owner_id)), keyboards.trace(st)
    )
    await call.answer(f"Храню {value} дн.")


@router.callback_query(F.data.startswith("fs:"))
async def on_score(call: CallbackQuery) -> None:
    value = int(call.data.split(":")[1])
    await db.set_setting(call.from_user.id, "filter_score", value)
    st = await db.settings_of(call.from_user.id)
    await _show(call, texts.guard_card(st), keyboards.guard(st))
    await call.answer(f"Порог антискама: {value}")


@router.callback_query(F.data.startswith("pf:"))
async def on_prefix(call: CallbackQuery) -> None:
    sign = call.data.split(":", 1)[1]
    if sign not in keyboards.PREFIXES:
        await call.answer()
        return
    await db.set_setting(call.from_user.id, "prefix", sign)
    st = await db.settings_of(call.from_user.id)
    await _show(
        call,
        texts.commands_card(st, commands.count(), _group_counts()),
        keyboards.commands(st),
    )
    await call.answer(f"Префикс команд: {sign}")


@router.callback_query(F.data == "cmd:list")
async def on_cmd_list(call: CallbackQuery) -> None:
    st = await db.settings_of(call.from_user.id)
    for page in commands.help_pages(st["prefix"] or "."):
        await call.message.answer(page)
    await call.answer("Список отправлен ниже")


@router.callback_query(F.data == "arch:clear")
async def on_clear(call: CallbackQuery) -> None:
    owner_id = call.from_user.id
    removed = await db.clear_archive(owner_id)
    st = await db.settings_of(owner_id)
    await _show(call, texts.trace_card(st, 0), keyboards.trace(st))
    await call.answer(f"Удалил из архива: {removed}")


@router.callback_query(F.data.regexp(r"^ign?:-?\d+$"))
async def on_ignore(call: CallbackQuery) -> None:
    owner_id = call.from_user.id
    prefix, raw = call.data.split(":", 1)
    chat_id = int(raw)
    chat = await db.chat_of(owner_id, chat_id)
    ignored = not chat["ignored"]
    await db.set_ignored(owner_id, chat_id, ignored)
    # Кнопка живёт в двух местах. На экране «Диалоги» (ig:) перерисовываем
    # список, под карточкой (ign:) перерисовывать нечего — там текст, а
    # не меню, поэтому только всплывашка.
    if prefix == "ig":
        rows = await db.recent_chats(owner_id, config.CHATS_PAGE)
        await _show(call, texts.chats_card(rows), keyboards.chats(rows))
    await call.answer(
        "Больше не отвечаю в этом чате" if ignored else "Снова отвечаю в этом чате",
        show_alert=True,
    )


@router.callback_query(F.data.regexp(r"^tr:-?\d+$"))
async def on_trust(call: CallbackQuery) -> None:
    """«Это не спам» — единственный способ переубедить фильтр."""
    chat_id = int(call.data.split(":")[1])
    await db.set_trusted(call.from_user.id, chat_id, True)
    await call.answer(
        "Чат помечен доверенным — антискам его больше не проверяет.",
        show_alert=True,
    )


@router.callback_query(F.data.regexp(r"^mu:-?\d+$"))
async def on_mute_toggle(call: CallbackQuery) -> None:
    owner_id = call.from_user.id
    chat_id = int(call.data.split(":")[1])
    chat = await db.chat_of(owner_id, chat_id)
    muted = not chat["muted"]
    await db.set_muted(owner_id, chat_id, muted)
    await call.answer(
        "Глухой режим включён: сообщения будут удаляться, текст приходить сюда."
        if muted
        else "Глухой режим снят.",
        show_alert=True,
    )


# --------------------------------------------------------------------------
# Правила
# --------------------------------------------------------------------------


async def start_rule(
    event: Message | CallbackQuery, state: FSMContext, owner_id: int
) -> None:
    if await db.count_rules(owner_id) >= config.MAX_RULES:
        text = f"Правил уже {config.MAX_RULES} — больше не помещается."
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
        else:
            await event.answer(text)
        return
    await state.set_state(Form.triggers)
    await _show(event, texts.ASK_TRIGGERS, keyboards.cancel())


@router.callback_query(F.data == "r:add")
async def on_rule_add(call: CallbackQuery, state: FSMContext) -> None:
    await start_rule(call, state, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "r:samples")
async def on_samples(call: CallbackQuery) -> None:
    owner_id = call.from_user.id
    for triggers, reply in config.SAMPLE_RULES:
        await db.add_rule(owner_id, triggers, reply)
    rules = await db.rules_of(owner_id)
    await _show(call, texts.rules_list(rules), keyboards.rules(rules))
    await call.answer(
        texts.SAMPLES_ADDED.format(n=len(config.SAMPLE_RULES)), show_alert=True
    )


@router.callback_query(F.data.startswith("r:"))
async def on_rule(call: CallbackQuery, state: FSMContext) -> None:
    owner_id = call.from_user.id
    parts = call.data.split(":")
    try:
        rule_id = int(parts[1])
    except ValueError:
        await call.answer()
        return
    action = parts[2] if len(parts) > 2 else ""

    rule = await db.rule_of(owner_id, rule_id)
    if rule is None:
        await call.answer("Правило уже удалено", show_alert=True)
        rules = await db.rules_of(owner_id)
        await _show(call, texts.rules_list(rules), keyboards.rules(rules))
        return

    if action == "t":
        await db.update_rule(owner_id, rule_id, enabled=0 if rule["enabled"] else 1)
        rule = await db.rule_of(owner_id, rule_id)
        await _show(
            call, texts.rule_card(rule), keyboards.rule(rule_id, rule["enabled"])
        )
        await call.answer("Включено" if rule["enabled"] else "Выключено")
    elif action == "d":
        await _show(call, texts.confirm_delete(rule), keyboards.confirm_delete(rule_id))
        await call.answer()
    elif action == "D":
        await db.delete_rule(owner_id, rule_id)
        rules = await db.rules_of(owner_id)
        await _show(call, texts.rules_list(rules), keyboards.rules(rules))
        await call.answer("Правило удалено")
    elif action == "e":
        await state.set_state(Form.rule_reply)
        await state.update_data(rule_id=rule_id)
        await _show(call, texts.ASK_REPLY, keyboards.cancel())
        await call.answer()
    else:
        await _show(
            call, texts.rule_card(rule), keyboards.rule(rule_id, rule["enabled"])
        )
        await call.answer()


@router.callback_query(F.data.startswith("e:"))
async def on_edit_text(call: CallbackQuery, state: FSMContext) -> None:
    field = call.data.split(":", 1)[1]
    if field not in EDITABLE:
        await call.answer()
        return
    st = await db.settings_of(call.from_user.id)
    await state.set_state(Form.text_field)
    await state.update_data(field=field)
    await _show(call, texts.ask_text(field, st[field]), keyboards.cancel())
    await call.answer()


# --------------------------------------------------------------------------
# Ввод текста
# --------------------------------------------------------------------------


@router.message(Form.triggers, F.text, ~F.text.startswith("/"))
async def got_triggers(message: Message, state: FSMContext) -> None:
    parts = engine.triggers_of(message.text)
    if not parts:
        await message.answer("Пусто. Пришлите слова через <code>|</code>.")
        return
    if len(parts) > config.MAX_TRIGGERS:
        await message.answer(
            f"Слишком много: максимум {config.MAX_TRIGGERS} через <code>|</code>."
        )
        return
    await state.update_data(triggers=engine.SEP.join(parts))
    await state.set_state(Form.reply)
    await message.answer(texts.ASK_REPLY, reply_markup=keyboards.cancel())


@router.message(Form.reply, F.text, ~F.text.startswith("/"))
async def got_reply(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    reply = message.text.strip()[: config.MAX_TEXT_LEN]
    rule_id = await db.add_rule(message.from_user.id, data["triggers"], reply)
    await state.clear()
    rule = await db.rule_of(message.from_user.id, rule_id)
    await message.answer(
        texts.rule_saved(rule), reply_markup=keyboards.rule(rule_id, 1)
    )


@router.message(Form.rule_reply, F.text, ~F.text.startswith("/"))
async def got_rule_reply(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    rule_id = int(data["rule_id"])
    await db.update_rule(
        message.from_user.id, rule_id, reply=message.text.strip()[: config.MAX_TEXT_LEN]
    )
    await state.clear()
    rule = await db.rule_of(message.from_user.id, rule_id)
    if rule is None:
        await message.answer("Правило исчезло, пока вы писали ответ.")
        return
    await message.answer(
        texts.rule_card(rule), reply_markup=keyboards.rule(rule_id, rule["enabled"])
    )


@router.message(Form.text_field, F.text, ~F.text.startswith("/"))
async def got_text_field(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data["field"]
    value = message.text.strip()[: config.MAX_TEXT_LEN]
    if field == "filter_words" and value in ("-", "нет", "пусто"):
        value = ""
    await db.set_setting(message.from_user.id, field, value)
    await state.clear()
    st = await db.settings_of(message.from_user.id)
    if field == "filter_words":
        await message.answer(texts.guard_card(st), reply_markup=keyboards.guard(st))
    else:
        await message.answer(texts.texts_card(st), reply_markup=keyboards.texts_menu(st))


@router.message(
    StateFilter(Form.triggers, Form.reply, Form.text_field, Form.rule_reply)
)
async def wrong_input(message: Message) -> None:
    await message.answer(
        "Сейчас жду текст сообщением. Команды снова заработают после /cancel."
    )


@router.message(F.chat.type == "private")
async def anything(message: Message, bot: Bot) -> None:
    """Любое другое сообщение в личке открывает панель."""
    await root(message, bot, message.from_user.id)


@strangers.message()
async def stranger(message: Message) -> None:
    await message.answer(texts.NOT_ALLOWED)


@strangers.callback_query()
async def stranger_call(call: CallbackQuery) -> None:
    await call.answer(texts.NOT_ALLOWED, show_alert=True)
