from __future__ import annotations

import discord
from discord import app_commands


MIN_GRACE = 3
MAX_GRACE = 120


def register_setup_grace(setup: app_commands.Group, bot) -> None:
    @setup.command(name="grace", description="全員退出後、部屋を消すまでの秒数を変えます")
    @app_commands.describe(seconds="3〜120。省略すると現在の値を表示します")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def setup_grace(
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 3, 120] | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
            return
        current = await bot.store.get_grace_seconds(interaction.guild.id)
        if seconds is None:
            await interaction.response.send_message(
                f"全員がボイスを出てから **{current}秒** 後に部屋を削除します。\n"
                f"変更する例: `/setup grace seconds:5`（{MIN_GRACE}〜{MAX_GRACE}秒）",
                ephemeral=True,
            )
            return
        value = int(seconds)
        await bot.store.upsert_grace_seconds(interaction.guild.id, value)
        await interaction.response.send_message(
            f"全員退出後の削除待ちを **{value}秒** にしました。\n"
            "すでにカウント中の部屋は、次に空になったときから新しい秒数になります。",
            ephemeral=True,
        )
