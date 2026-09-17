from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def once(text: str, old: str, new: str, label: str) -> str:
    if new.strip() in text and old not in text:
        return text
    if old not in text:
        raise SystemExit(f"missing snippet: {label}")
    return text.replace(old, new, 1)
