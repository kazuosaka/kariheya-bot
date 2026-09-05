from __future__ import annotations

import asyncio
import os
import time

import discord
from discord.ext import commands, tasks

from db import Database
from ui import (
    CreatePanel,
    GRACE_SECONDS,
    MAX_LIMIT,
    ROOM_NAME_PREFIX,
    WAIT_FIRST_JOIN_SECONDS,
    describe_http_error,
    format_bot_access,
    format_limit,
    human_members,
    log,
    next_room_number,
    sanitize_name,
)


class KariheyaBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.store = Database()
        self._deletes: dict[int, asyncio.Task] = {}
        self._create_lock = asyncio.Lock()

    async def setup_hook(self) -> None:
        await self.store.connect()
        self.add_view(CreatePanel(self))
        guild_id = os.getenv("GUILD_ID", "").strip()
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("synced %s commands to guild %s", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            log.info("synced %s global commands", len(synced))
        self.sweep_empty_rooms.start()

    async def close(self) -> None:
        for task in list(self._deletes.values()):
            task.cancel()
        self.sweep_empty_rooms.cancel()
        await self.store.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("logged in as %s (%s)", self.user, self.user.id if self.user else "?")
        await self.restore_rooms()

    async def restore_rooms(self) -> None:
        stale: list[int] = []
        for row in await self.store.list_rooms():
            guild = self.get_guild(row["guild_id"])
            if guild is None:
                continue
            voice = guild.get_channel(row["voice_id"])
            text = guild.get_channel(row["text_id"])
            if not isinstance(voice, discord.VoiceChannel):
                stale.append(row["voice_id"])
                if isinstance(text, discord.TextChannel):
                    try:
                        await text.delete(reason="対応する一時ボイスが無いため削除")
                    except discord.HTTPException:
                        pass
                continue
            if human_members(voice):
                await self.store.mark_occupied(voice.id)
                if isinstance(text, discord.TextChannel):
                    await self.sync_text_access(voice, text)
            elif self._should_delete_empty(row):
                self.schedule_delete(voice.id)
        if stale:
            await self.store.delete_rooms(stale)

    def can_create(self, member: discord.Member, allowed: list[int]) -> bool:
        if member.guild_permissions.manage_channels:
            return True
        return any(role.id in allowed for role in member.roles)

    async def ensure_can_create(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
            return False
        allowed = await self.store.list_roles(interaction.guild.id)
        if self.can_create(interaction.user, allowed):
            return True
        if not allowed:
            msg = "まだ許可ロールがありません。管理者が `/setup role` で設定してください。"
        else:
            mentions = " ".join(f"<@&{rid}>" for rid in allowed)
            msg = f"部屋を作れるのは次のロールです: {mentions}"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return False
