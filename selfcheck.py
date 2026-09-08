"""Самопроверка без Telegram и без базы.

Запуск: python selfcheck.py

Проверяется то, за что бота ругают в реальной переписке: ответил, когда
должен был молчать; промолчал на второй вопрос; поймал триггер внутри
чужого слова; удалил живого человека вместо спамера; пропустил спам,
написанный латинскими буквами вперемешку с русскими.

Ни сети, ни базы — только engine.py, guard.py, styling.py и cmdbase.py,
поэтому гонять можно на любой машине, даже без установленного aiogram.
"""

from __future__ import annotations

import random
import sys

import engine
import guard
import styling

NOW = 1_700_000_000
FAILED: list[str] = []


def check(title: str, ok: bool, detail: str = "") -> bool:
    mark = "ok  " if ok else "ФЕЙЛ"
    print(f"[{mark}] {title}" + (f"\n       {detail}" if detail else ""))
    if not ok:
        FAILED.append(title)
    return ok


# --------------------------------------------------------------------------
# Автоответчик
# --------------------------------------------------------------------------

BASE_SETTINGS = {
    "active": 1,
    "away": 0,
    "greet": 0,
    "fallback": 0,
    "away_text": "Я отошёл, вернусь позже.",
    "greet_text": "Привет, {name}!",
    "fallback_text": "Отвечу позже.",
    "cooldown": 120,
    "pause_minutes": 30,
}

BASE_CHAT = {
    "ignored": 0,
    "greeted": 1,
    "last_reply": 0,
    "last_rule": 0,
    "owner_seen": 0,
}

RULES = [
    {"id": 1, "enabled": 1, "triggers": "цена|сколько стоит", "reply": "Прайс скину."},
    {"id": 2, "enabled": 1, "triggers": "сроки|когда будет", "reply": "На неделе."},
    {"id": 3, "enabled": 0, "triggers": "скидка", "reply": "Скидок нет."},
    {"id": 4, "enabled": 1, "triggers": "=да", "reply": "Отлично!"},
]


def case(title: str, expect: str, *, text: str, settings=None, chat=None, now=NOW):
    st = {**BASE_SETTINGS, **(settings or {})}
    ch = {**BASE_CHAT, **(chat or {})}
    got = engine.decide(text=text, settings=st, rules=RULES, chat=ch, now=now)
    tail = got.reason if got.kind == "skip" else engine.render(got.text, name="Аня")
    return check(title, got.kind == expect, f"ждали {expect}, получили {got.kind}: {tail}")


def autoreply_checks() -> None:
    print("\n=== АВТООТВЕТЫ ===")
    case("правило сработало", "rule", text="а какая цена?")
    case("триггер внутри слова не ловится", "skip", text="это правда оценка")
    case("точное совпадение =да", "rule", text="да")
    case("=да не ловит «да, конечно»", "skip", text="да, конечно")
    case("выключенное правило молчит", "skip", text="а скидка будет?")
    case("владелец сам в диалоге", "skip", text="цена?", chat={"owner_seen": NOW - 60})
    case("пауза владельца истекла", "rule", text="цена?", chat={"owner_seen": NOW - 3600})
    case(
        "кулдаун после того же правила", "skip",
        text="а цена точно такая?", chat={"last_reply": NOW - 30, "last_rule": 1},
    )
    case(
        "другое правило кулдаун обходит", "rule",
        text="а сроки какие?", chat={"last_reply": NOW - 30, "last_rule": 1},
    )
    case("чат в исключениях", "skip", text="цена?", chat={"ignored": 1})
    case("автоответы выключены", "skip", text="цена?", settings={"active": 0})
    case("режим «отошёл» отвечает на всё", "away", text="привет", settings={"away": 1})
    case(
        "приветствие новому чату", "greet",
        text="привет", settings={"greet": 1}, chat={"greeted": 0},
    )
    case(
        "правило важнее приветствия", "rule",
        text="привет, сколько стоит?", settings={"greet": 1}, chat={"greeted": 0},
    )
    case("без правил и запасного текста — тишина", "skip", text="как дела?")
    case("ответ по умолчанию включён", "fallback", text="как дела?", settings={"fallback": 1})
    case(
        "пустой текст ответа не отправляется", "skip",
        text="привет", settings={"away": 1, "away_text": ""},
    )
    check(
        "фигурная скобка в тексте не ломает подстановку",
        engine.render("Скидка {50%} для {name}", name="Аня") == "Скидка {50%} для Аня",
    )


# --------------------------------------------------------------------------
# Антискам
# --------------------------------------------------------------------------


def scam(
    title: str,
    should_block: bool,
    *,
    text: str = "",
    file_name: str = "",
    established: bool = False,
    buttons: bool = False,
    from_bot: bool = False,
    own: str = "",
    threshold: int = 3,
) -> None:
    snap = guard.Snapshot(
        text=text, file_name=file_name, has_buttons=buttons, from_bot=from_bot
    )
    v = guard.inspect(snap, established=established, own_words=own, threshold=threshold)
    ok = v.bad == should_block
    want = "заблокировать" if should_block else "пропустить"
    check(title, ok, f"ждали {want}, получили {v.score} очк. — {v.why() or 'признаков нет'}")


