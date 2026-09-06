from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from db import Database
from envfile import configured_owner_guild_id, write_owner_guild_id
from lifecycle import RoomLifecycleMixin
from ui import (
    CreatePanel,
    DEFAULT_HUB_LIMITS,
    GRACE_SECONDS,
    MAX_LIMIT,
    WAIT_FIRST_JOIN_SECONDS,
    describe_http_error,
    format_bot_access,
    format_limit,
    hub_channel_name,
    human_members,
    log,
    next_room_number,
    sanitize_name,
)

class KariheyaBot(RoomLifecycleMixin, commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.store = Database()
        self._deletes: dict[int, asyncio.Task] = {}
        self._create_lock = asyncio.Lock()
        self.owner_group: app_commands.Group | None = None
        self.owner_bind_only: app_commands.Group | None = None

    async def setup_hook(self) -> None:
        await self.store.connect()
        self.add_view(CreatePanel(self))
        guild_id = os.getenv("GUILD_ID", "").strip()
        owner_guild_id = configured_owner_guild_id()
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("synced %s commands to guild %s", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            log.info("synced %s global commands", len(synced))

        if self.owner_group is not None and owner_guild_id:
            target = discord.Object(id=int(owner_guild_id))
            self.tree.add_command(self.owner_group, guild=target)
            extra = await self.tree.sync(guild=target)
            log.info("synced %s owner commands to guild %s", len(extra), owner_guild_id)
        elif self.owner_bind_only is not None:
            target_id = guild_id or None
            if target_id:
                target = discord.Object(id=int(target_id))
                self.tree.add_command(self.owner_bind_only, guild=target)
                extra = await self.tree.sync(guild=target)
                log.info("synced %s bind command to guild %s", len(extra), target_id)
            else:
                self.tree.add_command(self.owner_bind_only)
                extra = await self.tree.sync()
                log.info("synced %s global bind commands", len(extra))
        self.sweep_empty_rooms.start()

    async def lock_owner_guild(self, guild: discord.Guild) -> Path:
        path = write_owner_guild_id(guild.id)
        if self.owner_group is None:
            return path
        try:
            if self.tree.get_command("owner") is not None:
                self.tree.remove_command("owner")
            if self.tree.get_command("owner", guild=guild) is not None:
                self.tree.remove_command("owner", guild=guild)
            self.tree.add_command(self.owner_group, guild=discord.Object(id=guild.id))
            await self.tree.sync()
            await self.tree.sync(guild=guild)
            log.info("locked owner commands to guild %s (%s)", guild.id, guild.name)
        except Exception:
            log.exception("owner command resync after bind failed; bind itself is saved")
        return path

    async def is_owner_user(self, user_id: int) -> bool:
        app = self.application
        if app is None:
            app = await self.application_info()
        if app.owner is not None and app.owner.id == user_id:
            return True
        if app.team is not None:
            return any(member.id == user_id for member in app.team.members)
        return False

    async def is_guild_silenced(self, guild_id: int | None) -> bool:
        if guild_id is None:
            return False
        return await self.store.is_guild_disabled(guild_id)

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
            if await self.store.is_guild_disabled(row["guild_id"]):
                continue
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

    async def create_room(
        self,
        interaction: discord.Interaction,
        *,
        name: str | None,
        limit: int,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
            return
        if await self.store.is_guild_disabled(interaction.guild.id):
            return
        if not await self.ensure_can_create(interaction):
            return
        existing = await self.store.get_room_by_owner(interaction.guild.id, interaction.user.id)
        if existing is not None:
            voice = interaction.guild.get_channel(existing["voice_id"])
            if isinstance(voice, discord.VoiceChannel):
                await interaction.response.send_message(
                    f"すでに {voice.mention} を持っています。1人1部屋までです。",
                    ephemeral=True,
                )
                return
            await self.store.delete_room(existing["voice_id"])
        if limit < 0 or limit > MAX_LIMIT:
            await interaction.response.send_message(
                f"人数上限は 0〜{MAX_LIMIT} です（0は制限なし）。",
                ephemeral=True,
            )
            return

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        settings = await self.store.get_settings(interaction.guild.id)
        category: discord.CategoryChannel | None = None
        if settings and settings["category_id"]:
            found = interaction.guild.get_channel(settings["category_id"])
            if isinstance(found, discord.CategoryChannel):
                category = found
        if category is None:
            await interaction.followup.send(
                "先に `/setup category` で一時部屋のカテゴリを指定してください。",
                ephemeral=True,
            )
            return

        owner = interaction.user
        prefix = await self.store.get_room_prefix(interaction.guild.id)
        async with self._create_lock:
            if name:
                room_name = sanitize_name(name)
            else:
                room_name = f"{prefix}_{next_room_number(category, prefix)}"

            voice = None
            text = None
            stage = "準備"
            try:
                stage = "ボイス作成"
                voice = await category.create_voice_channel(
                    name=room_name,
                    user_limit=limit,
                    reason=f"{owner} が一時ボイスを作成",
                )
                stage = "テキスト作成"
                text = await category.create_text_channel(
                    name=room_name,
                    topic=f"「{room_name}」の専用チャット。カテゴリの権限を持つメンバーが使えます。",
                    reason=f"{owner} が一時テキストを作成",
                )
            except discord.Forbidden as exc:
                if voice is not None:
                    try:
                        await voice.delete()
                    except discord.HTTPException:
                        pass
                log.exception("forbidden while creating room at %s", stage)
                await interaction.followup.send(
                    "チャンネルを作る権限がありません。\n"
                    f"失敗した段階: **{stage}**\n"
                    f"{describe_http_error(exc)}\n"
                    f"{format_bot_access(interaction.guild, category)}",
                    ephemeral=True,
                )
                return
            except discord.HTTPException as exc:
                if voice is not None:
                    try:
                        await voice.delete()
                    except discord.HTTPException:
                        pass
                log.exception("failed to create room at %s", stage)
                await interaction.followup.send(
                    f"部屋を作れませんでした。\n失敗した段階: **{stage}**\n"
                    f"{describe_http_error(exc)}\n"
                    f"{format_bot_access(interaction.guild, category)}",
                    ephemeral=True,
                )
                return

        await self.store.add_room(
            voice_id=voice.id,
            text_id=text.id,
            guild_id=interaction.guild.id,
            owner_id=owner.id,
            user_limit=limit,
            created_at=int(time.time()),
        )

        moved_note = await self.move_creator_to_voice(owner, voice)

        await text.send(
            content=f"{owner.mention} がこの部屋を作りました。カテゴリの権限を持つメンバーはテキストを閲覧・投稿できます。",
            embed=discord.Embed(
                title=room_name,
                description=(
                    f"人数上限: **{format_limit(limit)}**\n"
                    f"ボイス: {voice.mention}\n"
                    "全員がボイスを出ると、ボイスとテキストの両方を削除します。"
                ),
                color=0xC9893A,
            ),
        )

        await interaction.followup.send(
            f"部屋を作りました。\nボイス: {voice.mention}\nテキスト: {text.mention}\n"
            f"人数上限: {format_limit(limit)}\n{moved_note}",
            ephemeral=True,
        )

    async def move_creator_to_voice(
        self,
        owner: discord.Member,
        voice: discord.VoiceChannel,
    ) -> str:
        current = owner.voice.channel if owner.voice else None
        if not isinstance(current, discord.VoiceChannel):
            return (
                "いま通話に入っていないため、自動では参加できません。"
                f"{voice.mention} をクリックして入ってください。"
                "（Discordの仕様で、未参加の人をボットが通話に入れることはできません）\n"
                f"{WAIT_FIRST_JOIN_SECONDS // 60}分以内に誰も入らないと部屋を消します。"
            )
        if current.id == voice.id:
            await self.store.mark_occupied(voice.id)
            return "作成したボイスに参加しています。"
        try:
            await owner.move_to(voice, reason="作成した一時ボイスへ移動")
            await self.store.mark_occupied(voice.id)
            return "作成したボイスへ移動しました。"
        except discord.Forbidden:
            return (
                "自動移動する権限が足りません。"
                f"{voice.mention} に手動で参加してください。"
            )
        except discord.HTTPException as exc:
            log.warning("could not move creator %s: %s", owner.id, exc)
            return f"自動移動できませんでした。{voice.mention} に参加してください。"


bot = KariheyaBot()
