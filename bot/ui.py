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
    name = (prefix or ROOM_NAME_PREFIX).strip() or ROOM_NAME_PREFIX
    return f"＋ {name}（{format_limit(limit)}）"


def yesno(value: bool) -> str:
    return "はい" if value else "いいえ"


def describe_http_error(exc: discord.HTTPException) -> str:
    labels = {
        50001: "Missing Access（対象を見られない／触れない）",
        50013: "Missing Permissions（権限不足）",
        60003: "Two factor required（サーバーがモデレーターに2FAを要求）",
        30013: "Maximum channels in category（カテゴリのチャンネル上限）",
    }
    label = labels.get(int(exc.code), "（上記コードの説明は未登録）")
    text = (exc.text or "").strip() or "（本文なし）"
    return f"HTTP {exc.status} / Discord {exc.code} {label}\nAPI: {text}"


def format_bot_access(
    guild: discord.Guild,
    category: discord.CategoryChannel | None,
) -> str:
    me = guild.me
    if me is None:
        return "ボット自身のメンバー情報を取得できません。"
    gp = me.guild_permissions
    lines = [
        f"ボット: {me} ({me.id})",
        f"最上ロール: {me.top_role.name}（位置 {me.top_role.position}）",
        (
            "サーバー権限: "
            f"管理者={yesno(gp.administrator)} "
            f"チャンネル管理={yesno(gp.manage_channels)} "
            f"ロール管理={yesno(gp.manage_roles)} "
            f"接続={yesno(gp.connect)} "
            f"移動={yesno(gp.move_members)}"
        ),
        f"サーバーの2FA要求: {guild.mfa_level}",
    ]
    if category is None:
        lines.append("カテゴリ: 未設定")
        return "\n".join(lines)
    cp = category.permissions_for(me)
    lines.append(
        f"カテゴリ: {category.name} ({category.id}) 内チャンネル数={len(category.channels)}"
    )
    lines.append(
        "カテゴリ実効権限: "
        f"閲覧={yesno(cp.view_channel)} "
        f"チャンネル管理={yesno(cp.manage_channels)} "
        f"権限管理={yesno(cp.manage_roles)} "
        f"接続={yesno(cp.connect)}"
    )
    return "\n".join(lines)


class CreateModal(discord.ui.Modal, title="部屋を作成"):
    room_name = discord.ui.TextInput(
        label="部屋名",
        placeholder="例: 雑談、Valorant 5人",
        max_length=100,
        required=False,
    )
    room_limit = discord.ui.TextInput(
        label="人数上限（0で制限なし、最大99）",
        placeholder="0",
        max_length=2,
        required=False,
    )

    def __init__(self, bot: "KariheyaBot") -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_limit = str(self.room_limit.value or "0").strip()
        if not raw_limit.isdigit():
            await interaction.response.send_message(
                "人数上限は 0〜99 の数字で指定してください。",
                ephemeral=True,
            )
            return
        limit = int(raw_limit)
        if limit > MAX_LIMIT:
            await interaction.response.send_message(
                f"人数上限は {MAX_LIMIT} までです。",
                ephemeral=True,
            )
            return
        name = str(self.room_name.value).strip() or None
        await self.bot.create_room(interaction, name=name, limit=limit)


class CreatePanel(discord.ui.View):
    def __init__(self, bot: "KariheyaBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot

    async def _create(self, interaction: discord.Interaction, limit: int) -> None:
        await self.bot.create_room(interaction, name=None, limit=limit)

    @discord.ui.button(
        label="制限なし",
        style=discord.ButtonStyle.primary,
        custom_id="kariheya:create:0",
    )
    async def unlimited(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._create(interaction, 0)

    @discord.ui.button(
        label="2人",
        style=discord.ButtonStyle.secondary,
        custom_id="kariheya:create:2",
    )
    async def two(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._create(interaction, 2)

    @discord.ui.button(
        label="4人",
        style=discord.ButtonStyle.secondary,
        custom_id="kariheya:create:4",
    )
    async def four(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._create(interaction, 4)

    @discord.ui.button(
        label="5人",
        style=discord.ButtonStyle.secondary,
        custom_id="kariheya:create:5",
    )
    async def five(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._create(interaction, 5)

    @discord.ui.button(
        label="10人",
        style=discord.ButtonStyle.secondary,
        custom_id="kariheya:create:10",
    )
    async def ten(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._create(interaction, 10)

    @discord.ui.button(
        label="名前と人数を指定",
        style=discord.ButtonStyle.success,
        custom_id="kariheya:create:custom",
        row=1,
    )
    async def custom(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.bot.ensure_can_create(interaction):
            return
        await interaction.response.send_modal(CreateModal(self.bot))
