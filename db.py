"""SQLite: подключения, настройки, правила, чаты, архив сообщений, журнал.

Один экземпляр бота обслуживает сколько угодно владельцев: у каждого
своё подключение к Telegram Business, свои правила и своя статистика.
Поэтому owner_id стоит почти в каждой таблице и в каждом запросе — это
и есть граница между людьми. Забыть его в WHERE значит показать одному
человеку переписку другого, так что все выборки идут только через
функции этого модуля.

Две горячие таблицы:

* chats — состояние диалога. В неё пишется каждое сообщение, чтобы бот
  помнил, когда владелец отвечал сам и когда бот отвечал за него. Без
  этих двух отметок автоответчик начинает вклиниваться в живые диалоги.
* messages — архив входящих. Telegram в апдейте об удалении присылает
  только номера сообщений, без текста, поэтому «увидеть удалённое»
  можно единственным способом: сохранить сообщение при получении и
  достать из своей базы, когда его удалят. Живёт архив keep_days дней.
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterable

import aiosqlite

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
    id           TEXT PRIMARY KEY,
    owner_id     INTEGER NOT NULL,
    user_chat_id INTEGER NOT NULL,
    username     TEXT,
    name         TEXT,
    enabled      INTEGER NOT NULL DEFAULT 1,
    can_reply    INTEGER NOT NULL DEFAULT 0,
    can_read     INTEGER NOT NULL DEFAULT 1,
    rights       TEXT,
    bot_id       INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS connections_owner ON connections (owner_id);

CREATE TABLE IF NOT EXISTS settings (
    owner_id      INTEGER PRIMARY KEY,
    active        INTEGER NOT NULL DEFAULT 1,
    away          INTEGER NOT NULL DEFAULT 0,
    greet         INTEGER NOT NULL DEFAULT 0,
    fallback      INTEGER NOT NULL DEFAULT 0,
    spy           INTEGER NOT NULL DEFAULT 1,
    spy_edits     INTEGER NOT NULL DEFAULT 1,
    away_text     TEXT NOT NULL,
    greet_text    TEXT NOT NULL,
    fallback_text TEXT NOT NULL,
    cooldown      INTEGER NOT NULL,
    pause_minutes INTEGER NOT NULL,
    keep_days     INTEGER NOT NULL,
    prefix        TEXT    NOT NULL DEFAULT '.',
    commands      INTEGER NOT NULL DEFAULT 1,
    filter_on     INTEGER NOT NULL DEFAULT 1,
    filter_delete INTEGER NOT NULL DEFAULT 1,
    filter_score  INTEGER NOT NULL DEFAULT 3,
    filter_words  TEXT    NOT NULL DEFAULT '',
    filter_files  INTEGER NOT NULL DEFAULT 1,
    notify_new    INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id   INTEGER NOT NULL,
    triggers   TEXT NOT NULL,
    reply      TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    hits       INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rules_owner ON rules (owner_id, id);

CREATE TABLE IF NOT EXISTS chats (
    owner_id   INTEGER NOT NULL,
    chat_id    INTEGER NOT NULL,
    title      TEXT,
    username   TEXT,
    ignored    INTEGER NOT NULL DEFAULT 0,
    greeted    INTEGER NOT NULL DEFAULT 0,
    last_reply INTEGER NOT NULL DEFAULT 0,
    last_rule  INTEGER NOT NULL DEFAULT 0,
    owner_seen INTEGER NOT NULL DEFAULT 0,
    seen       INTEGER NOT NULL DEFAULT 0,
    replies    INTEGER NOT NULL DEFAULT 0,
    muted      INTEGER NOT NULL DEFAULT 0,
    muted_until INTEGER NOT NULL DEFAULT 0,
    trusted    INTEGER NOT NULL DEFAULT 0,
    note       TEXT,
    incoming   INTEGER NOT NULL DEFAULT 0,
    deleted    INTEGER NOT NULL DEFAULT 0,
    edited     INTEGER NOT NULL DEFAULT 0,
    flagged    INTEGER NOT NULL DEFAULT 0,
    first_seen INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_id, chat_id)
);
CREATE INDEX IF NOT EXISTS chats_seen ON chats (owner_id, seen);

CREATE TABLE IF NOT EXISTS bot_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id    INTEGER NOT NULL,
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    total       INTEGER NOT NULL DEFAULT 0,
    sent        INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    blocked     INTEGER NOT NULL DEFAULT 0,
    preview     TEXT
);
CREATE INDEX IF NOT EXISTS broadcasts_at ON broadcasts (started_at);

CREATE TABLE IF NOT EXISTS profiles (
    owner_id   INTEGER PRIMARY KEY,
    first_name TEXT,
    last_name  TEXT,
    bio        TEXT,
    photo_id   TEXT,
    saved_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS snips (
    owner_id INTEGER NOT NULL,
    name     TEXT NOT NULL,
    body     TEXT NOT NULL,
    used     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_id, name)
);

CREATE TABLE IF NOT EXISTS scores (
    owner_id INTEGER NOT NULL,
    chat_id  INTEGER NOT NULL,
    game     TEXT NOT NULL,
    wins     INTEGER NOT NULL DEFAULT 0,
    losses   INTEGER NOT NULL DEFAULT 0,
    draws    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_id, chat_id, game)
);

CREATE TABLE IF NOT EXISTS messages (
    owner_id   INTEGER NOT NULL,
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    from_id    INTEGER,
    from_name  TEXT,
    at         INTEGER NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'text',
    text       TEXT,
    file_id    TEXT,
    edits      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_id, chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS messages_at ON messages (at);

CREATE TABLE IF NOT EXISTS log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    chat_id  INTEGER NOT NULL,
    kind     TEXT NOT NULL,
    rule_id  INTEGER,
    incoming TEXT,
    text     TEXT
);
CREATE INDEX IF NOT EXISTS log_owner ON log (owner_id, at);

CREATE TABLE IF NOT EXISTS trail (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    chat_id  INTEGER NOT NULL,
    at       INTEGER NOT NULL,
    event    TEXT NOT NULL,
    kind     TEXT NOT NULL DEFAULT 'text',
    text     TEXT,
    before   TEXT,
    file_id  TEXT
);
CREATE INDEX IF NOT EXISTS trail_chat ON trail (owner_id, chat_id, event, at);

CREATE TABLE IF NOT EXISTS timers (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL,
    due      INTEGER NOT NULL,
    action   TEXT NOT NULL,
    chat_id  INTEGER,
    conn_id  TEXT,
    title    TEXT,
    text     TEXT
);
CREATE INDEX IF NOT EXISTS timers_due ON timers (due);

CREATE TABLE IF NOT EXISTS sponsors (
    chat_id  INTEGER PRIMARY KEY,
    title    TEXT NOT NULL,
    url      TEXT NOT NULL,
    added_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS mirrors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id   INTEGER NOT NULL,
    bot_id     INTEGER NOT NULL UNIQUE,
    token      TEXT NOT NULL,
    username   TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',
    active     INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS mirrors_owner ON mirrors (owner_id);

CREATE TABLE IF NOT EXISTS bot_users (
    bot_id     INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    first_seen INTEGER NOT NULL,
    blocked    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (bot_id, user_id)
);
"""

