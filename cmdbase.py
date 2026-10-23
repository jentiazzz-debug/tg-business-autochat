"""Каркас команд, которые владелец пишет прямо в своих чатах.

Как это работает. Владелец отправляет в переписке «.жирный привет» —
это его собственное исходящее сообщение, и бот получает его апдейтом
business_message. Бот распознаёт команду, **удаляет сообщение владельца**
и отправляет вместо него результат от его же имени. Со стороны выглядит
так, будто человек сразу написал жирным.

Отсюда два требования к правам в «Автоматизации чатов»:

* «отвечать на сообщения» — иначе бот не отправит результат;
* «удалять мои сообщения» — иначе команда останется висеть в чате
  над результатом. Бот в этом случае всё равно работает, просто
  некрасиво, и говорит об этом один раз в личке.

Реестр команд общий и заполняется декоратором @command из модулей
cmd_*.py. Справка собирается из него же, так что забыть описать новую
команду невозможно — она сама появится в /help и в .help.
"""

from __future__ import annotations

import json
import logging
import shlex
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Mapping

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

import config
import pe
from pe import e

log = logging.getLogger("autochat.cmd")

BRAND = config.BRAND

#: Префиксы, с которых начинается команда. Точка — как у всех
#: юзерботов, восклицательный знак нужен тем, у кого точка мешает
#: обычной переписке.
PREFIXES = (".", "!")

#: Права из BusinessBotRights, на которые ссылаются команды.
RIGHT_TITLES = {
    "can_reply": "отвечать на сообщения",
    "can_delete_outgoing_messages": "удалять мои сообщения",
    "can_delete_all_messages": "удалять любые сообщения",
    "can_edit_name": "менять имя аккаунта",
    "can_edit_bio": "менять «о себе»",
    "can_edit_profile_photo": "менять аватар",
    "can_edit_username": "менять юзернейм",
    "can_view_gifts_and_stars": "видеть подарки и звёзды",
    "can_manage_stories": "публиковать истории",
    "can_read_messages": "читать сообщения",
}


def rights_from(conn: Mapping[str, Any] | None) -> dict[str, bool]:
    """Права бота из строки подключения.

    Хранятся JSON-ом: список прав Telegram растёт с каждой версией
    Bot API, и заводить под каждое отдельный столбец — гарантированная
    миграция на каждый апдейт.
    """
    if conn is None:
        return {}
    raw = conn["rights"] if "rights" in conn.keys() else None
    if not raw:
        # Старое подключение, записанное до появления столбца: о правах
        # известно только то, что было в плоских полях.
        return {"can_reply": bool(conn["can_reply"]), "can_read_messages": True}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return {k: bool(v) for k, v in data.items()}


@dataclass(slots=True)
class Ctx:
    """Всё, что нужно команде для работы."""

    bot: Bot
    conn_id: str
    owner_id: int
    owner_chat_id: int
    chat_id: int
    message: Message
    args: str
    settings: Mapping[str, Any]
    #: Как зовут участников — нужно играм и карточкам.
    owner_name: str = "вы"
    peer_name: str = "собеседник"
    peer_id: int = 0
    rights: dict[str, bool] = field(default_factory=dict)
    #: Удалось ли убрать сообщение с командой — влияет на подсказки.
    dropped: bool = False

    # ----------------------------------------------------------------- ввод

    @property
    def reply(self) -> Message | None:
        return self.message.reply_to_message

    def text(self) -> str:
        """Текст для команды: аргументы, иначе текст сообщения-ответа.

        Так работает вся серия стилизаций: «.жирный привет» и «.жирный»
        ответом на своё сообщение дают одно и то же.
        """
        if self.args.strip():
            return self.args.strip()
        if self.reply is not None:
            return self.reply.text or self.reply.caption or ""
        return ""

    def words(self) -> list[str]:
        """Аргументы как список, с учётом кавычек."""
        try:
            return shlex.split(self.args)
        except ValueError:
            return self.args.split()

    def has(self, right: str) -> bool:
        return bool(self.rights.get(right))

    # --------------------------------------------------------------- вывод

    async def drop_command(self) -> bool:
        """Убрать из чата сообщение с командой."""
        try:
            await self.bot.delete_business_messages(
                business_connection_id=self.conn_id,
                message_ids=[self.message.message_id],
            )
            self.dropped = True
        except TelegramAPIError as err:
            log.info("не удалил команду в %s: %s", self.chat_id, err)
            self.dropped = False
        return self.dropped

    async def send(self, text: str, *, html: bool = False, **kw: Any) -> Message | None:
        """Отправить в чат от имени владельца."""
        try:
            return await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                business_connection_id=self.conn_id,
                parse_mode="HTML" if html else None,
                **kw,
            )
        except TelegramAPIError as err:
            log.warning("не отправил результат команды в %s: %s", self.chat_id, err)
            return None

    async def replace(self, text: str, *, html: bool = False, **kw: Any) -> Message | None:
        """Подменить команду результатом — основной приём всех команд."""
        await self.drop_command()
        return await self.send(text, html=html, **kw)

    async def edit(self, message: Message, text: str, *, html: bool = False) -> bool:
        """Переписать уже отправленное сообщение бота (для анимаций)."""
        try:
            await self.bot.edit_message_text(
                text=text,
                chat_id=self.chat_id,
                message_id=message.message_id,
                business_connection_id=self.conn_id,
                parse_mode="HTML" if html else None,
            )
            return True
        except TelegramAPIError:
            return False

    async def to_owner(self, text: str, **kw: Any) -> None:
        """Написать владельцу в личку бота — без следа в чужом чате."""
        try:
            await self.bot.send_message(self.owner_chat_id, text, **kw)
        except TelegramAPIError as err:
            log.warning("не написал владельцу %s: %s", self.owner_id, err)

    async def fail(self, why: str) -> None:
        """Сообщить об ошибке владельцу в личку, а не в чат.

        Принцип: собеседник не должен видеть, что у владельца что-то не
        сработало. Поэтому команда либо даёт результат в чате, либо
        тихо исчезает, а объяснение уходит в личку.
        """
        await self.drop_command()
        await self.to_owner(f"{e('warning')} <code>{self.args_head()}</code> — {why}")

    def args_head(self) -> str:
        import html as _h

        return _h.escape((self.message.text or "")[:60], quote=False)


