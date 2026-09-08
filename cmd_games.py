"""Игры и рандом в переписке.

Две вещи, которых нет у чужих наборов.

Первая: **в игры играет собеседник, а не только владелец**. Партия
объявляется командой, а ходы оба делают обычными сообщениями — «5» в
крестиках, «камень» в кнб. Бот читает входящие и так узнаёт ход. Кнопки
под сообщением в бизнес-чате работают ненадёжно, а сообщение долетает
всегда.

Вторая: кубики и дартс не просто бросаются — бот дожидается конца
анимации Telegram и **комментирует результат**. Значение броска
приходит в ответе на sendDice, но показывается собеседнику только через
несколько секунд, поэтому комментарий уходит с паузой: иначе он
появляется раньше, чем кубик остановился, и спойлерит результат.

Ставок на звёзды здесь нет и не будет: звёзды — реальный платёжный
актив, а автоматический перевод их между людьми по итогам броска кубика
я делать не стану. Счёт ведётся в очках, он хранится в базе по каждому
чату отдельно.
"""

from __future__ import annotations

import asyncio
import random

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import db
import games
from cmdbase import Ctx, command

#: Сколько ждать, пока Telegram доиграет анимацию броска.
ROLL_PAUSE = 3.8


async def _say(bot: Bot, conn_id: str, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            business_connection_id=conn_id,
            parse_mode="HTML",
        )
    except TelegramAPIError:
        pass


# --------------------------------------------------------------------------
# Броски Telegram
# --------------------------------------------------------------------------

#: Что сказать про результат. Ключ — эмодзи, значение — функция от
#: выпавшего числа.
def _dice_note(value: int) -> str:
    if value == 6:
        return "🎲 Шесть. Так и запишем."
    if value == 1:
        return "🎲 Единица. Бывает."
    return f"🎲 {value}."


def _dart_note(value: int) -> str:
    return {
        1: "🎯 Мимо. Совсем мимо.",
        2: "🎯 По краю.",
        3: "🎯 Уже теплее.",
        4: "🎯 Почти.",
        5: "🎯 Рядом с центром!",
        6: "🎯 В яблочко!",
    }.get(value, "🎯")


def _ball_note(value: int) -> str:
    return "🏀 Есть!" if value >= 4 else "🏀 Мимо кольца."


def _foot_note(value: int) -> str:
    return "⚽️ Гол!" if value >= 3 else "⚽️ Вратарь взял."


def _bowl_note(value: int) -> str:
    if value == 6:
        return "🎳 Страйк!"
    if value == 1:
        return "🎳 Ни одной."
    return f"🎳 Сбито кеглей: {value - 1}."


def _slot_note(value: int) -> str:
    return "🎰 Джекпот! Три семёрки." if value == 64 else "🎰 Не сошлось."


ROLLS = {
    "кубик": ("🎲", _dice_note, ("кубик", "куб")),
    "дартс": ("🎯", _dart_note, ("дартс", "дрт")),
    "баскет": ("🏀", _ball_note, ("баскет", "мяч")),
    "футбол": ("⚽", _foot_note, ("футбол", "фт")),
    "боулинг": ("🎳", _bowl_note, ("боулинг", "кегли")),
    "слот": ("🎰", _slot_note, ("слот", "казик")),
}


def _make_roll(emoji: str, note):
    async def run(ctx: Ctx) -> None:
        await ctx.drop_command()
        try:
            sent = await ctx.bot.send_dice(
                chat_id=ctx.chat_id,
                emoji=emoji,
                business_connection_id=ctx.conn_id,
            )
        except TelegramAPIError as err:
            await ctx.to_owner(f"⚠️ бросок не ушёл: {err}")
            return
        value = sent.dice.value if sent.dice else 0
        await asyncio.sleep(ROLL_PAUSE)
        await ctx.send(note(value))

    return run


for _key, (_emoji, _note, _names) in ROLLS.items():
    command(
        *_names,
        group="азарт",
        about=f"бросок {_emoji} с комментарием",
    )(_make_roll(_emoji, _note))


# --------------------------------------------------------------------------
# Мелкий рандом
# --------------------------------------------------------------------------


