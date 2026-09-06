from __future__ import annotations

import discord
from discord import app_commands

from envfile import configured_owner_guild_id
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


def _parse_guild_id(raw: str) -> int | None:
    cleaned = raw.strip()
    if not cleaned.isdigit() or not (17 <= len(cleaned) <= 20):
        return None
    return int(cleaned)


def attach_bind(group: app_commands.Group, bot) -> None:
    @group.command(name="bind", description="運用者コマンドをこのサーバーに固定します（未設定時のみ）")
    async def owner_bind(interaction: discord.Interaction) -> None:
        if not await bot.is_owner_user(interaction.user.id):
            await interaction.response.send_message("この操作はボット運用者だけができます。", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
            return
        current = configured_owner_guild_id()
        if current:
            await interaction.response.send_message(
                f"すでに `{current}` に固定されています。\n"
                "変更する場合は `.env` の `OWNER_GUILD_ID` を直接書き換えて、ボットを再起動してください。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await bot.lock_owner_guild(interaction.guild)
        except OSError:
            await interaction.followup.send(
                "`.env` に書き込めませんでした。docker-compose で `.env` がコンテナにマウントされているか確認してください。",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"このサーバー（`{interaction.guild.id}`）を運用サーバーに固定し、`.env` へ書き込みました。\n"
            "`/owner block` などはここでのみ使えます。変更は `.env` の直接編集だけです。",
            ephemeral=True,
        )


def register_silence(group: app_commands.Group, bot) -> None:
    attach_bind(group, bot)
    @group.command(name="block", description="指定サーバーでボットを無応答にします（運用者専用）")
    @app_commands.describe(guild_id="停止するサーバーID")
    async def setup_block(interaction: discord.Interaction, guild_id: str) -> None:
        if not await bot.is_owner_user(interaction.user.id):
            await interaction.response.send_message("この操作はボット運用者だけができます。", ephemeral=True)
            return
        parsed = _parse_guild_id(guild_id)
        if parsed is None:
            await interaction.response.send_message("サーバーIDが正しくありません。数字のIDを指定してください。", ephemeral=True)
            return
        if interaction.guild is not None and parsed == interaction.guild.id:
            await interaction.response.send_message(
                "今いるサーバーは停止できません。停止すると、ここから解除できなくなります。",
                ephemeral=True,
            )
            return
        await bot.store.disable_guild(parsed)
        for row in await bot.store.list_rooms(parsed):
            bot.cancel_delete(int(row["voice_id"]))
        found = bot.get_guild(parsed)
        label = f"{found.name} (`{parsed}`)" if found is not None else f"`{parsed}`"
        await interaction.response.send_message(
            f"{label} を停止しました。そのサーバーでは応答しません。",
            ephemeral=True,
        )

    @group.command(name="unblock", description="停止したサーバーを再開します（運用者専用）")
    @app_commands.describe(guild_id="再開するサーバーID")
    async def setup_unblock(interaction: discord.Interaction, guild_id: str) -> None:
        if not await bot.is_owner_user(interaction.user.id):
            await interaction.response.send_message("この操作はボット運用者だけができます。", ephemeral=True)
            return
        parsed = _parse_guild_id(guild_id)
        if parsed is None:
            await interaction.response.send_message("サーバーIDが正しくありません。数字のIDを指定してください。", ephemeral=True)
            return
        await bot.store.enable_guild(parsed)
        found = bot.get_guild(parsed)
        label = f"{found.name} (`{parsed}`)" if found is not None else f"`{parsed}`"
        await interaction.response.send_message(f"{label} を再開しました。", ephemeral=True)

    @group.command(name="blocked", description="停止中のサーバー一覧（運用者専用）")
    async def setup_blocked(interaction: discord.Interaction) -> None:
        if not await bot.is_owner_user(interaction.user.id):
            await interaction.response.send_message("この操作はボット運用者だけができます。", ephemeral=True)
            return
        ids = await bot.store.list_disabled_guilds()
        if not ids:
            await interaction.response.send_message("停止中のサーバーはありません。", ephemeral=True)
            return
        lines = []
        for gid in ids:
            found = bot.get_guild(gid)
            lines.append(f"- {found.name} (`{gid}`)" if found is not None else f"- `{gid}`")
        await interaction.response.send_message("停止中:\n" + "\n".join(lines), ephemeral=True)

    @group.command(name="servers", description="ボットが入っているサーバー一覧（運用者専用）")
    async def setup_servers(interaction: discord.Interaction) -> None:
        if not await bot.is_owner_user(interaction.user.id):
            await interaction.response.send_message("この操作はボット運用者だけができます。", ephemeral=True)
            return
        silenced = set(await bot.store.list_disabled_guilds())
        lines = []
        for guild in bot.guilds:
            mark = " 停止中" if guild.id in silenced else ""
            lines.append(f"- {guild.name} (`{guild.id}`){mark}")
        if not lines:
            await interaction.response.send_message("参加中のサーバーはありません。", ephemeral=True)
            return
        text = "参加中のサーバー:\n" + "\n".join(lines)
        if len(text) > 1800:
            text = text[:1800] + "\n…"
        await interaction.response.send_message(text, ephemeral=True)
