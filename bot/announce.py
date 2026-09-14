from __future__ import annotations

import discord
from discord import app_commands

from ui import format_limit


async def post_room_announce(
    bot,
    guild_id: int,
    member: discord.abc.User,
    text: discord.TextChannel,
    voice: discord.VoiceChannel,
    room_name: str,
    limit: int,
) -> None:
    if not await bot.store.get_announce_enabled(guild_id):
        return
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


def register_setup_announce(setup: app_commands.Group, bot) -> None:
    @setup.command(name="announce", description="部屋作成時のテキスト案内を出すかどうかを変えます")
    @app_commands.describe(mode="投稿する / 投稿しない。省略すると現在の設定を表示")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="投稿する", value="on"),
            app_commands.Choice(name="投稿しない", value="off"),
        ]
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def setup_announce(
        interaction: discord.Interaction,
        mode: app_commands.Choice[str] | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
            return
        current = await bot.store.get_announce_enabled(interaction.guild.id)
        if mode is None:
            state = "投稿する" if current else "投稿しない"
            await interaction.response.send_message(
                f"部屋作成時の案内は、いま **{state}** です。\n"
                "変える例: `/setup announce mode:投稿しない`\n"
                "投稿しない場合も、同名のテキストチャンネルは空のまま作られます。",
                ephemeral=True,
            )
            return
        enabled = mode.value == "on"
        await bot.store.upsert_announce_enabled(interaction.guild.id, enabled)
        if enabled:
            await interaction.response.send_message(
                "これから作る部屋のテキストに、案内を投稿します。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "これから作る部屋では、テキストへの案内投稿を止めます。\n"
            "テキストチャンネル自体は、空の状態で今までどおり作られます。",
            ephemeral=True,
        )