Runner = Callable[[Ctx], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Cmd:
    names: tuple[str, ...]
    group: str
    about: str
    run: Runner
    usage: str = ""
    #: Права, без которых команда не выполнится.
    needs: tuple[str, ...] = ()
    #: Показывать в справке (служебные псевдонимы прячем).
    listed: bool = True
    #: Пример для справки — аргументы после имени команды. Пусто — пример
    #: не показывается.
    example: str = ""

    @property
    def name(self) -> str:
        return self.names[0]


REGISTRY: dict[str, Cmd] = {}
ORDER: list[Cmd] = []

#: Порядок разделов в справке.
GROUPS = (
    "след",
    "диалог",
    "время",
    "слово",
    "кадры",
    "азарт",
    "личина",
    "картинка",
    "служба",
)

#: Как раздел выглядит в справке: иконка из пака, подпись, пояснение.
GROUP_TITLES = {
    "след": ("eye", "След", "удалённое, правки, сохранить себе"),
    "диалог": ("chats", "Диалог", "мут, досье, уборка, автоответчик"),
    "время": ("alarm", "Время", "напоминания и отложенные сообщения"),
    "слово": ("edit", "Слово", "как выглядит написанное"),
    "кадры": ("video", "Кадры", "текст, который двигается"),
    "азарт": ("target", "Азарт", "игры на двоих и рандом"),
    "личина": ("avatar", "Личина", "имя, аватар, подарки"),
    "картинка": ("image", "Картинка", "обработка фото"),
    "служба": ("gear", "Служба", "всё остальное"),
}


def command(
    *names: str,
    group: str,
    about: str,
    usage: str = "",
    needs: Iterable[str] = (),
    listed: bool = True,
    example: str = "",
) -> Callable[[Runner], Runner]:
    """Зарегистрировать команду под всеми её именами."""

    def wrapper(fn: Runner) -> Runner:
        cmd = Cmd(
            names=tuple(names),
            group=group,
            about=about,
            run=fn,
            usage=usage,
            needs=tuple(needs),
            listed=listed,
            example=example,
        )
        for name in names:
            if name in REGISTRY:
                raise RuntimeError(f"команда {name!r} уже занята")
            REGISTRY[name] = cmd
        ORDER.append(cmd)
        return fn

    return wrapper


def parse(text: str, prefixes: Iterable[str] = PREFIXES) -> tuple[str, str] | None:
    """Разобрать «.жирный привет» на («жирный», «привет»).

    Возвращает None, если это не команда: обычное сообщение владельца
    должно уходить дальше нетронутым.
    """
    if not text:
        return None
    stripped = text.lstrip()
    prefix = next((p for p in prefixes if stripped.startswith(p)), None)
    if prefix is None:
        return None
    body = stripped[len(prefix) :]
    if not body or body[0].isspace():
        return None
    head, _, tail = body.partition(" ")
    name = head.split("@")[0].strip().lower()
    if not name:
        return None
    return name, tail.strip()


def find(name: str) -> Cmd | None:
    return REGISTRY.get(name)


def missing_rights(cmd: Cmd, rights: Mapping[str, bool]) -> list[str]:
    return [r for r in cmd.needs if not rights.get(r)]


def _plural(n: int) -> str:
    tail = n % 100
    if 11 <= tail <= 14:
        return "команд"
    tail %= 10
    if tail == 1:
        return "команда"
    if 2 <= tail <= 4:
        return "команды"
    return "команд"


#: Сколько символов кладём в одно сообщение справки. Лимит Telegram —
#: 4096 видимых символов, а теги иконок в него не входят; запас нужен
#: под заголовок страницы.
PAGE_LIMIT = 3300


def group_title(group: str) -> tuple[str, str, str]:
    return GROUP_TITLES.get(group, ("dots", group.capitalize(), ""))


def listed(group: str) -> list[Cmd]:
    return [c for c in ORDER if c.group == group and c.listed]


def help_overview(prefix: str = ".") -> str:
    """Первый экран справки: как работают команды и какие есть разделы."""
    total = sum(1 for c in ORDER if c.listed)
    lines = [
        f"{e('code')} <b>{BRAND} · команды</b>",
        f"<i>{total} {_plural(total)} прямо в ваших личных чатах</i>",
        "",
        f"{e('info')} <b>Как это работает</b>",
        f"Пишете в любом чате <code>{prefix}команда</code> — бот убирает её и "
        "ставит на её место результат. Со стороны выглядит так, будто вы "
        "сразу так и написали.",
        "",
        f"{e('lightbulb')} Многие команды работают <b>ответом на сообщение</b>: "
        f"ответьте на чужое фото и напишите <code>{prefix}сохрани</code>.",
        f"{e('lock')} Всё служебное (досье, удалённое, заметки) приходит "
        "<b>сюда, в личку</b> — собеседник этого не видит.",
        "",
        f"{e('menu')} <b>Разделы</b>",
    ]
    for group in GROUPS:
        items = listed(group)
        if not items:
            continue
        icon, title, hint = group_title(group)
        lines.append(f"{e(icon)} <b>{title}</b> · {len(items)} — <i>{hint}</i>")
    lines += [
        "",
        f"{e('star')} <b>Самое нужное</b>",
        f"<code>{prefix}мут 30м</code> — заглушить собеседника на 30 минут",
        f"<code>{prefix}удалённые</code> — что он удалил в этом чате",
        f"<code>{prefix}досье</code> — кто это и как себя ведёт",
        f"<code>{prefix}напомни 1ч позвонить</code> — напоминание вам",
        "",
        "<i>Выберите раздел кнопкой ниже.</i>",
    ]
    return "\n".join(lines)


def _cmd_block(cmd: Cmd, prefix: str) -> str:
    import html as _h

    head = f"<code>{prefix}{cmd.names[0]}</code>"
    if cmd.usage:
        head += f" <i>{_h.escape(cmd.usage, quote=False)}</i>"
    if len(cmd.names) > 1:
        head += " · " + " · ".join(f"<code>{prefix}{n}</code>" for n in cmd.names[1:])
    block = f"{head}\n{cmd.about}"
    if cmd.example:
        block += f"\n{e('chevron_right')} <code>{prefix}{cmd.names[0]} {_h.escape(cmd.example, quote=False)}</code>"
    if cmd.needs:
        rights = ", ".join(RIGHT_TITLES.get(r, r) for r in cmd.needs)
        block += f"\n<i>нужно право: {rights}</i>"
    return block


def help_section(group: str, prefix: str = ".") -> list[str]:
    """Страницы одного раздела — по PAGE_LIMIT символов."""
    icon, title, hint = group_title(group)
    items = listed(group)
    head = (
        f"{e(icon)} <b>{title.upper()}</b> · {len(items)} {_plural(len(items))}\n"
        f"<i>{hint}</i>\n"
    )
    pages: list[str] = []
    current: list[str] = [head]
    size = len(pe.strip(head))
    for cmd in items:
        block = _cmd_block(cmd, prefix)
        visible = len(pe.strip(block)) + 2
        if size + visible > PAGE_LIMIT and len(current) > 1:
            pages.append("\n\n".join(current))
            current = [f"{e(icon)} <b>{title.upper()}</b> · продолжение\n"]
            size = 40
        current.append(block)
        size += visible
    pages.append("\n\n".join(current))
    return pages


def help_pages(prefix: str = ".") -> list[str]:
    """Вся справка подряд: обзор и все разделы."""
    pages = [help_overview(prefix)]
    for group in GROUPS:
        if listed(group):
            pages += help_section(group, prefix)
    return pages
