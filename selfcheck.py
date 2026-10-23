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


def premium_checks() -> None:
    """Премиум-иконки: каждая, на которую ссылается код, есть в паке."""
    import re
    from pathlib import Path

    import pe

    print("\n=== ПРЕМИУМ-ЭМОДЗИ ===")
    used: set[str] = set()
    for path in Path(__file__).resolve().parent.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        used |= set(re.findall(r"""\be\(\s*["'](\w+)["']\s*\)""", src))
        used |= set(re.findall(r"""_b\(\s*\w+,\s*["'](\w+)["']""", src))
        used |= set(re.findall(r"""btn\(\s*["'](\w+)["']""", src))
    missing = sorted(n for n in used if n not in pe.ICONS)
    check("все иконки из кода есть в паке", not missing, f"нет: {missing}" if missing else f"иконок в ходу: {len(used)}")

    tag = pe.e("mute")
    check("тег собирается с заменителем", tag.startswith("<tg-emoji emoji-id=") and "🔇" in tag)
    check("strip оставляет заменитель", pe.strip(f"{tag} в муте") == "🔇 в муте")

    import texts

    shown = texts.mute_public("Вася <3", "30 мин")
    check(
        "«… в муте» с иконкой и экранированием",
        "<tg-emoji" in shown and "Вася &lt;3" in shown and "в муте" in shown,
        pe.strip(shown),
    )

    from aiogram.methods import SendMessage
    from aiogram.types import InlineKeyboardMarkup

    import keyboards

    method = SendMessage(
        chat_id=1,
        text=f"{tag} привет",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[keyboards.btn("mute", "Мут", callback_data="x")]]),
    )
    plain = pe._plain_method(method)
    button = plain.reply_markup.inline_keyboard[0][0]
    check(
        "откат: теги → заменители, иконки сняты с кнопок",
        plain.text == "🔇 привет" and button.icon_custom_emoji_id is None and button.text == "Мут",
    )
    check("откат не трогает исходный запрос", method.text.startswith("<tg-emoji"))


def timer_checks() -> None:
    import timers

    print("\n=== СРОКИ ===")
    cases = {
        "30м": 1800, "10мин": 600, "2ч": 7200, "1д": 86400, "1ч30м": 5400,
        "45": 2700, "30s": 30, "1w": 604800,
    }
    bad = {raw: timers.parse_span(raw) for raw, want in cases.items() if timers.parse_span(raw) != want}
    check("срок разбирается", not bad, f"не так: {bad}" if bad else ", ".join(cases))
    junk = [raw for raw in ("привет", "", "м", "10 яблок", "-5м", "5x") if timers.parse_span(raw) is not None]
    check("не срок — None", not junk, f"принял: {junk}" if junk else "")
    check("срок режется до 30 дней", timers.parse_span("400д") == timers.MAX_SPAN)
    check(
        "срок отделяется от текста",
        timers.split_span("1ч перезвонить ему") == (3600, "перезвонить ему")
        and timers.split_span("перезвонить через час") == (None, "перезвонить через час"),
    )
    check("срок словами", timers.span_words(5400) == "1 ч 30 мин" and timers.span_words(172800) == "2 дн")


def help_checks() -> None:
    import cmdbase
    import commands  # noqa: F401 — регистрация команд
    import handlers

    print("\n=== СПРАВКА ===")
    pages = [cmdbase.help_overview(".")]
    for group in cmdbase.GROUPS:
        pages += cmdbase.help_section(group, ".")
    longest = max(handlers.visible_len(p) for p in pages)
    check("каждая страница влезает в сообщение", longest <= 4096, f"{len(pages)} стр., максимум {longest} видимых симв.")
    lost = [c.name for c in cmdbase.ORDER if c.listed and c.group not in cmdbase.GROUPS]
    check("у каждой команды есть раздел", not lost, f"без раздела: {lost}" if lost else "")
    for name in ("мут", "размут", "муты", "удалённые", "правки", "сохрани", "напомни", "отложи", "таймеры", "отмени", "свой"):
        if cmdbase.find(name) is None:
            check(f"команда .{name} есть", False)
            break
    else:
        check("новые команды зарегистрированы", True, f"всего команд: {len(cmdbase.ORDER)}")


def storage_checks() -> None:
    import asyncio

    from aiogram.fsm.storage.base import StorageKey

    from storage import LeanStorage

    print("\n=== ПАМЯТЬ ===")

    async def run() -> bool:
        st = LeanStorage()
        key = StorageKey(bot_id=1, chat_id=2, user_id=2)
        await st.set_state(key, "Form:text")
        await st.set_data(key, {"a": 1})
        filled = await st.get_state(key) == "Form:text" and await st.get_data(key) == {"a": 1}
        await st.set_state(key, None)
        await st.set_data(key, {})
        return filled and not st._states and not st._data

    check("FSM не держит пустые записи", asyncio.run(run()))


