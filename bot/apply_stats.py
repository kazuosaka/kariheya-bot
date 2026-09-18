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
