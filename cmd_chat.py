"""Команды по чату: карточка собеседника, мут, уборка, заметки, правила.

Здесь живёт то, чем этот набор отличается от чужих сильнее всего.

«.инфо» у других ботов — это анкета: id, ник, дата регистрации. То же
самое показывает и наш, но добавляет главное: **что человек делал в
переписке с вами**. Сколько сообщений прислал, сколько из них потом
удалил, сколько переписал, сколько раз на нём срабатывал антискам, с
какого числа вы общаетесь. Эти цифры бот собирает сам, поэтому их
неоткуда взять боту, который просто пересылает события.

«.мут» здесь тоже другой. Заглушить человека в личке Telegram нельзя —
такой возможности в API нет ни у бота, ни у аккаунта. Зато можно
удалять его сообщения по мере поступления, а текст присылать владельцу
в личку. Получается «глухой режим»: собеседник пишет в пустоту, владелец
всё читает, но чат не мигает.
"""

from __future__ import annotations

import ast
import html
import operator
import time
from datetime import datetime

from aiogram.exceptions import TelegramAPIError

import db
import engine
import state
import texts
import whois
from cmdbase import Ctx, command

MAX_PURGE = 100


def esc(text: object) -> str:
    return html.escape(str(text or ""), quote=False)


# --------------------------------------------------------------------------
# Кто это
# --------------------------------------------------------------------------


@command("досье", "инфо", group="диалог", about="карточка собеседника и его поведение")
async def cmd_info(ctx: Ctx) -> None:
    chat = await db.chat_of(ctx.owner_id, ctx.chat_id)
    peer_id = ctx.peer_id or ctx.chat_id
    lines = [f"<b>{esc(ctx.peer_name)}</b>"]
    if chat["username"]:
        lines.append(f"@{esc(chat['username'])}")
    lines.append(f"id: <code>{peer_id}</code>")

    when = whois.registered(peer_id)
    if when:
        lines.append(
            f"в Telegram примерно с {when.strftime('%m.%Y')} "
            f"· {whois.age_words(when)} <i>(оценка по id)</i>"
        )

    lines += ["", "<b>В переписке с вами</b>"]
    lines.append(f"диалог с {whois.since_words(chat['first_seen'])}")
    lines.append(f"его сообщений: <b>{chat['incoming']}</b>")
    lines.append(f"автоответов бота: <b>{chat['replies']}</b>")
    if chat["deleted"]:
        lines.append(f"🗑 удалил сообщений: <b>{chat['deleted']}</b>")
    if chat["edited"]:
        lines.append(f"✏️ правил сообщений: <b>{chat['edited']}</b>")
    if chat["flagged"]:
        lines.append(f"🛡 срабатываний антискама: <b>{chat['flagged']}</b>")

    score, word = whois.trust(chat)
    if score:
        lines.append(f"поведение: <b>{word}</b> ({score}/100)")

    flags = []
    if chat["muted"]:
        flags.append("🔇 в муте")
    if chat["ignored"]:
        flags.append("🔕 без автоответов")
    if flags:
        lines += ["", " · ".join(flags)]

    if chat["note"]:
        lines += ["", f"📝 <i>{esc(chat['note'])}</i>"]

    await ctx.replace("\n".join(lines), html=True)


@command("ид", "номер", group="диалог", about="id собеседника")
async def cmd_id(ctx: Ctx) -> None:
    await ctx.replace(f"<code>{ctx.peer_id or ctx.chat_id}</code>", html=True)


@command("заметка", "помета", group="диалог", about="заметка о собеседнике", usage="[текст]")
async def cmd_note(ctx: Ctx) -> None:
    text = ctx.text()
    if not text:
        chat = await db.chat_of(ctx.owner_id, ctx.chat_id)
        current = chat["note"] or "пусто"
        await ctx.drop_command()
        await ctx.to_owner(f"📝 Заметка о {esc(ctx.peer_name)}: <i>{esc(current)}</i>")
        return
    if text.strip() in ("-", "снять", "убрать"):
        await db.set_note(ctx.owner_id, ctx.chat_id, None)
        await ctx.drop_command()
        await ctx.to_owner("📝 Заметка снята.")
        return
    await db.set_note(ctx.owner_id, ctx.chat_id, text[:500])
    await ctx.drop_command()
    # Заметка — вещь для себя, собеседнику её видеть незачем, поэтому
    # подтверждение уходит в личку, а в чате не остаётся ничего.
    await ctx.to_owner(f"📝 Записал о {esc(ctx.peer_name)}: <i>{esc(text[:500])}</i>")