def db_checks() -> None:
    """База на временном файле: миграция, след, таймеры, зеркала."""
    import asyncio
    import os
    import tempfile
    import time

    print("\n=== БАЗА ===")

    async def run() -> list[str]:
        import config
        import db

        fails = []
        with tempfile.TemporaryDirectory() as tmp:
            config.DB_PATH = __import__("pathlib").Path(tmp) / "t.db"
            await db.connect()
            try:
                await db.set_muted(1, 10, True, int(time.time()) - 1)
                if [r["chat_id"] for r in await db.expired_mutes(int(time.time()))] != [10]:
                    fails.append("мут на время не истекает")
                await db.set_muted(1, 10, False)
                if await db.expired_mutes(int(time.time())):
                    fails.append("снятый мут всё ещё в очереди")

                await db.add_trail(1, 10, "del", kind="photo", text="фото", file_id="F")
                await db.add_trail(1, 10, "edit", text="стало", before="было")
                dels = await db.trail_of(1, 10, "del")
                if len(dels) != 1 or dels[0]["file_id"] != "F":
                    fails.append("след удалённого")
                if (await db.trail_of(1, 10, "edit"))[0]["before"] != "было":
                    fails.append("след правок")
                if await db.trail_of(2, 10, "del"):
                    fails.append("след виден чужому владельцу")

                tid = await db.add_timer(1, int(time.time()) - 1, "remind", text="позвонить")
                if [r["id"] for r in await db.due_timers(int(time.time()))] != [tid]:
                    fails.append("таймер не созрел")
                if await db.drop_timer(2, tid):
                    fails.append("чужой таймер удалился")
                if not await db.drop_timer(1, tid):
                    fails.append("свой таймер не удалился")

                mid = await db.add_mirror(1, 555, "555:" + "x" * 40, "my_bot", "Мой")
                again = await db.add_mirror(1, 555, "555:" + "y" * 40, "my_bot", "Мой")
                if mid != again or len(await db.mirrors_of(1)) != 1:
                    fails.append("повторное подключение плодит зеркала")
                await db.seen_user(555, 7)
                await db.seen_user(555, 7)
                if (await db.users_count(555))[0] != 1:
                    fails.append("пользователь зеркала посчитан дважды")
                await db.mark_blocked(555, 7)
                if await db.bot_audience():
                    fails.append("заблокировавший остался в рассылке")

                await db.add_sponsor(-100, "Канал", "https://t.me/x")
                await db.add_sponsor(-100, "Канал 2", "https://t.me/y")
                if [r["title"] for r in await db.sponsors()] != ["Канал 2"]:
                    fails.append("спонсор задвоился")
            finally:
                await db.close()
        return fails

    fails = asyncio.run(run())
    check("мут на время, след, таймеры, зеркала, спонсоры", not fails, "; ".join(fails))


def subs_checks() -> None:
    """Подписка на поддельном боте: подписан, нет, бот не админ."""
    import asyncio
    from types import SimpleNamespace

    from aiogram.exceptions import TelegramBadRequest

    import config
    import db
    import subs

    print("\n=== ПОДПИСКА ===")

    class FakeBot:
        def __init__(self) -> None:
            self.members: dict[int, str] = {}
            self.calls = 0
            self.broken = False

        async def get_chat(self, chat_id):
            return SimpleNamespace(title="Solutions", username="solutions_org", invite_link=None)

        async def get_chat_member(self, chat_id, user_id):
            self.calls += 1
            if self.broken:
                raise TelegramBadRequest(method=None, message="member list is inaccessible")
            return SimpleNamespace(status=self.members.get(user_id, "left"))

    async def no_sponsors():
        return []

    async def run() -> list[str]:
        fails = []
        bot = FakeBot()
        saved = (subs.MAIN_BOT, db.sponsors, config.REQUIRED_CHANNEL)
        subs.MAIN_BOT, db.sponsors, config.REQUIRED_CHANNEL = bot, no_sponsors, -1003552364867
        subs.reset_cards()
        try:
            need = await subs.missing(5)
            if [c["url"] for c in need] != ["https://t.me/solutions_org"]:
                fails.append(f"неподписанному не показан канал: {need}")
            calls = bot.calls
            await subs.missing(5)
            if bot.calls != calls:
                fails.append("отказ не кэшируется — дёргает Telegram на каждое сообщение")
            bot.members[5] = "member"
            if await subs.missing(5, fresh=True):
                fails.append("«Я подписался» не видит подписку")
            bot.members[5] = "left"
            if await subs.missing(5):
                fails.append("подписанный не закэширован")
            bot.broken = True
            if await subs.missing(6):
                fails.append("бот не админ — людей заперло")
        finally:
            subs.MAIN_BOT, db.sponsors, config.REQUIRED_CHANNEL = saved
            subs.reset_cards()
        return fails

    fails = asyncio.run(run())
    check("подписка: стена, кэш, «Я подписался», отказ Telegram", not fails, "; ".join(fails))


def main() -> int:
    autoreply_checks()
    guard_checks()
    command_checks()
    styling_checks()
    premium_checks()
    timer_checks()
    help_checks()
    storage_checks()
    db_checks()
    subs_checks()
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
