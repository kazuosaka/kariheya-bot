from __future__ import annotations

import discord
from discord import app_commands

from ui import describe_http_error, hub_channel_name, sanitize_name, sanitize_prefix


def register_rename(room: app_commands.Group, bot) -> None:
    @room.command(name="rename", description="自分が作った一時部屋の名前を変えます")
    @app_commands.describe(name="新しい部屋名")
    async def room_rename(interaction: discord.Interaction, name: str) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
            return
        room_name = sanitize_name(name)
        if not room_name:
            await interaction.response.send_message("有効な部屋名を入力してください。", ephemeral=True)
            return

        row = await bot.store.get_room_by_owner(interaction.guild.id, interaction.user.id)
        if row is None and interaction.user.guild_permissions.manage_channels:
            current = interaction.user.voice.channel if interaction.user.voice else None
            if isinstance(current, discord.VoiceChannel):
                row = await bot.store.get_room_by_voice(current.id)
        if row is None:
            await interaction.response.send_message(
                "名前を変えられる一時部屋がありません。先に部屋を作ってください。",
                ephemeral=True,
            )
            return

        voice = interaction.guild.get_channel(row["voice_id"])
        text = interaction.guild.get_channel(row["text_id"])
        if not isinstance(voice, discord.VoiceChannel):
            await bot.store.delete_room(row["voice_id"])
            await interaction.response.send_message("部屋が見つかりませんでした。", ephemeral=True)
            return
        text_same = not isinstance(text, discord.TextChannel) or text.name == room_name
        if voice.name == room_name and text_same:
            await interaction.response.send_message("同じ名前です。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await voice.edit(name=room_name, reason=f"{interaction.user} が部屋名を変更")
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"ボイスの名前を変えられませんでした。\n{describe_http_error(exc)}",
                ephemeral=True,
            )
            return
        if isinstance(text, discord.TextChannel):
            try:
                await text.edit(
                    name=room_name,
                    topic=f"「{room_name}」の専用チャット。カテゴリの権限を持つメンバーが使えます。",
                    reason=f"{interaction.user} が部屋名を変更",
                )
            except discord.HTTPException as exc:
                await interaction.followup.send(
                    f"ボイスは {voice.mention} に変えました。テキストの名前変更に失敗しました。\n"
                    f"{describe_http_error(exc)}",
                    ephemeral=True,
                )
                return
        await interaction.followup.send(f"部屋名を **{room_name}** にしました。", ephemeral=True)


def register_setup_name(setup: app_commands.Group, bot) -> None:
    @setup.command(name="name", description="新しく作る部屋のデフォルト名を変えます")
    @app_commands.describe(prefix="部屋名の先頭。後ろに _1, _2 と番号が付きます")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def setup_name(interaction: discord.Interaction, prefix: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
            return
        cleaned = sanitize_prefix(prefix)
        if not cleaned:
            await interaction.response.send_message(
                "有効な名前を入力してください。`#` `,` `:` は使えません。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await bot.store.upsert_room_prefix(interaction.guild.id, cleaned)
        hubs = await bot.store.list_hubs(interaction.guild.id)
        for hub in hubs:
            channel = interaction.guild.get_channel(hub["channel_id"])
            if not isinstance(channel, discord.VoiceChannel):
                continue
            new_name = hub_channel_name(int(hub["user_limit"]), cleaned)
            if channel.name == new_name:
                continue
            try:
                await channel.edit(name=new_name, reason="部屋のデフォルト名に合わせて作成用ボイス名を変更")
            except discord.HTTPException as exc:
                await interaction.followup.send(
                    f"部屋名は **{cleaned}** にしましたが、作成用ボイスの名前変更に失敗しました。\n"
                    f"{describe_http_error(exc)}",
                    ephemeral=True,
                )
                return
        await interaction.followup.send(
            f"これから作る部屋は **{cleaned}_1**、**{cleaned}_2** … になります。\n"
            f"作成用ボイスの名前も **＋ {cleaned}（人数）** に合わせました。\n"
            "すでに存在する一時部屋の名前は変わりません。",
            ephemeral=True,
        )
