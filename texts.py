"""Тексты и карточки — лицо бота.

Разметка везде HTML, она включена по умолчанию в main.py. Всё, что
приходит от людей (имена, тексты сообщений, триггеры), проходит через
esc(): в чужом сообщении легко встретится «<» или «&», и без
экранирования Telegram отклонит карточку целиком.

Исключение — сами автоответы: они уходят plain text. Владелец писал их
для человека, а не для парсера, и знак «<» в ответе не должен ронять
отправку.

Разделы названы своими словами, а не переводом чужих меню:
«След» — то, что собеседник пытался стереть; «Антискам» — разбор
первых сообщений; «Личина» — профиль; «Слово» — стилизация текста.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Mapping, Sequence

import config

BRAND = config.BRAND
LINE = "━━━━━━━━━━━━━━━━━"


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


def short(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


#: Как называть тип вложения в карточках.
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


# --------------------------------------------------------------------------
# Знакомство
# --------------------------------------------------------------------------

START = (
    f"🎭 <b>{BRAND}</b>\n"
    "<i>выходит на площадку вместо вас</i>\n\n"
    "Бот подключается к вашему Telegram Business и в личных чатах умеет "
    "три вещи:\n\n"
    "💬 <b>Отвечать за вас</b> — по правилам «слова → ответ», с режимом "
    "«отошёл» и приветствием новым.\n"
    "🗑 <b>Держать след</b> — показывать, что собеседник удалил или "
    "переписал: текст, фото, гифку, голосовое.\n"
    "⌨️ <b>Слушать команды</b> — {commands} команд прямо в переписке: "
    "стилизация текста, игры на двоих, обработка фото, профиль.\n\n"
    "<b>Как подключить</b>\n"
    "1. Настройки Telegram → <b>Telegram для бизнеса</b> → "
    "<b>Автоматизация чатов</b>\n"
    "2. Вставьте <code>@{bot}</code>\n"
    "3. Выдайте права — что разрешите, то и заработает\n\n"
    "<i>Нужен Telegram Premium: без него раздела «для бизнеса» в "
    "настройках нет.</i>"
)


def connected(rights: Mapping[str, bool], st: Mapping[str, Any]) -> str:
    """Что сказать сразу после подключения."""
    from cmdbase import RIGHT_TITLES

    given = [name for name, ok in rights.items() if ok]
    lost = [
        RIGHT_TITLES[name]
        for name in ("can_reply", "can_delete_outgoing_messages", "can_delete_all_messages")
        if not rights.get(name)
    ]
    lines = [
        f"🎭 <b>{BRAND} на площадке.</b>",
        f"<i>Прав выдано: {len(given)}</i>",
        "",
        "Что дальше:",
        "📋 <b>Правила</b> — на какие слова отвечать;",
        "🛡 <b>Антискам</b> — уже включён, разбирает первые сообщения от "
        "незнакомых;",
        "🗑 <b>След</b> — уже включён, покажет удалённое и правки;",
        f"⌨️ <b>Команды</b> — напишите <code>{st['prefix']}помощь</code> в "
        "любом своём чате.",
        "",
        "<i>Пока правил нет, от вашего имени бот не пишет ничего сам.</i>",
    ]
    if lost:
        lines += [
            "",
            "⚠️ Не выдано: " + ", ".join(f"«{t}»" for t in lost) + ".",
            "Без первого бот не сможет отвечать, без остальных — убирать "
            "сообщения с командами и работать с глухим режимом.",
        ]
    return "\n".join(lines)


DISCONNECTED = (
    f"🎭 <b>{BRAND} ушёл со сцены.</b>\n\n"
    "Подключение к Telegram Business отключено. Правила, тексты и "
    "настройки сохранены — при повторном подключении всё поднимется "
    "как было."
)

NOT_ALLOWED = (
    "Этот бот приватный: подключать его к своим чатам может только "
    "владелец. Поднимите свою копию — исходники у того, кто дал вам "
    "ссылку."
)

NO_REPLY_RIGHT = (
    "⚠️ Боту не выдано право отвечать в чатах. Откройте «Автоматизация "
    "чатов» и включите разрешение отвечать — иначе он сможет только "
    "следить за удалённым."
)


def no_connection(bot_username: str) -> str:
    return (
        "⚠️ <b>Бот пока не подключён к вашим чатам.</b>\n\n"
        "Настройки Telegram → <b>Telegram для бизнеса</b> → "
        f"<b>Автоматизация чатов</b> → вставьте <code>@{bot_username}</code>.\n\n"
        "Настройки ниже можно задать заранее — они применятся сразу "
        "после подключения."
    )


# --------------------------------------------------------------------------
# Панель
# --------------------------------------------------------------------------


def panel(
    *,
    bot_username: str,
    conn: Mapping[str, Any] | None,
    st: Mapping[str, Any],
    rules: int,
    active_rules: int,
    archive: int,
    chats: int,
    commands_total: int,
) -> str:
    """Главный экран. Одна строка на раздел, состояние видно сразу."""
    if conn is None:
        status = "не подключён"
    elif not conn["enabled"]:
        status = "подключение отключено в Telegram"
    elif not conn["can_reply"]:
        status = "подключён, но без права отвечать"
    else:
        status = f"на площадке · {chats} {plural(chats, 'чат', 'чата', 'чатов')}"

    mode = "🌙 отошёл" if st["away"] else ("🟢 в работе" if st["active"] else "🔴 молчит")

    rules_note = (
        f"{active_rules} из {rules}" if rules else "нет ни одного"
    )
    filter_note = (
        f"порог {st['filter_score']} · "
        + ("удаляет" if st["filter_delete"] else "только сообщает")
        if st["filter_on"]
        else "выключен"
    )
    trace_note = (
        f"{archive} в архиве · {st['keep_days']} дн."
        if st["spy"]
        else "выключен"
    )
    cmd_note = (
        f"{commands_total} · префикс «{st['prefix']}»"
        if st["commands"]
        else "выключены"
    )

    return "\n".join(
        (
            f"🎭 <b>{BRAND}</b>",
            f"<i>{status}</i>",
            "",
            f"       <b>{mode}</b>",
            LINE,
            f"💬 <b>Автоответы</b> · правил {rules_note}",
            f"🛡 <b>Антискам</b> · {filter_note}",
            f"🗑 <b>След</b> · {trace_note}",
            f"⌨️ <b>Команды</b> · {cmd_note}",
            LINE,
            f"⏳ пауза после вашего ответа — {mins(st['pause_minutes'])}",
            f"🕒 между автоответами — {secs(st['cooldown'])}",
        )
    )


def how() -> str:
    return (
        f"<b>Как {BRAND} устроен</b>\n\n"
        "<b>💬 Автоответы.</b> Правило — это слова-триггеры и готовый "
        "ответ. Совпадение ищется с начала слова: <code>цен</code> поймает "
        "«цену» и «ценник», но не «оценку». <code>=да</code> — только "
        "точное «да».\n"
        "Бот молчит, если вы сами написали в чат, если только что уже "
        "отвечал, если чат исключён или если ничего не подошло. Разобрать "
        "конкретный случай — <code>.почему</code> в том чате.\n\n"
        "<b>🛡 Антискам.</b> Каждый признак даёт очки: работа и заработок "
        "— 3, крипта — 3, просьба прислать код — 5, ссылка — 2, кнопки — "
        "2. Сумма выше порога — сообщение убирается, а вам приходит "
        "карточка с текстом и разбором, по каким именно признакам.\n"
        "Коммерческие признаки проверяются только у тех, с кем переписки "
        "ещё не было. Исполняемые файлы и выпрашивание кодов — всегда, "
        "даже у знакомых: так выглядит взломанный аккаунт друга.\n\n"
        "<b>🗑 След.</b> Telegram сообщает боту только номера удалённых "
        "сообщений — без текста и файлов. Поэтому бот складывает входящие "
        "в свой архив и достаёт оттуда, когда их удаляют. Видно только "
        "то, что пришло после подключения.\n\n"
        "<b>⌨️ Команды.</b> Пишутся в любом вашем чате с префиксом. Бот "
        "убирает вашу команду и ставит на её место результат — со стороны "
        "выглядит так, будто вы сразу так и написали. Список — "
        "<code>.помощь</code>."
    )


# --------------------------------------------------------------------------
# Карточки в личку владельцу
# --------------------------------------------------------------------------


def who(name: str | None, username: str | None, user_id: int | None) -> str:
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
    total_deleted: int = 0,
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
            lines.append(
                f"{icon} {stamp} · <i>{KINDS.get(kind, kind)}</i>"
                + (f"\n{body}" if body else "")
                + ("" if row["file_id"] else "\n<i>файл не сохранён</i>")
            )
        lines.append("")
    if extra:
        more = plural(extra, "сообщение", "сообщения", "сообщений")
        lines.append(f"<i>…и ещё {extra} {more} — показаны последние.</i>")
    if total_deleted > total:
        lines.append(
            f"<i>Всего этот человек удалил у вас {total_deleted} "
            f"{plural(total_deleted, 'сообщение', 'сообщения', 'сообщений')}.</i>"
        )
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


def muted_card(
    *,
    name: str | None,
    username: str | None,
    user_id: int | None,
    kind: str,
    text: str,
    removed: bool,
) -> str:
    icon = KIND_ICONS.get(kind, "💬")
    tail = "" if removed else "\n\n<i>Из чата убрать не вышло — нет права.</i>"
    body = esc(text) or f"<i>{KINDS.get(kind, kind)}</i>"
    return (
        f"🔇 <b>Глухой режим</b> · {who(name, username, user_id)}\n\n"
        f"{icon} {body}{tail}"
    )


def filtered_card(
    *,
    name: str | None,
    username: str | None,
    user_id: int | None,
    kind: str,
    text: str,
    verdict: Any,
    removed: bool,
) -> str:
    """Карточка антискама с разбором — главное отличие от чужих фильтров."""
    icon = KIND_ICONS.get(kind, "💬")
    signals = "\n".join(f"   ▪️ {esc(s.note)} <code>+{s.weight}</code>" for s in verdict.signals)
    action = "убрано из чата" if removed else "оставлено в чате"
    return (
        f"🛡 <b>Антискам</b> · {who(name, username, user_id)}\n"
        f"<i>{verdict.score} из {verdict.threshold} нужных · {action}</i>\n\n"
        f"{signals}\n\n"
        f"{icon} <b>Текст:</b>\n{esc(short(text, 700)) or f'<i>{KINDS.get(kind, kind)}</i>'}"
    )


def new_dialog_card(
    *,
    name: str | None,
    username: str | None,
    user_id: int | None,
    text: str,
) -> str:
    return (
        f"👋 <b>Новый диалог</b> · {who(name, username, user_id)}\n\n"
        f"{esc(short(text, 400)) or '<i>без текста</i>'}"
    )


# --------------------------------------------------------------------------
# Экраны настроек
# --------------------------------------------------------------------------


def rules_list(rules: Sequence[Mapping[str, Any]]) -> str:
    if not rules:
        return (
            "💬 <b>Автоответы</b>\n\nПравил нет. Правило — это слова-триггеры "
            "и готовый ответ на них. Проверяются сверху вниз, отвечает "
            "первое подошедшее."
        )
    lines = [
        "💬 <b>Автоответы</b>",
        "<i>Проверяются сверху вниз, отвечает первое подошедшее.</i>",
        "",
    ]
    for i, rule in enumerate(rules, 1):
        mark = "" if rule["enabled"] else " (выключено)"
        hits = f" · сработало {rule['hits']}" if rule["hits"] else ""
        lines.append(
            f"{i}. <code>{esc(rule['triggers'])}</code>{mark}{hits}\n"
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


def rule_saved(rule: Mapping[str, Any]) -> str:
    return "✅ <b>Правило сохранено</b>\n\n" + rule_card(rule)


def confirm_delete(rule: Mapping[str, Any]) -> str:
    return (
        f"Удалить правило <code>{esc(short(rule['triggers'], 40))}</code>?\n\n"
        "Отменить это будет нельзя — текст ответа придётся набрать заново."
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
    "Добавил {n} правила-примера. Откройте каждое и перепишите под себя — "
    "сейчас там заглушки, которые уйдут вашим собеседникам как есть."
)


def texts_card(st: Mapping[str, Any]) -> str:
    return (
        "✍️ <b>Тексты</b>\n\n"
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
        "filter_words": "свои слова для антискама через |",
    }
    return (
        f"Пришлите новый {titles.get(field, 'текст')}.\n\n"
        f"<b>Сейчас:</b>\n{esc(current) or '<i>пусто</i>'}\n\n"
        "Подстановки: <code>{name}</code>, <code>{username}</code>, "
        "<code>{time}</code>, <code>{date}</code>.\n"
        "Отмена: /cancel"
    )


def timings_card(st: Mapping[str, Any]) -> str:
    return (
        "⏱ <b>Паузы</b>\n\n"
        f"🕒 <b>Между ответами в одном чате: {secs(st['cooldown'])}</b>\n"
        "Держит бота от очереди одинаковых ответов, когда человек пишет "
        "мысль в три сообщения. Ответ по другому правилу эту паузу "
        "обходит — на новый вопрос бот отвечает сразу.\n\n"
        f"⏳ <b>После вашего ответа: {mins(st['pause_minutes'])}</b>\n"
        "Главное правило вежливости: вы написали в чат сами — бот "
        "замолкает и не лезет в живой диалог.\n\n"
        "<i>Верхний ряд — между ответами, нижний — после вашего.</i>"
    )


def trace_card(st: Mapping[str, Any], archive: int) -> str:
    days = f"{st['keep_days']} дн."
    return (
        "🗑 <b>След</b>\n"
        "<i>то, что собеседник пытался стереть</i>\n\n"
        f"Ловить удалённые: <b>{onoff(st['spy'])}</b>\n"
        f"Сообщать о правках: <b>{onoff(st['spy_edits'])}</b>\n"
        f"В архиве сейчас: <b>{archive}</b>\n"
        f"Срок хранения: <b>{days}</b>\n\n"
        "<b>Как это работает.</b> Telegram присылает боту только номера "
        "удалённых сообщений — без текста и файлов. Поэтому бот "
        "складывает входящие в свою базу и достаёт их оттуда, когда "
        "сообщение удалили.\n\n"
        "Отсюда два ограничения:\n"
        f"• видно только то, что пришло <b>после</b> подключения;\n"
        f"• архив живёт {days} — потом записи стираются.\n\n"
        "<i>Свои сообщения бот не архивирует, только входящие.</i>"
    )


def guard_card(st: Mapping[str, Any]) -> str:
    words = st["filter_words"] or ""
    return (
        "🛡 <b>Антискам</b>\n"
        "<i>разбор первых сообщений от незнакомых</i>\n\n"
        f"Фильтр: <b>{onoff(st['filter_on'])}</b>\n"
        f"Что делает: <b>{'удаляет и сообщает' if st['filter_delete'] else 'только сообщает'}</b>\n"
        f"Порог срабатывания: <b>{st['filter_score']}</b> очк.\n"
        f"Уведомлять о новых диалогах: <b>{onoff(st['notify_new'])}</b>\n"
        f"Свои слова: <code>{esc(short(words, 90)) or 'нет'}</code>\n\n"
        "<b>Очки за признаки</b>\n"
        "▪️ выпрашивает код или пароль — 5\n"
        "▪️ исполняемый файл — 5\n"
        "▪️ работа, заработок, крипта, ставки — 3\n"
        "▪️ просит денег или реквизиты — 3\n"
        "▪️ ссылка, кнопки, зовёт в бота — 2\n"
        "▪️ пишет бот, розыгрыш — 2\n"
        "▪️ срочность, простыня текста, форвард — 1\n"
        "▪️ ваше слово из списка — 4\n\n"
        "Порог <b>2</b> — строго, <b>3</b> — как надо, <b>5</b> — только "
        "явный спам.\n\n"
        "<i>Коммерческие признаки проверяются только у тех, с кем "
        "переписки ещё не было. Файлы и выпрашивание кодов — всегда.</i>"
    )


def commands_card(st: Mapping[str, Any], total: int, groups: Sequence[tuple[str, str, int]]) -> str:
    lines = [
        "⌨️ <b>Команды</b>",
        f"<i>{total} {plural(total, 'команда', 'команды', 'команд')} прямо в переписке</i>",
        "",
        f"Состояние: <b>{onoff(st['commands'])}</b>",
        f"Префикс: <code>{esc(st['prefix'])}</code>",
        "",
    ]
    for icon, title, count in groups:
        lines.append(f"{icon} <b>{title}</b> — {count}")
    lines += [
        "",
        f"Полный список — <code>{esc(st['prefix'])}помощь</code> в любом "
        "своём чате, или кнопкой ниже.",
        "",
        "<i>Бот убирает вашу команду и ставит на её место результат. Для "
        "этого нужно право «удалять мои сообщения».</i>",
    ]
    return "\n".join(lines)


def chats_card(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return (
            "💬 <b>Диалоги</b>\n\nПока пусто. Здесь появятся личные чаты, в "
            "которых бот увидел сообщения после подключения."
        )
    lines = [
        "💬 <b>Диалоги</b>",
        "<i>Нажатие переключает: отвечать в этом чате или молчать.</i>",
        "",
    ]
    for row in rows:
        marks = []
        if row["ignored"]:
            marks.append("🔕")
        if row["muted"]:
            marks.append("🔇")
        if row["trusted"]:
            marks.append("🛡")
        nick = f" @{esc(row['username'])}" if row["username"] else ""
        tail = []
        if row["deleted"]:
            tail.append(f"удалил {row['deleted']}")
        if row["edited"]:
            tail.append(f"правил {row['edited']}")
        if row["flagged"]:
            tail.append(f"фильтр {row['flagged']}")
        lines.append(
            f"{''.join(marks) or '🔔'} <b>{esc(row['title'] or row['chat_id'])}</b>{nick}\n"
            f"    его {row['incoming']} · ответов {row['replies']}"
            + (f" · {', '.join(tail)}" if tail else "")
        )
    return "\n".join(lines)


def stats_card(data: Mapping[str, Any], archive: int) -> str:
    lines = [
        "📊 <b>Сводка</b>",
        "",
        f"Автоответов за сутки: <b>{data['day']}</b>",
        f"За неделю: <b>{data['week']}</b>",
        f"Всего: <b>{data['total']}</b>",
        f"Диалогов на обслуживании: <b>{data['chats']}</b>",
        f"Сообщений в архиве: <b>{archive}</b>",
    ]
    if data["kinds"]:
        lines += ["", "<i>За неделю по типам:</i>"]
        for kind, n in data["kinds"]:
            lines.append(f"· {REPLY_KINDS.get(kind, kind)} — {n}")
    return "\n".join(lines)


def log_card(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "🧾 <b>Последние ответы</b>\n\nПока бот ничего не отправлял."
    lines = ["🧾 <b>Последние ответы</b>", ""]
    for row in rows:
        lines.append(
            f"<code>{when(row['at'])}</code> · "
            f"{REPLY_KINDS.get(row['kind'], row['kind'])}\n"
            f"им: {esc(short(row['incoming'] or '—', 50))}\n"
            f"бот: {esc(short(row['text'], 50))}"
        )
        lines.append("")
    return "\n".join(lines)
