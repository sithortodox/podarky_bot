"""Асинхронный доступ к SQLite + модуль-синглтон `db`."""
from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from app.config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  user_id INTEGER PRIMARY KEY,
  username TEXT, full_name TEXT,
  stage TEXT DEFAULT 'start',
  dice_value INTEGER, gift_id INTEGER,
  shots INTEGER DEFAULT 0,
  paid INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS gifts(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL,
  link TEXT DEFAULT '', image TEXT DEFAULT '', note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sponsors(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT NOT NULL, title TEXT NOT NULL, url TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER, stage TEXT, created_at TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self.texts_cache: dict[str, str] = {}

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.executemany(
            "INSERT OR IGNORE INTO gifts(id,title) VALUES(?,?)",
            [(i, f"Подарок №{i}") for i in range(1, 7)],
        )
        await self.conn.commit()
        await self.reload_texts()

    async def reload_texts(self) -> None:
        rows = await self.execute("SELECT key, value FROM settings")
        self.texts_cache = {
            r["key"]: r["value"]
            for r in rows
            if r["key"].startswith("text_")
        }
        # ключи вида text_start_caption -> start_caption
        self.texts_cache = {k[5:]: v for k, v in self.texts_cache.items()}

    async def execute(self, sql: str, args: tuple = ()) -> list[aiosqlite.Row]:
        assert self.conn is not None
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return await cur.fetchall()

    async def rows(self, sql: str, args: tuple = ()) -> list[aiosqlite.Row]:
        assert self.conn is not None
        cur = await self.conn.execute(sql, args)
        return await cur.fetchall()

    async def one(self, sql: str, args: tuple = ()) -> aiosqlite.Row | None:
        rows = await self.rows(sql, args)
        return rows[0] if rows else None

    async def scalar(self, sql: str, args: tuple = (), default=0):
        row = await self.one(sql, args)
        return (row[0] if row and row[0] is not None else default) if row else default

    async def touch_user(self, user_id: int, username: str | None, full_name: str, stage: str | None = None, log: bool = True) -> None:
        await self.execute(
            "INSERT INTO users(user_id,username,full_name,stage,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
            "username=COALESCE(excluded.username, users.username), "
            "full_name=CASE WHEN excluded.full_name='' THEN users.full_name ELSE excluded.full_name END, "
            "updated_at=excluded.updated_at",
            (user_id, username, full_name, stage or "start", now(), now()),
        )
        if stage:
            await self.execute(
                "UPDATE users SET stage=?, updated_at=? WHERE user_id=?", (stage, now(), user_id)
            )
            if log:
                await self.execute(
                    "INSERT INTO events(user_id,stage,created_at) VALUES(?,?,?)",
                    (user_id, stage, now()),
                )

    async def set_setting(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        if key.startswith("text_"):
            self.texts_cache[key[5:]] = value

    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self.one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()


db = Database(Config.from_env().db_path)