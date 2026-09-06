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
from room_extra import attach_bind, register_rename, register_setup_name, register_silence

setup = app_commands.Group(name="setup", description="仮部屋の管理者設定")
room = app_commands.Group(name="room", description="一時ボイス部屋")
owner = app_commands.Group(
    name="owner",
    description="ボット運用者専用",
    default_permissions=discord.Permissions.none(),
)
owner_bind_only = app_commands.Group(
    name="owner",
    description="ボット運用者専用",
    default_permissions=discord.Permissions.none(),
)


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
    prefix = await bot.store.get_room_prefix(interaction.guild.id)
    await interaction.response.send_message(
        f"作成先カテゴリ: {cat_text}\n許可ロール: {role_text}\n"
        f"部屋のデフォルト名: **{prefix}_n**\n"
        f"作成専用ハブ: {hub_text}\n稼働中の一時部屋: {len(rooms)}",
        ephemeral=True,
    )


@setup.command(name="hub", description="作成専用ボイスを1つ追加・変更・削除します")
@app_commands.describe(
    action="追加、変更、または削除",
    limit="このハブで作る部屋の人数上限。0は制限なし",
    new_limit="変更するときだけ指定する、新しい人数上限",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="追加", value="add"),
        app_commands.Choice(name="変更", value="change"),
        app_commands.Choice(name="削除", value="remove"),
    ]
)
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_hub(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    limit: app_commands.Range[int, 0, 99],
    new_limit: app_commands.Range[int, 0, 99] | None = None,
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

    prefix = await bot.store.get_room_prefix(interaction.guild.id)
    limit = int(limit)
    row = await bot.store.get_hub_by_limit(interaction.guild.id, limit)
    channel = interaction.guild.get_channel(row["channel_id"]) if row else None

    if action.value == "add":
        if isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message(
                f"人数上限 {format_limit(limit)} のハブはすでにあります: {channel.mention}",
                ephemeral=True,
            )
            return
        if row is not None:
            await bot.store.delete_hub(row["channel_id"])
        await interaction.response.defer(ephemeral=True)
        try:
            channel = await category.create_voice_channel(
                name=hub_channel_name(limit, prefix),
                user_limit=1,
                reason="仮部屋作成ハブ",
            )
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"ハブを作れませんでした。\n{describe_http_error(exc)}",
                ephemeral=True,
            )
            return
        await bot.store.upsert_hub(channel.id, interaction.guild.id, limit)
        await interaction.followup.send(
            f"作成しました: {channel.mention}\n入ると {format_limit(limit)} の一時部屋ができます。",
            ephemeral=True,
        )
        return

    if not isinstance(channel, discord.VoiceChannel):
        if row is not None:
            await bot.store.delete_hub(row["channel_id"])
        await interaction.response.send_message(
            f"人数上限 {format_limit(limit)} のハブはありません。`/setup hub` の追加で作れます。",
            ephemeral=True,
        )
        return

    if action.value == "remove":
        await interaction.response.defer(ephemeral=True)
        name = channel.mention
        try:
            await channel.delete(reason="仮部屋作成ハブを削除")
        except discord.HTTPException as exc:
            await bot.store.delete_hub(channel.id)
            await interaction.followup.send(
                f"チャンネル削除に失敗したため、記録だけ消しました。\n{describe_http_error(exc)}",
                ephemeral=True,
            )
            return
        await bot.store.delete_hub(channel.id)
        await interaction.followup.send(f"{name} を削除しました。", ephemeral=True)
        return

    if new_limit is None:
        await interaction.response.send_message(
            "変更するには `new_limit` に新しい人数上限を指定してください。",
            ephemeral=True,
        )
        return
    new_limit = int(new_limit)
    if new_limit == limit:
        await interaction.response.send_message("同じ人数上限です。", ephemeral=True)
        return
    other = await bot.store.get_hub_by_limit(interaction.guild.id, new_limit)
    if other is not None:
        other_ch = interaction.guild.get_channel(other["channel_id"])
        mention = other_ch.mention if isinstance(other_ch, discord.VoiceChannel) else "別のハブ"
        await interaction.response.send_message(
            f"人数上限 {format_limit(new_limit)} はすでに {mention} です。",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True)
    try:
        await channel.edit(name=hub_channel_name(new_limit, prefix), reason="仮部屋作成ハブの人数上限を変更")
    except discord.HTTPException as exc:
        await interaction.followup.send(
            f"名前の変更に失敗しました。\n{describe_http_error(exc)}",
            ephemeral=True,
        )
        return
    await bot.store.upsert_hub(channel.id, interaction.guild.id, new_limit)
    await interaction.followup.send(
        f"{channel.mention} を {format_limit(limit)} → {format_limit(new_limit)} に変更しました。",
        ephemeral=True,
    )


