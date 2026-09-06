from __future__ import annotations

import asyncio
import time

import discord
from discord.ext import tasks

from ui import GRACE_SECONDS, WAIT_FIRST_JOIN_SECONDS, format_limit, human_members, log, next_room_number


class RoomLifecycleMixin:
    async def handle_hub_join(self, member: discord.Member, hub_channel_id: int) -> int | None:
        guild = member.guild
        hub = await self.store.get_hub(hub_channel_id)
        if hub is None:
            return None
        allowed = await self.store.list_roles(guild.id)
        if not self.can_create(member, allowed):
            try:
                await member.move_to(None, reason="部屋作成が許可されていないため切断")
            except discord.HTTPException:
                pass
            return None

        existing = await self.store.get_room_by_owner(guild.id, member.id)
        if existing is not None:
            dest = guild.get_channel(existing["voice_id"])
            if isinstance(dest, discord.VoiceChannel):
                try:
                    await member.move_to(dest, reason="既存の一時部屋へ戻す")
                    await self.store.mark_occupied(dest.id)
                except discord.HTTPException:
                    pass
                return dest.id
            await self.store.delete_room(existing["voice_id"])

        settings = await self.store.get_settings(guild.id)
        category = None
        if settings and settings["category_id"]:
            found = guild.get_channel(settings["category_id"])
            if isinstance(found, discord.CategoryChannel):
                category = found
        if category is None:
            try:
                await member.move_to(None, reason="作成先カテゴリ未設定")
            except discord.HTTPException:
                pass
            return None

        limit = int(hub["user_limit"])
        prefix = await self.store.get_room_prefix(guild.id)
        async with self._create_lock:
            still = await self.store.get_room_by_owner(guild.id, member.id)
            if still is not None:
                dest = guild.get_channel(still["voice_id"])
                if isinstance(dest, discord.VoiceChannel):
                    try:
                        await member.move_to(dest, reason="既存の一時部屋へ戻す")
                    except discord.HTTPException:
                        pass
                    return dest.id
            room_name = f"{prefix}_{next_room_number(category, prefix)}"
            voice = None
            text = None
            try:
                voice = await category.create_voice_channel(
                    name=room_name,
                    user_limit=limit,
                    reason=f"{member} がハブから一時ボイスを作成",
                )
                text = await category.create_text_channel(
                    name=room_name,
                    topic=f"「{room_name}」の専用チャット。カテゴリの権限を持つメンバーが使えます。",
                    reason=f"{member} がハブから一時テキストを作成",
                )
            except discord.HTTPException:
                log.exception("hub create failed")
                if voice is not None:
                    try:
                        await voice.delete()
                    except discord.HTTPException:
                        pass
                try:
                    await member.move_to(None, reason="部屋作成に失敗したため切断")
                except discord.HTTPException:
                    pass
                return None
            await self.store.add_room(
                voice_id=voice.id,
                text_id=text.id,
                guild_id=guild.id,
                owner_id=member.id,
                user_limit=limit,
                created_at=int(time.time()),
            )
        try:
            await member.move_to(voice, reason="作成した一時ボイスへ移動")
            await self.store.mark_occupied(voice.id)
        except discord.HTTPException:
            log.warning("could not move %s into new room", member.id)
        try:
            await text.send(
                content=f"{member.mention} がこの部屋を作りました。カテゴリの権限を持つメンバーはテキストを閲覧・投稿できます。",
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
        except discord.HTTPException:
            pass
        return voice.id

    async def sync_text_access(
        self,
        voice: discord.VoiceChannel,
        text: discord.TextChannel,
    ) -> None:
        return

    def _should_delete_empty(self, row: object) -> bool:
        occupied = 0
        try:
            occupied = int(row["occupied"])  # type: ignore[index]
        except (KeyError, IndexError, TypeError, ValueError):
            occupied = 0
        if occupied:
            return True
        created_at = int(row["created_at"])  # type: ignore[index]
        return int(time.time()) - created_at >= WAIT_FIRST_JOIN_SECONDS

    def schedule_delete(self, voice_id: int) -> None:
        existing = self._deletes.get(voice_id)
        if existing and not existing.done():
            return
        self._deletes[voice_id] = asyncio.create_task(self._delete_when_still_empty(voice_id))

    def cancel_delete(self, voice_id: int) -> None:
        task = self._deletes.pop(voice_id, None)
        if task and not task.done():
            task.cancel()

    async def _delete_when_still_empty(self, voice_id: int) -> None:
        try:
            await asyncio.sleep(GRACE_SECONDS)
            row = await self.store.get_room_by_voice(voice_id)
            if row is None:
                return
            guild = self.get_guild(row["guild_id"])
            if guild is None:
                return
            voice = guild.get_channel(voice_id)
            if isinstance(voice, discord.VoiceChannel) and human_members(voice):
                return
            await self.delete_pair(row["voice_id"], row["text_id"], row["guild_id"])
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("delete task failed for %s", voice_id)
        finally:
            self._deletes.pop(voice_id, None)

    async def delete_pair(self, voice_id: int, text_id: int, guild_id: int) -> None:
        guild = self.get_guild(guild_id)
        if guild is not None:
            text = guild.get_channel(text_id)
            voice = guild.get_channel(voice_id)
            if isinstance(text, discord.TextChannel):
                try:
                    await text.delete(reason="一時部屋が空になったため削除")
                except discord.HTTPException:
                    pass
            if isinstance(voice, discord.VoiceChannel):
                if human_members(voice):
                    return
                try:
                    await voice.delete(reason="一時部屋が空になったため削除")
                except discord.HTTPException:
                    pass
        await self.store.delete_room(voice_id)

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return
        before_id = before.channel.id if isinstance(before.channel, discord.VoiceChannel) else None
        after_id = after.channel.id if isinstance(after.channel, discord.VoiceChannel) else None
        if before_id == after_id:
            return

        keep_voice_id: int | None = None
        if after_id and await self.store.get_hub(after_id) is not None:
            keep_voice_id = await self.handle_hub_join(member, after_id)

        if after_id:
            row = await self.store.get_room_by_voice(after_id)
            if row is not None:
                self.cancel_delete(after_id)
                await self.store.mark_occupied(after_id)
                guild = member.guild
                voice = after.channel
                text = guild.get_channel(row["text_id"])
                if isinstance(voice, discord.VoiceChannel) and isinstance(text, discord.TextChannel):
                    await self.sync_text_access(voice, text)

        if before_id and before_id != keep_voice_id:
            row = await self.store.get_room_by_voice(before_id)
            if row is not None:
                guild = member.guild
                voice = before.channel
                text = guild.get_channel(row["text_id"])
                if isinstance(voice, discord.VoiceChannel) and isinstance(text, discord.TextChannel):
                    await self.sync_text_access(voice, text)
                    if human_members(voice):
                        self.cancel_delete(before_id)
                    elif self._should_delete_empty(row):
                        self.schedule_delete(before_id)
                elif not isinstance(voice, discord.VoiceChannel):
                    await self.store.delete_room(before_id)

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if isinstance(channel, discord.VoiceChannel):
            row = await self.store.get_room_by_voice(channel.id)
            if row is not None:
                self.cancel_delete(channel.id)
                guild = channel.guild
                text = guild.get_channel(row["text_id"])
                if isinstance(text, discord.TextChannel):
                    try:
                        await text.delete(reason="一時ボイスが削除されたため")
                    except discord.HTTPException:
                        pass
                await self.store.delete_room(channel.id)
            await self.store.delete_hub(channel.id)
        elif isinstance(channel, discord.TextChannel):
            row = await self.store.get_room_by_text(channel.id)
            if row is not None:
                pass

    @tasks.loop(seconds=60)
    async def sweep_empty_rooms(self) -> None:
        for row in await self.store.list_rooms():
            guild = self.get_guild(row["guild_id"])
            if guild is None:
                continue
            voice = guild.get_channel(row["voice_id"])
            if not isinstance(voice, discord.VoiceChannel):
                await self.delete_pair(row["voice_id"], row["text_id"], row["guild_id"])
                continue
            if human_members(voice):
                await self.store.mark_occupied(voice.id)
                continue
            if self._should_delete_empty(row):
                self.schedule_delete(voice.id)

    @sweep_empty_rooms.before_loop
    async def before_sweep(self) -> None:
        await self.wait_until_ready()