# --------------------------------------------------------------------------
# Тишина
# --------------------------------------------------------------------------


@command(
    "глушь", "мут",
    group="диалог",
    about="глухой режим: сообщения удаляются, текст — вам в личку",
    needs=("can_delete_all_messages",),
)
async def cmd_mute(ctx: Ctx) -> None:
    await db.set_muted(ctx.owner_id, ctx.chat_id, True)
    await ctx.drop_command()
    await ctx.to_owner(
        f"🔇 <b>{esc(ctx.peer_name)}</b> в глухом режиме.\n\n"
        "Его сообщения будут удаляться из чата, а текст приходить сюда. "
        "Снять — <code>.разглушь</code> в том же чате."
    )


@command("разглушь", "размут", group="диалог", about="снять глухой режим")
async def cmd_unmute(ctx: Ctx) -> None:
    await db.set_muted(ctx.owner_id, ctx.chat_id, False)
    await ctx.drop_command()
    await ctx.to_owner(f"🔊 <b>{esc(ctx.peer_name)}</b> снова пишет обычно.")


@command("тихо", "молчи", group="диалог", about="не отвечать автоответами в этом чате")
async def cmd_ignore(ctx: Ctx) -> None:
    chat = await db.chat_of(ctx.owner_id, ctx.chat_id)
    new = not chat["ignored"]
    await db.set_ignored(ctx.owner_id, ctx.chat_id, new)
    await ctx.drop_command()
    await ctx.to_owner(
        f"{'🔕' if new else '🔔'} Автоответы в чате с <b>{esc(ctx.peer_name)}</b> "
        f"{'выключены' if new else 'включены'}."
    )


# --------------------------------------------------------------------------
# Уборка
# --------------------------------------------------------------------------


@command(
    "удали", "снеси",
    group="диалог",
    about="удалить сообщение — ответом на него",
    needs=("can_delete_all_messages",),
)
async def cmd_del(ctx: Ctx) -> None:
    if ctx.reply is None:
        await ctx.fail("примените команду ответом на сообщение")
        return
    ids = [ctx.reply.message_id, ctx.message.message_id]
    try:
        await ctx.bot.delete_business_messages(
            business_connection_id=ctx.conn_id, message_ids=ids
        )
    except TelegramAPIError as err:
        await ctx.fail(f"не удалилось: {err}")


@command(
    "чисти", "зачистка",
    group="диалог",
    about="удалить всё от сообщения-ответа до текущего",
    needs=("can_delete_all_messages",),
)
async def cmd_purge(ctx: Ctx) -> None:
    if ctx.reply is None:
        await ctx.fail(
            "ответьте на сообщение, с которого начинать уборку — удалится "
            "всё от него до этой команды"
        )
        return
    start, end = sorted((ctx.reply.message_id, ctx.message.message_id))
    ids = list(range(start, end + 1))
    if len(ids) > MAX_PURGE:
        await ctx.fail(f"слишком много: {len(ids)} сообщений, предел — {MAX_PURGE}")
        return
    try:
        await ctx.bot.delete_business_messages(
            business_connection_id=ctx.conn_id, message_ids=ids
        )
        gone = len(ids)
    except TelegramAPIError:
        # В диапазоне попадаются номера, которых в чате нет (служебные
        # события, чужие удалённые). Telegram отклоняет такой пакет
        # целиком, поэтому добиваем по одному.
        gone = 0
        for mid in ids:
            try:
                await ctx.bot.delete_business_messages(
                    business_connection_id=ctx.conn_id, message_ids=[mid]
                )
                gone += 1
            except TelegramAPIError:
                continue
    await ctx.to_owner(f"🧹 Убрано сообщений: <b>{gone}</b> из {len(ids)}.")


@command("прочти", "прочитано", group="диалог", about="отметить чат прочитанным")
async def cmd_read(ctx: Ctx) -> None:
    target = ctx.reply.message_id if ctx.reply else ctx.message.message_id
    await ctx.drop_command()
    try:
        await ctx.bot.read_business_message(
            business_connection_id=ctx.conn_id,
            chat_id=ctx.chat_id,
            message_id=target,
        )
    except TelegramAPIError as err:
        await ctx.to_owner(f"⚠️ не отметилось прочитанным: {err}")


# --------------------------------------------------------------------------
# Автоответчик из чата
# --------------------------------------------------------------------------


