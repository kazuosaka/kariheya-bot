from __future__ import annotations

import os

import discord
from discord import app_commands

from kariheya import (
    bot,
    log,
    CreatePanel,
    DEFAULT_HUB_LIMITS,
    describe_http_error,
    format_bot_access,
    format_limit,
    hub_channel_name,
)
from ui import sanitize_name

setup = app_commands.Group(name="setup", description="仮部屋の管理者設定")
room = app_commands.Group(name="room", description="一時ボイス部屋")


@setup.command(name="category", description="一時部屋を作るカテゴリを指定します")
@app_commands.describe(category="一時ボイスとテキストを作るカテゴリ")
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_category(
    interaction: discord.Interaction,
    category: discord.CategoryChannel,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
        return
    await bot.store.upsert_category(interaction.guild.id, category.id)
    await interaction.response.send_message(
        f"作成先カテゴリを {category.mention} にしました。",
        ephemeral=True,
    )


@setup.command(name="role", description="部屋を作れるロールを追加または削除します")
@app_commands.describe(role="許可するロール", action="追加するか削除するか")
@app_commands.choices(
    action=[
        app_commands.Choice(name="追加", value="add"),
        app_commands.Choice(name="削除", value="remove"),
    ]
)
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_role(
    interaction: discord.Interaction,
    role: discord.Role,
    action: app_commands.Choice[str],
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
        return
    if action.value == "add":
        await bot.store.add_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"{role.mention} を作成許可に追加しました。",
            ephemeral=True,
        )
    else:
        await bot.store.remove_role(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"{role.mention} を作成許可から外しました。",
            ephemeral=True,
        )


@setup.command(name="show", description="いまの設定を表示します")
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_show(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
        return
    settings = await bot.store.get_settings(interaction.guild.id)
    roles = await bot.store.list_roles(interaction.guild.id)
    rooms = await bot.store.list_rooms(interaction.guild.id)
    hubs = await bot.store.list_hubs(interaction.guild.id)
    category = None
    if settings and settings["category_id"]:
        category = interaction.guild.get_channel(settings["category_id"])
    role_text = " ".join(f"<@&{rid}>" for rid in roles) or "（未設定）"
    cat_text = category.mention if isinstance(category, discord.CategoryChannel) else "（未設定）"
    hub_bits: list[str] = []
    for hub in hubs:
        ch = interaction.guild.get_channel(hub["channel_id"])
        label = format_limit(int(hub["user_limit"]))
        hub_bits.append(ch.mention if isinstance(ch, discord.VoiceChannel) else f"（欠落:{label}）")
    hub_text = " ".join(hub_bits) or "（未作成。`/setup hubs`）"
    await interaction.response.send_message(
        f"作成先カテゴリ: {cat_text}\n許可ロール: {role_text}\n"
        f"作成専用ハブ: {hub_text}\n稼働中の一時部屋: {len(rooms)}",
        ephemeral=True,
    )
