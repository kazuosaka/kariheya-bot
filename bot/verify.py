"""Static checks for kariheya-bot. Exit 1 if sources must not be released."""
from __future__ import annotations

import ast
import compileall
import importlib
import inspect
import py_compile
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_IMPORT = {"verify", "apply_secret", "fix_db_indent"}
REQUIRED_FILES = (
    "main.py",
    "kariheya.py",
    "db.py",
    "lifecycle.py",
    "ui.py",
    "secret.py",
    "hubname.py",
    "announce.py",
    "grace.py",
    "envfile.py",
    "room_extra.py",
)
errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def python_files() -> list[Path]:
    return sorted(p for p in ROOT.glob("*.py") if p.is_file())


def check_required_files() -> None:
    for name in REQUIRED_FILES:
        if not (ROOT / name).is_file():
            fail(f"missing required file: {name}")


def check_no_tabs_and_tokenize(path: Path) -> None:
    raw = path.read_bytes()
    if b"\t" in raw:
        fail(f"{path.name}: contains tab characters (use 4 spaces)")
    try:
        with path.open("rb") as fh:
            list(tokenize.tokenize(fh.readline))
    except tokenize.TokenError as exc:
        fail(f"{path.name}: tokenize error: {exc}")
    except IndentationError as exc:
        fail(f"{path.name}: {exc.__class__.__name__}: {exc}")


def check_compile(path: Path) -> ast.AST | None:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        fail(f"{path.name}: not valid UTF-8: {exc}")
        return None
    try:
        tree = ast.parse(source, filename=path.name)
    except SyntaxError as exc:
        line = exc.lineno or "?"
        fail(f"{path.name}:{line}: {exc.msg}")
        return None
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        fail(str(exc))
        return tree
    return tree


def ast_has_call(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == name:
                return True
            if isinstance(func, ast.Attribute) and func.attr == name:
                return True
    return False


def ast_has_name(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return True
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return True
    return False


def check_contracts() -> None:
    db_src = (ROOT / "db.py").read_text(encoding="utf-8")
    if "ALTER TABLE hubs ADD COLUMN secret" not in db_src:
        fail("db.py: missing hubs.secret migration")
    if "ALTER TABLE rooms ADD COLUMN secret" not in db_src:
        fail("db.py: missing rooms.secret migration")
    db_tree = ast.parse(db_src, filename="db.py")
    for fn in ("upsert_hub", "get_hub_by_limit", "add_room"):
        if not ast_has_name(db_tree, fn):
            fail(f"db.py: missing {fn}")

    main_tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"), filename="main.py")
    for name in (
        "register_setup_secrethub",
        "register_setup_announce",
        "register_setup_grace",
        "register_setup_hubname",
    ):
        if not ast_has_call(main_tree, name):
            fail(f"main.py: {name} is never called")
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    if "bot.tree.add_command(setup)" not in main_src:
        fail("main.py: setup group is not added to the command tree")
    if "bot.tree.add_command(room)" not in main_src:
        fail("main.py: room group is not added to the command tree")

    life_src = (ROOT / "lifecycle.py").read_text(encoding="utf-8")
    if "secret_text_overwrites" not in life_src:
        fail("lifecycle.py: secret room creation helper not referenced")
    if "apply_secret_text_access" not in life_src:
        fail("lifecycle.py: secret access sync not referenced")

    kari_src = (ROOT / "kariheya.py").read_text(encoding="utf-8")
    if "_sync_locks" not in kari_src:
        fail("kariheya.py: missing _sync_locks")


def check_imports() -> None:
    sys.path.insert(0, str(ROOT))
    modules = [
        "db",
        "ui",
        "secret",
        "lifecycle",
        "kariheya",
        "hubname",
        "announce",
        "grace",
        "envfile",
        "room_extra",
        "category_lock",
    ]
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:
            fail(f"import {name}: {type(exc).__name__}: {exc}")
            return

    from db import Database
    from secret import register_setup_secrethub
    from ui import hub_channel_name
    from kariheya import bot

    if "secret" not in inspect.signature(Database.get_hub_by_limit).parameters:
        fail("Database.get_hub_by_limit must accept secret")
    if "secret" not in inspect.signature(Database.upsert_hub).parameters:
        fail("Database.upsert_hub must accept secret")
    if "secret" not in inspect.signature(Database.add_room).parameters:
        fail("Database.add_room must accept secret")
    if "secret" not in inspect.signature(hub_channel_name).parameters:
        fail("hub_channel_name must accept secret")
    if not callable(register_setup_secrethub):
        fail("register_setup_secrethub is not callable")
    if not hasattr(bot, "_sync_locks"):
        fail("KariheyaBot is missing _sync_locks")


def main() -> int:
    check_required_files()
    if not compileall.compile_dir(str(ROOT), quiet=1, force=True, rx=None):
        fail("compileall reported a failure")
    for path in python_files():
        check_no_tabs_and_tokenize(path)
        check_compile(path)
    if not errors:
        check_contracts()
    if not errors:
        check_imports()
    if errors:
        print("VERIFY FAILED")
        for item in errors:
            print(f"  - {item}")
        return 1
    print(f"VERIFY OK ({len(python_files())} python files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