@command("отошел", "афк", group="диалог", about="включить режим «отошёл»", usage="[текст]")
async def cmd_afk(ctx: Ctx) -> None:
    text = ctx.text()
    if text:
        await db.set_setting(ctx.owner_id, "away_text", text[:900])
    await db.set_setting(ctx.owner_id, "away", 1)
    await ctx.drop_command()
    st = await db.settings_of(ctx.owner_id)
    await ctx.to_owner(
        "🌙 Режим «отошёл» включён. Всем, кто напишет, уйдёт:\n\n"
        f"<i>{esc(st['away_text'])}</i>\n\nВернуться — <code>.вернулся</code>"
    )


@command("вернулся", "тут", group="диалог", about="выключить режим «отошёл»")
async def cmd_back(ctx: Ctx) -> None:
    await db.set_setting(ctx.owner_id, "away", 0)
    await ctx.drop_command()
    await ctx.to_owner("☀️ Режим «отошёл» выключен.")


@command("почему", "разбор", group="диалог", about="почему бот промолчал или ответил")
async def cmd_why(ctx: Ctx) -> None:
    await ctx.drop_command()
    seen = state.last(ctx.owner_id, ctx.chat_id)
    if seen is None:
        await ctx.to_owner(
            "🤔 По этому чату решений пока не было — бот ещё не получал "
            "здесь входящих после запуска."
        )
        return
    when, kind, reason = seen
    ago = int(time.time() - when)
    titles = {
        "rule": "ответил по правилу",
        "greet": "отправил приветствие",
        "away": "ответил как «отошёл»",
        "fallback": "ответил по умолчанию",
        "skip": "промолчал",
        "muted": "удалил сообщение — чат в муте",
        "filtered": "удалил сообщение — антискам",
        "game": "принял как ход в игре",
    }
    await ctx.to_owner(
        f"🤔 Последнее решение по чату с <b>{esc(ctx.peer_name)}</b> "
        f"({ago} с назад):\n\n<b>{titles.get(kind, kind)}</b>"
        + (f"\n<i>{esc(reason)}</i>" if reason else "")
    )


@command("правило", "прав", group="диалог", about="добавить правило автоответа", usage="слова = ответ")
async def cmd_rule(ctx: Ctx) -> None:
    raw = ctx.text()
    if "=" not in raw:
        await ctx.fail(
            "формат: <code>.правило цена|прайс = скину через час</code>"
        )
        return
    triggers, _, reply = raw.partition("=")
    parts = engine.triggers_of(triggers)
    if not parts or not reply.strip():
        await ctx.fail("нужны и слова, и текст ответа")
        return
    rule_id = await db.add_rule(
        ctx.owner_id, engine.SEP.join(parts), reply.strip()[:900]
    )
    await ctx.drop_command()
    await ctx.to_owner(
        f"📋 Правило #{rule_id} добавлено:\n<code>{esc(engine.SEP.join(parts))}</code>\n"
        f"→ {esc(reply.strip()[:900])}"
    )


# --------------------------------------------------------------------------
# Прочее
# --------------------------------------------------------------------------


@command("запомни", "шаб", group="диалог", about="сохранить заготовку", usage="имя = текст")
async def cmd_remember(ctx: Ctx) -> None:
    raw = ctx.text()
    if "=" not in raw:
        await ctx.fail("формат: <code>.запомни прайс = стрижка 1500, борода 800</code>")
        return
    name, _, body = raw.partition("=")
    name, body = name.strip().lower(), body.strip()
    if not name or not body:
        return await ctx.fail("нужны и имя, и текст")
    if len(name.split()) > 1:
        return await ctx.fail("имя заготовки — одно слово")
    await db.set_snip(ctx.owner_id, name, body[:900])
    await ctx.drop_command()
    await ctx.to_owner(
        f"💾 Заготовка <code>{esc(name)}</code> сохранена.\n"
        f"Вставить в любом чате: <code>.вставь {esc(name)}</code>"
    )


@command("вставь", "заготовка", group="диалог", about="вставить заготовку", usage="имя")
async def cmd_snip(ctx: Ctx) -> None:
    name = ctx.text().strip().lower()
    if not name:
        await ctx.fail("укажите имя заготовки — список в <code>.шаблоны</code>")
        return
    row = await db.snip_of(ctx.owner_id, name)
    if row is None:
        await ctx.fail(f"заготовки <code>{esc(name)}</code> нет")
        return
    # Заготовка уходит plain text: её писал человек, и знак «<» в
    # прайсе не должен ронять отправку.
    await ctx.replace(row["body"])


