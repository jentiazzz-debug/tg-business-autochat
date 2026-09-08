"""Обработка картинок: чистые функции над байтами.

Все функции принимают и возвращают bytes, поэтому их можно прогнать без
Telegram — в selfcheck.py они проверяются на сгенерированной картинке.

Pillow — библиотека синхронная и на большой картинке занимает процессор
на десятки миллисекунд. В боте, который обслуживает много владельцев,
этого достаточно, чтобы подвесить обработку всех остальных апдейтов,
поэтому вызываются они через asyncio.to_thread — см. cmd_media.py.
"""

from __future__ import annotations

import io
import random

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

#: Больше этого по стороне не обрабатываем: входящее фото из Telegram
#: бывает и 2560 пикселей, а на выходе всё равно нужен мем.
MAX_SIDE = 1280


def _open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE))
    return image


def _save(image: Image.Image, quality: int = 88, fmt: str = "JPEG") -> bytes:
    buffer = io.BytesIO()
    if fmt == "JPEG" and image.mode != "RGB":
        image = image.convert("RGB")
    image.save(buffer, format=fmt, quality=quality, optimize=True)
    return buffer.getvalue()


def shakal(data: bytes, passes: int = 3) -> bytes:
    """«Шакал»: несколько кругов пересжатия с низким качеством.

    Один проход с quality=5 даёт просто мягкую картинку. Артефакты,
    которые все узнают, появляются от повторного сжатия уже сжатого —
    поэтому кругов несколько, и между ними картинка ужимается по
    размеру и растягивается обратно.
    """
    image = _open(data)
    for step in range(passes):
        small = image.resize(
            (max(image.width // 2, 32), max(image.height // 2, 32)), Image.BILINEAR
        )
        image = small.resize(image.size, Image.NEAREST)
        image = Image.open(io.BytesIO(_save(image, quality=6 + step * 2)))
    return _save(image, quality=5)


def deepfry(data: bytes) -> bytes:
    """Прожарка: контраст, кислотные цвета, резкость и шум."""
    image = _open(data).convert("RGB")
    image = ImageEnhance.Color(image).enhance(4.0)
    image = ImageEnhance.Contrast(image).enhance(2.6)
    image = ImageEnhance.Sharpness(image).enhance(6.0)
    pixels = image.load()
    for _ in range(int(image.width * image.height * 0.02)):
        x = random.randrange(image.width)
        y = random.randrange(image.height)
        r, g, b = pixels[x, y]
        pixels[x, y] = (min(255, r + 90), max(0, g - 30), max(0, b - 30))
    return _save(image, quality=12)


def pixelate(data: bytes, blocks: int = 40) -> bytes:
    image = _open(data)
    small = image.resize((blocks, max(1, blocks * image.height // image.width)), Image.BILINEAR)
    return _save(small.resize(image.size, Image.NEAREST))


def grayscale(data: bytes) -> bytes:
    return _save(ImageOps.grayscale(_open(data)))


def invert(data: bytes) -> bytes:
    return _save(ImageOps.invert(_open(data).convert("RGB")))


def mirror(data: bytes) -> bytes:
    return _save(ImageOps.mirror(_open(data)))


def blur(data: bytes, radius: int = 6) -> bytes:
    return _save(_open(data).filter(ImageFilter.GaussianBlur(radius)))


def sticker(data: bytes) -> bytes:
    """Фото в стикер: webp, длинная сторона ровно 512.

    Требование Telegram именно такое — 512 по одной из сторон, иначе
    загрузка стикера отклоняется.
    """
    image = _open(data)
    ratio = 512 / max(image.size)
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    image = image.resize(size, Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=92, method=4)
    return buffer.getvalue()


EFFECTS = {
    "shakal": shakal,
    "deepfry": deepfry,
    "pixelate": pixelate,
    "grayscale": grayscale,
    "invert": invert,
    "mirror": mirror,
    "blur": blur,
}
