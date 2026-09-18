"""Commands for weekly/monthly voice-start counts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

try:
    JST = ZoneInfo("Asia/Tokyo")
except Exception:
    JST = timezone(timedelta(hours=9))

MAX_ROWS = 20


def week_range(now: datetime | None = None) -> tuple[int, int, str]:
    local = (now or datetime.now(tz=JST)).astimezone(JST)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=local.weekday())
    end = start + timedelta(days=7)
    last = end - timedelta(seconds=1)
    label = f"{start.month}/{start.day}\u301c{last.month}/{last.day}"
    return int(start.timestamp()), int(end.timestamp()), label


def month_range(now: datetime | None = None) -> tuple[int, int, str]:
    local = (now or datetime.now(tz=JST)).astimezone(JST)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    label = f"{start.year}\u5e74{start.month}\u6708"
    return int(start.timestamp()), int(end.timestamp()), label


def _name(guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    if member is not None:
        return member.display_name
    return f"<@{user_id}>"


async def _ranking_text(
    bot,
    guild: discord.Guild,
    start_ts: int,
    end_ts: int,
    title: str,
) -> str:
    rows = await bot.store.count_room_starts(guild.id, start_ts, end_ts, limit=MAX_ROWS)
    total, users = await bot.store.count_room_starts_total(guild.id, start_ts, end_ts)
    if total == 0:
        return (
            f"**{title}**\n"
            "\u3053\u306e\u671f\u9593\u306b\u8a18\u9332\u3055\u308c\u305f\u958b\u59cb\u306f\u3042\u308a\u307e\u305b\u3093\u3002\n"
            "\u4f5c\u6210\u7528\u30dc\u30a4\u30b9\u304b\u3089\u90e8\u5c4b\u3092\u4f5c\u3063\u305f\u3068\u304d\u304b\u3089\u96c6\u8a08\u3055\u308c\u307e\u3059\u3002"
        )
    lines = [f"**{title}**", f"\u5408\u8a08 **{total}\u56de** / **{users}\u4eba**", ""]
    rank = 0
    last_count = None
    for index, row in enumerate(rows, start=1):
        count = int(row["cnt"])
        if count != last_count:
            rank = index
            last_count = count
        lines.append(f"{rank}. {_name(guild, int(row['user_id']))} \u2014 **{count}\u56de**")
    if users > len(rows):
        lines.append(f"\u2026\u307b\u304b {users - len(rows)}\u4eba")
    return "\n".join(lines)


def register_stats(bot) -> app_commands.Group:
    stats = app_commands.Group(name="stats", description="\u97f3\u58f0\u901a\u8a71\u3092\u59cb\u3081\u305f\u56de\u6570")

    @stats.command(name="week", description="\u4eca\u9031\u3001\u97f3\u58f0\u901a\u8a71\u3092\u59cb\u3081\u305f\u56de\u6570\u306e\u30e9\u30f3\u30ad\u30f3\u30b0")
    async def stats_week(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("\u30b5\u30fc\u30d0\u30fc\u5185\u3067\u306e\u307f\u4f7f\u3048\u307e\u3059\u3002", ephemeral=True)
            return
        start_ts, end_ts, label = week_range()
        text = await _ranking_text(bot, interaction.guild, start_ts, end_ts, f"\u4eca\u9031\u306e\u958b\u59cb\u56de\u6570\uff08{label}\uff09")
        await interaction.response.send_message(text)

    @stats.command(name="month", description="\u4eca\u6708\u3001\u97f3\u58f0\u901a\u8a71\u3092\u59cb\u3081\u305f\u56de\u6570\u306e\u30e9\u30f3\u30ad\u30f3\u30b0")
    async def stats_month(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("\u30b5\u30fc\u30d0\u30fc\u5185\u3067\u306e\u307f\u4f7f\u3048\u307e\u3059\u3002", ephemeral=True)
            return
        start_ts, end_ts, label = month_range()
        text = await _ranking_text(bot, interaction.guild, start_ts, end_ts, f"\u4eca\u6708\u306e\u958b\u59cb\u56de\u6570\uff08{label}\uff09")
        await interaction.response.send_message(text)

    @stats.command(name="me", description="\u81ea\u5206\u306e\u4eca\u9031\u30fb\u4eca\u6708\u306e\u958b\u59cb\u56de\u6570")
    async def stats_me(interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("\u30b5\u30fc\u30d0\u30fc\u5185\u3067\u306e\u307f\u4f7f\u3048\u307e\u3059\u3002", ephemeral=True)
            return
        week_start, week_end, week_label = week_range()
        month_start, month_end, month_label = month_range()
        week_count = await bot.store.count_room_starts_for_user(
            interaction.guild.id, interaction.user.id, week_start, week_end
        )
        month_count = await bot.store.count_room_starts_for_user(
            interaction.guild.id, interaction.user.id, month_start, month_end
        )
        await interaction.response.send_message(
            f"**{interaction.user.display_name}** \u306e\u958b\u59cb\u56de\u6570\n"
            f"\u4eca\u9031\uff08{week_label}\uff09: **{week_count}\u56de**\n"
            f"\u4eca\u6708\uff08{month_label}\uff09: **{month_count}\u56de**",
            ephemeral=True,
        )

    return stats
