"""Преобразования текста для команд в чате.

Здесь только чистые функции: строка на входе, строка на выходе. Ни
Telegram, ни базы — поэтому весь набор гоняется в selfcheck.py и любую
новую стилизацию видно сразу, без запуска бота.

Главное отличие от чужих наборов: всё, что можно, работает **с русским
текстом**. Юникод-шрифты (𝓼𝓬𝓻𝓲𝓹𝓽, ᴀʙᴄ, ⓐ) физически существуют только
для латиницы — в Unicode нет ни рукописной, ни капительной кириллицы, и
никакой бот это не обойдёт. Поэтому такие стили помечены LATIN и честно
говорят об этом в справке, а вместо них для русского есть свои:
разрядка, залго, хлопки, случайный регистр, лит, транслит, смена
раскладки и увуфикация — они кириллицу обрабатывают полноценно.
"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable

# --------------------------------------------------------------------------
# Раскладка клавиатуры
# --------------------------------------------------------------------------

#: ЙЦУКЕН против QWERTY, посимвольно. Порядок обоих рядов совпадает,
#: поэтому одну строку можно превратить в другую простой заменой.
_RU_LOWER = "йцукенгшщзхъфывапролджэячсмитьбю.ё"
_EN_LOWER = "qwertyuiop[]asdfghjkl;'zxcvbnm,./`"
_RU_UPPER = "ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,Ё"
_EN_UPPER = 'QWERTYUIOP{}ASDFGHJKL:"ZXCVBNM<>?~'

_TO_EN = str.maketrans(_RU_LOWER + _RU_UPPER, _EN_LOWER + _EN_UPPER)
_TO_RU = str.maketrans(_EN_LOWER + _EN_UPPER, _RU_LOWER + _RU_UPPER)


def has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[а-яёА-ЯЁ]", text))


def switch_layout(text: str) -> str:
    """«Ghbdtn» → «Привет» и обратно.

    Направление выбирается по тексту: если кириллицы больше, значит
    печатали в русской раскладке латиницу. Ошибиться тут не страшно —
    команда обратима, повторный вызов вернёт как было.
    """
    cyr = len(re.findall(r"[а-яёА-ЯЁ]", text))
    lat = len(re.findall(r"[a-zA-Z]", text))
    return text.translate(_TO_EN if cyr > lat else _TO_RU)


# --------------------------------------------------------------------------
# Транслит и лит
# --------------------------------------------------------------------------

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

#: Кириллица похожими латинскими буквами: «писать как дебил».
_LEET = {
    "а": "a", "б": "b", "в": "b", "г": "r", "д": "d", "е": "e", "ё": "e",
    "ж": "x", "з": "3", "и": "u", "й": "u", "к": "k", "л": "l", "м": "m",
    "н": "h", "о": "o", "п": "n", "р": "p", "с": "c", "т": "m", "у": "y",
    "ф": "f", "х": "x", "ц": "u", "ч": "4", "ш": "w", "щ": "w", "ъ": "b",
    "ы": "bl", "ь": "b", "э": "e", "ю": "io", "я": "9",
    "a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù",
}

#: Чем разбавлять лит, чтобы он не выглядел таблицей замен.
_LEET_SALT = {"a": "à", "e": "è", "o": "ò", "u": "ù", "i": "ì", "c": "ç"}


def _keep_case(src: str, out: str) -> str:
    """Вернуть регистр исходной буквы результату замены."""
    return out.upper() if src.isupper() else out


def translit(text: str) -> str:
    """Кириллица латиницей по чтению: «привет» → «privet»."""
    out = []
    for ch in text:
        low = ch.lower()
        if low in _TRANSLIT:
            out.append(_keep_case(ch, _TRANSLIT[low]))
        else:
            out.append(ch)
    return "".join(out)


def leet(text: str) -> str:
    """«писать как дебил» → «nucamb kak debul»."""
    out = []
    for ch in text:
        low = ch.lower()
        if low in _LEET:
            out.append(_keep_case(ch, _LEET[low]))
        else:
            out.append(ch)
    salted = []
    for ch in "".join(out):
        # Каждая шестая подходящая буква получает диакритику: так текст
        # выглядит кривым, а не механически подменённым.
        if ch in _LEET_SALT and random.random() < 0.18:
            salted.append(_LEET_SALT[ch])
        else:
            salted.append(ch)
    return "".join(salted)


# --------------------------------------------------------------------------
# Игры с формой: работают и с кириллицей
# --------------------------------------------------------------------------


def spaced(text: str) -> str:
    """р а з р я д к а."""
    return " ".join(text)


def wide(text: str) -> str:
    """Разрядка с сохранением слов: «п р и в е т   м и р»."""
    return "   ".join(" ".join(word) for word in text.split())


def sponge(text: str) -> str:
    """сЛуЧаЙнЫй РеГиСтР — работает с русским как есть."""
    return "".join(
        ch.upper() if random.random() < 0.5 else ch.lower() for ch in text
    )


def reverse(text: str) -> str:
    """«привет» → «тевирп»."""
    return text[::-1]


#: Метки для залго берутся только те, у которых ненулевой класс
#: комбинирования. В диапазоне есть символы вроде U+034F, которые
#: формально не комбинирующие: они невидимы, но «.очисти» их снять не
#: может, и текст остаётся с невыводимым мусором внутри.
_ZALGO = [
    chr(c) for c in range(0x0300, 0x0370) if unicodedata.combining(chr(c))
]


def zalgo(text: str, power: int = 3) -> str:
    """з̸̛а̷͝л̶̡г̴̀о̵͢ — комбинирующие метки поверх букв."""
    out = []
    for ch in text:
        out.append(ch)
        if ch.strip():
            out.extend(random.choice(_ZALGO) for _ in range(random.randint(1, power)))
    return "".join(out)


def clap(text: str, mark: str = "👏") -> str:
    """👏 хлопки 👏 между 👏 словами."""
    words = text.split()
    if not words:
        return text
    return f" {mark} ".join(words)


def hearts(text: str) -> str:
    return clap(text, "❤️")


def uwu(text: str) -> str:
    """Увуфикация по-русски: «привет» → «пвивет~».

    Латинский uwu меняет r и l на w. В русском тот же детский выговор
    даёт замена р и л на в — иначе на кириллице команда просто ничего не
    делала бы, как у чужих ботов.
    """
    out = []
    for ch in text:
        low = ch.lower()
        if low in ("р", "л"):
            out.append(_keep_case(ch, "в"))
        elif low in ("r", "l"):
            out.append(_keep_case(ch, "w"))
        else:
            out.append(ch)
    result = "".join(out)
    tail = random.choice((" ~", " uwu", " owo", " >_<", " ^^", ""))
    return result + tail


def stutter(text: str) -> str:
    """З-заикание: первая буква слова удваивается через дефис.

    Если рандом не зацепил ни одного слова, заикание ставится
    принудительно на первое подходящее: команда, которая иногда
    возвращает текст без изменений, выглядит сломанной.
    """
    words = text.split()
    out: list[str] = []
    touched = False
    for word in words:
        if len(word) > 2 and word[0].isalpha() and random.random() < 0.6:
            out.append(f"{word[0]}-{word}")
            touched = True
        else:
            out.append(word)
    if not touched:
        for i, word in enumerate(out):
            if len(word) > 2 and word[0].isalpha():
                out[i] = f"{word[0]}-{word}"
                break
    return " ".join(out)


# --------------------------------------------------------------------------
# Юникод-шрифты: только латиница, кириллица остаётся как была
# --------------------------------------------------------------------------


def _shift(text: str, upper_base: int, lower_base: int, digit_base: int | None = None) -> str:
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(upper_base + ord(ch) - ord("A")))
        elif "a" <= ch <= "z":
            out.append(chr(lower_base + ord(ch) - ord("a")))
        elif digit_base is not None and ch.isdigit():
            out.append(chr(digit_base + int(ch)))
        else:
            out.append(ch)
    return "".join(out)


#: Берутся именно жирные варианты математических шрифтов. В обычных
#: Script и Fraktur часть букв (B, E, F, H, I, L, M, R, e, g, o и другие)
#: вынесена в отдельный блок Letterlike Symbols, и наивный сдвиг
#: попадает в незанятые позиции — вместо буквы у человека появляется
#: пустой квадрат. В жирных блоках дырок нет.
def cursive(text: str) -> str:
    """𝓻𝓾𝓴𝓸𝓹𝓲𝓼𝓷𝓸𝓮 — математический скрипт (латиница)."""
    return _shift(text, 0x1D4D0, 0x1D4EA)


def fraktur(text: str) -> str:
    """𝖌𝖔𝖙𝖎𝖐𝖆 (латиница)."""
    return _shift(text, 0x1D56C, 0x1D586)


def monowide(text: str) -> str:
    """𝚖𝚘𝚗𝚘𝚜𝚙𝚊𝚌𝚎 юникодом (латиница и цифры)."""
    return _shift(text, 0x1D670, 0x1D68A, 0x1D7F6)


def bubble(text: str) -> str:
    """ⓑⓤⓑⓑⓛⓔ (латиница)."""
    return _shift(text, 0x24B6, 0x24D0)


def smallcaps(text: str) -> str:
    """ᴋᴀᴘɪᴛᴇʟ (латиница)."""
    table = {
        "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ", "g": "ɢ",
        "h": "ʜ", "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ",
        "o": "ᴏ", "p": "ᴘ", "q": "q", "r": "ʀ", "s": "s", "t": "ᴛ", "u": "ᴜ",
        "v": "ᴠ", "w": "ᴡ", "x": "x", "y": "ʏ", "z": "ᴢ",
    }
    return "".join(table.get(ch.lower(), ch) for ch in text)


def vapor(text: str) -> str:
    """ｖａｐｏｒｗａｖｅ — полноширинные знаки (латиница, цифры, пробел)."""
    out = []
    for ch in text:
        code = ord(ch)
        if 0x21 <= code <= 0x7E:
            out.append(chr(code + 0xFEE0))
        elif ch == " ":
            out.append("　")
        else:
            out.append(ch)
    return "".join(out)


_FLIP = {
    "a": "ɐ", "b": "q", "c": "ɔ", "d": "p", "e": "ǝ", "f": "ɟ", "g": "ƃ",
    "h": "ɥ", "i": "ᴉ", "j": "ɾ", "k": "ʞ", "l": "l", "m": "ɯ", "n": "u",
    "o": "o", "p": "d", "q": "b", "r": "ɹ", "s": "s", "t": "ʇ", "u": "n",
    "v": "ʌ", "w": "ʍ", "x": "x", "y": "ʎ", "z": "z",
    "а": "ɐ", "б": "ƍ", "в": "ʚ", "г": "ɹ", "е": "ǝ", "и": "и", "к": "ʞ",
    "л": "v", "м": "w", "н": "н", "о": "о", "п": "u", "р": "d", "с": "ɔ",
    "т": "ɯ", "у": "ʎ", "ф": "ф", "х": "х", "ч": "һ", "ь": "q", "э": "є",
    "?": "¿", "!": "¡", ".": "˙", ",": "'", "(": ")", ")": "(",
    "[": "]", "]": "[", "1": "Ɩ", "2": "ᄅ", "3": "Ɛ", "4": "ㄣ", "5": "ϛ",
    "6": "9", "7": "ㄥ", "9": "6", "&": "⅋", "_": "‾",
}


def upside(text: str) -> str:
    """ʇxǝʇ ʎʞɔɐʌǝdǝu — перевёрнутый текст, часть кириллицы тоже."""
    return "".join(_FLIP.get(ch.lower(), ch) for ch in reversed(text))


def emojify(text: str) -> str:
    """Латинские буквы региональными индикаторами (флажковые буквы).

    Если латиницы и цифр в тексте нет, возвращаем его как был: иначе
    русское слово просто разъезжалось пробелами, притворяясь, что
    команда сработала.
    """
    if not any(("a" <= ch.lower() <= "z") or ch.isdigit() for ch in text):
        return text
    out = []
    for ch in text:
        if "a" <= ch.lower() <= "z":
            out.append(chr(0x1F1E6 + ord(ch.lower()) - ord("a")))
        elif ch.isdigit():
            out.append(f"{ch}️⃣")
        else:
            out.append(ch)
    return " ".join(out)


def strip_marks(text: str) -> str:
    """Снять диакритику и невидимые метки — «очистить» чужой залго."""
    normalized = unicodedata.normalize("NFD", text)
    cleaned = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", cleaned)


# --------------------------------------------------------------------------
# Роли: текст отвечает в характере
# --------------------------------------------------------------------------

_KAWAII = ("(・ω・)", "(=^･ω･^=)", "(´｡• ω •｡`)", "٩(◕‿◕)۶", "(◍•ᴗ•◍)", "(⁄ ⁄•⁄ω⁄•⁄ ⁄)")
_TSUNDERE_PRE = ("Б-бака! ", "Х-хмф. ", "Н-не то чтобы мне было важно, но ", "Ч-что?! ")
_TSUNDERE_POST = (
    " ...и не подумай, что мне это нужно!",
    " Б-баka, не пойми неправильно!",
    " ...хмф.",
    " Не то чтобы я о тебе думала!",
)
_YANDERE_PRE = ("Ня~ ", "Хи-хи~ ", "Любимый~ ", "")
_YANDERE_POST = (
    " ...ты ведь никуда не уйдёшь? ♡",
    " Я знаю, где ты. ♡",
    " Только мой. Навсегда. ♡",
    " ...не заставляй меня волноваться. ♡",
)


def kawaii(text: str) -> str:
    return f"{text} {random.choice(_KAWAII)}"


def tsundere(text: str) -> str:
    return random.choice(_TSUNDERE_PRE) + stutter(text) + random.choice(_TSUNDERE_POST)


def yandere(text: str) -> str:
    return random.choice(_YANDERE_PRE) + text + random.choice(_YANDERE_POST)


# --------------------------------------------------------------------------
# Реестр: из него собираются команды и справка
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Style:
    fn: Callable[[str], str]
    title: str
    #: Результат уже содержит HTML-разметку и уходит с parse_mode=HTML.
    html: bool = False
    #: Работает только с латиницей — в справке об этом пишется прямо.
    latin: bool = False


def _wrap(tag: str) -> Callable[[str], str]:
    def inner(text: str) -> str:
        import html as _h

        return f"<{tag}>{_h.escape(text, quote=False)}</{tag}>"

    return inner


STYLES: dict[str, Style] = {
    # Разметка Telegram
    "bold": Style(_wrap("b"), "жирный", html=True),
    "italic": Style(_wrap("i"), "курсив", html=True),
    "mono": Style(_wrap("code"), "моноширинный", html=True),
    "under": Style(_wrap("u"), "подчёркнутый", html=True),
    "strike": Style(_wrap("s"), "зачёркнутый", html=True),
    "spoiler": Style(_wrap("tg-spoiler"), "под спойлером", html=True),
    "quote": Style(_wrap("blockquote"), "цитата", html=True),
    "code": Style(_wrap("pre"), "блок кода", html=True),
    # Русский текст
    "sw": Style(switch_layout, "сменить раскладку"),
    "leet": Style(leet, "nucamb kak debul"),
    "translit": Style(translit, "транслитом"),
    "space": Style(wide, "р а з р я д к а"),
    "zalgo": Style(zalgo, "з̷а̶л̷г̸о̶"),
    "clap": Style(clap, "👏 хлопки 👏"),
    "hearts": Style(hearts, "❤️ сердечки"),
    "sponge": Style(sponge, "сЛуЧаЙнЫй РеГиСтР"),
    "rev": Style(reverse, "тевирп"),
    "upside": Style(upside, "ʇxǝʇ ʎʞɔɐʌǝdǝu"),
    "uwu": Style(uwu, "пвивет~"),
    "stutter": Style(stutter, "з-заикание"),
    "clean": Style(strip_marks, "снять диакритику и залго"),
    "upper": Style(str.upper, "ВЕРХНИЙ РЕГИСТР"),
    "lower": Style(str.lower, "нижний регистр"),
    # Роли
    "kawaii": Style(kawaii, "kawaii-режим"),
    "tsundere": Style(tsundere, "цундере-режим"),
    "yandere": Style(yandere, "яндере-режим"),
    # Юникод-шрифты: латиница
    "cursive": Style(cursive, "𝓻𝓾𝓴𝓸𝓹𝓲𝓼𝓷𝓸", latin=True),
    "fraktur": Style(fraktur, "𝖌𝖔𝖙𝖎𝖐𝖆", latin=True),
    "monowide": Style(monowide, "𝚖𝚘𝚗𝚘", latin=True),
    "bubble": Style(bubble, "ⓑⓤⓑⓑⓛⓔ", latin=True),
    "small": Style(smallcaps, "ᴋᴀᴘɪᴛᴇʟ", latin=True),
    "vapor": Style(vapor, "ｖａｐｏｒ", latin=True),
    "emoji": Style(emojify, "🇧🇺🇰🇻🇾", latin=True),
}