@command("шаблоны", "заготовки", group="диалог", about="список заготовок")
async def cmd_snips(ctx: Ctx) -> None:
    await ctx.drop_command()
    rows = await db.snips_of(ctx.owner_id)
    if not rows:
        await ctx.to_owner(
            "💾 Заготовок нет.\n\nСохранить: "
            "<code>.запомни прайс = стрижка 1500</code>\n"
            "Вставить: <code>.вставь прайс</code>"
        )
        return
    lines = ["💾 <b>Заготовки</b>", ""]
    for row in rows:
        used = f" · вставлено {row['used']}" if row["used"] else ""
        lines.append(
            f"<code>{esc(row['name'])}</code>{used}\n"
            f"    {esc(texts.short(row['body'], 60))}"
        )
    await ctx.to_owner("\n".join(lines))


@command("помощь", "команды", "хелп", group="служба", about="список команд — вам в личку")
async def cmd_help(ctx: Ctx) -> None:
    import cmdbase

    await ctx.drop_command()
    prefix = ctx.settings["prefix"] or "."
    for page in cmdbase.help_pages(prefix):
        await ctx.to_owner(page)
    if not ctx.dropped:
        await ctx.to_owner(
            "⚠️ Сообщение с командой осталось в чате: боту не выдано право "
            "«удалять мои сообщения» в «Автоматизации чатов»."
        )


@command("префикс", "знак", group="служба", about="сменить префикс команд", usage="символ")
async def cmd_prefix(ctx: Ctx) -> None:
    new = ctx.text().strip()
    if len(new) != 1 or new.isalnum():
        await ctx.fail("нужен один знак, не буква и не цифра: например <code>.</code> или <code>!</code>")
        return
    await db.set_setting(ctx.owner_id, "prefix", new)
    await ctx.drop_command()
    await ctx.to_owner(f"Префикс команд теперь <code>{esc(new)}</code>")


_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def calc(expression: str) -> float:
    """Арифметика без eval.

    eval на строке от пользователя — это исполнение произвольного кода;
    в боте, который стоит на чужом сервере, такого быть не должно.
    Поэтому выражение разбирается в дерево и считается вручную: числа,
    скобки и шесть операций, ничего больше.
    """
    tree = ast.parse(expression, mode="eval")

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            if isinstance(node.op, ast.Pow):
                right = walk(node.right)
                if abs(right) > 100:
                    raise ValueError("слишком большая степень")
                return _OPS[type(node.op)](walk(node.left), right)
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        raise ValueError("так считать не умею")

    return walk(tree)


@command("посчитай", "калк", group="служба", about="калькулятор", usage="2+2*10")
async def cmd_calc(ctx: Ctx) -> None:
    expression = ctx.text()
    if not expression:
        await ctx.fail("напишите выражение: <code>.калк (2+2)*10</code>")
        return
    try:
        value = calc(expression)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as err:
        await ctx.fail(f"не посчиталось: {esc(err)}")
        return
    pretty = f"{value:.10g}"
    await ctx.replace(f"{esc(expression)} = <b>{pretty}</b>", html=True)


@command("пинг", "отклик", group="служба", about="задержка до Telegram")
async def cmd_ping(ctx: Ctx) -> None:
    started = time.perf_counter()
    await ctx.drop_command()
    message = await ctx.send("🏓")
    delay = (time.perf_counter() - started) * 1000
    if message is not None:
        await ctx.edit(message, f"🏓 {delay:.0f} мс")


@command("время", "часы", group="служба", about="текущее время")
async def cmd_time(ctx: Ctx) -> None:
    # Эмодзи и «·» собираются в Python, а не внутри strftime: строка
    # формата уходит в системную функцию и на Windows кодируется
    # локалью, где эмодзи попросту нет — команда падала на ней целиком.
    now = datetime.now()
    await ctx.replace(f"🕒 {now.strftime('%H:%M:%S')} · {now.strftime('%d.%m.%Y')}")


@command("сводка", "статистика", group="служба", about="сводка по всем чатам")
async def cmd_stat(ctx: Ctx) -> None:
    await ctx.drop_command()
    data = await db.stats_of(ctx.owner_id)
    archive = await db.archive_size(ctx.owner_id)
    await ctx.to_owner(texts.stats_card(data, archive))