@command("монетка", "орел", group="азарт", about="подбросить монетку")
async def cmd_coin(ctx: Ctx) -> None:
    await ctx.drop_command()
    message = await ctx.send("🪙 Крутится…")
    result = random.choice(games.COIN)
    if message is not None:
        await asyncio.sleep(1.2)
        await ctx.edit(message, result)
    else:
        await ctx.send(result)


@command("рандом", "число", group="азарт", about="случайное число", usage="[до] | [от до]")
async def cmd_rand(ctx: Ctx) -> None:
    parts = [p for p in ctx.words() if p.lstrip("-").isdigit()]
    if len(parts) >= 2:
        low, high = int(parts[0]), int(parts[1])
    elif len(parts) == 1:
        low, high = 1, int(parts[0])
    else:
        low, high = 1, 100
    if low > high:
        low, high = high, low
    await ctx.replace(f"🎲 {random.randint(low, high)}  <i>({low}–{high})</i>", html=True)


@command("выбери", "выбор", group="азарт", about="выбрать из вариантов", usage="а | б | в")
async def cmd_choose(ctx: Ctx) -> None:
    raw = ctx.text()
    options = [o.strip() for o in raw.replace(" или ", "|").split("|") if o.strip()]
    if len(options) < 2:
        options = [o for o in raw.split() if o]
    if len(options) < 2:
        await ctx.fail("нужно хотя бы два варианта через <code>|</code>")
        return
    import html as _h

    pick = random.choice(options)
    await ctx.replace(f"🤔 {_h.escape(pick, quote=False)}", html=True)


@command("шар", "оракул", group="азарт", about="магический шар", usage="вопрос")
async def cmd_ball(ctx: Ctx) -> None:
    question = ctx.text()
    if not question:
        await ctx.fail("задайте вопрос")
        return
    await ctx.replace(f"🔮 {random.choice(games.BALL)}")


@command("шанс", "процент", group="азарт", about="вероятность события", usage="вопрос")
async def cmd_chance(ctx: Ctx) -> None:
    question = ctx.text()
    if not question:
        await ctx.fail("напишите, вероятность чего считаем")
        return
    percent = games.chance(question)
    await ctx.replace(
        f"📊 <b>{percent}%</b>\n<code>{games.bar(percent)}</code>", html=True
    )


@command("ктоиз", "кто", group="азарт", about="кто из вас двоих", usage="вопрос")
async def cmd_who(ctx: Ctx) -> None:
    import html as _h

    question = ctx.text()
    pick = random.choice((ctx.owner_name, ctx.peer_name))
    tail = f"\n<i>{_h.escape(question, quote=False)}</i>" if question else ""
    await ctx.replace(f"👉 <b>{_h.escape(pick, quote=False)}</b>{tail}", html=True)


@command("когда", "срок", group="азарт", about="когда это случится", usage="вопрос")
async def cmd_when(ctx: Ctx) -> None:
    answers = (
        "сегодня", "завтра", "на этой неделе", "в понедельник", "через месяц",
        "в этом году", "когда-нибудь", "уже случилось", "никогда",
        "как только перестанешь спрашивать", "после дождичка в четверг",
    )
    await ctx.replace(f"📅 {random.choice(answers)}")


@command("рулетка", "барабан", group="азарт", about="шуточная рулетка без ставок")
async def cmd_roulette(ctx: Ctx) -> None:
    await ctx.drop_command()
    message = await ctx.send("🔫 Крутим барабан…")
    await asyncio.sleep(1.6)
    shot = games.roulette()
    text = "💥 Выстрел. Ты был хорошим собеседником." if shot else "😮‍💨 Щёлк. Повезло."
    if message is not None:
        await ctx.edit(message, text)
    else:
        await ctx.send(text)


@command("дуэль", "поединок", group="азарт", about="дуэль на очки со счётом по чату")
async def cmd_duel(ctx: Ctx) -> None:
    await ctx.drop_command()
    message = await ctx.send("⚔️ Дуэль! Считаем до трёх…")
    await asyncio.sleep(1.8)
    owner_won = random.random() < 0.5
    win, lose = (
        (ctx.owner_name, ctx.peer_name) if owner_won else (ctx.peer_name, ctx.owner_name)
    )
    await db.bump_score(ctx.owner_id, ctx.chat_id, "duel", "win" if owner_won else "loss")
    score = await db.score_of(ctx.owner_id, ctx.chat_id, "duel")
    story = games.duel_story(win, lose)
    tail = f"\n\n<i>Счёт в этом чате — {score['wins']}:{score['losses']}</i>"
    if message is not None and await ctx.edit(message, story + tail, html=True):
        return
    await ctx.send(story + tail, html=True)


