
from datetime import datetime, timezone

import discord
from discord import app_commands

from analytics.guardian_storage import (
    get_guardian_incidents,
    initialize_guardian_storage,
    resolve_guardian_incident,
)


guardian_group = app_commands.Group(
    name="guardian",
    description="Review and manage Guardian moderation incidents.",
)


def _can_manage_guardian(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False

    permissions = interaction.user.guild_permissions

    return (
        permissions.manage_messages
        or permissions.administrator
    )


def _get_value(incident, key, default=None):
    try:
        value = incident[key]
    except (KeyError, IndexError, TypeError):
        return default

    return default if value is None else value


def _format_timestamp(value) -> str:
    try:
        timestamp = datetime.fromtimestamp(
            float(value),
            tz=timezone.utc,
        )
        return timestamp.strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return "Unknown"


@guardian_group.command(
    name="history",
    description="View recent Guardian incidents in this server.",
)
@app_commands.describe(
    limit="Number of recent incidents to display, from 1 to 10.",
)
async def guardian_history(
    interaction: discord.Interaction,
    limit: app_commands.Range[int, 1, 10] = 10,
):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a server.",
            ephemeral=True,
        )
        return

    if not _can_manage_guardian(interaction):
        await interaction.response.send_message(
            "You need Manage Messages or Administrator permission "
            "to view Guardian incidents.",
            ephemeral=True,
        )
        return

    try:
        initialize_guardian_storage()

        incidents = get_guardian_incidents(
            guild_id=guild.id,
            limit=limit,
        )
    except Exception:
        await interaction.response.send_message(
            "I couldn't retrieve Guardian history. Check the bot logs.",
            ephemeral=True,
        )
        return

    if not incidents:
        await interaction.response.send_message(
            "No Guardian incidents were found for this server.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title=f"Guardian Incident History · {guild.name}",
        description=f"Showing up to {limit} recent incidents.",
        color=discord.Color.orange(),
    )

    for incident in incidents:
        incident_id = _get_value(incident, "id", "?")
        user_id = _get_value(incident, "user_id")
        channel_id = _get_value(incident, "channel_id")
        incident_type = _get_value(
            incident,
            "incident_type",
            "Unknown",
        )
        reason = _get_value(
            incident,
            "reason",
            "No reason recorded.",
        )
        status = _get_value(incident, "status", "unknown")
        detected_at = _format_timestamp(
            _get_value(incident, "detected_at")
        )
        violation_count = _get_value(
            incident,
            "violation_count",
            0,
        )
        deletion_status = _get_value(
            incident,
            "deletion_status",
            "unknown",
        )
        message_url = _get_value(incident, "message_url")
        excerpt = _get_value(
            incident,
            "message_excerpt",
            "",
        )

        lines = [
            f"**Member:** <@{user_id}>"
            if user_id
            else "**Member:** Unknown",
            f"**Type:** `{str(incident_type)[:80]}`",
            f"**Status:** `{str(status)[:30]}`",
            f"**Detected:** {detected_at}",
            f"**Violations:** {violation_count}",
            f"**Deletion:** `{str(deletion_status)[:40]}`",
            f"**Reason:** {str(reason)[:250]}",
        ]

        if channel_id:
            lines.append(f"**Channel:** <#{channel_id}>")

        if excerpt:
            safe_excerpt = str(excerpt).replace("`", "ˋ")
            lines.append(
                f"**Excerpt:** `{safe_excerpt[:180]}`"
            )

        if message_url:
            lines.append(f"[Open message]({message_url})")

        embed.add_field(
            name=f"Incident #{incident_id}",
            value="\n".join(lines)[:1024],
            inline=False,
        )

    embed.set_footer(
        text="Incident IDs are server-scoped for resolution."
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@guardian_group.command(
    name="resolve",
    description="Mark a Guardian incident as resolved.",
)
@app_commands.describe(
    incident_id="The incident ID shown in Guardian history.",
)
async def guardian_resolve(
    interaction: discord.Interaction,
    incident_id: app_commands.Range[int, 1],
):
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a server.",
            ephemeral=True,
        )
        return

    if not _can_manage_guardian(interaction):
        await interaction.response.send_message(
            "You need Manage Messages or Administrator permission "
            "to resolve Guardian incidents.",
            ephemeral=True,
        )
        return

    try:
        initialize_guardian_storage()

        resolved = resolve_guardian_incident(
            incident_id=incident_id,
            guild_id=guild.id,
        )
    except Exception:
        await interaction.response.send_message(
            "I couldn't resolve that incident. Check the bot logs.",
            ephemeral=True,
        )
        return

    if not resolved:
        await interaction.response.send_message(
            f"Incident `#{incident_id}` wasn't found in this server, "
            "or it has already been resolved.",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"Resolved Guardian incident `#{incident_id}`.",
        ephemeral=True,
    )


def setup(bot):
    initialize_guardian_storage()
    bot.tree.add_command(guardian_group)
