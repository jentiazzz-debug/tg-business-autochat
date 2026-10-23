"""Команды сейв-мода и таймеров.

След: «.удалённые» и «.правки» поднимают историю по текущему чату из
журнала trail — карточка в личке приходит один раз, а спросить «что он
там удалял вчера» хочется и потом. «.сохрани» ответом на сообщение
кладёт его копию владельцу в личку — до того, как собеседник передумает.

Время: напоминания себе и отложенные сообщения в чат. Сроки хранятся в
базе (timers.py), так что перезапуск бота их не теряет.
"""

from __future__ import annotations

import html
import time

import db
import texts
import timers
from cmdbase import Ctx, command
from pe import e

#: Сколько событий показывать по умолчанию и максимум.
TRAIL_DEFAULT = 10
TRAIL_MAX = 30
#: Сколько вложений переотправлять за раз — чтобы личка не утонула.
FILES_MAX = 5


def esc(text: object) -> str:
    return html.escape(str(text or ""), quote=False)


def _count(ctx: Ctx) -> int:
    raw = ctx.args.strip()
    if raw.isdigit():
        return max(1, min(int(raw), TRAIL_MAX))
    return TRAIL_DEFAULT


# --------------------------------------------------------------------------
# След
# --------------------------------------------------------------------------


@command(
    "удалённые", "удаленные", "след",
    group="след",
    about="что собеседник удалил в этом чате — вам в личку, с файлами",
    usage="[сколько]",
    example="20",
)
async def cmd_deleted(ctx: Ctx) -> None:
    from business import resend

    await ctx.drop_command()
    rows = await db.trail_of(ctx.owner_id, ctx.chat_id, "del", _count(ctx))
    if not rows:
        await ctx.to_owner(
            f"{e('trash')} <b>{esc(ctx.peer_name)}</b> ничего не удалял — или "
            "удалял до подключения бота / раньше срока хранения архива."
        )
        return
    lines = [f"{e('trash')} <b>Удалённое</b> · {esc(ctx.peer_name)} · {len(rows)}", ""]
    for row in rows:
        body = esc(texts.short(row["text"] or "", 300))
        kind = row["kind"]
        label = "" if kind == "text" else f" · <i>{texts.KINDS.get(kind, kind)}</i>"
        lines.append(
            f"{texts.kind_icon(kind)} <code>{texts.when(row['at'])}</code>{label}"
            + (f"\n{body}" if body else "")
        )
        lines.append("")
    await ctx.to_owner("\n".join(lines).strip()[:4000])
    files = [r for r in rows if r["file_id"]][-FILES_MAX:]
    for row in files:
        await resend(ctx.bot, ctx.owner_chat_id, row["kind"], row["file_id"])


@command(
    "правки", "изменения",
    group="след",
    about="что собеседник переписывал в этом чате: было → стало",
    usage="[сколько]",
)
async def cmd_edits(ctx: Ctx) -> None:
    await ctx.drop_command()
    rows = await db.trail_of(ctx.owner_id, ctx.chat_id, "edit", _count(ctx))
    if not rows:
        await ctx.to_owner(f"{e('edit')} <b>{esc(ctx.peer_name)}</b> ничего не переписывал.")
        return
    lines = [f"{e('edit')} <b>Правки</b> · {esc(ctx.peer_name)} · {len(rows)}", ""]
    for row in rows:
        lines.append(
            f"<code>{texts.when(row['at'])}</code>\n"
            f"<b>было:</b> {esc(texts.short(row['before'] or '', 200)) or '<i>пусто</i>'}\n"
            f"<b>стало:</b> {esc(texts.short(row['text'] or '', 200)) or '<i>пусто</i>'}"
        )
        lines.append("")
    await ctx.to_owner("\n".join(lines).strip()[:4000])


@command(
    "сохрани", "сейв",
    group="след",
    about="ответом на сообщение — копия вам в личку, даже если его потом удалят",
)
async def cmd_save(ctx: Ctx) -> None:
    from business import extract, resend

    if ctx.reply is None:
        await ctx.fail("ответьте этой командой на сообщение, которое нужно сохранить")
        return
    await ctx.drop_command()
    kind, text, file_id = extract(ctx.reply)
    author = ctx.reply.from_user.full_name if ctx.reply.from_user else ctx.peer_name
    stamp = texts.when(int(ctx.reply.date.timestamp()))
    head = (
        f"{e('save')} <b>Сохранено</b> · {esc(author)}\n"
        f"<code>{stamp}</code> · из чата с {esc(ctx.peer_name)}"
    )
    body = f"\n\n{esc(text)}" if text else ""
    await ctx.to_owner((head + body)[:4000])
    if file_id:
        await resend(ctx.bot, ctx.owner_chat_id, kind, file_id)


