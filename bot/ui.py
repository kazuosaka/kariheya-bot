from __future__ import annotations

import asyncio
import logging
import os
import re
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from db import Database

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("kariheya")

GRACE_SECONDS = 20
WAIT_FIRST_JOIN_SECONDS = 300
MAX_LIMIT = 99
ROOM_NAME_PREFIX = "仮音声通話"
HUB_NAME_PREFIX = "新しく音声通話を始める"
DEFAULT_HUB_LIMITS = [0, 2, 4, 5, 10]


def sanitize_name(name: str) -> str:
    cleaned = "".join(ch for ch in name.strip() if ch not in "#,:" )
    cleaned = " ".join(cleaned.split())
    return (cleaned or "部屋")[:100]


def sanitize_prefix(name: str) -> str:
    cleaned = "".join(ch for ch in name.strip() if ch not in "#,:" )
    cleaned = " ".join(cleaned.split())
    return cleaned[:80]


def next_room_number(category: discord.CategoryChannel, prefix: str) -> int:
    pat = re.compile(rf"^{re.escape(prefix)}_(\d+)$")
    max_n = 0
    for channel in category.channels:
        matched = pat.match(channel.name)
        if matched:
            max_n = max(max_n, int(matched.group(1)))
    return max_n + 1


def human_members(channel: discord.VoiceChannel) -> list[discord.Member]:
    return [m for m in channel.members if not m.bot]


def format_limit(limit: int) -> str:
    return "制限なし" if limit <= 0 else f"{limit}人"


def hub_channel_name(limit: int, prefix: str | None = None) -> str:
    name = (prefix or HUB_NAME_PREFIX).strip() or HUB_NAME_PREFIX
    suffix = f"（{format_limit(limit)}）"
    keep = 100 - len(suffix)
    if keep < 1:
        return suffix[:100]
    return f"{name[:keep]}{suffix}"
