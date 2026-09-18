"""Set default room names. Refuses to save invalid Python."""
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


def unique_replace(text: str, old: str, new: str, label: str, skip_if: str | None = None) -> str:
    if skip_if and skip_if in text:
        return text
    if old not in text:
        if new in text:
            return text
        raise PatchError(f"{label}: target not found")
    if text.count(old) > 1:
        raise PatchError(f"{label}: target matched more than once")
    updated = text.replace(old, new, 1)
    must_compile(updated, label)
    return updated


def patch_ui(text: str) -> str:
    return unique_replace(
        text,
        f'ROOM_NAME_PREFIX = "{OLD_ROOM}"',
        f'ROOM_NAME_PREFIX = "{ROOM}"\nSECRET_ROOM_NAME_PREFIX = "{SECRET_ROOM}"',
        "ui.py prefix",
        skip_if=f'ROOM_NAME_PREFIX = "{ROOM}"',
    )


def patch_lifecycle(text: str) -> str:
    return unique_replace(
        text,
        "prefix = await self.store.get_room_prefix(guild.id)",
        "prefix = await self.store.get_room_prefix(guild.id, secret=secret)",
        "lifecycle.py prefix",
        skip_if="get_room_prefix(guild.id, secret=secret)",
    )


def patch_db(text: str) -> str:
    text = unique_replace(
        text,
        f"DEFAULT '{OLD_ROOM}'",
        f"DEFAULT '{ROOM}'",
        "db.py alter default",
        skip_if=f"DEFAULT '{ROOM}'",
    )
    if "secret_room_prefix" not in text:
        needle = (
            '        if "announce_enabled" not in gcols:\n'
            '            await self._db.execute(\n'
            '                "ALTER TABLE guild_settings ADD COLUMN announce_enabled INTEGER NOT NULL DEFAULT 1"\n'
            '            )\n'
        )
        insert = needle + (
            '        if "secret_room_prefix" not in gcols:\n'
            '            await self._db.execute(\n'
            f'                "ALTER TABLE guild_settings ADD COLUMN secret_room_prefix TEXT NOT NULL DEFAULT \'{SECRET_ROOM}\'"\n'
            '            )\n'
        )
        text = unique_replace(text, needle, insert, "db.py secret_room_prefix column")
    if "PRAGMA user_version = 2" not in text:
        old = (
            '            await self._db.execute("PRAGMA user_version = 1")\n'
            '        await self._db.commit()\n'
        )
        new = (
            '            await self._db.execute("PRAGMA user_version = 1")\n'
            '            schema_ver = 1\n'
            '        if schema_ver < 2:\n'
            '            await self._db.execute(\n'
            f'                "UPDATE guild_settings SET room_prefix = \'{ROOM}\' WHERE room_prefix = \'{OLD_ROOM}\'"\n'
            '            )\n'
            '            await self._db.execute("PRAGMA user_version = 2")\n'
            '        await self._db.commit()\n'
        )
        text = unique_replace(text, old, new, "db.py migrate prefix")
    text = unique_replace(
        text,
        "room_prefix, hub_prefix, announce_enabled FROM guild_settings",
        "room_prefix, hub_prefix, announce_enabled, secret_room_prefix FROM guild_settings",
        "db.py get_settings select",
        skip_if="secret_room_prefix FROM guild_settings",
    )
    old_fn = (
        '    async def get_room_prefix(self, guild_id: int) -> str:\n'
        '        settings = await self.get_settings(guild_id)\n'
        '        if settings is None:\n'
        f'            return "{OLD_ROOM}"\n'
        '        prefix = str(settings["room_prefix"] or "").strip()\n'
        f'        return prefix or "{OLD_ROOM}"\n'
    )
    new_fn = (
        '    async def get_room_prefix(self, guild_id: int, secret: bool = False) -> str:\n'
        '        if secret:\n'
        '            return await self.get_secret_room_prefix(guild_id)\n'
        '        settings = await self.get_settings(guild_id)\n'
        '        if settings is None:\n'
        f'            return "{ROOM}"\n'
        '        prefix = str(settings["room_prefix"] or "").strip()\n'
        f'        if prefix == "{OLD_ROOM}":\n'
        f'            return "{ROOM}"\n'
        f'        return prefix or "{ROOM}"\n'
        '\n'
        '    async def get_secret_room_prefix(self, guild_id: int) -> str:\n'
        '        settings = await self.get_settings(guild_id)\n'
        '        if settings is None:\n'
        f'            return "{SECRET_ROOM}"\n'
        '        try:\n'
        '            prefix = str(settings["secret_room_prefix"] or "").strip()\n'
        '        except (KeyError, IndexError):\n'
        '            prefix = ""\n'
        f'        return prefix or "{SECRET_ROOM}"\n'
    )
    text = unique_replace(
        text,
        old_fn,
        new_fn,
        "db.py get_room_prefix",
        skip_if="async def get_secret_room_prefix",
    )
    return text


def patch_main(text: str) -> str:
    if "get_secret_room_prefix" in text:
        return text
    text = unique_replace(
        text,
        "    prefix = await bot.store.get_room_prefix(interaction.guild.id)\n    hub_prefix = await bot.store.get_hub_prefix(interaction.guild.id)\n",
        "    prefix = await bot.store.get_room_prefix(interaction.guild.id)\n    secret_prefix = await bot.store.get_secret_room_prefix(interaction.guild.id)\n    hub_prefix = await bot.store.get_hub_prefix(interaction.guild.id)\n",
        "main.py show vars",
    )
    old = '        f"\u90e8\u5c4b\u306e\u30c7\u30d5\u30a9\u30eb\u30c8\u540d: **{prefix}_n**\\n"\n'
    new = old + '        f"\u79d8\u5bc6\u306e\u90e8\u5c4b\u306e\u30c7\u30d5\u30a9\u30eb\u30c8\u540d: **{secret_prefix}_n**\\n"\n'
    return unique_replace(text, old, new, "main.py show text")


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
