"""Клавиатуры панели управления.

Вся навигация — на inline-кнопках в личке владельца: панель живёт одним
сообщением, которое перерисовывается на месте. Поэтому в callback_data
кодируется только адрес экрана и минимум данных, а состояние берётся из
базы при каждой отрисовке — так две открытые панели не расходятся.

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
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import texts


def _mark(flag: Any) -> str:
    return "🟢" if flag else "⚪️"


def root(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    """Главный экран панели."""
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f"{_mark(st['active'])} Автоответы", callback_data="t:active"
    )
    kb.button(
        text=f"{'🌙' if st['away'] else '☀️'} Отошёл", callback_data="t:away"
    )
    kb.button(text="💬 Правила", callback_data="m:rules")
    kb.button(text="🛡 Антискам", callback_data="m:guard")
    kb.button(text="🗑 След", callback_data="m:trace")
    kb.button(text="⌨️ Команды", callback_data="m:cmds")
    kb.button(text="✍️ Тексты", callback_data="m:texts")
    kb.button(text="⏱ Паузы", callback_data="m:time")
    kb.button(text="💬 Диалоги", callback_data="m:chats")
    kb.button(text="📊 Сводка", callback_data="m:stats")
    kb.button(text="❓ Как это работает", callback_data="m:how")
    kb.adjust(2, 2, 2, 2, 2, 1)
    return kb.as_markup()


def back(to: str = "m:root") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="‹ Назад", callback_data=to)]]
    )


def rules(items: Sequence[Mapping[str, Any]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i, rule in enumerate(items, 1):
        mark = "" if rule["enabled"] else "⚪️ "
        kb.button(
            text=f"{mark}{i}. {texts.short(rule['triggers'], 28)}",
            callback_data=f"r:{rule['id']}",
        )
    kb.adjust(1)
    tail = InlineKeyboardBuilder()
    tail.button(text="＋ Добавить правило", callback_data="r:add")
    if not items:
        tail.button(text="✨ Добавить примеры", callback_data="r:samples")
    tail.button(text="‹ Назад", callback_data="m:root")
    tail.adjust(1)
    kb.attach(tail)
    return kb.as_markup()


def rule(rule_id: int, enabled: Any) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text="⏸ Выключить" if enabled else "▶️ Включить",
        callback_data=f"r:{rule_id}:t",
    )
    kb.button(text="✍️ Изменить ответ", callback_data=f"r:{rule_id}:e")
    kb.button(text="🗑 Удалить", callback_data=f"r:{rule_id}:d")
    kb.button(text="‹ К правилам", callback_data="m:rules")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def confirm_delete(rule_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить", callback_data=f"r:{rule_id}:D")
    kb.button(text="‹ Отмена", callback_data=f"r:{rule_id}")
    kb.adjust(1)
    return kb.as_markup()


def texts_menu(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Текст «отошёл»", callback_data="e:away_text")
    kb.button(text=f"{_mark(st['greet'])} Приветствие", callback_data="t:greet")
    kb.button(text="✍️ Текст приветствия", callback_data="e:greet_text")
    kb.button(
        text=f"{_mark(st['fallback'])} Ответ по умолчанию", callback_data="t:fallback"
    )
    kb.button(text="✍️ Текст по умолчанию", callback_data="e:fallback_text")
    kb.button(text="‹ Назад", callback_data="m:root")
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


def timings(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for value, label in COOLDOWNS:
        picked = "• " if int(st["cooldown"]) == value else ""
        kb.button(text=f"{picked}{label}", callback_data=f"cd:{value}")
    kb.adjust(3, 3)
    tail = InlineKeyboardBuilder()
    for value, label in PAUSES:
        picked = "• " if int(st["pause_minutes"]) == value else ""
        tail.button(text=f"{picked}{label}", callback_data=f"pa:{value}")
    tail.adjust(3, 3)
    kb.attach(tail)
    end = InlineKeyboardBuilder()
    end.button(text="‹ Назад", callback_data="m:root")
    kb.attach(end)
    return kb.as_markup()


def trace(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{_mark(st['spy'])} Ловить удалённые", callback_data="t:spy")
    kb.button(
        text=f"{_mark(st['spy_edits'])} Сообщать о правках", callback_data="t:spy_edits"
    )
    kb.adjust(1)
    days = InlineKeyboardBuilder()
    for value, label in KEEP:
        picked = "• " if int(st["keep_days"]) == value else ""
        days.button(text=f"{picked}{label}", callback_data=f"kd:{value}")
    days.adjust(3, 2)
    kb.attach(days)
    tail = InlineKeyboardBuilder()
    tail.button(text="🧹 Очистить архив", callback_data="arch:clear")
    tail.button(text="‹ Назад", callback_data="m:root")
    tail.adjust(1)
    kb.attach(tail)
    return kb.as_markup()


def guard(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{_mark(st['filter_on'])} Фильтр", callback_data="t:filter_on")
    kb.button(
        text="🗑 Удаляет" if st["filter_delete"] else "🔔 Только сообщает",
        callback_data="t:filter_delete",
    )
    kb.adjust(2)
    scores = InlineKeyboardBuilder()
    for value, label in SCORES:
        picked = "• " if int(st["filter_score"]) == value else ""
        scores.button(text=f"{picked}{label}", callback_data=f"fs:{value}")
    scores.adjust(2, 2)
    kb.attach(scores)
    tail = InlineKeyboardBuilder()
    tail.button(text="✍️ Свои слова", callback_data="e:filter_words")
    tail.button(
        text=f"{_mark(st['notify_new'])} Сообщать о новых диалогах",
        callback_data="t:notify_new",
    )
    tail.button(text="‹ Назад", callback_data="m:root")
    tail.adjust(1)
    kb.attach(tail)
    return kb.as_markup()


def commands(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{_mark(st['commands'])} Команды", callback_data="t:commands")
    kb.adjust(1)
    pref = InlineKeyboardBuilder()
    for sign in PREFIXES:
        picked = "• " if st["prefix"] == sign else ""
        pref.button(text=f"{picked}{sign}", callback_data=f"pf:{sign}")
    pref.adjust(5)
    kb.attach(pref)
    tail = InlineKeyboardBuilder()
    tail.button(text="📖 Показать все команды", callback_data="cmd:list")
    tail.button(text="‹ Назад", callback_data="m:root")
    tail.adjust(1)
    kb.attach(tail)
    return kb.as_markup()


def chats(items: Sequence[Mapping[str, Any]]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for chat in items:
        mark = "🔕 " if chat["ignored"] else ""
        name = texts.short(chat["title"] or str(chat["chat_id"]), 26)
        kb.button(text=f"{mark}{name}", callback_data=f"ig:{chat['chat_id']}")
    kb.adjust(1)
    tail = InlineKeyboardBuilder()
    tail.button(text="‹ Назад", callback_data="m:root")
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
    kb.button(text="👤 Открыть чат", url=f"tg://user?id={chat_id}")
    kb.button(text="🔕 Не отвечать в чате", callback_data=f"ign:{chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def filtered(chat_id: int) -> InlineKeyboardMarkup:
    """Под карточкой антискама: главное — возможность его переубедить."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Это не спам, доверять", callback_data=f"tr:{chat_id}")
    kb.button(text="🔇 В глухой режим", callback_data=f"mu:{chat_id}")
    kb.button(text="👤 Открыть чат", url=f"tg://user?id={chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def muted(chat_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔊 Снять глухой режим", callback_data=f"mu:{chat_id}")
    kb.button(text="👤 Открыть чат", url=f"tg://user?id={chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def new_dialog(chat_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔇 В глухой режим", callback_data=f"mu:{chat_id}")
    kb.button(text="🔕 Не отвечать в чате", callback_data=f"ign:{chat_id}")
    kb.button(text="👤 Открыть чат", url=f"tg://user?id={chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✖️ Отмена", callback_data="m:root")]
        ]
    )
