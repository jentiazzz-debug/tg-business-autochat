"""Премиум-эмодзи бренда в сообщениях и на кнопках.

Иконки — пак Solutions Project (t.me/addemoji/solutions_project_by_Solutmark_bot):
200 монохромных пиктограмм, id лежат в premium_emoji.json рядом. У
каждой есть обычный эмодзи-заменитель — его Telegram показывает там,
где кастом-эмодзи не рисуются (уведомления, пересылка без Premium).

Когда Telegram их пропускает. Бот может слать кастом-эмодзи, если у
владельца бота есть Premium (или юзернейм бота куплен на Fragment) —
это про сообщения, которые бот отправляет сам: личка, панель, карточки.
Сообщения от имени бизнес-аккаунта — отдельный случай, и правила для
них Telegram явно не описывает. Поэтому всё построено так, чтобы отказ
ничего не ломал: слой PremiumFallback ловит ошибку, заменяет теги на
заменители, снимает иконки с кнопок и повторяет запрос. Запомнив отказ,
для того же вида сообщений он дальше шлёт заменители сразу, без лишней
попытки.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest

log = logging.getLogger("autochat.pe")

_PATH = Path(__file__).resolve().parent / "premium_emoji.json"
#: имя → (custom_emoji_id, заменитель)
ICONS: dict[str, tuple[str, str]] = {
    name: (pair[0], pair[1])
    for name, pair in json.loads(_PATH.read_text(encoding="utf-8")).items()
}

_TAG = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.S)
_TAG_ID = re.compile(r'<tg-emoji emoji-id="(\d+)">(.*?)</tg-emoji>', re.S)
_BY_ID = {icon[0]: name for name, icon in ICONS.items()}


def e(name: str) -> str:
    """Иконка для HTML-текста: <tg-emoji> с заменителем внутри."""
    icon = ICONS.get(name)
    if icon is None:
        raise KeyError(f"иконки {name!r} нет в паке")
    return f'<tg-emoji emoji-id="{icon[0]}">{icon[1]}</tg-emoji>'


def plain(name: str) -> str:
    """Заменитель иконки — для мест, где разметки нет совсем."""
    return ICONS[name][1]


def id_of(name: str) -> str:
    """custom_emoji_id — для icon_custom_emoji_id на кнопке."""
    return ICONS[name][0]


def strip(text: str) -> str:
    """Заменить все <tg-emoji> их заменителями."""
    return _TAG.sub(r"\1", text)


#: Иконки, которые и без премиума несут смысл: «в муте» без 🔇 — просто
#: фраза. Остальные заменители — цветные 🔘 💻 ✅ — превращают монохромный
#: экран в пестроту, поэтому при отказе Telegram они просто убираются.
KEEP_PLAIN = {"mute", "volume", "warning"}


def drop(text: str) -> str:
    """Убрать иконки совсем (кроме KEEP_PLAIN) — вид без премиума."""

    def one(match: re.Match) -> str:
        name = _BY_ID.get(match.group(1))
        return match.group(2) if name in KEEP_PLAIN else ""

    text = _TAG_ID.sub(one, text)
    # «<icon> Текст» без иконки оставит пробел в начале строки.
    return re.sub(r"(^|\n|>) +", r"\1", text)


# --------------------------------------------------------------------------
# Страховка от отказа Telegram
# --------------------------------------------------------------------------

#: Виды сообщений, где Telegram уже отказал. «business» — от имени
#: владельца, «bot» — от имени самого бота.
_REFUSED: set[str] = set()

_TEXT_FIELDS = ("text", "caption")


def _scope(method: Any) -> str:
    return "business" if getattr(method, "business_connection_id", None) else "bot"


def _has_tags(method: Any) -> bool:
    return any("<tg-emoji" in (getattr(method, f, None) or "") for f in _TEXT_FIELDS)


def _has_icons(method: Any) -> bool:
    markup = getattr(method, "reply_markup", None)
    rows = getattr(markup, "inline_keyboard", None) or []
    return any(getattr(b, "icon_custom_emoji_id", None) for row in rows for b in row)


def _plain_method(method: Any) -> Any:
    """Копия запроса без кастом-эмодзи: теги → заменители, кнопки без иконок."""
    update: dict[str, Any] = {}
    for field in _TEXT_FIELDS:
        value = getattr(method, field, None)
        if isinstance(value, str) and "<tg-emoji" in value:
            update[field] = drop(value)
    markup = getattr(method, "reply_markup", None)
    rows = getattr(markup, "inline_keyboard", None)
    if rows:
        update["reply_markup"] = markup.model_copy(
            update={
                "inline_keyboard": [
                    [b.model_copy(update={"icon_custom_emoji_id": None}) for b in row]
                    for row in rows
                ]
            }
        )
    return method.model_copy(update=update)


class PremiumFallback(BaseRequestMiddleware):
    """Повторить запрос без кастом-эмодзи, если Telegram их не принял."""

    async def __call__(self, make_request, bot, method):
        if not (_has_tags(method) or _has_icons(method)):
            return await make_request(bot, method)
        scope = _scope(method)
        if scope in _REFUSED:
            return await make_request(bot, _plain_method(method))
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as err:
            # «message is not modified» к эмодзи отношения не имеет.
            if "not modified" in str(err):
                raise
            # Отказ мог быть и не из-за эмодзи (чат не найден, текст
            # пустой). Тогда без эмодзи запрос упадёт так же, и запоминать
            # «премиум не работает» нельзя — ошибка уйдёт наверх как есть.
            result = await make_request(bot, _plain_method(method))
            log.warning(
                "Telegram не принял премиум-эмодзи (%s, %s): %s — дальше шлю "
                "обычные. Нужен Premium у владельца бота.",
                type(method).__name__,
                scope,
                err,
            )
            _REFUSED.add(scope)
            return result
