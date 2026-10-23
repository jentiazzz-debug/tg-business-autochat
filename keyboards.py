"""Клавиатуры панели управления.

Вся навигация — на inline-кнопках в личке владельца: панель живёт одним
сообщением, которое перерисовывается на месте. Поэтому в callback_data
кодируется только адрес экрана и минимум данных, а состояние берётся из
базы при каждой отрисовке — так две открытые панели не расходятся.

Иконки на кнопках — премиум-эмодзи пака бренда через
icon_custom_emoji_id: Telegram рисует их перед текстом кнопки. Если он
их не примет, pe.PremiumFallback снимет иконки и повторит запрос —
кнопки останутся, просто без картинок.

Схема адресов:
    m:<экран>      переход
    t:<поле>       переключить настройку
    e:<поле>       ввести новый текст
    r:add|samples  правила
    r:<id>[:t|:d]  правило: открыть, включить/выключить, удалить
    cd|pa|kd:<n>   кулдаун, пауза, срок хранения
    fs:<n>         порог антискама
    pf:<знак>      префикс команд
    ig|ign:<chat>  чат в исключения и обратно
    tr:<chat>      доверять чату (антискам его пропускает)
    mu:<chat>      снять глухой режим
    h:<раздел>[:n] справка по разделу команд, n — страница
    sub:check      проверить обязательную подписку
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import pe
import texts


def _b(kb: InlineKeyboardBuilder, icon: str | None, text: str, **kw: Any) -> None:
    """Кнопка с иконкой из пака."""
    if icon:
        kw["icon_custom_emoji_id"] = pe.id_of(icon)
    kb.button(text=text, **kw)


def btn(icon: str | None, text: str, **kw: Any) -> InlineKeyboardButton:
    if icon:
        kw["icon_custom_emoji_id"] = pe.id_of(icon)
    return InlineKeyboardButton(text=text, **kw)


def _mark(flag: Any) -> str:
    return "toggle_on" if flag else "toggle_off"


def root(st: Mapping[str, Any], *, mirrors_on: bool = False) -> InlineKeyboardMarkup:
    """Главный экран панели. mirrors_on — кнопка зеркал (только основной бот)."""
    kb = InlineKeyboardBuilder()
    _b(kb, _mark(st["active"]), "Автоответы", callback_data="t:active")
    _b(kb, "pause" if st["away"] else "play", "Отошёл", callback_data="t:away")
    _b(kb, "trash", "След", callback_data="m:trace")
    _b(kb, "shield", "Антискам", callback_data="m:guard")
    _b(kb, "checklist", "Правила", callback_data="m:rules")
    _b(kb, "code", "Команды", callback_data="m:cmds")
    _b(kb, "edit", "Тексты", callback_data="m:texts")
    _b(kb, "timer", "Паузы", callback_data="m:time")
    _b(kb, "chats", "Диалоги", callback_data="m:chats")
    _b(kb, "bar_chart", "Сводка", callback_data="m:stats")
    _b(kb, "faq", "Как это работает", callback_data="m:how")
    if mirrors_on:
        _b(kb, "rocket", "Своё зеркало бота", callback_data="mr:home")
    kb.adjust(2, 2, 2, 2, 2, 1, 1)
    return kb.as_markup()


def back(to: str = "m:root") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn("back", "Назад", callback_data=to)]])


def rules(items: Sequence[Mapping[str, Any]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, rule in enumerate(items, 1):
        _b(
            kb,
            None if rule["enabled"] else "toggle_off",
            f"{i}. {texts.short(rule['triggers'], 28)}",
            callback_data=f"r:{rule['id']}",
        )
    kb.adjust(1)
    tail = InlineKeyboardBuilder()
    _b(tail, "plus", "Добавить правило", callback_data="r:add")
    if not items:
        _b(tail, "sparkle", "Добавить примеры", callback_data="r:samples")
    _b(tail, "back", "Назад", callback_data="m:root")
    tail.adjust(1)
    kb.attach(tail)
    return kb.as_markup()


def rule(rule_id: int, enabled: Any) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _b(
        kb,
        "pause" if enabled else "play",
        "Выключить" if enabled else "Включить",
        callback_data=f"r:{rule_id}:t",
    )
    _b(kb, "edit", "Изменить ответ", callback_data=f"r:{rule_id}:e")
    _b(kb, "trash", "Удалить", callback_data=f"r:{rule_id}:d")
    _b(kb, "back", "К правилам", callback_data="m:rules")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def confirm_delete(rule_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _b(kb, "trash", "Да, удалить", callback_data=f"r:{rule_id}:D")
    _b(kb, "back", "Отмена", callback_data=f"r:{rule_id}")
    kb.adjust(1)
    return kb.as_markup()


def texts_menu(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _b(kb, "edit", "Текст «отошёл»", callback_data="e:away_text")
    _b(kb, _mark(st["greet"]), "Приветствие", callback_data="t:greet")
    _b(kb, "edit", "Текст приветствия", callback_data="e:greet_text")
    _b(kb, _mark(st["fallback"]), "Ответ по умолчанию", callback_data="t:fallback")
    _b(kb, "edit", "Текст по умолчанию", callback_data="e:fallback_text")
    _b(kb, "back", "Назад", callback_data="m:root")
    kb.adjust(1)
    return kb.as_markup()


#: Пресеты пауз. Ручной ввод был бы лишним экраном ради значений,
#: которые всё равно выбираются из этого же ряда.
COOLDOWNS = (
    (0, "без паузы"), (60, "1 мин"), (120, "2 мин"),
    (300, "5 мин"), (900, "15 мин"), (3600, "1 ч"),
)
PAUSES = (
    (0, "выкл"), (10, "10 мин"), (30, "30 мин"),
    (60, "1 ч"), (180, "3 ч"), (720, "12 ч"),
)
KEEP = ((1, "1 день"), (3, "3 дня"), (7, "7 дней"), (14, "14 дней"), (30, "30 дней"))
SCORES = ((2, "2 · строго"), (3, "3 · как надо"), (4, "4"), (5, "5 · только явный"))
PREFIXES = (".", "!", ",", ";", "~")


def _pick(flag: bool) -> str | None:
    return "check" if flag else None


def timings(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, label in COOLDOWNS:
        _b(kb, _pick(int(st["cooldown"]) == value), label, callback_data=f"cd:{value}")
    kb.adjust(3, 3)
    tail = InlineKeyboardBuilder()
    for value, label in PAUSES:
        _b(tail, _pick(int(st["pause_minutes"]) == value), label, callback_data=f"pa:{value}")
    tail.adjust(3, 3)
    kb.attach(tail)
    end = InlineKeyboardBuilder()
    _b(end, "back", "Назад", callback_data="m:root")
    kb.attach(end)
    return kb.as_markup()


def trace(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _b(kb, _mark(st["spy"]), "Ловить удалённые", callback_data="t:spy")
    _b(kb, _mark(st["spy_edits"]), "Сообщать о правках", callback_data="t:spy_edits")
    kb.adjust(1)
    days = InlineKeyboardBuilder()
    for value, label in KEEP:
        _b(days, _pick(int(st["keep_days"]) == value), label, callback_data=f"kd:{value}")
    days.adjust(3, 2)
    kb.attach(days)
    tail = InlineKeyboardBuilder()
    _b(tail, "trash", "Очистить архив", callback_data="arch:clear")
    _b(tail, "back", "Назад", callback_data="m:root")
    tail.adjust(1)
    kb.attach(tail)
    return kb.as_markup()


def guard(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _b(kb, _mark(st["filter_on"]), "Фильтр", callback_data="t:filter_on")
    _b(
        kb,
        "trash" if st["filter_delete"] else "bell",
        "Удаляет" if st["filter_delete"] else "Только сообщает",
        callback_data="t:filter_delete",
    )
    kb.adjust(2)
    scores = InlineKeyboardBuilder()
    for value, label in SCORES:
        _b(scores, _pick(int(st["filter_score"]) == value), label, callback_data=f"fs:{value}")
    scores.adjust(2, 2)
    kb.attach(scores)
    tail = InlineKeyboardBuilder()
    _b(tail, "edit", "Свои слова", callback_data="e:filter_words")
    _b(tail, _mark(st["notify_new"]), "Сообщать о новых диалогах", callback_data="t:notify_new")
    _b(tail, "back", "Назад", callback_data="m:root")
    tail.adjust(1)
    kb.attach(tail)
    return kb.as_markup()


def commands(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _b(kb, _mark(st["commands"]), "Команды в чатах", callback_data="t:commands")
    kb.adjust(1)
    pref = InlineKeyboardBuilder()
    for sign in PREFIXES:
        _b(pref, _pick(st["prefix"] == sign), sign, callback_data=f"pf:{sign}")
    pref.adjust(5)
    kb.attach(pref)
    tail = InlineKeyboardBuilder()
    _b(tail, "menu", "Справка по командам", callback_data="h:")
    _b(tail, "back", "Назад", callback_data="m:root")
    tail.adjust(1)
    kb.attach(tail)
    return kb.as_markup()


def help_menu(back_to: str | None = None) -> InlineKeyboardMarkup:
    """Кнопки разделов под обзором справки."""
    import cmdbase

    kb = InlineKeyboardBuilder()
    for group in cmdbase.GROUPS:
        if not cmdbase.listed(group):
            continue
        icon, title, _ = cmdbase.group_title(group)
        _b(kb, icon, title, callback_data=f"h:{group}")
    kb.adjust(3)
    if back_to:
        tail = InlineKeyboardBuilder()
        _b(tail, "back", "Назад", callback_data=back_to)
        kb.attach(tail)
    return kb.as_markup()


def help_page(group: str, page: int, pages: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if page > 0:
        _b(kb, "chevron_left", "Назад", callback_data=f"h:{group}:{page - 1}")
    if page + 1 < pages:
        _b(kb, "chevron_right", "Дальше", callback_data=f"h:{group}:{page + 1}")
    _b(kb, "menu", "Все разделы", callback_data="h:")
    kb.adjust(2 if page > 0 and page + 1 < pages else 1, 1)
    return kb.as_markup()


def chats(items: Sequence[Mapping[str, Any]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for chat in items:
        name = texts.short(chat["title"] or str(chat["chat_id"]), 26)
        _b(
            kb,
            "bell_off" if chat["ignored"] else ("mute" if chat["muted"] else None),
            name,
            callback_data=f"ig:{chat['chat_id']}",
        )
    kb.adjust(1)
    tail = InlineKeyboardBuilder()
    _b(tail, "back", "Назад", callback_data="m:root")
    kb.attach(tail)
    return kb.as_markup()


# --------------------------------------------------------------------------
# Кнопки под карточками в личке
# --------------------------------------------------------------------------


def deleted(chat_id: int) -> InlineKeyboardMarkup:
    """Под карточкой удалённого сообщения.

    Префикс ign вместо ig — не мелочь: под карточкой нечего
    перерисовывать, там текст, а не меню. По разным префиксам обработчик
    понимает, показать ли экран «Диалоги» или обойтись всплывашкой.
    """
    kb = InlineKeyboardBuilder()
    _b(kb, "user", "Открыть чат", url=f"tg://user?id={chat_id}")
    _b(kb, "bell_off", "Не отвечать в чате", callback_data=f"ign:{chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def filtered(chat_id: int) -> InlineKeyboardMarkup:
    """Под карточкой антискама: главное — возможность его переубедить."""
    kb = InlineKeyboardBuilder()
    _b(kb, "shield_check", "Это не спам, доверять", callback_data=f"tr:{chat_id}")
    _b(kb, "mute", "В мут", callback_data=f"mu:{chat_id}")
    _b(kb, "user", "Открыть чат", url=f"tg://user?id={chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def muted(chat_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _b(kb, "volume", "Снять мут", callback_data=f"mu:{chat_id}")
    _b(kb, "user", "Открыть чат", url=f"tg://user?id={chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def new_dialog(chat_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    _b(kb, "mute", "В мут", callback_data=f"mu:{chat_id}")
    _b(kb, "bell_off", "Не отвечать в чате", callback_data=f"ign:{chat_id}")
    _b(kb, "user", "Открыть чат", url=f"tg://user?id={chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[btn("cross", "Отмена", callback_data="m:root")]]
    )


def subscribe(channels: Sequence[Mapping[str, Any]]) -> InlineKeyboardMarkup:
    """Обязательная подписка: по кнопке на канал и «Проверить»."""
    rows = [[btn("megaphone", ch["title"], url=ch["url"])] for ch in channels]
    rows.append([btn("check", "Я подписался", callback_data="sub:check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
