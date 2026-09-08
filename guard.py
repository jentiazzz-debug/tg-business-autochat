"""Антискам: разбор первых сообщений от незнакомых людей.

Чужие фильтры устроены как список слов: слово нашлось — сообщение
удалено. Такой фильтр либо пропускает половину (спамер пишет «рaбота» с
латинской «a»), либо режет живых людей, которые просто спросили про
работу.

Здесь иначе. Каждый признак даёт очки, и решение принимается по сумме,
которую видно владельцу: «6 очков — заработок, ссылка, кнопки». Ошибку
в такой системе можно понять и поправить порогом, а не гаданием.

Второе отличие — контекст диалога. Коммерческий спам ловится только у
тех, с кем переписки ещё не было: вопрос «сколько стоит?» от давнего
знакомого удалять нельзя. А вот исполняемый файл и просьба прислать код
из СМС ловятся всегда — именно так выглядит взломанный аккаунт друга, и
это самый частый способ увести Telegram.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Расширения, которые в личке присылают только с плохими намерениями.
DANGEROUS = (
    ".exe", ".apk", ".bat", ".cmd", ".com", ".scr", ".msi", ".vbs", ".js",
    ".jar", ".ps1", ".lnk", ".pif", ".reg", ".hta", ".sh",
)

#: Похожие латинские буквы, которыми маскируют русские слова: «рaбота»
#: с латинской «a» мимо обычного списка слов проходит свободно.
_LOOKALIKE = str.maketrans(
    {
        "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
        "b": "ь", "h": "н", "k": "к", "m": "м", "t": "т", "3": "з", "0": "о",
        "4": "ч", "1": "і", "6": "б", "9": "я",
    }
)


def plain(text: str) -> str:
    """Только регистр, ё и пробелы — латиница и цифры целы."""
    return re.sub(r"\s+", " ", text.replace("ё", "е").replace("Ё", "Е").lower())


def folded(text: str) -> str:
    """То же плюс похожие латинские буквы, приведённые к кириллице.

    Спамеры мешают алфавиты в одном слове — «pa6oта» мимо обычного
    списка слов проходит свободно. Свёртка это чинит.

    Но искать по одной свёрнутой строке нельзя: в ней «https» станет
    «нттрс», «usdt» — «усдт», а «5000» — «5ооо», и все латинские и
    числовые признаки перестанут находиться вообще. Поэтому каждое
    правило проверяется по двум строкам сразу — см. _hit().
    """
    return plain(text).translate(_LOOKALIKE)


#: Оставлено для обратной совместимости с прежним именем.
norm = folded


@dataclass(slots=True)
class Snapshot:
    """Всё, что фильтр знает о сообщении."""

    text: str = ""
    file_name: str = ""
    has_buttons: bool = False
    forwarded: bool = False
    from_bot: bool = False
    contact: bool = False


@dataclass(slots=True)
class Signal:
    code: str
    weight: int
    note: str


@dataclass(slots=True)
class Verdict:
    score: int = 0
    signals: list[Signal] = field(default_factory=list)
    threshold: int = 3

    @property
    def bad(self) -> bool:
        return self.score >= self.threshold

    def why(self) -> str:
        return ", ".join(s.note for s in self.signals)


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    weight: int
    note: str
    words: tuple[str, ...] = ()
    pattern: str = ""
    #: Проверять только в диалогах, где переписки ещё не было.
    only_new: bool = True


#: Порядок не важен, важны веса. Пять очков — почти приговор при пороге
#: по умолчанию, одно — только добавка к остальным.
RULES: tuple[Rule, ...] = (
    Rule(
        "job", 3, "предложение работы",
        words=(
            "работа", "работу", "подработ", "ваканс", "заработок", "заработ",
            "доход", "требуются", "нужны люди", "нужны сотрудники", "з/п",
            "зп от", "оплата ежедневно", "без опыта", "удаленн", "занятость",
            "устройство на работу", "трудоустрой",
        ),
    ),
    Rule(
        "money", 3, "суммы и обещания дохода",
        pattern=r"(от\s*\d{3,}|\d{3,}\s*(р|руб|рублей|\$|usd|тыс)|\d+\s*%\s*в\s*(день|неделю|месяц))",
    ),
    Rule(
        "crypto", 3, "крипта и инвестиции",
        words=(
            "крипт", "usdt", "биткоин", "bitcoin", "трейд", "инвест", "биржа",
            "депозит", "p2p", "арбитраж", "обменник", "кошелек",
        ),
    ),
    Rule(
        "casino", 3, "ставки и казино",
        words=("казино", "ставки", "букмекер", "фрибет", "слоты", "промокод", "1win", "бонус за регистрацию"),
    ),
    Rule(
        "prize", 2, "розыгрыш или приз",
        words=("розыгрыш", "вы выиграли", "приз", "победитель", "поздравляем вы", "халява", "бесплатно раздаю"),
    ),
    Rule(
        "urgent", 1, "давит срочностью",
        words=("срочно", "успей", "только сегодня", "последний день", "мест осталось", "пиши быстрее"),
    ),
    Rule(
        "pay", 3, "просит денег или реквизиты",
        words=(
            "переведи", "перевести", "предоплат", "оплати", "реквизит",
            "номер карты", "скинь на карту", "закинь", "займи", "одолжи",
        ),
        only_new=False,
    ),
    Rule(
        "creds", 5, "выпрашивает коды и пароли",
        words=(
            "код из смс", "код из sms", "смс код", "код подтверждения",
            "пароль", "логин и пароль", "подтверди вход", "проголосуй за меня",
            "код авторизации", "отправь код",
        ),
        only_new=False,
    ),
    Rule(
        "invite", 2, "зовёт в бота или канал",
        pattern=r"(t\.me/\S+\?start|t\.me/\S*bot|@\w+bot\b|подпишись|перейди по ссылке)",
    ),
    Rule(
        "link", 2, "ссылка в первом сообщении",
        pattern=r"(https?://|t\.me/|www\.)",
    ),
    Rule("long", 1, "простыня текста", pattern=r"^.{600,}$"),
)


def _hit(rule: Rule, raw: str, soft: str) -> bool:
    """Проверить правило по обеим строкам: как написано и как свёрнуто."""
    if rule.words and any(w in raw or w in soft for w in rule.words):
        return True
    if rule.pattern and (
        re.search(rule.pattern, raw, re.S) or re.search(rule.pattern, soft, re.S)
    ):
        return True
    return False


def inspect(
    snap: Snapshot,
    *,
    established: bool,
    own_words: str = "",
    threshold: int = 3,
) -> Verdict:
    """Разобрать сообщение и вернуть решение с объяснением.

    established — переписка уже была: владелец здесь отвечал или писал
    сам. В таких чатах коммерческие признаки не проверяются, иначе бот
    начнёт удалять сообщения знакомых, которые спросили про работу.
    """
    verdict = Verdict(threshold=threshold)
    raw = plain(snap.text)
    soft = folded(snap.text)

    lower_name = (snap.file_name or "").lower()
    if lower_name.endswith(DANGEROUS):
        verdict.signals.append(Signal("exe", 5, f"исполняемый файл {lower_name[-12:]}"))

    for rule in RULES:
        if rule.only_new and established:
            continue
        if raw and _hit(rule, raw, soft):
            verdict.signals.append(Signal(rule.code, rule.weight, rule.note))

    if not established:
        if snap.has_buttons:
            verdict.signals.append(Signal("buttons", 2, "кнопки под сообщением"))
        if snap.from_bot:
            verdict.signals.append(Signal("bot", 2, "пишет бот"))
        if snap.forwarded:
            verdict.signals.append(Signal("forward", 1, "переслано из канала"))
        if snap.contact:
            verdict.signals.append(Signal("contact", 1, "прислал контакт"))

    own = [w.strip() for w in own_words.split("|") if w.strip()] if own_words else []
    for word in own:
        if folded(word) in soft or plain(word) in raw:
            verdict.signals.append(Signal("own", 4, f"ваше слово «{word}»"))
            break

    verdict.score = sum(s.weight for s in verdict.signals)
    return verdict


def snapshot_of(message) -> Snapshot:
    """Собрать снимок из сообщения aiogram."""
    document = getattr(message, "document", None)
    markup = getattr(message, "reply_markup", None)
    return Snapshot(
        text=(message.text or message.caption or ""),
        file_name=(getattr(document, "file_name", "") or "") if document else "",
        has_buttons=bool(getattr(markup, "inline_keyboard", None)),
        forwarded=bool(
            getattr(message, "forward_origin", None)
            or getattr(message, "forward_from_chat", None)
        ),
        from_bot=bool(getattr(getattr(message, "from_user", None), "is_bot", False)),
        contact=bool(getattr(message, "contact", None)),
    )
