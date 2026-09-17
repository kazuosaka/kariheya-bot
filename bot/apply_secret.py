"""Indent-safe patches for secret-mode. Never writes a file that does not compile.

Run from the bot directory:
    python apply_secret.py
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class PatchError(Exception):
    pass


def indent_of(line: str) -> str:
    i = 0
    while i < len(line) and line[i] == " ":
        i += 1
    return line[:i]


def read_py(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    text = data.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), newline


def encode_py(text: str, newline: str) -> bytes:
    if not text.endswith("\n"):
        text += "\n"
    return text.replace("\n", newline).encode("utf-8")


def write_py(path: Path, text: str, newline: str) -> None:
    must_compile(text, path.name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(encode_py(text, newline))
    tmp.replace(path)


def must_compile(text: str, label: str) -> None:
    try:
        ast.parse(text, filename=label)
    except SyntaxError as exc:
        raise PatchError(f"{label}:{exc.lineno}: {exc.msg}") from exc


def unique_replace(text: str, old: str, new: str, label: str, skip_if: str | None = None) -> str:
    if skip_if and skip_if in text:
        return text
    if old == new:
        return text
    count = text.count(old)
    if count == 0:
        if new in text:
            return text
        raise PatchError(f"{label}: target not found")
    if count > 1:
        raise PatchError(f"{label}: target matched {count} times, need exactly 1")
    updated = text.replace(old, new, 1)
    must_compile(updated, label)
    return updated


def insert_block_before(
    text: str,
    marker: str,
    relative_lines: list[tuple[int, str]],
    label: str,
    already: str,
) -> str:
    if already in text:
        return text
    lines = text.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if marker in line]
    if len(hits) != 1:
        raise PatchError(f"{label}: marker '{marker}' matched {len(hits)} times")
    idx = hits[0]
    base = indent_of(lines[idx].replace("\n", ""))
    rendered: list[str] = []
    for extra, code in relative_lines:
        if code == "":
            rendered.append("\n")
            continue
        rendered.append(f"{base}{'    ' * extra}{code}\n")
    updated = "".join(lines[:idx] + rendered + lines[idx:])
    must_compile(updated, label)
    return updated


def reindent_span_to(lines: list[str], start: int, end: int, base: str) -> list[str]:
    block = lines[start:end]
    nonempty = [line for line in block if line.strip()]
    if not nonempty:
        return lines
    min_indent = min(len(indent_of(line.replace("\n", ""))) for line in nonempty)
    rebuilt: list[str] = []
    for line in block:
        raw = line.replace("\n", "")
        if not raw.strip():
            rebuilt.append("\n")
            continue
        extra = len(indent_of(raw)) - min_indent
        rebuilt.append(base + (" " * extra) + raw.lstrip(" ") + "\n")
    return lines[:start] + rebuilt + lines[end:]


def repair_db_secret_block(text: str) -> str:
    """Reindent the secret ALTER block to match connect() body indent."""
    lines = text.splitlines(keepends=True)
    uv = next((i for i, line in enumerate(lines) if "PRAGMA user_version" in line), None)
    hubs = next((i for i, line in enumerate(lines) if "PRAGMA table_info(hubs)" in line), None)
    if uv is None or hubs is None:
        return text
    base = indent_of(lines[uv].replace("\n", ""))
    lines = reindent_span_to(lines, hubs, uv, base)
    updated = "".join(lines)
    must_compile(updated, "db.py")
    return updated


def main() -> int:
    path = ROOT / "db.py"
    if not path.is_file():
        print("PATCH FAILED: db.py not found")
        return 1
    original, newline = read_py(path)
    backup = original
    try:
        updated = repair_db_secret_block(original)
        must_compile(updated, "db.py")
        if updated != original:
            write_py(path, updated, newline)
            print("updated db.py")
        else:
            print("unchanged db.py")
        print("PATCH OK")
        return 0
    except PatchError as exc:
        path.write_bytes(encode_py(backup, newline))
        print(f"PATCH FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