#: Поля настроек, которые разрешено менять из админки. Имя столбца
#: подставляется в SQL, и белый список тут не формальность:
#: callback_data приходит снаружи.
SETTING_FIELDS = (
    "active",
    "away",
    "greet",
    "fallback",
    "spy",
    "spy_edits",
    "away_text",
    "greet_text",
    "fallback_text",
    "cooldown",
    "pause_minutes",
    "keep_days",
    "prefix",
    "commands",
    "filter_on",
    "filter_delete",
    "filter_score",
    "filter_words",
    "filter_files",
    "notify_new",
)

#: Ключ баннера главного меню в bot_meta.
BANNER_KEY = "menu_banner"

_db: aiosqlite.Connection | None = None


async def connect() -> None:
    global _db
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    # WAL: бот пишет в chats и messages на каждое сообщение и
    # одновременно читает правила. На стандартном журнале это упирается
    # в блокировки.
    await _db.execute("PRAGMA journal_mode=WAL")
    # Кэш страниц SQLite — 1 МБ вместо 2 по умолчанию, временные таблицы
    # на диске. Бот крутится на дешёвых хостингах с лимитом памяти, а
    # горячие запросы и так бьют в индексы.
    await _db.execute("PRAGMA cache_size=-1024")
    await _db.execute("PRAGMA temp_store=FILE")
    await _db.commit()
    await _migrate()


#: Столбцы, появившиеся после первых установок. CREATE TABLE IF NOT
#: EXISTS существующую таблицу не трогает, поэтому новые поля нужно
#: досыпать вручную — иначе у всех, кто уже запустил бота, обновление
#: падает на первом же запросе.
_ADDED = {
    "connections": {"rights": "TEXT", "bot_id": "INTEGER NOT NULL DEFAULT 0"},
    "settings": {
        "prefix": "TEXT NOT NULL DEFAULT '.'",
        "commands": "INTEGER NOT NULL DEFAULT 1",
        "filter_on": "INTEGER NOT NULL DEFAULT 1",
        "filter_delete": "INTEGER NOT NULL DEFAULT 1",
        "filter_score": "INTEGER NOT NULL DEFAULT 3",
        "filter_words": "TEXT NOT NULL DEFAULT ''",
        "filter_files": "INTEGER NOT NULL DEFAULT 1",
        "notify_new": "INTEGER NOT NULL DEFAULT 0",
    },
    "chats": {
        "muted": "INTEGER NOT NULL DEFAULT 0",
        "muted_until": "INTEGER NOT NULL DEFAULT 0",
        "trusted": "INTEGER NOT NULL DEFAULT 0",
        "note": "TEXT",
        "incoming": "INTEGER NOT NULL DEFAULT 0",
        "deleted": "INTEGER NOT NULL DEFAULT 0",
        "edited": "INTEGER NOT NULL DEFAULT 0",
        "flagged": "INTEGER NOT NULL DEFAULT 0",
        "first_seen": "INTEGER NOT NULL DEFAULT 0",
    },
}