# --------------------------------------------------------------------------
# Партии с собеседником
# --------------------------------------------------------------------------

TTT_HINT = "Ходите цифрой от 1 до 9 обычным сообщением. Бросить партию — <code>.стоп</code>"


@command("крестики", "хо", group="азарт", about="крестики-нолики", usage="[бот]")
async def cmd_ttt(ctx: Ctx) -> None:
    vs_bot = bool(ctx.args) and ctx.args.strip().lower() in ("бот", "bot", "ai", "комп")
    session = games.Session(
        kind="ttt",
        vs_bot=vs_bot,
        marks={ctx.owner_id: "X", ctx.peer_id: "O"},
        turn=ctx.owner_id,
    )
    games.start(ctx.owner_id, ctx.chat_id, session)
    who = "против бота" if vs_bot else f"против {ctx.peer_name}"
    await ctx.replace(
        f"<b>Крестики-нолики</b> · {who}\n\n{games.render(session.board)}\n\n"
        f"Вы ❌, ход ваш.\n{TTT_HINT}",
        html=True,
    )


@command("кнб", "камень", group="азарт", about="камень-ножницы-бумага с собеседником")
async def cmd_rps(ctx: Ctx) -> None:
    games.start(ctx.owner_id, ctx.chat_id, games.Session(kind="rps"))
    await ctx.replace(
        "<b>Камень-ножницы-бумага</b>\n\nОба напишите свой ход обычным "
        "сообщением: <code>камень</code>, <code>ножницы</code> или "
        "<code>бумага</code>. Ход видно только когда оба определились.",
        html=True,
    )


@command("стоп", "хватит", group="азарт", about="прекратить партию")
async def cmd_stop(ctx: Ctx) -> None:
    if games.session(ctx.owner_id, ctx.chat_id) is None:
        await ctx.fail("в этом чате нет активной партии")
        return
    games.stop(ctx.owner_id, ctx.chat_id)
    await ctx.replace("Партия прекращена.")


@command("табло", "счет", group="азарт", about="счёт игр в этом чате")
async def cmd_score(ctx: Ctx) -> None:
    rows = await db.scores_of(ctx.owner_id, ctx.chat_id)
    if not rows:
        await ctx.fail("в этом чате ещё не играли")
        return
    titles = {"duel": "Дуэли", "ttt": "Крестики", "rps": "Камень-ножницы-бумага"}
    lines = ["<b>Счёт в этом чате</b>", ""]
    for row in rows:
        title = titles.get(row["game"], row["game"])
        lines.append(
            f"{title}: <b>{row['wins']}</b> : <b>{row['losses']}</b>"
            + (f" · ничьих {row['draws']}" if row["draws"] else "")
        )
    await ctx.replace("\n".join(lines), html=True)


# --------------------------------------------------------------------------
# Ходы обычными сообщениями
# --------------------------------------------------------------------------


async def handle_move(
    bot: Bot,
    conn_id: str,
    owner_id: int,
    chat_id: int,
    sender_id: int,
    text: str,
    *,
    owner_name: str,
    peer_name: str,
) -> bool:
    """Разобрать сообщение как ход в партии.

    Возвращает True, если сообщение было ходом — тогда автоответчик его
    уже не трогает: отвечать правилом на «5» посреди партии не нужно.
    """
    session = games.session(owner_id, chat_id)
    if session is None:
        return False
    if session.kind == "ttt":
        return await _ttt_move(
            bot, conn_id, owner_id, chat_id, sender_id, text, session,
            owner_name=owner_name, peer_name=peer_name,
        )
    if session.kind == "rps":
        return await _rps_move(
            bot, conn_id, owner_id, chat_id, sender_id, text, session,
            owner_name=owner_name, peer_name=peer_name,
        )
    return False


