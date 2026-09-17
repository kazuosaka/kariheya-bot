from __future__ import annotations

import discord
from discord import app_commands

from ui import (
    describe_http_error,
    format_limit,
    hub_channel_name,
    human_members,
    log,
)


def is_secret_row(row: object) -> bool:
    try:
        return int(row["secret"]) != 0  # type: ignore[index]
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def secret_text_overwrites(
    guild: discord.Guild,
    members: list[discord.Member],
) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
            read_message_history=False,
        ),
    }
    me = guild.me
    if me is not None:
        overwrites[me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            embed_links=True,
            attach_files=True,
        )
    for member in members:
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            attach_files=True,
            add_reactions=True,
        )
    return overwrites


async def apply_secret_text_access(
    text: discord.TextChannel,
    voice: discord.VoiceChannel,
) -> None:
    try:
        await text.edit(
            overwrites=secret_text_overwrites(text.guild, human_members(voice)),
            reason="秘密部屋の閲覧者を通話メンバーに合わせる",
        )
    except discord.HTTPException:
        log.exception("failed to sync secret text access for %s", text.id)


def register_setup_secrethub(setup: app_commands.Group, bot) -> None:
    @setup.command(name="secrethub", description="通話中だけテキストが読める作成用ボイスを追加・削除します")
    @app_commands.describe(
        action="追加または削除",
        limit="このハブで作る部屋の人数上限。0は制限なし",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="追加", value="add"),
            app_commands.Choice(name="削除", value="remove"),
        ]
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def setup_secrethub(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        limit: app_commands.Range[int, 0, 99],
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
            return
        settings = await bot.store.get_settings(interaction.guild.id)
        category = None
        if settings and settings["category_id"]:
            found = interaction.guild.get_channel(settings["category_id"])
            if isinstance(found, discord.CategoryChannel):
                category = found
        if category is None:
            await interaction.response.send_message(
                "先に `/setup category` でカテゴリを指定してください。",
                ephemeral=True,
            )
            return
        limit_i = int(limit)
        row = await bot.store.get_hub_by_limit(interaction.guild.id, limit_i, secret=True)
        channel = interaction.guild.get_channel(row["channel_id"]) if row else None
        hub_prefix = await bot.store.get_hub_prefix(interaction.guild.id)

        if action.value == "add":
            if isinstance(channel, discord.VoiceChannel):
                await interaction.response.send_message(
                    f"秘密・人数上限 {format_limit(limit_i)} のハブはすでにあります: {channel.mention}",
                    ephemeral=True,
                )
                return
            if row is not None:
                await bot.store.delete_hub(row["channel_id"])
            await interaction.response.defer(ephemeral=True)
            try:
                channel = await category.create_voice_channel(
                    name=hub_channel_name(limit_i, hub_prefix, secret=True),
                    user_limit=1,
                    reason="仮部屋 秘密ハブ",
                )
            except discord.HTTPException as exc:
                await interaction.followup.send(
                    f"ハブを作れませんでした。\n{describe_http_error(exc)}",
                    ephemeral=True,
                )
                return
            await bot.store.upsert_hub(channel.id, interaction.guild.id, limit_i, secret=True)
            await interaction.followup.send(
                f"作成しました: {channel.mention}\n"
                "ここに入ると、テキストは通話中の人だけが読める一時部屋ができます。",
                ephemeral=True,
            )
            return

        if not isinstance(channel, discord.VoiceChannel):
            if row is not None:
                await bot.store.delete_hub(row["channel_id"])
            await interaction.response.send_message(
                f"秘密・人数上限 {format_limit(limit_i)} のハブはありません。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        name = channel.mention
        try:
            await channel.delete(reason="秘密ハブを削除")
        except discord.HTTPException as exc:
            await bot.store.delete_hub(channel.id)
            await interaction.followup.send(
                f"チャンネル削除に失敗したため、記録だけ消しました。\n{describe_http_error(exc)}",
                ephemeral=True,
            )
            return
        await bot.store.delete_hub(channel.id)
        await interaction.followup.send(f"{name} を削除しました。", ephemeral=True)
