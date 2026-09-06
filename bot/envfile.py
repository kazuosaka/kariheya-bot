from __future__ import annotations

import os
from pathlib import Path


def env_file_candidates() -> list[Path]:
    raw = os.getenv("ENV_FILE", "").strip()
    paths: list[Path] = []
    if raw:
        paths.append(Path(raw))
    paths.append(Path("/app/.env"))
    paths.append(Path(".env"))
    return paths


def fallback_owner_path() -> Path:
    return Path(os.getenv("DATA_DIR", "/app/data")) / "owner_guild_id"


def configured_owner_guild_id() -> str:
    value = os.getenv("OWNER_GUILD_ID", "").strip()
    if value:
        return value
    path = fallback_owner_path()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def _update_env_text(text: str, guild_id: int) -> str:
    lines = text.splitlines()
    found = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("OWNER_GUILD_ID=") and not stripped.startswith("#"):
            out.append(f"OWNER_GUILD_ID={guild_id}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1] != "":
            out.append("")
        out.append(f"OWNER_GUILD_ID={guild_id}")
    return "\n".join(out) + "\n"


def write_owner_guild_id(guild_id: int) -> Path:
    os.environ["OWNER_GUILD_ID"] = str(guild_id)
    last_error: OSError | None = None

    for path in env_file_candidates():
        if path.exists() and path.is_dir():
            continue
        try:
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_update_env_text(text, guild_id), encoding="utf-8")
        except OSError as exc:
            last_error = exc
            continue
        try:
            fallback_owner_path().parent.mkdir(parents=True, exist_ok=True)
            fallback_owner_path().write_text(str(guild_id), encoding="utf-8")
        except OSError:
            pass
        return path

    fallback = fallback_owner_path()
    try:
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(str(guild_id), encoding="utf-8")
        return fallback
    except OSError as exc:
        raise last_error or exc
