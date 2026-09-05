from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import aiosqlite

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "rooms.db"


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")
        await self._db.execute("PRAGMA foreign_keys=ON;")
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                category_id INTEGER,
                grace_seconds INTEGER NOT NULL DEFAULT 20
            );

            CREATE TABLE IF NOT EXISTS allowed_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            );

            CREATE TABLE IF NOT EXISTS rooms (
                voice_id INTEGER PRIMARY KEY,
                text_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL,
                user_limit INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                occupied INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS hubs (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                user_limit INTEGER NOT NULL
            );
            """
        )
        cur = await self._db.execute("PRAGMA table_info(rooms)")
        cols = {row[1] for row in await cur.fetchall()}
        if "occupied" not in cols:
            await self._db.execute(
                "ALTER TABLE rooms ADD COLUMN occupied INTEGER NOT NULL DEFAULT 0"
            )
        await self._db.commit()

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("database is not connected")
        return self._db

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def get_settings(self, guild_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT guild_id, category_id, grace_seconds FROM guild_settings WHERE guild_id = ?",
            (guild_id,),
        )
        return await cur.fetchone()

    async def upsert_category(self, guild_id: int, category_id: int) -> None:
        await self.db.execute(
            """
            INSERT INTO guild_settings (guild_id, category_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET category_id = excluded.category_id
            """
            ,
            (guild_id, category_id),
        )
        await self.db.commit()

    async def add_role(self, guild_id: int, role_id: int) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO allowed_roles (guild_id, role_id) VALUES (?, ?)",
            (guild_id, role_id),
        )
        await self.db.commit()

    async def remove_role(self, guild_id: int, role_id: int) -> None:
        await self.db.execute(
            "DELETE FROM allowed_roles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )
        await self.db.commit()

    async def list_roles(self, guild_id: int) -> list[int]:
        cur = await self.db.execute(
            "SELECT role_id FROM allowed_roles WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cur.fetchall()
        return [int(row["role_id"]) for row in rows]

    async def upsert_hub(self, channel_id: int, guild_id: int, user_limit: int) -> None:
        await self.db.execute(
            """
            INSERT INTO hubs (channel_id, guild_id, user_limit)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                user_limit = excluded.user_limit
            """
            ,
            (channel_id, guild_id, user_limit),
        )
        await self.db.commit()

    async def get_hub(self, channel_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT channel_id, guild_id, user_limit FROM hubs WHERE channel_id = ?",
            (channel_id,),
        )
        return await cur.fetchone()

    async def get_hub_by_limit(self, guild_id: int, user_limit: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT channel_id, guild_id, user_limit FROM hubs WHERE guild_id = ? AND user_limit = ?",
            (guild_id, user_limit),
        )
        return await cur.fetchone()

    async def list_hubs(self, guild_id: int) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            "SELECT channel_id, guild_id, user_limit FROM hubs WHERE guild_id = ? ORDER BY user_limit",
            (guild_id,),
        )
        return await cur.fetchall()

    async def delete_hub(self, channel_id: int) -> None:
        await self.db.execute("DELETE FROM hubs WHERE channel_id = ?", (channel_id,))
        await self.db.commit()

    async def get_room_by_owner(self, guild_id: int, owner_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM rooms WHERE guild_id = ? AND owner_id = ?",
            (guild_id, owner_id),
        )
        return await cur.fetchone()

    async def add_room(
        self,
        *,
        voice_id: int,
        text_id: int,
        guild_id: int,
        owner_id: int,
        user_limit: int,
        created_at: int,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO rooms (voice_id, text_id, guild_id, owner_id, user_limit, created_at, occupied)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """
            ,
            (voice_id, text_id, guild_id, owner_id, user_limit, created_at),
        )
        await self.db.commit()

    async def get_room_by_voice(self, voice_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM rooms WHERE voice_id = ?",
            (voice_id,),
        )
        return await cur.fetchone()

    async def mark_occupied(self, voice_id: int) -> None:
        await self.db.execute(
            "UPDATE rooms SET occupied = 1 WHERE voice_id = ?",
            (voice_id,),
        )
        await self.db.commit()

    async def get_room_by_text(self, text_id: int) -> aiosqlite.Row | None:
        cur = await self.db.execute(
            "SELECT * FROM rooms WHERE text_id = ?",
            (text_id,),
        )
        return await cur.fetchone()

    async def list_rooms(self, guild_id: int | None = None) -> list[aiosqlite.Row]:
        if guild_id is None:
            cur = await self.db.execute("SELECT * FROM rooms")
        else:
            cur = await self.db.execute(
                "SELECT * FROM rooms WHERE guild_id = ?",
                (guild_id,),
            )
        return await cur.fetchall()

    async def delete_room(self, voice_id: int) -> None:
        await self.db.execute("DELETE FROM rooms WHERE voice_id = ?", (voice_id,))
        await self.db.commit()

    async def delete_rooms(self, voice_ids: Iterable[int]) -> None:
        ids = list(voice_ids)
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        await self.db.execute(
            f"DELETE FROM rooms WHERE voice_id IN ({placeholders})",
            ids,
        )
        await self.db.commit()
