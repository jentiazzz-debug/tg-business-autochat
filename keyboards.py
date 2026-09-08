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
    ig:<chat_id>   чат в исключения и обратно
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
    kb.button(text="📋 Правила", callback_data="m:rules")
    kb.button(text="🗑 Удалённые", callback_data="m:spy")
    kb.button(text="✍️ Тексты", callback_data="m:texts")
    kb.button(text="⏱ Паузы", callback_data="m:time")
    kb.button(text="💬 Чаты", callback_data="m:chats")
    kb.button(text="📊 Статистика", callback_data="m:stats")
    kb.button(text="❓ Справка", callback_data="m:help")
    kb.adjust(2, 2, 2, 2, 1)
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


def texts_menu(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️ Текст «отошёл»", callback_data="e:away_text")
    kb.button(text=f"{_mark(st['greet'])} Приветствие", callback_data="t:greet")
    kb.button(text="✍️ Текст приветствия", callback_data="e:greet_text")
    kb.button(text=f"{_mark(st['fallback'])} Ответ по умолчанию", callback_data="t:fallback")
    kb.button(text="✍️ Текст по умолчанию", callback_data="e:fallback_text")
    kb.button(text="‹ Назад", callback_data="m:root")
    kb.adjust(1)
    return kb.as_markup()


#: Пресеты пауз. Ручной ввод тут был бы лишним экраном ради значений,
#: которые всё равно выбираются из этого же ряда.
COOLDOWNS = ((0, "без паузы"), (60, "1 мин"), (120, "2 мин"), (300, "5 мин"), (900, "15 мин"), (3600, "1 ч"))
PAUSES = ((0, "выкл"), (10, "10 мин"), (30, "30 мин"), (60, "1 ч"), (180, "3 ч"), (720, "12 ч"))
KEEP = ((1, "1 день"), (3, "3 дня"), (7, "7 дней"), (14, "14 дней"), (30, "30 дней"))


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


def spy(st: Mapping[str, Any]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"{_mark(st['spy'])} Ловить удалённые", callback_data="t:spy")
    kb.button(text=f"{_mark(st['spy_edits'])} Сообщать о правках", callback_data="t:spy_edits")
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


def confirm_delete(rule_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить", callback_data=f"r:{rule_id}:D")
    kb.button(text="‹ Отмена", callback_data=f"r:{rule_id}")
    kb.adjust(1)
    return kb.as_markup()


def deleted(chat_id: int) -> InlineKeyboardMarkup:
    """Кнопки под карточкой удалённого сообщения.

    Префикс ign вместо ig — не мелочь: под карточкой нечего
    перерисовывать, там текст, а не меню. По разным префиксам обработчик
    понимает, показать ли новый экран «Чаты» или обойтись всплывашкой.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="👤 Открыть чат", url=f"tg://user?id={chat_id}")
    kb.button(text="🔕 Не следить за чатом", callback_data=f"ign:{chat_id}")
    kb.adjust(1)
    return kb.as_markup()


def cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✖️ Отмена", callback_data="m:root")]]
    )
