"""Add weekly/monthly start-count stats. Never saves invalid Python."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class PatchError(Exception):
    pass


def read_py(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    text = data.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), newline


def encode_py(text: str, newline: str) -> bytes:
    if not text.endswith("\n"):
        text += "\n"
    return text.replace("\n", newline).encode("utf-8")


def must_compile(text: str, label: str) -> None:
    try:
        ast.parse(text, filename=label)
    except SyntaxError as exc:
        raise PatchError(f"{label}:{exc.lineno}: {exc.msg}") from exc


def unique_replace(
    text: str,
    old: str,
    new: str,
    label: str,
    skip_if: str | None = None,
    optional: bool = False,
) -> str:
    if skip_if and skip_if in text:
        return text
    if old not in text:
        if new in text or optional:
            return text
        raise PatchError(f"{label}: target not found")
    if text.count(old) > 1:
        raise PatchError(f"{label}: target matched more than once")
    updated = text.replace(old, new, 1)
    must_compile(updated, label)
    return updated


def method_span(text: str, name: str) -> tuple[int, int] | None:
    lines = text.splitlines(keepends=True)
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if line.startswith(f"    async def {name}(") or line.startswith(f"    def {name}(")
        ),
        None,
    )
    if start is None:
        return None
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.startswith("    async def ") or line.startswith("    def ") or line.startswith("    @"):
            break
        if line.startswith("class "):
            break
        end += 1
    return start, end


DDL = '''
            CREATE TABLE IF NOT EXISTS room_starts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                started_at INTEGER NOT NULL,
                secret INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_room_starts_guild_time
                ON room_starts (guild_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_room_starts_guild_user
                ON room_starts (guild_id, user_id, started_at);
'''

ADD_ROOM_INSERT = '''
        await self.db.execute(
            """
            INSERT INTO room_starts (guild_id, user_id, started_at, secret)
            VALUES (?, ?, ?, ?)
            """,
            (guild_id, owner_id, created_at, 1 if secret else 0),
        )
'''

METHODS = '''
    async def count_room_starts(
        self,
        guild_id: int,
        start_ts: int,
        end_ts: int,
        limit: int = 25,
    ) -> list[aiosqlite.Row]:
        cur = await self.db.execute(
            """
            SELECT user_id, COUNT(*) AS cnt
            FROM room_starts
            WHERE guild_id = ? AND started_at >= ? AND started_at < ?
            GROUP BY user_id
            ORDER BY cnt DESC, user_id ASC
            LIMIT ?
            """,
            (guild_id, start_ts, end_ts, limit),
        )
        return await cur.fetchall()

    async def count_room_starts_total(
        self,
        guild_id: int,
        start_ts: int,
        end_ts: int,
    ) -> tuple[int, int]:
        cur = await self.db.execute(
            """
            SELECT COUNT(*) AS starts, COUNT(DISTINCT user_id) AS users
            FROM room_starts
            WHERE guild_id = ? AND started_at >= ? AND started_at < ?
            """,
            (guild_id, start_ts, end_ts),
        )
        row = await cur.fetchone()
        if row is None:
            return 0, 0
        return int(row["starts"]), int(row["users"])

    async def count_room_starts_for_user(
        self,
        guild_id: int,
        user_id: int,
        start_ts: int,
        end_ts: int,
    ) -> int:
        cur = await self.db.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM room_starts
            WHERE guild_id = ? AND user_id = ? AND started_at >= ? AND started_at < ?
            """,
            (guild_id, user_id, start_ts, end_ts),
        )
        row = await cur.fetchone()
        return int(row["cnt"]) if row is not None else 0
'''


def patch_db(text: str) -> str:
    if "CREATE TABLE IF NOT EXISTS room_starts" not in text:
        text = unique_replace(
            text,
            "            CREATE TABLE IF NOT EXISTS disabled_guilds (\n                guild_id INTEGER PRIMARY KEY\n            );\n",
            "            CREATE TABLE IF NOT EXISTS disabled_guilds (\n                guild_id INTEGER PRIMARY KEY\n            );\n"
            + DDL,
            "db.py room_starts ddl",
        )
    if "INSERT INTO room_starts" not in text:
        text = unique_replace(
            text,
            "            (voice_id, text_id, guild_id, owner_id, user_limit, created_at, 1 if secret else 0),\n        )\n        await self.db.commit()\n",
            "            (voice_id, text_id, guild_id, owner_id, user_limit, created_at, 1 if secret else 0),\n        )"
            + ADD_ROOM_INSERT
            + "        await self.db.commit()\n",
            "db.py add_room insert",
        )
    if "async def count_room_starts(" not in text:
        span = method_span(text, "delete_rooms")
        if span is None:
            raise PatchError("db.py: delete_rooms not found")
        _, end = span
        lines = text.splitlines(keepends=True)
        text = "".join(lines[:end]) + METHODS + "".join(lines[end:])
        must_compile(text, "db.py methods")
    return text


def patch_main(text: str) -> str:
    if "from stats import register_stats" not in text:
        if "from category_lock import register_setup_lock\n" in text:
            text = unique_replace(
                text,
                "from category_lock import register_setup_lock\n",
                "from category_lock import register_setup_lock\nfrom stats import register_stats\n",
                "main.py import lock",
            )
        else:
            text = unique_replace(
                text,
                "from secret import is_secret_row, register_setup_secrethub\n",
                "from secret import is_secret_row, register_setup_secrethub\nfrom stats import register_stats\n",
                "main.py import secret",
                optional=True,
            )
            if "from stats import register_stats" not in text:
                text = unique_replace(
                    text,
                    "from grace import register_setup_grace\n",
                    "from grace import register_setup_grace\nfrom stats import register_stats\n",
                    "main.py import grace",
                )
    if "register_stats(bot)" not in text:
        text = unique_replace(
            text,
            "bot.tree.add_command(setup)\nbot.tree.add_command(room)\n",
            "bot.tree.add_command(setup)\nbot.tree.add_command(room)\nbot.tree.add_command(register_stats(bot))\n",
            "main.py add stats command",
        )
    return text


def apply_file(name: str, patcher) -> None:
    path = ROOT / name
    if not path.is_file():
        raise PatchError(f"{name} not found")
    original, newline = read_py(path)
    try:
        updated = patcher(original)
        must_compile(updated, name)
        if updated != original:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(encode_py(updated, newline))
            tmp.replace(path)
            print(f"updated {name}")
        else:
            print(f"unchanged {name}")
    except Exception:
        path.write_bytes(encode_py(original, newline))
        raise


def write_stats_py() -> None:
    src = Path(__file__).with_name("stats.py")
    if not src.is_file():
        raise PatchError("stats.py is missing. Download it next to this script.")
    must_compile(src.read_text(encoding="utf-8"), "stats.py")
    print("ok stats.py")


def main() -> int:
    try:
        write_stats_py()
        apply_file("db.py", patch_db)
        apply_file("main.py", patch_main)
    except PatchError as exc:
        print(f"PATCH FAILED: {exc}")
        return 1
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