async def _migrate() -> None:
    for table, columns in _ADDED.items():
        rows = await _all(f"PRAGMA table_info({table})")
        have = {r["name"] for r in rows}
        for name, ddl in columns.items():
            if name not in have:
                await _run(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


async def close() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


def _conn() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("db.connect() не вызван")
    return _db


async def _one(sql: str, args: Iterable[Any] = ()) -> aiosqlite.Row | None:
    async with _conn().execute(sql, tuple(args)) as cur:
        return await cur.fetchone()


async def _all(sql: str, args: Iterable[Any] = ()) -> list[aiosqlite.Row]:
    async with _conn().execute(sql, tuple(args)) as cur:
        return list(await cur.fetchall())


async def _run(sql: str, args: Iterable[Any] = ()) -> None:
    await _conn().execute(sql, tuple(args))
    await _conn().commit()


# --------------------------------------------------------------------------
# Подключения к Telegram Business
# --------------------------------------------------------------------------


async def save_connection(
    conn_id: str,
    owner_id: int,
    user_chat_id: int,
    *,
    enabled: bool,
    can_reply: bool,
    can_read: bool = True,
    rights: dict[str, bool] | None = None,
    username: str | None = None,
    name: str | None = None,
    bot_id: int = 0,
) -> None:
    """Записать или обновить подключение.

    Владелец может переподключить бота заново — тогда приходит новый
    conn_id, а старый остаётся в базе выключенным. Это нормально:
    ответы всегда уходят с тем id, который пришёл в сообщении.
    """
    now = int(time.time())
    await _run(
        """
        INSERT INTO connections (
            id, owner_id, user_chat_id, username, name,
            enabled, can_reply, can_read, rights, bot_id, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            owner_id = excluded.owner_id,
            user_chat_id = excluded.user_chat_id,
            username = COALESCE(excluded.username, connections.username),
            name = COALESCE(excluded.name, connections.name),
            enabled = excluded.enabled,
            can_reply = excluded.can_reply,
            can_read = excluded.can_read,
            rights = COALESCE(excluded.rights, connections.rights),
            bot_id = CASE WHEN excluded.bot_id THEN excluded.bot_id ELSE connections.bot_id END,
            updated_at = excluded.updated_at
        """,
        (
            conn_id,
            owner_id,
            user_chat_id,
            username,
            name,
            int(enabled),
            int(can_reply),
            int(can_read),
            json.dumps(rights, ensure_ascii=False) if rights else None,
            bot_id,
            now,
            now,
        ),
    )


async def connection_by_id(conn_id: str) -> aiosqlite.Row | None:
    return await _one("SELECT * FROM connections WHERE id = ?", (conn_id,))


async def connection_of(owner_id: int, bot_id: int = 0) -> aiosqlite.Row | None:
    """Свежайшее подключение владельца — к этому боту, если он указан.

    Владелец может подключить к Business и основной бот, и зеркало;
    панель каждого бота должна показывать своё подключение.
    """
    if bot_id:
        return await _one(
            "SELECT * FROM connections WHERE owner_id = ? AND bot_id = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (owner_id, bot_id),
        )
    return await _one(
        "SELECT * FROM connections WHERE owner_id = ? ORDER BY updated_at DESC LIMIT 1",
        (owner_id,),
    )


async def adopt_legacy(bot_id: int) -> None:
    """Подключения из версии без зеркал принадлежат основному боту."""
    await _run("UPDATE connections SET bot_id = ? WHERE bot_id = 0", (bot_id,))


async def disable_connection(conn_id: str) -> None:
    await _run(
        "UPDATE connections SET enabled = 0, updated_at = ? WHERE id = ?",
        (int(time.time()), conn_id),
    )


# --------------------------------------------------------------------------
# Настройки владельца
# --------------------------------------------------------------------------


async def settings_of(owner_id: int) -> aiosqlite.Row:
    """Настройки владельца; при первом обращении создаются заводские."""
    row = await _one("SELECT * FROM settings WHERE owner_id = ?", (owner_id,))
    if row is not None:
        return row
    await _run(
        """
        INSERT INTO settings (
            owner_id, spy, spy_edits, away_text, greet_text, fallback_text,
            cooldown, pause_minutes, keep_days, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(owner_id) DO NOTHING
        """,
        (
            owner_id,
            int(config.SPY),
            int(config.SPY_EDITS),
            config.DEFAULT_AWAY,
            config.DEFAULT_GREET,
            config.DEFAULT_FALLBACK,
            config.COOLDOWN,
            config.PAUSE_MINUTES,
            config.KEEP_DAYS,
            int(time.time()),
        ),
    )
    row = await _one("SELECT * FROM settings WHERE owner_id = ?", (owner_id,))
    assert row is not None
    return row


async def set_setting(owner_id: int, field: str, value: Any) -> None:
    if field not in SETTING_FIELDS:
        raise ValueError(f"поле {field!r} менять нельзя")
    await settings_of(owner_id)
    await _run(f"UPDATE settings SET {field} = ? WHERE owner_id = ?", (value, owner_id))


async def toggle_setting(owner_id: int, field: str) -> bool:
    row = await settings_of(owner_id)
    new = 0 if row[field] else 1
    await set_setting(owner_id, field, new)
    return bool(new)


async def owners_with_spy() -> list[int]:
    """Кому нужен архив сообщений — для уборки старых записей."""
    rows = await _all("SELECT owner_id FROM settings WHERE spy = 1")
    return [int(r["owner_id"]) for r in rows]


# --------------------------------------------------------------------------
# Правила
# --------------------------------------------------------------------------


async def rules_of(owner_id: int, *, only_enabled: bool = False) -> list[aiosqlite.Row]:
    sql = "SELECT * FROM rules WHERE owner_id = ?"
    if only_enabled:
        sql += " AND enabled = 1"
    sql += " ORDER BY id"
    return await _all(sql, (owner_id,))


async def rule_of(owner_id: int, rule_id: int) -> aiosqlite.Row | None:
    return await _one(
        "SELECT * FROM rules WHERE owner_id = ? AND id = ?", (owner_id, rule_id)
    )


async def add_rule(owner_id: int, triggers: str, reply: str) -> int:
    cur = await _conn().execute(
        "INSERT INTO rules (owner_id, triggers, reply, created_at) VALUES (?, ?, ?, ?)",
        (owner_id, triggers, reply, int(time.time())),
    )
    await _conn().commit()
    return int(cur.lastrowid or 0)


async def update_rule(owner_id: int, rule_id: int, **fields: Any) -> None:
    allowed = ("triggers", "reply", "enabled")
    parts = [f"{k} = ?" for k in allowed if k in fields]
    args = [fields[k] for k in allowed if k in fields]
    if not parts:
        return
    await _run(
        f"UPDATE rules SET {', '.join(parts)} WHERE owner_id = ? AND id = ?",
        (*args, owner_id, rule_id),
    )


async def delete_rule(owner_id: int, rule_id: int) -> None:
    await _run("DELETE FROM rules WHERE owner_id = ? AND id = ?", (owner_id, rule_id))


async def bump_rule(rule_id: int) -> None:
    await _run("UPDATE rules SET hits = hits + 1 WHERE id = ?", (rule_id,))


async def count_rules(owner_id: int) -> int:
    row = await _one("SELECT COUNT(*) AS n FROM rules WHERE owner_id = ?", (owner_id,))
    return int(row["n"]) if row else 0


# --------------------------------------------------------------------------
# Состояние чатов
# --------------------------------------------------------------------------


async def chat_of(owner_id: int, chat_id: int) -> aiosqlite.Row:
    row = await _one(
        "SELECT * FROM chats WHERE owner_id = ? AND chat_id = ?", (owner_id, chat_id)
    )
    if row is not None:
        return row
    await _run(
        "INSERT INTO chats (owner_id, chat_id) VALUES (?, ?) "
        "ON CONFLICT (owner_id, chat_id) DO NOTHING",
        (owner_id, chat_id),
    )
    row = await _one(
        "SELECT * FROM chats WHERE owner_id = ? AND chat_id = ?", (owner_id, chat_id)
    )
    assert row is not None
    return row


async def touch_chat(
    owner_id: int,
    chat_id: int,
    *,
    title: str | None = None,
    username: str | None = None,
    from_owner: bool = False,
) -> aiosqlite.Row:
    """Отметить сообщение в чате и вернуть его состояние.

    from_owner — сообщение написал сам владелец из своего Telegram. Это
    и есть сигнал «человек здесь, бот не нужен»: с этой секунды
    начинается пауза длиной pause_minutes.
    """
    now = int(time.time())
    await chat_of(owner_id, chat_id)
    await _run(
        """
        UPDATE chats SET
            title = COALESCE(?, title),
            username = COALESCE(?, username),
            seen = ?,
            first_seen = CASE WHEN first_seen = 0 THEN ? ELSE first_seen END,
            incoming = incoming + CASE WHEN ? THEN 0 ELSE 1 END,
            owner_seen = CASE WHEN ? THEN ? ELSE owner_seen END
        WHERE owner_id = ? AND chat_id = ?
        """,
        (
            title,
            username,
            now,
            now,
            int(from_owner),
            int(from_owner),
            now,
            owner_id,
            chat_id,
        ),
    )
    return await chat_of(owner_id, chat_id)


async def bump_chat(owner_id: int, chat_id: int, field: str, by: int = 1) -> None:
    """Счётчики поведения собеседника: удаления, правки, срабатывания фильтра.

    Из них собирается карточка «сколько раз этот человек удалял у вас
    сообщения» — то, чего не даёт ни один чужой бот, потому что для
    этого нужно вести историю, а не просто пересылать событие.
    """
    if field not in ("deleted", "edited", "flagged", "replies", "incoming"):
        raise ValueError(f"счётчика {field!r} нет")
    await chat_of(owner_id, chat_id)
    await _run(
        f"UPDATE chats SET {field} = {field} + ? WHERE owner_id = ? AND chat_id = ?",
        (by, owner_id, chat_id),
    )


async def set_muted(
    owner_id: int, chat_id: int, muted: bool, until: int = 0
) -> None:
    """Глухой режим. until — когда снять самому, 0 — пока не снимут."""
    await chat_of(owner_id, chat_id)
    await _run(
        "UPDATE chats SET muted = ?, muted_until = ? WHERE owner_id = ? AND chat_id = ?",
        (int(muted), int(until) if muted else 0, owner_id, chat_id),
    )


async def muted_chats(owner_id: int) -> list[aiosqlite.Row]:
    return await _all(
        "SELECT * FROM chats WHERE owner_id = ? AND muted = 1 ORDER BY seen DESC",
        (owner_id,),
    )


async def expired_mutes(now: int) -> list[aiosqlite.Row]:
    """Муты на время, срок которых вышел, — их снимает фоновая задача."""
    return await _all(
        "SELECT * FROM chats WHERE muted = 1 AND muted_until > 0 AND muted_until <= ?",
        (now,),
    )


async def set_trusted(owner_id: int, chat_id: int, trusted: bool) -> None:
    """Пометить чат доверенным — антискам его больше не проверяет.

    Нужно ровно для одного случая: фильтр ошибся, и владелец нажал «это
    не спам». Без такой кнопки единственным способом договориться с
    фильтром остаётся его отключение целиком.
    """
    await chat_of(owner_id, chat_id)
    await _run(
        "UPDATE chats SET trusted = ? WHERE owner_id = ? AND chat_id = ?",
        (int(trusted), owner_id, chat_id),
    )


async def set_note(owner_id: int, chat_id: int, note: str | None) -> None:
    await chat_of(owner_id, chat_id)
    await _run(
        "UPDATE chats SET note = ? WHERE owner_id = ? AND chat_id = ?",
        (note, owner_id, chat_id),
    )


# --------------------------------------------------------------------------
# Настройки самого бота и рассылки
# --------------------------------------------------------------------------


async def meta_get(key: str, default: str | None = None) -> str | None:
    row = await _one("SELECT value FROM bot_meta WHERE key = ?", (key,))
    return row["value"] if row else default


async def meta_set(key: str, value: str | None) -> None:
    if value is None:
        await _run("DELETE FROM bot_meta WHERE key = ?", (key,))
        return
    await _run(
        "INSERT INTO bot_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


async def owner_chats() -> list[int]:
    """Кому уходит рассылка: все, кто открывал бота или подключал его.

    Личный чат человека с ботом имеет тот же id, что и сам человек,
    поэтому owner_id из настроек — уже готовый адрес. Подключения
    добавляются отдельно: там Telegram присылает user_chat_id, и он
    может отличаться, если бота подключили, ни разу не открыв.
    """
    rows = await _all(
        """
        SELECT owner_id AS chat FROM settings
        UNION
        SELECT user_chat_id AS chat FROM connections
        """
    )
    return [int(r["chat"]) for r in rows if r["chat"]]


async def global_stats() -> dict[str, Any]:
    """Сводка по всему боту — для админской панели."""
    now = int(time.time())

    async def one(sql: str, args: Iterable[Any] = ()) -> int:
        row = await _one(sql, args)
        return int(row["n"] or 0) if row else 0

    return {
        "owners": await one("SELECT COUNT(*) AS n FROM settings"),
        "connected": await one(
            "SELECT COUNT(DISTINCT owner_id) AS n FROM connections WHERE enabled = 1"
        ),
        "connections": await one("SELECT COUNT(*) AS n FROM connections"),
        "new_week": await one(
            "SELECT COUNT(*) AS n FROM connections WHERE created_at >= ?",
            (now - 7 * 86400,),
        ),
        "chats": await one("SELECT COUNT(*) AS n FROM chats WHERE seen > 0"),
        "rules": await one("SELECT COUNT(*) AS n FROM rules"),
        "replies_day": await one(
            "SELECT COUNT(*) AS n FROM log WHERE at >= ?", (now - 86400,)
        ),
        "replies_week": await one(
            "SELECT COUNT(*) AS n FROM log WHERE at >= ?", (now - 7 * 86400,)
        ),
        "replies_all": await one("SELECT COUNT(*) AS n FROM log"),
        "archive": await one("SELECT COUNT(*) AS n FROM messages"),
        "caught_deleted": await one("SELECT SUM(deleted) AS n FROM chats"),
        "caught_edited": await one("SELECT SUM(edited) AS n FROM chats"),
        "flagged": await one("SELECT SUM(flagged) AS n FROM chats"),
        "muted": await one("SELECT COUNT(*) AS n FROM chats WHERE muted = 1"),
        "games": await one("SELECT SUM(wins + losses + draws) AS n FROM scores"),
        "snips": await one("SELECT COUNT(*) AS n FROM snips"),
    }


async def top_owners(limit: int = 5) -> list[aiosqlite.Row]:
    """Самые активные владельцы — по числу автоответов."""
    return await _all(
        """
        SELECT l.owner_id, COUNT(*) AS n,
               (SELECT name FROM connections c WHERE c.owner_id = l.owner_id
                ORDER BY updated_at DESC LIMIT 1) AS name
        FROM log l
        GROUP BY l.owner_id
        ORDER BY n DESC
        LIMIT ?
        """,
        (limit,),
    )


async def start_broadcast(admin_id: int, total: int, preview: str) -> int:
    cur = await _conn().execute(
        """
        INSERT INTO broadcasts (admin_id, started_at, total, preview)
        VALUES (?, ?, ?, ?)
        """,
        (admin_id, int(time.time()), total, preview[:200]),
    )
    await _conn().commit()
    return int(cur.lastrowid or 0)


async def finish_broadcast(
    broadcast_id: int, *, sent: int, failed: int, blocked: int
) -> None:
    await _run(
        """
        UPDATE broadcasts SET finished_at = ?, sent = ?, failed = ?, blocked = ?
        WHERE id = ?
        """,
        (int(time.time()), sent, failed, blocked, broadcast_id),
    )


async def last_broadcasts(limit: int = 5) -> list[aiosqlite.Row]:
    return await _all(
        "SELECT * FROM broadcasts ORDER BY started_at DESC LIMIT ?", (limit,)
    )


# --------------------------------------------------------------------------
# Сохранённый профиль владельца и шаблоны
# --------------------------------------------------------------------------


async def save_profile(
    owner_id: int,
    *,
    first_name: str | None,
    last_name: str | None,
    bio: str | None,
    photo_id: str | None,
) -> None:
    """Запомнить профиль перед клонированием, чтобы было куда вернуться."""
    await _run(
        """
        INSERT INTO profiles (owner_id, first_name, last_name, bio, photo_id, saved_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(owner_id) DO UPDATE SET
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            bio = excluded.bio,
            photo_id = excluded.photo_id,
            saved_at = excluded.saved_at
        """,
        (owner_id, first_name, last_name, bio, photo_id, int(time.time())),
    )


async def profile_of(owner_id: int) -> aiosqlite.Row | None:
    return await _one("SELECT * FROM profiles WHERE owner_id = ?", (owner_id,))


async def set_snip(owner_id: int, name: str, body: str) -> None:
    await _run(
        """
        INSERT INTO snips (owner_id, name, body) VALUES (?, ?, ?)
        ON CONFLICT (owner_id, name) DO UPDATE SET body = excluded.body
        """,
        (owner_id, name.lower(), body),
    )


async def snip_of(owner_id: int, name: str) -> aiosqlite.Row | None:
    row = await _one(
        "SELECT * FROM snips WHERE owner_id = ? AND name = ?", (owner_id, name.lower())
    )
    if row is not None:
        await _run(
            "UPDATE snips SET used = used + 1 WHERE owner_id = ? AND name = ?",
            (owner_id, name.lower()),
        )
    return row


async def snips_of(owner_id: int) -> list[aiosqlite.Row]:
    return await _all(
        "SELECT * FROM snips WHERE owner_id = ? ORDER BY used DESC, name", (owner_id,)
    )


async def drop_snip(owner_id: int, name: str) -> None:
    await _run(
        "DELETE FROM snips WHERE owner_id = ? AND name = ?", (owner_id, name.lower())
    )


# --------------------------------------------------------------------------
# Счёт игр
# --------------------------------------------------------------------------


async def bump_score(owner_id: int, chat_id: int, game: str, result: str) -> None:
    column = {"win": "wins", "loss": "losses", "draw": "draws"}.get(result)
    if column is None:
        raise ValueError(f"результат {result!r} неизвестен")
    await _run(
        f"""
        INSERT INTO scores (owner_id, chat_id, game, {column})
        VALUES (?, ?, ?, 1)
        ON CONFLICT (owner_id, chat_id, game) DO UPDATE SET
            {column} = {column} + 1
        """,
        (owner_id, chat_id, game),
    )


async def score_of(owner_id: int, chat_id: int, game: str) -> dict[str, int]:
    row = await _one(
        "SELECT wins, losses, draws FROM scores "
        "WHERE owner_id = ? AND chat_id = ? AND game = ?",
        (owner_id, chat_id, game),
    )
    if row is None:
        return {"wins": 0, "losses": 0, "draws": 0}
    return {"wins": row["wins"], "losses": row["losses"], "draws": row["draws"]}


async def scores_of(owner_id: int, chat_id: int) -> list[aiosqlite.Row]:
    return await _all(
        "SELECT * FROM scores WHERE owner_id = ? AND chat_id = ? ORDER BY game",
        (owner_id, chat_id),
    )


async def mark_reply(owner_id: int, chat_id: int, rule_id: int | None) -> None:
    await _run(
        """
        UPDATE chats SET
            last_reply = ?,
            last_rule = ?,
            greeted = 1,
            replies = replies + 1
        WHERE owner_id = ? AND chat_id = ?
        """,
        (int(time.time()), int(rule_id or 0), owner_id, chat_id),
    )


async def set_ignored(owner_id: int, chat_id: int, ignored: bool) -> None:
    await chat_of(owner_id, chat_id)
    await _run(
        "UPDATE chats SET ignored = ? WHERE owner_id = ? AND chat_id = ?",
        (int(ignored), owner_id, chat_id),
    )


async def recent_chats(owner_id: int, limit: int) -> list[aiosqlite.Row]:
    return await _all(
        "SELECT * FROM chats WHERE owner_id = ? AND seen > 0 "
        "ORDER BY seen DESC LIMIT ?",
        (owner_id, limit),
    )


# --------------------------------------------------------------------------
# Архив сообщений: то, из чего достаются удалённые
# --------------------------------------------------------------------------


async def save_message(
    owner_id: int,
    chat_id: int,
    message_id: int,
    *,
    from_id: int | None,
    from_name: str | None,
    kind: str,
    text: str | None,
    file_id: str | None,
    at: int | None = None,
) -> None:
    """Положить входящее сообщение в архив.

    ON CONFLICT нужен из-за повторной доставки апдейта: Telegram может
    прислать одно и то же сообщение дважды, если бот не успел ответить
    на getUpdates.
    """
    await _run(
        """
        INSERT INTO messages (
            owner_id, chat_id, message_id, from_id, from_name,
            at, kind, text, file_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (owner_id, chat_id, message_id) DO UPDATE SET
            text = excluded.text,
            kind = excluded.kind,
            file_id = excluded.file_id
        """,
        (
            owner_id,
            chat_id,
            message_id,
            from_id,
            from_name,
            int(at or time.time()),
            kind,
            (text or "")[: config.ARCHIVE_TEXT_LEN],
            file_id,
        ),
    )


async def find_messages(
    owner_id: int, chat_id: int, ids: Iterable[int]
) -> list[aiosqlite.Row]:
    """Найти в архиве сообщения по номерам."""
    ids = [int(i) for i in ids]
    if not ids:
        return []
    holes = ",".join("?" for _ in ids)
    return await _all(
        f"""
        SELECT * FROM messages
        WHERE owner_id = ? AND chat_id = ? AND message_id IN ({holes})
        ORDER BY message_id
        """,
        (owner_id, chat_id, *ids),
    )


async def forget_messages(owner_id: int, chat_id: int, ids: Iterable[int]) -> None:
    """Убрать из архива то, что уже показано владельцу.

    Вызывается только после успешной отправки карточки: если Telegram в
    этот момент недоступен, записи остаются и уйдут сами по сроку
    хранения — лучше так, чем стереть их до того, как о них сообщили.
    """
    ids = [int(i) for i in ids]
    if not ids:
        return
    holes = ",".join("?" for _ in ids)
    await _run(
        f"DELETE FROM messages WHERE owner_id = ? AND chat_id = ? "
        f"AND message_id IN ({holes})",
        (owner_id, chat_id, *ids),
    )


async def message_of(
    owner_id: int, chat_id: int, message_id: int
) -> aiosqlite.Row | None:
    return await _one(
        "SELECT * FROM messages WHERE owner_id = ? AND chat_id = ? AND message_id = ?",
        (owner_id, chat_id, message_id),
    )


async def replace_text(
    owner_id: int, chat_id: int, message_id: int, text: str | None
) -> None:
    """Переписать текст в архиве после правки и посчитать правку."""
    await _run(
        """
        UPDATE messages SET text = ?, edits = edits + 1
        WHERE owner_id = ? AND chat_id = ? AND message_id = ?
        """,
        ((text or "")[: config.ARCHIVE_TEXT_LEN], owner_id, chat_id, message_id),
    )


async def archive_size(owner_id: int) -> int:
    row = await _one(
        "SELECT COUNT(*) AS n FROM messages WHERE owner_id = ?", (owner_id,)
    )
    return int(row["n"]) if row else 0


async def clear_archive(owner_id: int) -> int:
    cur = await _conn().execute("DELETE FROM messages WHERE owner_id = ?", (owner_id,))
    await _conn().commit()
    return cur.rowcount or 0


async def prune_messages() -> int:
    """Убрать записи старше keep_days владельца.

    Срок у каждого свой, поэтому чистка идёт по join с настройками, а
    сообщения владельцев без настроек (подключение было, а панель ни
    разу не открывали) подчищаются заводским сроком.
    """
    now = int(time.time())
    cur = await _conn().execute(
        """
        DELETE FROM messages WHERE at < (
            SELECT ? - COALESCE(
                (SELECT keep_days FROM settings s WHERE s.owner_id = messages.owner_id),
                ?
            ) * 86400
        )
        """,
        (now, config.KEEP_DAYS),
    )
    await _conn().commit()
    return cur.rowcount or 0


# --------------------------------------------------------------------------
# Журнал и статистика
# --------------------------------------------------------------------------


async def log_reply(
    owner_id: int,
    chat_id: int,
    kind: str,
    rule_id: int | None,
    incoming: str,
    text: str,
) -> None:
    await _run(
        """
        INSERT INTO log (at, owner_id, chat_id, kind, rule_id, incoming, text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(time.time()),
            owner_id,
            chat_id,
            kind,
            rule_id,
            incoming[:300],
            text[:600],
        ),
    )


async def stats_of(owner_id: int) -> dict[str, Any]:
    now = int(time.time())
    total = await _one("SELECT COUNT(*) AS n FROM log WHERE owner_id = ?", (owner_id,))
    day = await _one(
        "SELECT COUNT(*) AS n FROM log WHERE owner_id = ? AND at >= ?",
        (owner_id, now - 86400),
    )
    week = await _one(
        "SELECT COUNT(*) AS n FROM log WHERE owner_id = ? AND at >= ?",
        (owner_id, now - 7 * 86400),
    )
    chats = await _one(
        "SELECT COUNT(*) AS n FROM chats WHERE owner_id = ? AND seen > 0", (owner_id,)
    )
    kinds = await _all(
        """
        SELECT kind, COUNT(*) AS n FROM log
        WHERE owner_id = ? AND at >= ?
        GROUP BY kind ORDER BY n DESC
        """,
        (owner_id, now - 7 * 86400),
    )
    return {
        "total": int(total["n"]) if total else 0,
        "day": int(day["n"]) if day else 0,
        "week": int(week["n"]) if week else 0,
        "chats": int(chats["n"]) if chats else 0,
        "kinds": [(r["kind"], int(r["n"])) for r in kinds],
    }


async def last_log(owner_id: int, limit: int = 10) -> list[aiosqlite.Row]:
    return await _all(
        "SELECT * FROM log WHERE owner_id = ? ORDER BY at DESC LIMIT ?",
        (owner_id, limit),
    )


async def prune_log(days: int) -> int:
    cur = await _conn().execute(
        "DELETE FROM log WHERE at < ?", (int(time.time()) - days * 86400,)
    )
    await _conn().commit()
    return cur.rowcount or 0


# --------------------------------------------------------------------------
# След: журнал удалённого и правок по чату
# --------------------------------------------------------------------------
#
# Архив messages отдаёт сообщение один раз: показали карточку — запись
# стёрта. А команды .удалённые и .правки должны поднять историю по
# чату и через час. Поэтому сам факт удаления или правки ложится сюда и
# живёт столько же, сколько архив, — keep_days владельца.


async def add_trail(
    owner_id: int,
    chat_id: int,
    event: str,
    *,
    kind: str = "text",
    text: str | None = None,
    before: str | None = None,
    file_id: str | None = None,
    at: int | None = None,
) -> None:
    if event not in ("del", "edit"):
        raise ValueError(f"события {event!r} нет")
    await _run(
        """
        INSERT INTO trail (owner_id, chat_id, at, event, kind, text, before, file_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            owner_id,
            chat_id,
            int(at or time.time()),
            event,
            kind,
            (text or "")[: config.ARCHIVE_TEXT_LEN],
            (before or "")[: config.ARCHIVE_TEXT_LEN] or None,
            file_id,
        ),
    )


async def trail_of(
    owner_id: int, chat_id: int, event: str, limit: int = 10
) -> list[aiosqlite.Row]:
    """Последние события по чату — старые сверху, как в переписке."""
    rows = await _all(
        """
        SELECT * FROM trail WHERE owner_id = ? AND chat_id = ? AND event = ?
        ORDER BY at DESC, id DESC LIMIT ?
        """,
        (owner_id, chat_id, event, limit),
    )
    return rows[::-1]


async def prune_trail() -> int:
    now = int(time.time())
    cur = await _conn().execute(
        """
        DELETE FROM trail WHERE at < (
            SELECT ? - COALESCE(
                (SELECT keep_days FROM settings s WHERE s.owner_id = trail.owner_id),
                ?
            ) * 86400
        )
        """,
        (now, config.KEEP_DAYS),
    )
    await _conn().commit()
    return cur.rowcount or 0


# --------------------------------------------------------------------------
# Таймеры: напоминания и отложенная отправка
# --------------------------------------------------------------------------
#
# Хранятся в базе, а не в asyncio-задачах: перезапуск бота не должен
# терять напоминание, поставленное на вечер.

#: Сколько таймеров может висеть у одного владельца.
MAX_TIMERS = 30


async def add_timer(
    owner_id: int,
    due: int,
    action: str,
    *,
    chat_id: int | None = None,
    conn_id: str | None = None,
    title: str | None = None,
    text: str | None = None,
) -> int:
    if action not in ("remind", "send"):
        raise ValueError(f"таймера {action!r} нет")
    cur = await _conn().execute(
        """
        INSERT INTO timers (owner_id, due, action, chat_id, conn_id, title, text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (owner_id, int(due), action, chat_id, conn_id, title, text),
    )
    await _conn().commit()
    return int(cur.lastrowid)


async def timers_of(owner_id: int) -> list[aiosqlite.Row]:
    return await _all(
        "SELECT * FROM timers WHERE owner_id = ? ORDER BY due", (owner_id,)
    )


async def count_timers(owner_id: int) -> int:
    row = await _one("SELECT COUNT(*) AS n FROM timers WHERE owner_id = ?", (owner_id,))
    return int(row["n"]) if row else 0


async def due_timers(now: int) -> list[aiosqlite.Row]:
    return await _all("SELECT * FROM timers WHERE due <= ? ORDER BY due", (now,))


async def drop_timer(owner_id: int, timer_id: int) -> bool:
    cur = await _conn().execute(
        "DELETE FROM timers WHERE owner_id = ? AND id = ?", (owner_id, timer_id)
    )
    await _conn().commit()
    return bool(cur.rowcount)


# --------------------------------------------------------------------------
# Обязательная подписка: спонсоры
# --------------------------------------------------------------------------


async def sponsors() -> list[aiosqlite.Row]:
    return await _all("SELECT * FROM sponsors ORDER BY added_at")


async def add_sponsor(chat_id: int, title: str, url: str) -> None:
    await _run(
        """
        INSERT INTO sponsors (chat_id, title, url, added_at) VALUES (?, ?, ?, ?)
        ON CONFLICT (chat_id) DO UPDATE SET title = excluded.title, url = excluded.url
        """,
        (chat_id, title, url, int(time.time())),
    )


async def drop_sponsor(chat_id: int) -> None:
    await _run("DELETE FROM sponsors WHERE chat_id = ?", (chat_id,))


# --------------------------------------------------------------------------
# Зеркала и пользователи по ботам
# --------------------------------------------------------------------------


async def add_mirror(owner_id: int, bot_id: int, token: str, username: str, title: str) -> int:
    cur = await _conn().execute(
        """
        INSERT INTO mirrors (owner_id, bot_id, token, username, title, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (bot_id) DO UPDATE SET
            owner_id = excluded.owner_id, token = excluded.token,
            username = excluded.username, title = excluded.title, active = 1
        """,
        (owner_id, bot_id, token, username, title, int(time.time())),
    )
    await _conn().commit()
    row = await mirror_by_bot(bot_id)
    return int(row["id"]) if row else int(cur.lastrowid)


async def mirror_by_bot(bot_id: int) -> aiosqlite.Row | None:
    return await _one("SELECT * FROM mirrors WHERE bot_id = ?", (bot_id,))


async def mirror_of(mirror_id: int) -> aiosqlite.Row | None:
    return await _one("SELECT * FROM mirrors WHERE id = ?", (mirror_id,))


async def mirrors_of(owner_id: int) -> list[aiosqlite.Row]:
    return await _all(
        "SELECT * FROM mirrors WHERE owner_id = ? ORDER BY id", (owner_id,)
    )


async def active_mirrors() -> list[aiosqlite.Row]:
    return await _all("SELECT * FROM mirrors WHERE active = 1 ORDER BY id")


async def all_mirrors() -> list[aiosqlite.Row]:
    return await _all("SELECT * FROM mirrors ORDER BY id")


async def set_mirror(mirror_id: int, **fields: Any) -> None:
    allowed = {"token", "username", "title", "active"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"поля {bad} нет")
    sets = ", ".join(f"{k} = ?" for k in fields)
    await _run(f"UPDATE mirrors SET {sets} WHERE id = ?", (*fields.values(), mirror_id))


async def drop_mirror(mirror_id: int) -> None:
    await _run("DELETE FROM mirrors WHERE id = ?", (mirror_id,))


async def seen_user(bot_id: int, user_id: int) -> None:
    """Человек написал боту — запомнить, через какого бота с ним говорить."""
    await _run(
        """
        INSERT INTO bot_users (bot_id, user_id, first_seen) VALUES (?, ?, ?)
        ON CONFLICT (bot_id, user_id) DO UPDATE SET blocked = 0
        """,
        (bot_id, user_id, int(time.time())),
    )


async def mark_blocked(bot_id: int, user_id: int) -> None:
    await _run(
        "UPDATE bot_users SET blocked = 1 WHERE bot_id = ? AND user_id = ?",
        (bot_id, user_id),
    )


async def bot_audience() -> list[aiosqlite.Row]:
    """Все, кому можно написать, — с ботом, через которого писать."""
    return await _all("SELECT bot_id, user_id FROM bot_users WHERE blocked = 0")


async def users_count(bot_id: int) -> tuple[int, int]:
    """(всего, за неделю) людей у бота — для кабинета зеркала."""
    week = int(time.time()) - 7 * 86400
    row = await _one(
        """
        SELECT COUNT(*) AS n, SUM(CASE WHEN first_seen >= ? THEN 1 ELSE 0 END) AS w
        FROM bot_users WHERE bot_id = ?
        """,
        (week, bot_id),
    )
    return (int(row["n"] or 0), int(row["w"] or 0)) if row else (0, 0)


async def connections_count(bot_id: int) -> int:
    row = await _one(
        "SELECT COUNT(*) AS n FROM connections WHERE bot_id = ? AND enabled = 1",
        (bot_id,),
    )
    return int(row["n"]) if row else 0


async def seed_audience(bot_id: int) -> None:
    """Люди из версии без зеркал — аудитория основного бота.

    Раньше адресатом рассылки был owner_id из настроек и подключений; с
    зеркалами нужен ещё и бот, через которого писать. Всех, кто был до
    них, записываем за основным — один раз, повторы игнорируются.
    """
    if await meta_get("audience_seeded"):
        return
    now = int(time.time())
    for chat in await owner_chats():
        await _conn().execute(
            "INSERT OR IGNORE INTO bot_users (bot_id, user_id, first_seen) VALUES (?, ?, ?)",
            (bot_id, chat, now),
        )
    await _conn().commit()
    await meta_set("audience_seeded", "1")
