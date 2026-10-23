"""Команды по картинкам: применяются ответом на фото.

Pillow работает синхронно и на секунду занимает процессор, поэтому
каждая обработка уходит в отдельный поток через asyncio.to_thread.
Иначе один «прожарь» на большой картинке подвешивает обработку
апдейтов у всех владельцев сразу — на общем боте это заметно.

Результат отправляется от имени владельца, а исходное сообщение с
командой убирается: в переписке остаётся только обработанная картинка.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from aiogram.exceptions import TelegramAPIError

from cmdbase import Ctx, command


def _lazy(name: str) -> Callable[..., bytes]:
    """Фильтр из imaging без импорта Pillow на старте.

    Pillow весит десятки мегабайт в памяти, а картиночные команды
    зовут редко — пусть он грузится при первом вызове, а не в каждом
    процессе бота навсегда.
    """

    def run(*args, **kwargs):
        import imaging

        return getattr(imaging, name)(*args, **kwargs)

    return run

log = logging.getLogger("autochat.media")

#: Больше этого не берём: скачивание и обработка десятимегабайтной
#: картинки стоят дороже, чем шутка от её прожарки.
MAX_BYTES = 12 * 1024 * 1024


async def _photo_bytes(ctx: Ctx) -> bytes | None:
    """Байты картинки из сообщения-ответа."""
    reply = ctx.reply
    if reply is None:
        await ctx.fail("примените команду ответом на картинку")
        return None

    file_id = None
    if reply.photo:
        file_id = reply.photo[-1].file_id
    elif reply.sticker and not reply.sticker.is_animated and not reply.sticker.is_video:
        file_id = reply.sticker.file_id
    elif reply.document and (reply.document.mime_type or "").startswith("image/"):
        if (reply.document.file_size or 0) > MAX_BYTES:
            await ctx.fail("картинка слишком большая")
            return None
        file_id = reply.document.file_id

    if file_id is None:
        await ctx.fail("в ответе нет картинки — нужно фото, картинка файлом или обычный стикер")
        return None

    try:
        buffer = await ctx.bot.download(file_id)
    except TelegramAPIError as err:
        await ctx.fail(f"не смог скачать картинку: {err}")
        return None
    if buffer is None:
        await ctx.fail("картинка не скачалась")
        return None
    return buffer.read()


def _make(effect: Callable[[bytes], bytes], caption: str):
    async def run(ctx: Ctx) -> None:
        data = await _photo_bytes(ctx)
        if data is None:
            return
        try:
            result = await asyncio.to_thread(effect, data)
        except Exception as err:  # noqa: BLE001 — Pillow бросает что угодно
            log.warning("обработка %s не удалась: %s", caption, err)
            await ctx.fail("картинка не обработалась — возможно, битый файл")
            return
        await ctx.drop_command()
        await ctx.send_file("photo", result, "p.jpg")

    return run


EFFECT_COMMANDS = (
    (("шакал", "жмых"), _lazy("shakal"), "шакал"),
    (("прожарь", "жар"), _lazy("deepfry"), "прожарка"),
    (("пиксели", "мыло"), _lazy("pixelate"), "пиксели"),
    (("чернобел", "чб"), _lazy("grayscale"), "ч/б"),
    (("негатив", "инверт"), _lazy("invert"), "негатив"),
    (("отрази", "зеркало"), _lazy("mirror"), "зеркало"),
    (("размой", "туман"), _lazy("blur"), "размытие"),
)

for _names, _effect, _title in EFFECT_COMMANDS:
    command(
        *_names,
        group="картинка",
        about=f"{_title} — ответом на фото",
    )(_make(_effect, _title))


@command("стикер", "стик", group="картинка", about="фото в стикер — ответом на фото")
async def cmd_sticker(ctx: Ctx) -> None:
    data = await _photo_bytes(ctx)
    if data is None:
        return
    try:
        webp = await asyncio.to_thread(_lazy("sticker"), data)
    except Exception as err:  # noqa: BLE001
        await ctx.fail(f"не собрался стикер: {err}")
        return
    await ctx.drop_command()
    await ctx.send_file("sticker", webp, "s.webp")
