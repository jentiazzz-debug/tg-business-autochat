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
        await self.to_owner(f"⚠️ <code>{self.args_head()}</code> — {why}")

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

    @property
    def name(self) -> str:
        return self.names[0]


REGISTRY: dict[str, Cmd] = {}
ORDER: list[Cmd] = []

#: Порядок разделов в справке.
GROUPS = (
    "слово",
    "кадры",
    "азарт",
    "диалог",
    "личина",
    "картинка",
    "служба",
)

#: Как раздел выглядит в справке: значок и человеческая подпись.
GROUP_TITLES = {
    "слово": ("✒️", "Слово", "как выглядит написанное"),
    "кадры": ("🎬", "Кадры", "текст, который двигается"),
    "азарт": ("🎲", "Азарт", "игры на двоих и рандом"),
    "диалог": ("💬", "Диалог", "управление перепиской"),
    "личина": ("🎭", "Личина", "имя, аватар, подарки"),
    "картинка": ("🖼", "Картинка", "обработка фото"),
    "служба": ("⚙️", "Служба", "всё остальное"),
}


def command(
    *names: str,
    group: str,
    about: str,
    usage: str = "",
    needs: Iterable[str] = (),
    listed: bool = True,
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


def help_pages(prefix: str = ".") -> list[str]:
    """Справка по разделам, готовая к отправке.

    Разбивается на сообщения по 3500 символов: команд много, а лимит
    Telegram на одно сообщение — 4096.
    """
    pages: list[str] = []
    current = [
        f"<b>{BRAND} · команды</b>",
        f"<i>{len(ORDER)} {_plural(len(ORDER))}, набираются прямо в переписке</i>",
        "",
    ]
    size = 80

    for group in GROUPS:
        items = [c for c in ORDER if c.group == group and c.listed]
        if not items:
            continue
        icon, title, hint = GROUP_TITLES.get(group, ("▫️", group.capitalize(), ""))
        block = [f"{icon} <b>{title.upper()}</b>  <i>{hint}</i>"]
        for cmd in items:
            names = " · ".join(f"<code>{prefix}{n}</code>" for n in cmd.names)
            usage = f" {cmd.usage}" if cmd.usage else ""
            block.append(f"{names}{usage} — {cmd.about}")
        block.append("")
        chunk = "\n".join(block)
        if size + len(chunk) > 3500:
            pages.append("\n".join(current))
            current, size = [], 0
        current.append(chunk)
        size += len(chunk)

    if current:
        pages.append("\n".join(current))
    return pages
