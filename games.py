"""Логика игр: чистые функции плюс живые партии в памяти.

Разделение здесь не формальное. Правила (кто победил, какой ход лучший,
как разрешается камень-ножницы-бумага) — чистые функции, они гоняются в
selfcheck.py без Telegram. Партии живут в словаре в памяти процесса:
после перезапуска бота они теряются, и это осознанный выбор — партия в
крестики живёт минуты, а тащить её через SQLite значит писать в базу на
каждый ход в каждом чате.

Главная механика, которой нет у чужих ботов: **играть может собеседник**.
Команды бот принимает только от владельца, но входящие сообщения он
читает все. Поэтому партия объявляется командой владельца, а ходы оба
делают обычными сообщениями — «5» или «камень». Никаких кнопок, которые
в бизнес-чатах работают ненадёжно.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Крестики-нолики
# --------------------------------------------------------------------------

EMPTY = " "
#: Клетки нумеруются как на телефонной клавиатуре: 1 — левая верхняя.
LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)

MARKS = {"X": "❌", "O": "⭕️"}
DIGITS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣")


def new_board() -> list[str]:
    return [EMPTY] * 9


def winner(board: list[str]) -> str | None:
    for a, b, c in LINES:
        if board[a] != EMPTY and board[a] == board[b] == board[c]:
            return board[a]
    return None


def full(board: list[str]) -> bool:
    return EMPTY not in board


def render(board: list[str]) -> str:
    """Поле тремя строками; пустые клетки показывают свой номер."""
    rows = []
    for r in range(3):
        cells = []
        for c in range(3):
            i = r * 3 + c
            cells.append(MARKS[board[i]] if board[i] != EMPTY else DIGITS[i])
        rows.append("".join(cells))
    return "\n".join(rows)


def best_move(board: list[str], me: str) -> int:
    """Идеальный ход минимаксом.

    Поле 3×3 перебирается целиком за доли секунды, поэтому «умный»
    противник тут не стоит ничего — зато бота нельзя обыграть, только
    свести вничью, и это честнее случайного хода.
    """
    foe = "O" if me == "X" else "X"

    def score(b: list[str], turn: str, depth: int) -> tuple[int, int]:
        won = winner(b)
        if won == me:
            return 10 - depth, -1
        if won == foe:
            return depth - 10, -1
        if full(b):
            return 0, -1

        best: tuple[int, int] | None = None
        for i in range(9):
            if b[i] != EMPTY:
                continue
            b[i] = turn
            value, _ = score(b, foe if turn == me else me, depth + 1)
            b[i] = EMPTY
            if best is None:
                best = (value, i)
            elif turn == me and value > best[0]:
                best = (value, i)
            elif turn == foe and value < best[0]:
                best = (value, i)
        return best or (0, -1)

    return score(list(board), me, 0)[1]


# --------------------------------------------------------------------------
# Камень-ножницы-бумага
# --------------------------------------------------------------------------

RPS = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}
RPS_ICONS = {"камень": "🪨", "ножницы": "✂️", "бумага": "📄"}
RPS_WORDS = {
    "камень": "камень", "камен": "камень", "к": "камень", "rock": "камень",
    "ножницы": "ножницы", "ножницa": "ножницы", "ножницы!": "ножницы",
    "н": "ножницы", "scissors": "ножницы",
    "бумага": "бумага", "б": "бумага", "paper": "бумага",
}


def rps_read(text: str) -> str | None:
    """Понять ход из обычного сообщения."""
    return RPS_WORDS.get(text.strip().lower().rstrip("!.,"))


def rps_beats(a: str, b: str) -> int:
    """1 — победил a, -1 — победил b, 0 — ничья."""
    if a == b:
        return 0
    return 1 if RPS[a] == b else -1


# --------------------------------------------------------------------------
# Живые партии
# --------------------------------------------------------------------------

#: Партия без ходов столько секунд считается брошенной.
TTL = 600


@dataclass(slots=True)
class Session:
    kind: str                      # ttt | rps
    board: list[str] = field(default_factory=new_board)
    #: Кто ходит: id владельца или id собеседника.
    turn: int = 0
    #: X принадлежит тому, кто начал.
    marks: dict[int, str] = field(default_factory=dict)
    #: Ход бота вместо собеседника.
    vs_bot: bool = False
    bot_mark: str = "O"
    #: Заявки в камень-ножницы-бумага: id -> ход.
    picks: dict[int, str] = field(default_factory=dict)
    started: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)

    def alive(self) -> bool:
        return time.time() - self.touched < TTL

    def touch(self) -> None:
        self.touched = time.time()


_sessions: dict[tuple[int, int], Session] = {}


def key(owner_id: int, chat_id: int) -> tuple[int, int]:
    return owner_id, chat_id


def session(owner_id: int, chat_id: int) -> Session | None:
    """Живая партия в чате, если она есть и не брошена."""
    s = _sessions.get(key(owner_id, chat_id))
    if s is None:
        return None
    if not s.alive():
        _sessions.pop(key(owner_id, chat_id), None)
        return None
    return s


def start(owner_id: int, chat_id: int, s: Session) -> Session:
    _sessions[key(owner_id, chat_id)] = s
    return s


def stop(owner_id: int, chat_id: int) -> None:
    _sessions.pop(key(owner_id, chat_id), None)


def active_count() -> int:
    return sum(1 for s in _sessions.values() if s.alive())


def cell_read(text: str) -> int | None:
    """Понять номер клетки из обычного сообщения: «5», «5!», «5 сюда»."""
    body = text.strip()
    if not body:
        return None
    head = body.split()[0].rstrip("!.,)")
    if len(head) == 1 and head.isdigit() and head != "0":
        return int(head) - 1
    return None


# --------------------------------------------------------------------------
# Мелкий рандом
# --------------------------------------------------------------------------

BALL = (
    "Бесспорно", "Даже не сомневайся", "Определённо да", "Можешь быть уверен",
    "Скорее всего", "Хорошие перспективы", "Знаки говорят «да»", "Да",
    "Пока не ясно, попробуй снова", "Спроси позже", "Лучше не рассказывать",
    "Сейчас нельзя предсказать", "Сосредоточься и спроси опять",
    "Даже не думай", "Мой ответ — нет", "По моим данным — нет",
    "Перспективы не очень", "Очень сомнительно",
)

COIN = ("Орёл 🦅", "Решка 🪙")

DUEL_WEAPONS = (
    "тапком", "клавиатурой", "холодным взглядом", "голосовым на две минуты",
    "стикером с котом", "скриншотом переписки", "мемом из 2007",
    "цитатой из устава", "сообщением «мы можем поговорить?»",
    "внезапным звонком", "гифкой на 40 мегабайт", "кружочком в 6 утра",
)
DUEL_FINISH = (
    "критом с первого удара", "на последнем проценте здоровья",
    "после трёх промахов", "случайно, но эффектно", "чисто и без шансов",
    "затянув на пять раундов", "в самый последний момент",
)


def duel_story(winner_name: str, loser_name: str) -> str:
    return (
        f"⚔️ <b>{winner_name}</b> победил <b>{loser_name}</b> "
        f"{random.choice(DUEL_WEAPONS)} {random.choice(DUEL_FINISH)}."
    )


def chance(question: str) -> int:
    """Устойчивый процент на один и тот же вопрос.

    Случайный ответ на «какова вероятность» разваливает всю шутку: тот
    же вопрос через минуту даёт другое число. Здесь процент считается от
    самого вопроса, поэтому он всегда один и тот же — как будто у бота
    правда есть мнение.
    """
    text = " ".join(question.lower().split())
    if not text:
        return random.randint(0, 100)
    return sum(ord(ch) * (i + 1) for i, ch in enumerate(text)) % 101


def bar(percent: int, width: int = 10) -> str:
    filled = round(percent / 100 * width)
    return "█" * filled + "░" * (width - filled)


def roulette(chambers: int = 6) -> bool:
    """True — выстрел. Шуточная рулетка без ставок."""
    return random.randrange(chambers) == 0