def guard_checks() -> None:
    print("\n=== АНТИСКАМ ===")
    scam(
        "спам про работу от незнакомого", True,
        text="Здравствуйте! Есть работа, доход от 5000 руб в день. Пишите в лс",
    )
    scam(
        "тот же спам латинскими подменами", True,
        text="Здpaвствуйте! Ищем людей на pa6oту, дохoд от 5000 в день",
    )
    scam("живой вопрос про цену от незнакомого", False, text="Привет! Сколько стоит стрижка?")
    scam("обычное «привет»", False, text="привет, ты тут?")
    scam(
        "знакомый спрашивает про работу — не трогаем", False,
        text="слушай, а на работу к вам можно?", established=True,
    )
    scam(
        "выпрашивает код из СМС — ловим даже у знакомого", True,
        text="скинь код из смс который сейчас придёт, срочно", established=True,
    )
    scam(
        "просит денег — ловим у знакомого тоже", True,
        text="переведи 5000 на карту срочно, потом отдам", established=True,
    )
    scam(
        "исполняемый файл от знакомого", True,
        text="посмотри что нашёл", file_name="doc_2026.exe", established=True,
    )
    scam("обычный документ", False, text="вот договор", file_name="dogovor.pdf")
    scam(
        "крипта плюс ссылка", True,
        text="Заработок на крипте, USDT, переходи по ссылке https://t.me/xxx",
    )
    scam("бот с кнопками пишет первым", True, text="Привет! Жми кнопку", buttons=True, from_bot=True)
    scam(
        "своё слово в списке", True,
        text="Привет! Хочешь подписаться на мой онлифанс?", own="онлифанс|OF",
    )
    scam(
        "строгий порог ловит одну ссылку", True,
        text="глянь https://example.com", threshold=2,
    )
    scam(
        "мягкий порог ту же ссылку пропускает", False,
        text="глянь https://example.com", threshold=5,
    )
    v = guard.inspect(
        guard.Snapshot(text="Работа! Доход от 5000 в день, крипта, жми https://t.me/x"),
        established=False, threshold=3,
    )
    check(
        "объяснение перечисляет признаки",
        len(v.signals) >= 3 and v.score >= 6,
        f"{v.score} очк.: {v.why()}",
    )


# --------------------------------------------------------------------------
# Команды и текст
# --------------------------------------------------------------------------


def command_checks() -> None:
    print("\n=== КОМАНДЫ ===")
    import cmdbase

    # Реестр наполняется импортом модулей команд.
    import commands  # noqa: F401

    check("реестр не пуст", len(cmdbase.ORDER) > 50, f"{len(cmdbase.ORDER)} команд")
    check(
        "нет латинских имён",
        not [n for n in cmdbase.REGISTRY if any(c.isascii() and c.isalpha() for c in n)],
    )
    check(
        "все команды в известных разделах",
        all(c.group in cmdbase.GROUPS for c in cmdbase.ORDER),
    )
    check("разбор «.жирный привет»", cmdbase.parse(".жирный привет", (".",)) == ("жирный", "привет"))
    check("разбор без аргументов", cmdbase.parse(".досье", (".",)) == ("досье", ""))
    check("обычный текст командой не считается", cmdbase.parse("привет", (".",)) is None)
    check("точка в конце фразы не команда", cmdbase.parse("ну ладно.", (".",)) is None)
    check("многоточие не команда", cmdbase.parse(". привет", (".",)) is None)
    check("свой префикс работает", cmdbase.parse("!досье", ("!",)) == ("досье", ""))
    check("чужой префикс не срабатывает", cmdbase.parse("!досье", (".",)) is None)
    pages = cmdbase.help_pages(".")
    check(
        "справка собирается и режется по лимиту",
        pages and all(len(p) <= 4096 for p in pages),
        f"{len(pages)} стр., максимум {max(len(p) for p in pages)} симв.",
    )


def styling_checks() -> None:
    print("\n=== ТЕКСТ ===")
    check("раскладка туда-обратно", styling.switch_layout(styling.switch_layout("Привет")) == "Привет")
    check("«Ghbdtn» → «Привет»", styling.switch_layout("Ghbdtn") == "Привет")
    lit = styling.leet("писать как дебил")
    check(
        "лит убирает кириллицу",
        not styling.has_cyrillic(lit) and lit != "писать как дебил",
        lit,
    )
    check("транслит", styling.translit("привет") == "privet")
    check("реверс", styling.reverse("привет") == "тевирп")
    check("ё приводится к е", engine.norm("ещё") == "еще")
    latin_only = [k for k, s in styling.STYLES.items() if s.latin]
    check(
        "латинские шрифты не портят кириллицу",
        all(styling.STYLES[k].fn("Привет") == "Привет" for k in latin_only),
        f"проверено стилей: {len(latin_only)}",
    )
    check(
        "«очисти» снимает залго",
        styling.strip_marks(styling.zalgo("привет")) == "привет",
    )
    # «очисти» на чистом тексте обязан ничего не менять, а «шепот» и
    # «крик» зависят от регистра исходника — поэтому вход со заглавными,
    # а бессмысленные для проверки стили исключены.
    random.seed(1)
    russian = [
        k for k, s in styling.STYLES.items()
        if not s.latin and not s.html and k != "clean"
    ]
    unchanged = [
        k for k in russian if styling.STYLES[k].fn("Привет, Мир!") == "Привет, Мир!"
    ]
    check(
        "русские стили меняют русский текст",
        not unchanged,
        f"проверено {len(russian)}" + (f", не сработали: {unchanged}" if unchanged else ""),
    )
    check(
        "пустая строка ничего не ломает",
        all(isinstance(s.fn(""), str) for s in styling.STYLES.values()),
    )


def main() -> int:
    autoreply_checks()
    guard_checks()
    command_checks()
    styling_checks()
    print()
    if FAILED:
        print(f"ПРОВАЛЕНО {len(FAILED)}:")
        for title in FAILED:
            print(f"  · {title}")
        return 1
    print("всё сошлось")
    return 0


if __name__ == "__main__":
    sys.exit(main())
