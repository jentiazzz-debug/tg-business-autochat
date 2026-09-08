"""Команды текста: стилизация и анимации.

Стилизации не перечисляются руками — они собираются из styling.STYLES,
поэтому новый стиль достаточно добавить туда и в таблицу имён ниже.

Имена команд только русские: полное и короткое — «.жирный» и «.ж». В
чужих наборах команды латинские, и чтобы набрать «.bold» посреди
русской переписки, приходится дважды переключать раскладку. Здесь
переключаться не нужно ни разу.

Анимации работают правкой уже отправленного сообщения. Кадров немного
намеренно: каждая правка — отдельный запрос к Telegram, и «плавная»
анимация на сорок кадров упирается в лимиты, после чего половина правок
просто не доезжает.
"""

from __future__ import annotations

import asyncio
import random

import styling
from cmdbase import Ctx, command

#: Имена команд для каждого стиля: полное и короткое. Первое идёт в
#: справку, второе — для тех, кто печатает быстро.
NAMES: dict[str, tuple[str, ...]] = {
    "bold": ("жирный", "ж"),
    "italic": ("курсив", "кур"),
    "mono": ("моно", "мн"),
    "under": ("подчерк", "пч"),
    "strike": ("зачерк", "зч"),
    "spoiler": ("спойлер", "сп"),
    "quote": ("цитата", "цит"),
    "code": ("код",),
    "sw": ("раскладка", "рас"),
    "leet": ("лит",),
    "translit": ("транслит", "тлт"),
    "space": ("разрядка", "рзр"),
    "zalgo": ("залго", "жуть"),
    "clap": ("хлопки", "хлоп"),
    "hearts": ("сердечки", "серд"),
    "sponge": ("вжирегистр", "вжр"),
    "rev": ("наоборот", "нао"),
    "upside": ("вверхногами", "вниз"),
    "uwu": ("уву",),
    "stutter": ("заикание", "заик"),
    "clean": ("очисти", "оч"),
    "upper": ("крик", "капс"),
    "lower": ("шепот", "тише"),
    "kawaii": ("кавай",),
    "tsundere": ("цундере", "цун"),
    "yandere": ("яндере", "янд"),
    "cursive": ("рукопись", "рук"),
    "fraktur": ("готика", "гот"),
    "monowide": ("печатная", "пчт"),
    "bubble": ("кружки", "круж"),
    "small": ("капитель", "кап"),
    "vapor": ("вапор", "вап"),
    "emoji": ("флажки", "флаг"),
}


def _make(style_key: str, style: styling.Style):
    async def run(ctx: Ctx) -> None:
        source = ctx.text()
        if not source:
            await ctx.fail(
                "нужен текст: напишите его после команды или примените "
                "команду ответом на своё сообщение"
            )
            return
        result = style.fn(source)
        if style.latin and styling.has_cyrillic(source) and result == source:
            await ctx.fail(
                f"стиль «{style.title}» существует в Unicode только для "
                "латиницы — кириллицу им не набрать. Для русского есть "
                "разрядка, залго, лит, регистр и транслит."
            )
            return
        await ctx.replace(result, html=style.html)

    return run


def _register_styles() -> None:
    for key, style in styling.STYLES.items():
        names = NAMES.get(key)
        if not names:
            continue
        about = style.title + (" · латиница" if style.latin else "")
        command(
            *names,
            group="слово",
            about=about,
            usage="текст",
        )(_make(key, style))


_register_styles()


# --------------------------------------------------------------------------
# Анимации
# --------------------------------------------------------------------------

#: Пауза между кадрами и предел кадров — держат анимацию в пределах
#: лимитов Telegram на правку одного сообщения.
FRAME_PAUSE = 0.55
MAX_FRAMES = 14


async def _play(ctx: Ctx, frames: list[str], *, html: bool = False) -> None:
    """Проиграть кадры правками одного сообщения."""
    if not frames:
        return
    await ctx.drop_command()
    message = await ctx.send(frames[0], html=html)
    if message is None:
        return
    for frame in frames[1:]:
        await asyncio.sleep(FRAME_PAUSE)
        if not await ctx.edit(message, frame, html=html):
            # Правку не пропустили (нет права или сообщение уже не то) —
            # дальше анимация всё равно не пойдёт, останавливаемся на
            # том кадре, что уже виден.
            return


def _thin(items: list[str], limit: int = MAX_FRAMES) -> list[str]:
    """Прорядить кадры, оставив первый и последний."""
    if len(items) <= limit:
        return items
    step = len(items) / (limit - 1)
    picked = [items[int(i * step)] for i in range(limit - 1)]
    picked.append(items[-1])
    return picked


@command("печать", "пиши", group="кадры", about="набор текста по буквам", usage="текст")
async def cmd_type(ctx: Ctx) -> None:
    text = ctx.text()
    if not text:
        await ctx.fail("нужен текст")
        return
    frames = [text[: i + 1] + "▌" for i in range(len(text))]
    frames = _thin(frames)
    frames.append(text)
    await _play(ctx, frames)


@command("любовь", "люблю", group="кадры", about="растущее сердце ❤️")
async def cmd_love(ctx: Ctx) -> None:
    stages = ["🤍", "💗", "💗💗", "💗💗💗", "❤️❤️❤️", "❤️", "❤️‍🔥"]
    target = ctx.text()
    frames = stages if not target else [f"{s}\n{target}" for s in stages]
    await _play(ctx, frames)


@command("отсчет", "три", group="кадры", about="обратный отсчёт", usage="[текст]")
async def cmd_count(ctx: Ctx) -> None:
    tail = ctx.text() or "поехали!"
    frames = ["3️⃣", "2️⃣", "1️⃣", tail]
    await _play(ctx, frames)


@command("волна", "вол", group="кадры", about="волна по тексту", usage="текст")
async def cmd_wave(ctx: Ctx) -> None:
    text = ctx.text()
    if not text:
        await ctx.fail("нужен текст")
        return
    frames = []
    for i in range(min(len(text), MAX_FRAMES)):
        chars = list(text)
        chars[i] = chars[i].upper()
        frames.append("".join(chars))
    frames.append(text)
    await _play(ctx, frames)


@command("матрица", "шум", group="кадры", about="проявление из шума", usage="текст")
async def cmd_matrix(ctx: Ctx) -> None:
    text = ctx.text()
    if not text:
        await ctx.fail("нужен текст")
        return
    noise = "01#$%&@*+=~"
    frames = []
    for step in range(6):
        shown = int(len(text) * step / 5)
        frames.append(
            text[:shown]
            + "".join(random.choice(noise) for _ in text[shown:])
        )
    frames.append(text)
    await _play(ctx, frames)


@command("тик", "готово", group="кадры", about="галочка после паузы", usage="[текст]")
async def cmd_tick(ctx: Ctx) -> None:
    tail = ctx.text()
    frames = ["⏳", "⌛️", "✅" + (f" {tail}" if tail else "")]
    await _play(ctx, frames)
