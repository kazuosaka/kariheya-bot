from __future__ import annotations

import asyncio
import time

import discord
from discord.ext import tasks

from announce import post_room_announce
from secret import apply_secret_text_access, is_secret_row, secret_text_overwrites
from ui import WAIT_FIRST_JOIN_SECONDS, human_members, log, next_room_number


class RoomLifecycleMixin:
    async def handle_hub_join(self, member: discord.Member, hub_channel_id: int) -> int | None:
        guild = member.guild
        hub = await self.store.get_hub(hub_channel_id)
        if hub is None:
            return None
        if await self.store.is_guild_disabled(guild.id):
            return None
        allowed = await self.store.list_roles(guild.id)
        if not self.can_create(member, allowed):
            log.info("hub join denied for %s in guild %s", member.id, guild.id)
            try:
                await member.send(
                    "\u4e00\u6642\u90e8\u5c4b\u3092\u4f5c\u308b\u30ed\u30fc\u30eb\u304c\u306a\u3044\u305f\u3081\u3001\u4f5c\u6210\u7528\u30dc\u30a4\u30b9\u304b\u3089\u5206\u65ad\u3057\u307e\u3057\u305f\u3002"
                    "\u30b5\u30fc\u30d0\u30fc\u7ba1\u7406\u8005\u306b `/setup role` \u3092\u4f9d\u983c\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
                )
            except discord.HTTPException:
                pass
            try:
                await member.move_to(None, reason="\u90e8\u5c4b\u4f5c\u6210\u304c\u8a31\u53ef\u3055\u308c\u3066\u3044\u306a\u3044\u305f\u3081\u5206\u65ad")
            except discord.HTTPException:
                pass
            return None

        existing = await self.store.get_room_by_owner(guild.id, member.id)
        if existing is not None:
            dest = guild.get_channel(existing["voice_id"])
            if isinstance(dest, discord.VoiceChannel):
                self.cancel_delete(dest.id)
                try:
                    await member.move_to(dest, reason="\u65e2\u5b58\u306e\u4e00\u6642\u90e8\u5c4b\u3078\u623b\u3059")
                    await self.store.mark_occupied(dest.id)
                except discord.HTTPException:
                    log.warning("could not move %s back to existing room", member.id)
                return dest.id
            await self.store.delete_room(existing["voice_id"])

        settings = await self.store.get_settings(guild.id)
        category = None
        if settings and settings["category_id"]:
            found = guild.get_channel(settings["category_id"])
            if isinstance(found, discord.CategoryChannel):
                category = found
        if category is None:
            log.warning("hub join without category in guild %s", guild.id)
            try:
                await member.send("\u4f5c\u6210\u5148\u30ab\u30c6\u30b4\u30ea\u304c\u672a\u8a2d\u5b9a\u3067\u3059\u3002\u7ba1\u7406\u8005\u304c `/setup category` \u3092\u5b9f\u884c\u3059\u308b\u5fc5\u8981\u304c\u3042\u308a\u307e\u3059\u3002")
            except discord.HTTPException:
                pass
            return None

        limit = int(hub["user_limit"])
        secret = is_secret_row(hub)
        prefix = await self.store.get_room_prefix(guild.id)
        async with self._create_lock:
            still = await self.store.get_room_by_owner(guild.id, member.id)
            if still is not None:
                dest = guild.get_channel(still["voice_id"])
                if isinstance(dest, discord.VoiceChannel):
                    self.cancel_delete(dest.id)
                    try:
                        await member.move_to(dest, reason="\u65e2\u5b58\u306e\u4e00\u6642\u90e8\u5c4b\u3078\u623b\u3059")
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
                    reason=f"{member} \u304c\u30cf\u30d6\u304b\u3089\u4e00\u6642\u30dc\u30a4\u30b9\u3092\u4f5c\u6210",
                )
                text_kwargs: dict = {
                    "name": room_name,
                    "reason": f"{member} \u304c\u30cf\u30d6\u304b\u3089\u4e00\u6642\u30c6\u30ad\u30b9\u30c8\u3092\u4f5c\u6210",
                }
                if secret:
                    text_kwargs["topic"] = f"\u300c{room_name}\u300d\u306e\u79d8\u5bc6\u30c1\u30e3\u30c3\u30c8\u3002\u901a\u8a71\u4e2d\u306e\u30e1\u30f3\u30d0\u30fc\u3060\u3051\u304c\u8aad\u3081\u307e\u3059\u3002"
                    text_kwargs["overwrites"] = secret_text_overwrites(guild, [member])
                else:
                    text_kwargs["topic"] = f"\u300c{room_name}\u300d\u306e\u5c02\u7528\u30c1\u30e3\u30c3\u30c8\u3002\u30ab\u30c6\u30b4\u30ea\u306e\u6a29\u9650\u3092\u6301\u3064\u30e1\u30f3\u30d0\u30fc\u304c\u4f7f\u3048\u307e\u3059\u3002"
                try:
                    text = await category.create_text_channel(**text_kwargs)
                except discord.HTTPException:
                    log.exception("secret text overwrites failed; creating without overwrites")
                    text_kwargs.pop("overwrites", None)
                    text = await category.create_text_channel(**text_kwargs)
            except discord.HTTPException:
                log.exception("hub create failed")
                if voice is not None:
                    try:
                        await voice.delete()
                    except discord.HTTPException:
                        pass
                try:
                    await member.send(
                        "\u4e00\u6642\u90e8\u5c4b\u306e\u4f5c\u6210\u306b\u5931\u6557\u3057\u307e\u3057\u305f\u3002\u30dc\u30c3\u30c8\u306b\u300c\u30c1\u30e3\u30f3\u30cd\u30eb\u306e\u7ba1\u7406\u300d\u3068\u300c\u30ed\u30fc\u30eb\u306e\u7ba1\u7406\u300d\u304c\u3042\u308b\u304b\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
                    )
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
                secret=secret,
            )
        await asyncio.sleep(0.5)
        try:
            await member.move_to(voice, reason="\u4f5c\u6210\u3057\u305f\u4e00\u6642\u30dc\u30a4\u30b9\u3078\u79fb\u52d5")
        except discord.HTTPException:
            log.warning("could not move %s into new room", member.id)
        else:
            await asyncio.sleep(0.5)
            current = member.voice.channel if member.voice else None
            if current is not None and current.id == voice.id:
                await self.store.mark_occupied(voice.id)
                self.cancel_delete(voice.id)
        await self.sync_text_access(voice, text)
        await post_room_announce(self, guild.id, member, text, voice, room_name, limit)
        return voice.id