# --------------------------------------------------------------------------
# Время
# --------------------------------------------------------------------------

SPAN_HELP = (
    "срок пишется так: <code>30с</code>, <code>10м</code>, <code>2ч</code>, "
    "<code>1д</code>, <code>1ч30м</code>; число без букв — минуты"
)


async def _room(ctx: Ctx) -> bool:
    if await db.count_timers(ctx.owner_id) >= db.MAX_TIMERS:
        await ctx.fail(
            f"таймеров уже {db.MAX_TIMERS} — отмените лишние: <code>.таймеры</code>"
        )
        return False
    return True


@command(
    "напомни", "напоминание",
    group="время",
    about="напоминание вам в личку через заданное время",
    usage="время текст",
    example="1ч перезвонить ему",
)
async def cmd_remind(ctx: Ctx) -> None:
    span, text = timers.split_span(ctx.args)
    if span is None or not text:
        await ctx.fail(f"формат: <code>.напомни 1ч перезвонить</code> — {SPAN_HELP}")
        return
    if not await _room(ctx):
        return
    timer_id = await db.add_timer(
        ctx.owner_id,
        int(time.time()) + span,
        "remind",
        chat_id=ctx.chat_id,
        title=ctx.peer_name,
        text=text[:900],
    )
    await ctx.drop_command()
    await ctx.to_owner(
        f"{e('alarm')} Напомню через <b>{timers.span_words(span)}</b> "
        f"<i>(#{timer_id})</i>:\n\n{esc(text[:900])}"
    )


@command(
    "отложи", "позже",
    group="время",
    about="отправить сообщение в этот чат от вашего имени через время",
    usage="время текст",
    example="20м я подъехал",
    needs=("can_reply",),
)
async def cmd_later(ctx: Ctx) -> None:
    span, text = timers.split_span(ctx.args)
    if span is None or not text:
        await ctx.fail(f"формат: <code>.отложи 20м я подъехал</code> — {SPAN_HELP}")
        return
    if not await _room(ctx):
        return
    timer_id = await db.add_timer(
        ctx.owner_id,
        int(time.time()) + span,
        "send",
        chat_id=ctx.chat_id,
        conn_id=ctx.conn_id,
        title=ctx.peer_name,
        text=text[:4000],
    )
    await ctx.drop_command()
    await ctx.to_owner(
        f"{e('send')} Через <b>{timers.span_words(span)}</b> в чат с "
        f"<b>{esc(ctx.peer_name)}</b> уйдёт <i>(#{timer_id})</i>:\n\n{esc(text[:900])}\n\n"
        f"<i>Отменить — <code>.отмени {timer_id}</code></i>"
    )


@command("таймеры", "очередь", group="время", about="ваши напоминания и отложенные — список в личку")
async def cmd_timers(ctx: Ctx) -> None:
    await ctx.drop_command()
    rows = await db.timers_of(ctx.owner_id)
    if not rows:
        await ctx.to_owner(f"{e('timer')} Таймеров нет.")
        return
    now = int(time.time())
    lines = [f"{e('timer')} <b>Таймеры</b> · {len(rows)}", ""]
    for row in rows:
        icon = e("alarm") if row["action"] == "remind" else e("send")
        what = "напоминание" if row["action"] == "remind" else f"в чат с {esc(row['title'])}"
        lines.append(
            f"{icon} <b>#{row['id']}</b> · через {timers.span_words(max(row['due'] - now, 0))} · {what}\n"
            f"<i>{esc(texts.short(row['text'] or '', 80))}</i>"
        )
    lines += ["", "<i>Отменить — <code>.отмени номер</code></i>"]
    await ctx.to_owner("\n".join(lines))


@command("отмени", "отмена", group="время", about="отменить таймер по номеру", usage="номер", example="12")
async def cmd_cancel(ctx: Ctx) -> None:
    raw = ctx.args.strip().lstrip("#")
    if not raw.isdigit():
        await ctx.fail("укажите номер таймера — список в <code>.таймеры</code>")
        return
    gone = await db.drop_timer(ctx.owner_id, int(raw))
    await ctx.drop_command()
    await ctx.to_owner(
        f"{e('check')} Таймер #{raw} отменён." if gone else f"{e('cross')} Таймера #{raw} нет."
    )