@setup.command(name="hubs", description="初期の作成専用ボイスを用意します。すでにある場合は一覧だけ出します")
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_hubs(interaction: discord.Interaction) -> None:
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
    await interaction.response.defer(ephemeral=True)
    existing = await bot.store.list_hubs(interaction.guild.id)
    live: list[str] = []
    for row in existing:
        channel = interaction.guild.get_channel(row["channel_id"])
        if isinstance(channel, discord.VoiceChannel):
            live.append(f"{channel.mention}（{format_limit(int(row['user_limit']))}）")
        else:
            await bot.store.delete_hub(row["channel_id"])
    if live:
        await interaction.followup.send(
            "作成専用ボイス:\n" + "\n".join(live) +
            "\n追加・変更・削除は `/setup hub` を使ってください。",
            ephemeral=True,
        )
        return
    created: list[str] = []
    prefix = await bot.store.get_room_prefix(interaction.guild.id)
    for limit in DEFAULT_HUB_LIMITS:
        name = hub_channel_name(limit, prefix)
        try:
            channel = await category.create_voice_channel(
                name=name,
                user_limit=1,
                reason="仮部屋作成ハブ",
            )
        except discord.HTTPException as exc:
            await interaction.followup.send(
                f"ハブ「{name}」を作れませんでした。\n{describe_http_error(exc)}",
                ephemeral=True,
            )
            return
        await bot.store.upsert_hub(channel.id, interaction.guild.id, limit)
        created.append(channel.mention)
    await interaction.followup.send(
        "初期の作成専用ボイスを作りました:\n" + " ".join(created) +
        "\n以降の追加・変更・削除は `/setup hub` です。",
        ephemeral=True,
    )


@setup.command(name="debug", description="ボットから見た権限を表示します（部屋は作りません）")
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_debug(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("サーバー内でのみ使えます。", ephemeral=True)
        return
    settings = await bot.store.get_settings(interaction.guild.id)
    category = None
    if settings and settings["category_id"]:
        found = interaction.guild.get_channel(settings["category_id"])
        if isinstance(found, discord.CategoryChannel):
            category = found
    await interaction.response.send_message(
        format_bot_access(interaction.guild, category),
        ephemeral=True,
    )


@room.command(name="create", description="一時ボイスと、同名のテキストを同時に作ります")
@app_commands.describe(
    name="部屋名（省略すると「名前の部屋」）",
    limit="人数上限。0で制限なし（最大99）",
)
async def room_create(
    interaction: discord.Interaction,
    name: str | None = None,
    limit: app_commands.Range[int, 0, 99] = 0,
) -> None:
    await bot.create_room(interaction, name=name, limit=int(limit))


@room.command(name="panel", description="人数ボタン付きの作成パネルをこのチャンネルに置きます")
@app_commands.checks.has_permissions(manage_channels=True)
async def room_panel(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="一時通話を始める",
        description=(
            "部屋を作るには、人数制限の付いた **＋ 仮音声通話（4人）** などの作成用ボイスに入ってください。\n"
            "同じ名前のテキストも自動で作られます。1人1部屋までです。"
        ),
        color=0xC9893A,
    )
    await interaction.response.send_message(embed=embed, view=CreatePanel(bot))


@bot.tree.error
async def on_app_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        msg = "この操作には「チャンネルの管理」権限が必要です。"
    elif isinstance(error, app_commands.CheckFailure):
        if interaction.guild is not None and await bot.store.is_guild_disabled(interaction.guild.id):
            return
        msg = "この操作を実行する権限がありません。"
    else:
        log.exception("command error")
        msg = "コマンドの実行に失敗しました。"
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


register_rename(room, bot)
register_setup_name(setup, bot)
register_silence(owner, bot)
attach_bind(owner_bind_only, bot)
bot.owner_group = owner
bot.owner_bind_only = owner_bind_only
bot.tree.add_command(setup)
bot.tree.add_command(room)


@bot.tree.interaction_check
async def reject_silenced_guild(interaction: discord.Interaction) -> bool:
    if interaction.guild is not None and await bot.store.is_guild_disabled(interaction.guild.id):
        return False
    return True


def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN がありません。.env にボットトークンを入れてください。")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
