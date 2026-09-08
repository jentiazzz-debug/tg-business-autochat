"""Команды профиля: имя, «о себе», аватар, юзернейм, подарки, звёзды.

Всё это Telegram разрешает боту делать с аккаунтом владельца через
отдельные права в «Автоматизации чатов». Каждая команда честно
проверяет своё право и объясняет, какую галочку включить, вместо
безмолвного «не сработало».

Про «.клон». У чужих ботов эта команда односторонняя: скопировал чужой
профиль — и разбирайся сам, как вернуть своё имя, био и аватар. Здесь
перед клонированием текущий профиль сохраняется в базу, включая
file_id аватара, и возвращается одной командой «.раклон». Мелочь,
из-за которой командой вообще можно пользоваться без страха.
"""

from __future__ import annotations

import html

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InputProfilePhotoStatic

import db
from cmdbase import Ctx, command


def esc(text: object) -> str:
    return html.escape(str(text or ""), quote=False)


async def _avatar_file_id(ctx: Ctx, chat_id: int) -> str | None:
    """Крупный file_id аватара чата, если он есть и виден боту."""
    try:
        info = await ctx.bot.get_chat(chat_id)
    except TelegramAPIError:
        return None
    photo = getattr(info, "photo", None)
    return getattr(photo, "big_file_id", None) if photo else None


async def _set_photo(ctx: Ctx, file_id: str) -> bool:
    """Поставить владельцу аватар по file_id.

    Telegram не принимает file_id в setBusinessAccountProfilePhoto —
    только загрузку файлом. Поэтому картинка сначала скачивается, потом
    заливается заново: другого пути нет.
    """
    try:
        buffer = await ctx.bot.download(file_id)
        if buffer is None:
            return False
        await ctx.bot.set_business_account_profile_photo(
            business_connection_id=ctx.conn_id,
            photo=InputProfilePhotoStatic(
                photo=BufferedInputFile(buffer.read(), filename="avatar.jpg")
            ),
        )
        return True
    except TelegramAPIError:
        return False


# --------------------------------------------------------------------------
# Имя, био, ник
# --------------------------------------------------------------------------


@command(
    "имя", "звать",
    group="личина",
    about="сменить имя аккаунта",
    usage="Имя [Фамилия]",
    needs=("can_edit_name",),
)
async def cmd_name(ctx: Ctx) -> None:
    text = ctx.text()
    if not text:
        await ctx.fail("напишите новое имя")
        return
    first, _, last = text.partition(" ")
    try:
        await ctx.bot.set_business_account_name(
            business_connection_id=ctx.conn_id,
            first_name=first[:64],
            last_name=(last.strip()[:64] or None),
        )
    except TelegramAPIError as err:
        await ctx.fail(f"Telegram не принял имя: {esc(err)}")
        return
    await ctx.drop_command()
    await ctx.to_owner(f"👤 Имя аккаунта теперь <b>{esc(text[:129])}</b>")


@command(
    "био", "осебе",
    group="личина",
    about="сменить «о себе»",
    usage="текст",
    needs=("can_edit_bio",),
)
async def cmd_bio(ctx: Ctx) -> None:
    text = ctx.text()
    try:
        await ctx.bot.set_business_account_bio(
            business_connection_id=ctx.conn_id, bio=text[:140]
        )
    except TelegramAPIError as err:
        await ctx.fail(f"Telegram не принял «о себе»: {esc(err)}")
        return
    await ctx.drop_command()
    await ctx.to_owner(
        f"📝 «О себе» теперь: <i>{esc(text[:140])}</i>" if text else "📝 «О себе» очищено."
    )


@command(
    "ник", "юзернейм",
    group="личина",
    about="сменить юзернейм аккаунта",
    usage="username",
    needs=("can_edit_username",),
)
async def cmd_nick(ctx: Ctx) -> None:
    name = ctx.text().strip().lstrip("@")
    try:
        await ctx.bot.set_business_account_username(
            business_connection_id=ctx.conn_id, username=name or None
        )
    except TelegramAPIError as err:
        await ctx.fail(f"Telegram не принял юзернейм: {esc(err)}")
        return
    await ctx.drop_command()
    await ctx.to_owner(f"🔗 Юзернейм теперь @{esc(name)}" if name else "🔗 Юзернейм снят.")


@command(
    "аватар", "ава",
    group="личина",
    about="поставить аватар — ответом на фото",
    needs=("can_edit_profile_photo",),
)
async def cmd_avatar(ctx: Ctx) -> None:
    reply = ctx.reply
    if reply is None or not reply.photo:
        await ctx.fail("примените команду ответом на фото")
        return
    if not await _set_photo(ctx, reply.photo[-1].file_id):
        await ctx.fail("Telegram не принял картинку")
        return
    await ctx.drop_command()
    await ctx.to_owner("🖼 Аватар обновлён.")


# --------------------------------------------------------------------------
# Клонирование с возвратом
# --------------------------------------------------------------------------


