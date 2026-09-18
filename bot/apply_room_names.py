"""Set default room names. Missing snippets are skipped. Never saves invalid Python."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROOM = "\u97f3\u58f0\u901a\u8a71"
SECRET_ROOM = "\u97f3\u58f0\u901a\u8a71\uff08\u79d8\u5bc6\uff09"
OLD_ROOM = "\u4eee\u97f3\u58f0\u901a\u8a71"


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


def unique_replace(text: str, old: str, new: str, label: str, skip_if: str | None = None, optional: bool = False) -> str:
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


def replace_method(text: str, name: str, new_src: str, label: str) -> str:
    span = method_span(text, name)
    if span is None:
        raise PatchError(f"{label}: method {name} not found")
    start, end = span
    lines = text.splitlines(keepends=True)
    block = new_src if new_src.endswith("\n") else new_src + "\n"
    if not block.endswith("\n\n") and end < len(lines) and lines[end].startswith("    "):
        block += "\n"
    updated = "".join(lines[:start]) + block + "".join(lines[end:])
    must_compile(updated, label)
    return updated


GET_ROOM_PREFIX = f'''    async def get_room_prefix(self, guild_id: int, secret: bool = False) -> str:
        if secret:
            return await self.get_secret_room_prefix(guild_id)
        settings = await self.get_settings(guild_id)
        if settings is None:
            return "{ROOM}"
        prefix = str(settings["room_prefix"] or "").strip()
        if prefix == "{OLD_ROOM}":
            return "{ROOM}"
        return prefix or "{ROOM}"
'''

GET_SECRET_PREFIX = f'''    async def get_secret_room_prefix(self, guild_id: int) -> str:
        settings = await self.get_settings(guild_id)
        if settings is None:
            return "{SECRET_ROOM}"
        try:
            prefix = str(settings["secret_room_prefix"] or "").strip()
        except (KeyError, IndexError):
            prefix = ""
        return prefix or "{SECRET_ROOM}"
'''
