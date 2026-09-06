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


def configured_owner_guild_id() -> str:
    return os.getenv("OWNER_GUILD_ID", "").strip()


def write_owner_guild_id(guild_id: int) -> Path:
    path: Path | None = None
    for candidate in env_file_candidates():
        if candidate.is_file():
            path = candidate
            break
    if path is None:
        path = env_file_candidates()[0]
        path.parent.mkdir(parents=True, exist_ok=True)

    text = path.read_text(encoding="utf-8") if path.is_file() else ""
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

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(path)
    os.environ["OWNER_GUILD_ID"] = str(guild_id)
    return path
