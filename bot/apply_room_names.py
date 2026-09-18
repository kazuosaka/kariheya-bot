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


def patch_ui(text: str) -> str:
    if f'ROOM_NAME_PREFIX = "{ROOM}"' in text and "SECRET_ROOM_NAME_PREFIX" in text:
        return text
    if "ROOM_NAME_PREFIX =" in text:
        lines = text.splitlines(keepends=True)
        out: list[str] = []
        replaced = False
        for line in lines:
            if line.startswith("ROOM_NAME_PREFIX =") and not replaced:
                out.append(f'ROOM_NAME_PREFIX = "{ROOM}"\n')
                if "SECRET_ROOM_NAME_PREFIX" not in text:
                    out.append(f'SECRET_ROOM_NAME_PREFIX = "{SECRET_ROOM}"\n')
                replaced = True
                continue
            out.append(line)
        updated = "".join(out)
        must_compile(updated, "ui.py")
        return updated
    raise PatchError("ui.py: ROOM_NAME_PREFIX not found")


def patch_db(text: str) -> str:
    text = unique_replace(
        text,
        f"DEFAULT '{OLD_ROOM}'",
        f"DEFAULT '{ROOM}'",
        "db.py alter default",
        skip_if=f"DEFAULT '{ROOM}'",
        optional=True,
    )
    if "secret_room_prefix" not in text.split("async def", 1)[0] and "ADD COLUMN secret_room_prefix" not in text:
        text = unique_replace(
            text,
            '        if "announce_enabled" not in gcols:\n            await self._db.execute(\n                "ALTER TABLE guild_settings ADD COLUMN announce_enabled INTEGER NOT NULL DEFAULT 1"\n            )\n',
            '        if "announce_enabled" not in gcols:\n            await self._db.execute(\n                "ALTER TABLE guild_settings ADD COLUMN announce_enabled INTEGER NOT NULL DEFAULT 1"\n            )\n        if "secret_room_prefix" not in gcols:\n            await self._db.execute(\n                "ALTER TABLE guild_settings ADD COLUMN secret_room_prefix TEXT NOT NULL DEFAULT \'' + SECRET_ROOM + '\'"\n            )\n',
            "db.py secret_room_prefix column",
            optional=True,
        )
        if "ADD COLUMN secret_room_prefix" not in text:
            text = unique_replace(
                text,
                '        cur = await self._db.execute("PRAGMA user_version")\n',
                '        if "secret_room_prefix" not in gcols:\n            await self._db.execute(\n                "ALTER TABLE guild_settings ADD COLUMN secret_room_prefix TEXT NOT NULL DEFAULT \'' + SECRET_ROOM + '\'"\n            )\n        cur = await self._db.execute("PRAGMA user_version")\n',
                "db.py secret_room_prefix before user_version",
            )
    text = unique_replace(
        text,
        "room_prefix, hub_prefix, announce_enabled FROM guild_settings",
        "room_prefix, hub_prefix, announce_enabled, secret_room_prefix FROM guild_settings",
        "db.py get_settings select",
        skip_if="secret_room_prefix FROM guild_settings",
        optional=True,
    )
    if "PRAGMA user_version = 2" not in text:
        text = unique_replace(
            text,
            '            await self._db.execute("PRAGMA user_version = 1")\n        await self._db.commit()\n',
            '            await self._db.execute("PRAGMA user_version = 1")\n            schema_ver = 1\n        if schema_ver < 2:\n            await self._db.execute(\n                "UPDATE guild_settings SET room_prefix = \'' + ROOM + '\' WHERE room_prefix = \'' + OLD_ROOM + '\'"\n            )\n            await self._db.execute("PRAGMA user_version = 2")\n        await self._db.commit()\n',
            "db.py migrate prefix",
            optional=True,
        )
    span = method_span(text, "get_room_prefix")
    if span is None:
        raise PatchError("db.py: get_room_prefix not found")
    start, end = span
    existing = "".join(text.splitlines(keepends=True)[start:end])
    if "secret: bool = False" not in existing:
        text = replace_method(text, "get_room_prefix", GET_ROOM_PREFIX, "db.py get_room_prefix")
    if method_span(text, "get_secret_room_prefix") is None:
        span = method_span(text, "get_room_prefix")
        assert span is not None
        _, end = span
        lines = text.splitlines(keepends=True)
        insert = GET_SECRET_PREFIX if GET_SECRET_PREFIX.endswith("\n") else GET_SECRET_PREFIX + "\n"
        text = "".join(lines[:end]) + "\n" + insert + "".join(lines[end:])
        must_compile(text, "db.py get_secret_room_prefix")
    return text


def patch_lifecycle(text: str) -> str:
    return unique_replace(
        text,
        "prefix = await self.store.get_room_prefix(guild.id)",
        "prefix = await self.store.get_room_prefix(guild.id, secret=secret)",
        "lifecycle.py prefix",
        skip_if="get_room_prefix(guild.id, secret=secret)",
        optional=True,
    )


def patch_main(text: str) -> str:
    if "get_secret_room_prefix" in text:
        return text
    text = unique_replace(
        text,
        "    prefix = await bot.store.get_room_prefix(interaction.guild.id)\n    hub_prefix = await bot.store.get_hub_prefix(interaction.guild.id)\n",
        "    prefix = await bot.store.get_room_prefix(interaction.guild.id)\n    secret_prefix = await bot.store.get_secret_room_prefix(interaction.guild.id)\n    hub_prefix = await bot.store.get_hub_prefix(interaction.guild.id)\n",
        "main.py show vars",
        optional=True,
    )
    old = "        f\"\u90e8\u5c4b\u306e\u30c7\u30d5\u30a9\u30eb\u30c8\u540d: **{prefix}_n**\\n\"\n"
    new = old + "        f\"\u79d8\u5bc6\u306e\u90e8\u5c4b\u306e\u30c7\u30d5\u30a9\u30eb\u30c8\u540d: **{secret_prefix}_n**\\n\"\n"
    return unique_replace(text, old, new, "main.py show text", optional=True)


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


def main() -> int:
    try:
        apply_file("ui.py", patch_ui)
        apply_file("db.py", patch_db)
        apply_file("lifecycle.py", patch_lifecycle)
        if (ROOT / "main.py").is_file():
            apply_file("main.py", patch_main)
    except PatchError as exc:
        print(f"PATCH FAILED: {exc}")
        return 1
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
