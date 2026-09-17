from __future__ import annotations

import discord

from ui import human_members, log


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
