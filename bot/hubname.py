from __future__ import annotations

import discord
from discord import app_commands

from ui import HUB_NAME_PREFIX, describe_http_error, hub_channel_name, sanitize_prefix


async def apply_hub_names(bot, guild: discord.Guild, prefix: str) -> str | None:
    hubs = await bot.store.list_hubs(guild.id)
    for hub in hubs:
        channel = guild.get_channel(hub["channel_id"])
        if not isinstance(channel, discord.VoiceChannel):
            continue
        new_name = hub_channel_name(int(hub["user_limit"]), prefix)
        if channel.name == new_name:
            continue
        try:
            await channel.edit(name=new_name, reason="作成用ボイス名を変更")
        except discord.HTTPException as exc:
            return describe_http_error(exc)
    return None


def register_setup_hubname(setup: app_commands.Group, bot) -> None:
    @setup.command(name="hubname", description="作成用ボイスの名前を変えます。部屋名とは別です")
    @app_commands.describe(name="作成用ボイスの名前。省略すると初期値に戻します")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def setup_hubname(
        interaction: discord.Interaction,
        name: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
            return
        cleaned = sanitize_prefix(name) if name else HUB_NAME_PREFIX
        if not cleaned:
            await interaction.response.send_message(
                "有効な名前を入力してください。`#` `,` `:` は使えません。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await bot.store.upsert_hub_prefix(interaction.guild.id, cleaned)
        err = await apply_hub_names(bot, interaction.guild, cleaned)
        if err:
            await interaction.followup.send(
                f"設定は **{cleaned}** にしましたが、チャンネル名の変更に失敗しました。\n{err}",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"作成用ボイスの名前を **{cleaned}（人数）** にしました。\n"
            "一時部屋の名前（例: 仮音声通話_1）は変わりません。",
            ephemeral=True,
        )
