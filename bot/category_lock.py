from __future__ import annotations

import discord

from ui import describe_http_error


def bot_role(guild: discord.Guild) -> discord.Role | None:
    me = guild.me
    if me is None:
        return None
    for role in reversed(me.roles):
        if role.is_bot_managed():
            return role
    if me.top_role != guild.default_role:
        return me.top_role
    return None


async def lock_category_creation(bot, category: discord.CategoryChannel) -> str:
    guild = category.guild
    me = guild.me
    if me is None:
        return "ボットのメンバー情報を取得できません。"
    role = bot_role(guild)
    if role is None:
        return "ボット専用ロールがありません。サーバーでボットのロールを確認してください。"
    try:
        bot_ow = category.overwrites_for(role)
        bot_ow.manage_channels = True
        bot_ow.manage_roles = True
        bot_ow.view_channel = True
        bot_ow.connect = True
        bot_ow.speak = True
        bot_ow.send_messages = True
        await category.set_permissions(
            role,
            overwrite=bot_ow,
            reason="仮部屋ボットがチャンネルを作れるようにする",
        )
    except discord.Forbidden:
        return (
            "カテゴリの権限を変更できません。"
            "ボットのロールを、対象カテゴリで操作できる位置まで上げてください。"
        )
    except discord.HTTPException as exc:
        return f"ボットロールの権限設定に失敗しました。\n{describe_http_error(exc)}"

    denied = 0
    skipped_admin: list[str] = []
    skipped_high: list[str] = []

    async def deny_manage(target: discord.Role) -> None:
        nonlocal denied
        overwrite = category.overwrites_for(target)
        if overwrite.manage_channels is False:
            return
        overwrite.manage_channels = False
        await category.set_permissions(
            target,
            overwrite=overwrite,
            reason="カテゴリ内の手動チャンネル作成を禁止",
        )
        denied += 1

    try:
        await deny_manage(guild.default_role)
    except discord.HTTPException:
        skipped_high.append("@everyone")

    for item in guild.roles:
        if item.is_default() or item.id == role.id:
            continue
        if item.managed:
            continue
        if item.permissions.administrator:
            skipped_admin.append(item.name)
            continue
        if not item.permissions.manage_channels:
            overwrite = category.overwrites_for(item)
            if overwrite.manage_channels is not True:
                continue
        if item >= me.top_role:
            skipped_high.append(item.name)
            continue
        try:
            await deny_manage(item)
        except discord.Forbidden:
            skipped_high.append(item.name)
        except discord.HTTPException:
            skipped_high.append(item.name)

    lines = [
        f"{category.mention} では、通常のチャンネル作成を禁止しました。ボットからの作成はできます。",
        f"チャンネル管理を禁止した対象: {denied} 件",
    ]
    if skipped_admin:
        lines.append(
            "管理者権限を持つロールは Discord の仕様で禁止できません: "
            + ", ".join(f"`{name}`" for name in skipped_admin[:8])
        )
    if skipped_high:
        lines.append(
            "ボットより上、または変更できなかったロール: "
            + ", ".join(f"`{name}`" for name in skipped_high[:8])
        )
    return "\n".join(lines)
