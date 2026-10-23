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
в личку. Собеседник видит в чате «… в муте» с премиум-иконкой и дальше
пишет в пустоту, владелец всё читает, но чат не мигает. Мут бывает на
время — «.мут 30м», — снимает его фоновая задача timers.py.
"""

from __future__ import annotations

import ast
import asyncio
import html
import operator
import time
from datetime import datetime

from aiogram.exceptions import TelegramAPIError

import db
import engine
import state
import texts
import timers
import whois
from pe import e
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
    lines = [f"{e('id_card')} <b>{esc(ctx.peer_name)}</b>"]
    if chat["username"]:
        lines.append(f"@{esc(chat['username'])}")
    lines.append(f"id: <code>{peer_id}</code>")

    when = whois.registered(peer_id)
    if when:
        lines.append(
            f"в Telegram примерно с {when.strftime('%m.%Y')} "
            f"· {whois.age_words(when)} <i>(оценка по id)</i>"
        )

    lines += ["", f"{e('chats')} <b>В переписке с вами</b>"]
    lines.append(f"диалог с {whois.since_words(chat['first_seen'])}")
    lines.append(f"его сообщений: <b>{chat['incoming']}</b>")
    lines.append(f"автоответов бота: <b>{chat['replies']}</b>")
    if chat["deleted"]:
        lines.append(f"{e('trash')} удалил сообщений: <b>{chat['deleted']}</b>")
    if chat["edited"]:
        lines.append(f"{e('edit')} правил сообщений: <b>{chat['edited']}</b>")
    if chat["flagged"]:
        lines.append(f"{e('shield')} срабатываний антискама: <b>{chat['flagged']}</b>")

    score, word = whois.trust(chat)
    if score:
        lines.append(f"{e('gauge')} поведение: <b>{word}</b> ({score}/100)")

    flags = []
    if chat["muted"]:
        flags.append(f"{e('mute')} в муте")
    if chat["ignored"]:
        flags.append(f"{e('bell_off')} без автоответов")
    if flags:
        lines += ["", " · ".join(flags)]

    if chat["note"]:
        lines += ["", f"{e('note')} <i>{esc(chat['note'])}</i>"]

    await ctx.replace("\n".join(lines), html=True)


@command("ид", "номер", group="диалог", about="id собеседника")
async def cmd_id(ctx: Ctx) -> None:
    await ctx.replace(f"{e('badge_id')} <code>{ctx.peer_id or ctx.chat_id}</code>", html=True)


@command(
    "заметка", "помета",
    group="диалог",
    about="заметка о собеседнике — видите только вы",
    usage="[текст]",
    example="должен 500 до пятницы",
)
async def cmd_note(ctx: Ctx) -> None:
    text = ctx.text()
    if not text:
        chat = await db.chat_of(ctx.owner_id, ctx.chat_id)
        current = chat["note"] or "пусто"
        await ctx.drop_command()
        await ctx.to_owner(f"{e('note')} Заметка о {esc(ctx.peer_name)}: <i>{esc(current)}</i>")
        return
    if text.strip() in ("-", "снять", "убрать"):
        await db.set_note(ctx.owner_id, ctx.chat_id, None)
        await ctx.drop_command()
        await ctx.to_owner(f"{e('note')} Заметка снята.")
        return
    await db.set_note(ctx.owner_id, ctx.chat_id, text[:500])
    await ctx.drop_command()
    # Заметка — вещь для себя, собеседнику её видеть незачем, поэтому
    # подтверждение уходит в личку, а в чате не остаётся ничего.
    await ctx.to_owner(f"{e('note')} Записал о {esc(ctx.peer_name)}: <i>{esc(text[:500])}</i>")


# --------------------------------------------------------------------------
# Тишина
# --------------------------------------------------------------------------


@command(
    "мут", "глушь",
    group="диалог",
    about="мут: его сообщения удаляются, текст приходит вам; в чате — «… в муте»",
    usage="[время]",
    example="30м",
    needs=("can_delete_all_messages",),
)
async def cmd_mute(ctx: Ctx) -> None:
    span = timers.parse_span(ctx.args) if ctx.args.strip() else None
    if ctx.args.strip() and span is None:
        await ctx.fail(
            "не понял срок. Примеры: <code>.мут 30м</code>, <code>.мут 2ч</code>, "
            "<code>.мут 1д</code> или просто <code>.мут</code> — до снятия"
        )
        return
    until = int(time.time()) + span if span else 0
    await db.set_muted(ctx.owner_id, ctx.chat_id, True, until)
    words = timers.span_words(span) if span else None
    await ctx.replace(texts.mute_public(ctx.peer_name, words), html=True)
    how_long = f"на <b>{words}</b>" if words else "до снятия"
    await ctx.to_owner(
        f"{e('mute')} <b>{esc(ctx.peer_name)}</b> в муте {how_long}.\n\n"
        "Его сообщения будут удаляться из чата, а текст и файлы — приходить "
        "сюда. Снять раньше — <code>.размут</code> в том же чате или "
        "<code>.муты</code> здесь."
    )


@command("размут", "разглушь", group="диалог", about="снять мут — в чате будет «… больше не в муте»")
async def cmd_unmute(ctx: Ctx) -> None:
    chat = await db.chat_of(ctx.owner_id, ctx.chat_id)
    if not chat["muted"]:
        await ctx.fail(f"{esc(ctx.peer_name)} и так не в муте")
        return
    await db.set_muted(ctx.owner_id, ctx.chat_id, False)
    await ctx.replace(texts.unmute_public(ctx.peer_name), html=True)


@command("муты", "глухие", group="диалог", about="кто сейчас в муте — список вам в личку")
async def cmd_mutes(ctx: Ctx) -> None:
    await ctx.drop_command()
    rows = await db.muted_chats(ctx.owner_id)
    if not rows:
        await ctx.to_owner(f"{e('volume')} Сейчас в муте никого нет.")
        return
    now = int(time.time())
    lines = [f"{e('mute')} <b>В муте</b> · {len(rows)}", ""]
    for row in rows:
        left = (
            f"ещё {timers.span_words(row['muted_until'] - now)}"
            if row["muted_until"]
            else "до снятия"
        )
        name = esc(row["title"] or row["chat_id"])
        lines.append(f'{e("dots")} <a href="tg://user?id={row["chat_id"]}">{name}</a> — {left}')
    lines += ["", "<i>Снять — <code>.размут</code> в чате с человеком.</i>"]
    await ctx.to_owner("\n".join(lines))


@command("свой", "доверяю", group="диалог", about="доверенный чат: антискам его не трогает")
async def cmd_trust(ctx: Ctx) -> None:
    chat = await db.chat_of(ctx.owner_id, ctx.chat_id)
    new = not chat["trusted"]
    await db.set_trusted(ctx.owner_id, ctx.chat_id, new)
    await ctx.drop_command()
    await ctx.to_owner(
        f"{e('shield_check')} <b>{esc(ctx.peer_name)}</b> — доверенный, антискам "
        "его больше не проверяет."
        if new
        else f"{e('shield')} <b>{esc(ctx.peer_name)}</b> снова проверяется антискамом."
    )


@command("тихо", "молчи", group="диалог", about="не отвечать автоответами в этом чате")
async def cmd_ignore(ctx: Ctx) -> None:
    chat = await db.chat_of(ctx.owner_id, ctx.chat_id)
    new = not chat["ignored"]
    await db.set_ignored(ctx.owner_id, ctx.chat_id, new)
    await ctx.drop_command()
    await ctx.to_owner(
        f"{e('bell_off') if new else e('bell')} Автоответы в чате с <b>{esc(ctx.peer_name)}</b> "
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
    await ctx.to_owner(f"{e('trash')} Убрано сообщений: <b>{gone}</b> из {len(ids)}.")


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
        await ctx.to_owner(f"{e('warning')} не отметилось прочитанным: {err}")


# --------------------------------------------------------------------------
# Автоответчик из чата
# --------------------------------------------------------------------------


@command(
    "отошел", "афк",
    group="диалог",
    about="режим «отошёл»: всем, кто напишет, уйдёт этот текст",
    usage="[текст]",
    example="на паре до 15:00",
)
async def cmd_afk(ctx: Ctx) -> None:
    text = ctx.text()
    if text:
        await db.set_setting(ctx.owner_id, "away_text", text[:900])
    await db.set_setting(ctx.owner_id, "away", 1)
    await ctx.drop_command()
    st = await db.settings_of(ctx.owner_id)
    await ctx.to_owner(
        f"{e('pause')} Режим «отошёл» включён. Всем, кто напишет, уйдёт:\n\n"
        f"<i>{esc(st['away_text'])}</i>\n\nВернуться — <code>.вернулся</code>"
    )


@command("вернулся", "тут", group="диалог", about="выключить режим «отошёл»")
async def cmd_back(ctx: Ctx) -> None:
    await db.set_setting(ctx.owner_id, "away", 0)
    await ctx.drop_command()
    await ctx.to_owner(f"{e('play')} Режим «отошёл» выключен.")


@command("почему", "разбор", group="диалог", about="почему бот промолчал или ответил")
async def cmd_why(ctx: Ctx) -> None:
    await ctx.drop_command()
    seen = state.last(ctx.owner_id, ctx.chat_id)
    if seen is None:
        await ctx.to_owner(
            f"{e('question')} По этому чату решений пока не было — бот ещё не получал "
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
        f"{e('question')} Последнее решение по чату с <b>{esc(ctx.peer_name)}</b> "
        f"({ago} с назад):\n\n<b>{titles.get(kind, kind)}</b>"
        + (f"\n<i>{esc(reason)}</i>" if reason else "")
    )


@command(
    "правило", "прав",
    group="диалог",
    about="добавить правило автоответа",
    usage="слова = ответ",
    example="цена|прайс = скину вечером",
)
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
        f"{e('checklist')} Правило #{rule_id} добавлено:\n<code>{esc(engine.SEP.join(parts))}</code>\n"
        f"→ {esc(reply.strip()[:900])}"
    )


# --------------------------------------------------------------------------
# Прочее
# --------------------------------------------------------------------------


@command(
    "запомни", "шаб",
    group="диалог",
    about="сохранить заготовку текста",
    usage="имя = текст",
    example="прайс = стрижка 1500, борода 800",
)
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
        f"{e('save')} Заготовка <code>{esc(name)}</code> сохранена.\n"
        f"Вставить в любом чате: <code>.вставь {esc(name)}</code>"
    )


@command("вставь", "заготовка", group="диалог", about="вставить заготовку", usage="имя", example="прайс")
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
            f"{e('save')} Заготовок нет.\n\nСохранить: "
            "<code>.запомни прайс = стрижка 1500</code>\n"
            "Вставить: <code>.вставь прайс</code>"
        )
        return
    lines = [f"{e('save')} <b>Заготовки</b>", ""]
    for row in rows:
        used = f" · вставлено {row['used']}" if row["used"] else ""
        lines.append(
            f"<code>{esc(row['name'])}</code>{used}\n"
            f"    {esc(texts.short(row['body'], 60))}"
        )
    await ctx.to_owner("\n".join(lines))


@command("помощь", "команды", "хелп", group="служба", about="справка по командам — вам в личку")
async def cmd_help(ctx: Ctx) -> None:
    import cmdbase
    import keyboards

    await ctx.drop_command()
    prefix = ctx.settings["prefix"] or "."
    await ctx.to_owner(cmdbase.help_overview(prefix), reply_markup=keyboards.help_menu())
    if not ctx.dropped:
        await ctx.to_owner(
            f"{e('warning')} Сообщение с командой осталось в чате: боту не выдано "
            "право «удалять мои сообщения» в «Автоматизации чатов»."
        )


@command("префикс", "знак", group="служба", about="сменить префикс команд", usage="символ", example="!")
async def cmd_prefix(ctx: Ctx) -> None:
    new = ctx.text().strip()
    if len(new) != 1 or new.isalnum():
        await ctx.fail("нужен один знак, не буква и не цифра: например <code>.</code> или <code>!</code>")
        return
    await db.set_setting(ctx.owner_id, "prefix", new)
    await ctx.drop_command()
    await ctx.to_owner(f"{e('check')} Префикс команд теперь <code>{esc(new)}</code>")


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


@command("посчитай", "калк", group="служба", about="калькулятор", usage="выражение", example="(2+2)*10")
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
    await ctx.replace(f"{e('code')}{esc(expression)} = <b>{pretty}</b>", html=True)


#: .спам: сколько раз по умолчанию и максимум. Больше 20 — уже не шутка,
#: а флуд, за который Telegram режет бизнес-подключение.
SPAM_DEFAULT = 5
SPAM_MAX = 20
SPAM_PAUSE = 0.5

#: Чаты, где спам идёт прямо сейчас: (владелец, чат) → флаг «остановить».
_spamming: dict[tuple[int, int], bool] = {}


def spam_args(raw: str) -> tuple[str, int]:
    """«лох 20» → («лох», 20). Число — последним словом, без него — 5.

    Отдельной функцией, чтобы selfcheck проверял разбор без Telegram.
    """
    words = raw.split()
    count = SPAM_DEFAULT
    if len(words) > 1 and words[-1].isdigit():
        count = int(words[-1])
        words = words[:-1]
    return " ".join(words), max(1, min(count, SPAM_MAX))


@command(
    "спам", "флуд",
    group="диалог",
    about=f"повторить текст в чате, до {SPAM_MAX} раз; «стоп» — остановить",
    usage="текст [сколько]",
    example="лох 20",
    needs=("can_reply",),
)
async def cmd_spam(ctx: Ctx) -> None:
    key = (ctx.owner_id, ctx.chat_id)
    raw = ctx.args.strip()
    if raw.lower() in ("стоп", "хватит", "stop"):
        await ctx.drop_command()
        if key in _spamming:
            _spamming[key] = True
        return
    text, count = spam_args(raw)
    if not text:
        await ctx.fail(
            f"формат: <code>.спам лох 20</code> — текст и число, максимум {SPAM_MAX}"
        )
        return
    if key in _spamming:
        await ctx.fail("в этом чате спам уже идёт — <code>.спам стоп</code>, чтобы остановить")
        return
    _spamming[key] = False
    await ctx.drop_command()
    try:
        for _ in range(count):
            if _spamming.get(key):
                break
            # plain text: что владелец написал, то и уйдёт, без разметки.
            if await ctx.send(text[:4000]) is None:
                break
            await asyncio.sleep(SPAM_PAUSE)
    finally:
        _spamming.pop(key, None)


@command("пинг", "отклик", group="служба", about="задержка до Telegram")
async def cmd_ping(ctx: Ctx) -> None:
    started = time.perf_counter()
    await ctx.drop_command()
    message = await ctx.send(f"{e('wifi')} …", html=True)
    delay = (time.perf_counter() - started) * 1000
    if message is not None:
        await ctx.edit(message, f"{e('wifi')} <b>{delay:.0f} мс</b>", html=True)


@command("время", "часы", group="служба", about="текущее время")
async def cmd_time(ctx: Ctx) -> None:
    # Эмодзи и «·» собираются в Python, а не внутри strftime: строка
    # формата уходит в системную функцию и на Windows кодируется
    # локалью, где эмодзи попросту нет — команда падала на ней целиком.
    now = datetime.now()
    await ctx.replace(
        f"{e('clock')} <b>{now.strftime('%H:%M:%S')}</b> · {now.strftime('%d.%m.%Y')}",
        html=True,
    )


@command("сводка", "статистика", group="служба", about="сводка по всем чатам")
async def cmd_stat(ctx: Ctx) -> None:
    await ctx.drop_command()
    data = await db.stats_of(ctx.owner_id)
    archive = await db.archive_size(ctx.owner_id)
    await ctx.to_owner(texts.stats_card(data, archive))