async def _ttt_move(
    bot: Bot,
    conn_id: str,
    owner_id: int,
    chat_id: int,
    sender_id: int,
    text: str,
    session: games.Session,
    *,
    owner_name: str,
    peer_name: str,
) -> bool:
    cell = games.cell_read(text)
    if cell is None:
        return False

    mark = session.marks.get(sender_id)
    if mark is None:
        # Сообщение от кого-то, кого в партии нет (например, владелец
        # начал партию «против бота», а пишет собеседник).
        return False
    if session.turn != sender_id:
        await _say(bot, conn_id, chat_id, "Сейчас не ваш ход.")
        return True
    if session.board[cell] != games.EMPTY:
        await _say(bot, conn_id, chat_id, "Клетка занята, выберите другую.")
        return True

    session.board[cell] = mark
    session.touch()

    done = await _ttt_finish(bot, conn_id, owner_id, chat_id, session,
                             owner_name=owner_name, peer_name=peer_name)
    if done:
        return True

    if session.vs_bot:
        move = games.best_move(session.board, session.bot_mark)
        if move >= 0:
            await asyncio.sleep(0.9)
            session.board[move] = session.bot_mark
            done = await _ttt_finish(bot, conn_id, owner_id, chat_id, session,
                                     owner_name=owner_name, peer_name=peer_name)
            if done:
                return True
        session.turn = owner_id
    else:
        others = [i for i in session.marks if i != sender_id]
        session.turn = others[0] if others else sender_id

    turn_name = owner_name if session.turn == owner_id else peer_name
    await _say(
        bot, conn_id, chat_id,
        f"{games.render(session.board)}\n\nХод: <b>{turn_name}</b>",
    )
    return True


async def _ttt_finish(
    bot: Bot,
    conn_id: str,
    owner_id: int,
    chat_id: int,
    session: games.Session,
    *,
    owner_name: str,
    peer_name: str,
) -> bool:
    """Если партия закончилась — объявить итог и убрать её."""
    won = games.winner(session.board)
    if won is None and not games.full(session.board):
        return False

    if won is None:
        result, tail = "draw", "Ничья."
    else:
        owner_mark = session.marks.get(owner_id, "X")
        owner_won = won == owner_mark
        if session.vs_bot:
            owner_won = won == owner_mark
            name = owner_name if owner_won else "Бот"
        else:
            name = owner_name if owner_won else peer_name
        result = "win" if owner_won else "loss"
        tail = f"Победил <b>{name}</b> ({games.MARKS[won]})."

    await db.bump_score(owner_id, chat_id, "ttt", result)
    games.stop(owner_id, chat_id)
    await _say(bot, conn_id, chat_id, f"{games.render(session.board)}\n\n{tail}")
    return True


async def _rps_move(
    bot: Bot,
    conn_id: str,
    owner_id: int,
    chat_id: int,
    sender_id: int,
    text: str,
    session: games.Session,
    *,
    owner_name: str,
    peer_name: str,
) -> bool:
    pick = games.rps_read(text)
    if pick is None:
        return False
    if sender_id in session.picks:
        await _say(bot, conn_id, chat_id, "Ваш ход уже принят, ждём второго.")
        return True

    session.picks[sender_id] = pick
    session.touch()
    if len(session.picks) < 2:
        await _say(bot, conn_id, chat_id, "Принято. Ждём второго игрока…")
        return True

    ids = list(session.picks)
    a, b = ids[0], ids[1]
    pick_a, pick_b = session.picks[a], session.picks[b]
    name_a = owner_name if a == owner_id else peer_name
    name_b = owner_name if b == owner_id else peer_name
    outcome = games.rps_beats(pick_a, pick_b)

    if outcome == 0:
        tail, result = "Ничья.", "draw"
    else:
        win_id = a if outcome == 1 else b
        win_name = name_a if outcome == 1 else name_b
        tail = f"Победил <b>{win_name}</b>."
        result = "win" if win_id == owner_id else "loss"

    await db.bump_score(owner_id, chat_id, "rps", result)
    games.stop(owner_id, chat_id)
    await _say(
        bot, conn_id, chat_id,
        f"{games.RPS_ICONS[pick_a]} {name_a} — {pick_a}\n"
        f"{games.RPS_ICONS[pick_b]} {name_b} — {pick_b}\n\n{tail}",
    )
    return True
