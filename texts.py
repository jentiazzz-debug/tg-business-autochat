"""Тексты и карточки. Собраны в одном месте, чтобы правились без раскопок.

Разметка везде HTML — она включена по умолчанию в main.py. Всё, что
приходит от людей (имена, тексты сообщений, триггеры правил), проходит
через esc(): в чужом сообщении легко встретится «<» или «&», и без
экранирования Telegram отклонит всю карточку целиком.

Исключение — сами автоответы: они уходят без разметки, plain text.
Владелец пишет их для человека, а не для парсера, и знак «<» в ответе
не должен ронять отправку.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Mapping, Sequence

import config


def esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=False)


def when(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")


def secs(value: int) -> str:
    value = int(value)
    if value <= 0:
        return "выкл"
    if value < 60:
        return f"{value} с"
    if value < 3600:
        return f"{value // 60} мин"
    return f"{value // 3600} ч"


def mins(value: int) -> str:
    return secs(int(value) * 60)


def onoff(flag: Any) -> str:
    return "включено" if flag else "выключено"


def plural(n: int, one: str, few: str, many: str) -> str:
    """«1 сообщение», «3 сообщения», «11 сообщений»."""
    tail = abs(int(n)) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


#: Как называть тип вложения в карточке удалённого.
KINDS: dict[str, str] = {
    "text": "сообщение",
    "photo": "фото",
    "video": "видео",
    "animation": "GIF",
    "voice": "голосовое",
    "video_note": "кружок",
    "audio": "аудио",
    "document": "файл",
    "sticker": "стикер",
    "contact": "контакт",
    "location": "геолокация",
    "poll": "опрос",
    "story": "история",
    "dice": "кубик",
    "other": "сообщение",
}

KIND_ICONS: dict[str, str] = {
    "text": "💬",
    "photo": "🖼",
    "video": "🎬",
    "animation": "🎞",
    "voice": "🎙",
    "video_note": "⭕️",
    "audio": "🎵",
    "document": "📎",
    "sticker": "🪄",
    "contact": "👤",
    "location": "📍",
    "poll": "📊",
    "story": "📖",
    "dice": "🎲",
    "other": "💬",
}

REPLY_KINDS = {
    "rule": "по правилу",
    "greet": "приветствие",
    "away": "режим «отошёл»",
    "fallback": "ответ по умолчанию",
}

START = (
    "<b>Автоответчик для Telegram Business</b>\n\n"
    "Бот отвечает в ваших личных чатах от вашего имени по правилам, "
    "которые вы зададите, и показывает удалённые и изменённые "
    "сообщения собеседников.\n\n"
    "<b>Как подключить</b>\n"
    "1. Настройки Telegram → <b>Telegram для бизнеса</b> → "
    "<b>Автоматизация чатов</b>.\n"
    "2. Вставьте <code>@{bot}</code> и выберите чаты.\n"
    "3. Вернитесь сюда — в панели появится «подключён».\n\n"
    "Бизнес-функции Telegram доступны только с Telegram Premium."
)

HELP = (
    "<b>Команды</b>\n"
    "/menu — панель управления\n"
    "/on, /off — включить и выключить автоответы\n"
    "/away [текст] — режим «отошёл», /back — вернуться\n"
    "/rules — правила, /add — добавить правило\n"
    "/stats — статистика, /log — последние ответы\n\n"
    "<b>Как работают правила</b>\n"
    "Триггеры пишутся через <code>|</code>: "
    "<code>цена|сколько стоит|прайс</code>.\n"
    "Совпадение ищется с начала слова: <code>цен</code> поймает «цена», "
    "«цену» и «ценник», но не «оценка».\n"
    "Знак <code>=</code> перед триггером требует точного совпадения: "
    "<code>=да</code> сработает только на «да».\n\n"
    "<b>Подстановки в ответах</b>\n"
    "<code>{name}</code> — имя собеседника, <code>{username}</code> — его "
    "ник, <code>{time}</code> — время, <code>{date}</code> — дата.\n\n"
    "<b>Когда бот молчит</b>\n"
    "• вы сами написали в этот чат — пауза;\n"
    "• только что уже отвечал — кулдаун;\n"
    "• чат в списке исключений;\n"
    "• ни одно правило не подошло.\n"
    "Разобрать конкретный случай: /log."
)

NO_CONNECTION = (
    "⚠️ Бот пока не подключён к вашему Telegram Business.\n\n"
    "Настройки Telegram → <b>Telegram для бизнеса</b> → "
    "<b>Автоматизация чатов</b> → вставьте <code>@{bot}</code>.\n"
    "Настройки ниже можно задать заранее — они применятся сразу после "
    "подключения."
)

NO_REPLY_RIGHT = (
    "⚠️ Боту не выдано право отвечать в чатах. Откройте «Автоматизация "
    "чатов» и включите разрешение отвечать на сообщения — иначе он "
    "сможет только показывать удалённое."
)

ASK_TRIGGERS = (
    "Пришлите слова, на которые бот ответит, через <code>|</code>:\n\n"
    "<code>цена|сколько стоит|прайс</code>\n\n"
    "Совпадение с начала слова: <code>цен</code> поймает «цену» и "
    "«ценник». Для точного совпадения — <code>=да</code>.\n"
    "Отмена: /cancel"
)

ASK_REPLY = (
    "Теперь текст ответа.\n\n"
    "Можно подставить <code>{name}</code> — имя собеседника, "
    "<code>{username}</code>, <code>{time}</code>, <code>{date}</code>.\n"
    "Отмена: /cancel"
)

SAMPLES_ADDED = (
    "Добавил {n} правила-примера. Откройте каждое и перепишите текст под "
    "себя — сейчас там заглушки, которые уйдут вашим собеседникам как "
    "есть."
)

ARCHIVE_NOTE = (
    "<b>Как это работает.</b> Telegram присылает боту только номера "
    "удалённых сообщений — без текста и файлов. Поэтому бот складывает "
    "входящие в свою базу и достаёт их оттуда, когда сообщение удалили.\n\n"
    "Отсюда два ограничения:\n"
    "• видно только то, что пришло <b>после</b> подключения бота;\n"
    "• архив живёт {days} — потом записи стираются.\n\n"
    "Свои сообщения бот не архивирует, только входящие."
)


def panel(
    *,
    bot_username: str,
    conn: Mapping[str, Any] | None,
    st: Mapping[str, Any],
    rules: int,
    active_rules: int,
    archive: int,
) -> str:
    if conn is None:
        head = "🔌 <b>Не подключён</b>"
    elif not conn["enabled"]:
        head = "🔌 <b>Подключение отключено в Telegram</b>"
    elif not conn["can_reply"]:
        head = "⚠️ <b>Подключён, но без права отвечать</b>"
    else:
        head = "✅ <b>Подключён</b>"

    away = " · 🌙 отошёл" if st["away"] else ""
    switch = "🟢 автоответы включены" if st["active"] else "🔴 автоответы выключены"

    lines = [
        head,
        f"{switch}{away}",
        "",
        f"📋 Правил: <b>{rules}</b>" + (f" (активных {active_rules})" if rules else ""),
        f"👋 Приветствие: <b>{onoff(st['greet'])}</b>",
        f"💬 Ответ по умолчанию: <b>{onoff(st['fallback'])}</b>",
        f"⏳ Пауза после вашего ответа: <b>{mins(st['pause_minutes'])}</b>",
        f"🕒 Пауза между ответами: <b>{secs(st['cooldown'])}</b>",
        "",
        f"🗑 Удалённые сообщения: <b>{onoff(st['spy'])}</b>",
        f"✏️ Изменённые: <b>{onoff(st['spy_edits'])}</b>",
        f"📦 В архиве: <b>{archive}</b> · хранится {st['keep_days']} дн.",
    ]
    if rules == 0 and not st["away"] and not st["greet"] and not st["fallback"]:
        lines += [
            "",
            "ℹ️ Отвечать пока нечем: правил нет, приветствие и ответ по "
            "умолчанию выключены. Бот только следит за удалёнными.",
        ]
    if conn is None:
        lines += ["", NO_CONNECTION.format(bot=bot_username)]
    elif conn["enabled"] and not conn["can_reply"]:
        lines += ["", NO_REPLY_RIGHT]
    return "\n".join(lines)


def rules_list(rules: Sequence[Mapping[str, Any]]) -> str:
    if not rules:
        return (
            "<b>Правила</b>\n\nПока пусто. Правило — это слова-триггеры и "
            "готовый ответ на них. Проверяются сверху вниз, первое "
            "подошедшее и отвечает."
        )
    lines = ["<b>Правила</b>", "Проверяются сверху вниз, отвечает первое подошедшее.", ""]
    for i, rule in enumerate(rules, 1):
        mark = "" if rule["enabled"] else " (выключено)"
        lines.append(
            f"{i}. <code>{esc(rule['triggers'])}</code>{mark}\n"
            f"    → {esc(short(rule['reply'], 60))}"
        )
    return "\n".join(lines)


def rule_card(rule: Mapping[str, Any]) -> str:
    return (
        f"<b>Правило #{rule['id']}</b>\n\n"
        f"Триггеры: <code>{esc(rule['triggers'])}</code>\n"
        f"Состояние: <b>{onoff(rule['enabled'])}</b>\n"
        f"Сработало раз: <b>{rule['hits']}</b>\n\n"
        f"Ответ:\n{esc(rule['reply'])}"
    )


def short(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def stats_card(data: Mapping[str, Any], archive: int) -> str:
    lines = [
        "<b>Статистика</b>",
        "",
        f"Ответов за сутки: <b>{data['day']}</b>",
        f"За неделю: <b>{data['week']}</b>",
        f"Всего: <b>{data['total']}</b>",
        f"Чатов на обслуживании: <b>{data['chats']}</b>",
        f"Сообщений в архиве: <b>{archive}</b>",
    ]
    if data["kinds"]:
        lines += ["", "<i>За неделю по типам:</i>"]
        for kind, n in data["kinds"]:
            lines.append(f"· {REPLY_KINDS.get(kind, kind)} — {n}")
    return "\n".join(lines)


def log_card(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "<b>Последние ответы</b>\n\nПока бот ничего не отправлял."
    lines = ["<b>Последние ответы</b>", ""]
    for row in rows:
        lines.append(
            f"<code>{when(row['at'])}</code> · {REPLY_KINDS.get(row['kind'], row['kind'])}\n"
            f"им: {esc(short(row['incoming'] or '—', 50))}\n"
            f"бот: {esc(short(row['text'], 50))}"
        )
        lines.append("")
    return "\n".join(lines)


def who(name: str | None, username: str | None, user_id: int | None) -> str:
    """Подпись собеседника: имя, ник и кликабельная ссылка на профиль."""
    label = esc(name or "Собеседник")
    if user_id:
        label = f'<a href="tg://user?id={user_id}">{label}</a>'
    if username:
        label += f" · @{esc(username)}"
    return label


def deleted_card(
    *,
    name: str | None,
    username: str | None,
    user_id: int | None,
    rows: Sequence[Mapping[str, Any]],
    extra: int = 0,
) -> str:
    """Карточка «удалено»: кто, когда и что именно."""
    head = f"🗑 <b>Удалено</b> · {who(name, username, user_id)}"
    total = len(rows) + extra
    if total > 1:
        head += f"\nСразу {total} {plural(total, 'сообщение', 'сообщения', 'сообщений')}"
    lines = [head, ""]
    for row in rows:
        kind = row["kind"]
        icon = KIND_ICONS.get(kind, "💬")
        stamp = f"<code>{when(row['at'])}</code>"
        body = esc(row["text"] or "")
        if kind == "text":
            lines.append(f"{icon} {stamp}\n{body or '<i>пустое сообщение</i>'}")
        else:
            title = KINDS.get(kind, kind)
            lines.append(
                f"{icon} {stamp} · <i>{title}</i>"
                + (f"\n{body}" if body else "")
                + ("" if row["file_id"] else "\n<i>файл не сохранён</i>")
            )
        lines.append("")
    if extra:
        more = plural(extra, "сообщение", "сообщения", "сообщений")
        lines.append(f"<i>…и ещё {extra} {more} — показаны последние.</i>")
    return "\n".join(lines).strip()


def edited_card(
    *,
    name: str | None,
    username: str | None,
    user_id: int | None,
    before: str,
    after: str,
    ts: int,
) -> str:
    return (
        f"✏️ <b>Изменено</b> · {who(name, username, user_id)}\n"
        f"<code>{when(ts)}</code>\n\n"
        f"<b>Было:</b>\n{esc(before) or '<i>пусто</i>'}\n\n"
        f"<b>Стало:</b>\n{esc(after) or '<i>пусто</i>'}"
    )


def texts_card(st: Mapping[str, Any]) -> str:
    return (
        "<b>Тексты</b>\n\n"
        f"🌙 <b>Отошёл</b> (сейчас {onoff(st['away'])})\n"
        f"{esc(st['away_text'])}\n\n"
        f"👋 <b>Приветствие</b> — первое сообщение из нового чата "
        f"({onoff(st['greet'])})\n"
        f"{esc(st['greet_text'])}\n\n"
        f"💬 <b>По умолчанию</b> — когда правила не подошли "
        f"({onoff(st['fallback'])})\n"
        f"{esc(st['fallback_text'])}\n\n"
        "<i>Приветствие уйдёт при первом сообщении из каждого чата — в том "
        "числе от давних собеседников: для бота они все новые.</i>"
    )


def ask_text(field: str, current: str) -> str:
    titles = {
        "away_text": "текст режима «отошёл»",
        "greet_text": "текст приветствия",
        "fallback_text": "текст ответа по умолчанию",
    }
    return (
        f"Пришлите новый {titles.get(field, 'текст')}.\n\n"
        f"<b>Сейчас:</b>\n{esc(current)}\n\n"
        "Подстановки: <code>{name}</code>, <code>{username}</code>, "
        "<code>{time}</code>, <code>{date}</code>.\n"
        "Отмена: /cancel"
    )


def timings_card(st: Mapping[str, Any]) -> str:
    return (
        "<b>Паузы</b>\n\n"
        f"🕒 <b>Между ответами в одном чате: {secs(st['cooldown'])}</b>\n"
        "Держит бота от очереди одинаковых ответов, когда человек пишет "
        "мысль в три сообщения. Ответ по другому правилу эту паузу "
        "обходит — на новый вопрос бот отвечает сразу.\n\n"
        f"⏳ <b>После вашего ответа: {mins(st['pause_minutes'])}</b>\n"
        "Главное правило вежливости: вы написали в чат сами — бот "
        "замолкает и не лезет в живой диалог.\n\n"
        "<i>Верхний ряд — между ответами, нижний — после вашего.</i>"
    )


def spy_card(st: Mapping[str, Any], archive: int) -> str:
    days = f"{st['keep_days']} дн."
    return (
        "<b>Удалённые и изменённые</b>\n\n"
        f"🗑 Ловить удалённые: <b>{onoff(st['spy'])}</b>\n"
        f"✏️ Сообщать о правках: <b>{onoff(st['spy_edits'])}</b>\n"
        f"📦 В архиве сейчас: <b>{archive}</b>\n"
        f"🕒 Срок хранения: <b>{days}</b>\n\n" + ARCHIVE_NOTE.format(days=days)
    )


def chats_card(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return (
            "<b>Чаты</b>\n\nПока пусто. Здесь появятся личные чаты, в "
            "которых бот увидел сообщения после подключения."
        )
    lines = [
        "<b>Чаты</b>",
        "Нажатие переключает: отвечать в этом чате или молчать.",
        "",
    ]
    for row in rows:
        mark = "🔕" if row["ignored"] else "🔔"
        nick = f" @{esc(row['username'])}" if row["username"] else ""
        lines.append(
            f"{mark} <b>{esc(row['title'] or row['chat_id'])}</b>{nick}\n"
            f"    ответов: {row['replies']} · был: {when(row['seen'])}"
        )
    return "\n".join(lines)


def rule_saved(rule: Mapping[str, Any]) -> str:
    return "✅ <b>Правило сохранено</b>\n\n" + rule_card(rule)


def confirm_delete(rule: Mapping[str, Any]) -> str:
    return (
        f"Удалить правило <code>{esc(short(rule['triggers'], 40))}</code>?\n\n"
        "Отменить это будет нельзя — текст ответа придётся набрать заново."
    )


CONNECTED = (
    "✅ <b>Бот подключён к вашим чатам.</b>\n\n"
    "Что дальше:\n"
    "• <b>Правила</b> — на какие слова и что отвечать;\n"
    "• <b>Удалённые</b> — присылать сюда то, что собеседник удалил;\n"
    "• кнопка <b>Автоответы</b> — общий выключатель.\n\n"
    "Пока правил нет, от вашего имени бот не пишет ничего."
)

DISCONNECTED = (
    "🔌 Подключение к Telegram Business отключено. Правила и настройки "
    "сохранены — при повторном подключении всё поднимется как было."
)

NOT_ALLOWED = (
    "Этот бот приватный: подключать его к своим чатам может только "
    "владелец. Поднимите свою копию — исходники у того, кто дал вам "
    "ссылку."
)