@command(
    "клон", "двойник",
    group="личина",
    about="скопировать профиль собеседника (возврат — .раклон)",
    needs=("can_edit_name",),
)
async def cmd_clone(ctx: Ctx) -> None:
    peer_id = ctx.peer_id or ctx.chat_id
    try:
        peer = await ctx.bot.get_chat(peer_id)
    except TelegramAPIError as err:
        await ctx.fail(f"не смог прочитать профиль собеседника: {esc(err)}")
        return

    # Сначала сохранить своё — иначе возвращать будет нечего.
    try:
        mine = await ctx.bot.get_chat(ctx.owner_chat_id)
        my_photo = getattr(getattr(mine, "photo", None), "big_file_id", None)
        await db.save_profile(
            ctx.owner_id,
            first_name=getattr(mine, "first_name", None),
            last_name=getattr(mine, "last_name", None),
            bio=getattr(mine, "bio", None),
            photo_id=my_photo,
        )
        saved = True
    except TelegramAPIError:
        saved = False

    first = (getattr(peer, "first_name", None) or ctx.peer_name)[:64]
    last = (getattr(peer, "last_name", None) or "")[:64] or None
    bio = (getattr(peer, "bio", None) or "")[:140]

    done = []
    try:
        await ctx.bot.set_business_account_name(
            business_connection_id=ctx.conn_id, first_name=first, last_name=last
        )
        done.append("имя")
    except TelegramAPIError:
        pass
    if bio and ctx.has("can_edit_bio"):
        try:
            await ctx.bot.set_business_account_bio(
                business_connection_id=ctx.conn_id, bio=bio
            )
            done.append("«о себе»")
        except TelegramAPIError:
            pass
    if ctx.has("can_edit_profile_photo"):
        photo_id = await _avatar_file_id(ctx, peer_id)
        if photo_id and await _set_photo(ctx, photo_id):
            done.append("аватар")

    await ctx.drop_command()
    if not done:
        await ctx.to_owner("⚠️ Скопировать не удалось ничего.")
        return
    tail = (
        "Вернуть своё — <code>.вернись</code>"
        if saved
        else "⚠️ Прежний профиль сохранить не удалось, возврата не будет."
    )
    await ctx.to_owner(
        f"👥 Скопировано: {', '.join(done)} у <b>{esc(ctx.peer_name)}</b>.\n\n{tail}"
    )


@command(
    "вернись", "раклон",
    group="личина",
    about="вернуть свой профиль после клонирования",
    needs=("can_edit_name",),
)
async def cmd_restore(ctx: Ctx) -> None:
    saved = await db.profile_of(ctx.owner_id)
    if saved is None:
        await ctx.fail("сохранённого профиля нет — клонирования ещё не было")
        return

    done = []
    try:
        await ctx.bot.set_business_account_name(
            business_connection_id=ctx.conn_id,
            first_name=(saved["first_name"] or "Я")[:64],
            last_name=(saved["last_name"] or None),
        )
        done.append("имя")
    except TelegramAPIError:
        pass
    if ctx.has("can_edit_bio"):
        try:
            await ctx.bot.set_business_account_bio(
                business_connection_id=ctx.conn_id, bio=(saved["bio"] or "")[:140]
            )
            done.append("«о себе»")
        except TelegramAPIError:
            pass
    if saved["photo_id"] and ctx.has("can_edit_profile_photo"):
        if await _set_photo(ctx, saved["photo_id"]):
            done.append("аватар")

    await ctx.drop_command()
    await ctx.to_owner(
        f"↩️ Возвращено: {', '.join(done)}." if done else "⚠️ Вернуть не удалось."
    )


# --------------------------------------------------------------------------
# Подарки и звёзды
# --------------------------------------------------------------------------


@command(
    "подарки", "гифты",
    group="личина",
    about="ваши подарки и их стоимость",
    needs=("can_view_gifts_and_stars",),
)
async def cmd_gifts(ctx: Ctx) -> None:
    await ctx.drop_command()
    try:
        owned = await ctx.bot.get_business_account_gifts(
            business_connection_id=ctx.conn_id, limit=100
        )
    except TelegramAPIError as err:
        await ctx.to_owner(f"⚠️ подарки не отдались: {esc(err)}")
        return

    gifts = list(getattr(owned, "gifts", []) or [])
    total = getattr(owned, "total_count", len(gifts))
    if not gifts:
        await ctx.to_owner("🎁 Подарков нет.")
        return

    stars = 0
    unique = 0
    for item in gifts:
        gift = getattr(item, "gift", None)
        price = getattr(gift, "star_count", None) or getattr(item, "star_count", None)
        if price:
            stars += int(price)
        if type(item).__name__.endswith("Unique") or getattr(gift, "name", None):
            unique += 1

    lines = [f"🎁 <b>Подарков: {total}</b>"]
    if unique:
        lines.append(f"из них коллекционных: <b>{unique}</b>")
    if stars:
        lines.append(f"суммарно по номиналу: <b>{stars}</b> ⭐")
    lines.append(f"<i>показано {len(gifts)} из {total}</i>")
    await ctx.to_owner("\n".join(lines))


@command(
    "звезды", "баланс",
    group="личина",
    about="баланс звёзд",
    needs=("can_view_gifts_and_stars",),
)
async def cmd_stars(ctx: Ctx) -> None:
    await ctx.drop_command()
    try:
        balance = await ctx.bot.get_business_account_star_balance(
            business_connection_id=ctx.conn_id
        )
    except TelegramAPIError as err:
        await ctx.to_owner(f"⚠️ баланс не отдался: {esc(err)}")
        return
    amount = getattr(balance, "amount", 0)
    await ctx.to_owner(f"⭐ Баланс: <b>{amount}</b>")
