import asyncio
import time

import discord

from analytics.guardian_storage import record_guardian_incident
from moderation.detector import SpamDetector
from moderation.violations import violation_tracker

from security.actions import (
    ActionRequest,
    can_execute_automatically,
    execute_action,
)


class ModerationManager:
    def __init__(self):
        self.detector = SpamDetector(
            max_messages=5,
            time_window=5,
            duplicate_limit=3,
        )
        self.alert_channel_name = "mod-logs"

    async def cleanup_warning(self, warning_message):
        await asyncio.sleep(10)

        try:
            await warning_message.delete()
            print("GUARDIAN WARNING CLEANUP: SUCCESS", flush=True)

        except discord.NotFound:
            print(
                "GUARDIAN WARNING CLEANUP: Already deleted.",
                flush=True,
            )

        except discord.Forbidden:
            print(
                "GUARDIAN WARNING CLEANUP: Missing permission.",
                flush=True,
            )

        except discord.HTTPException as error:
            print(
                f"GUARDIAN WARNING CLEANUP: {error}",
                flush=True,
            )

    async def send_incident_alert(
        self,
        message,
        result,
        violation_count,
        delete_status,
        incident_id,
    ):
        guild = message.guild

        alert_channel = discord.utils.get(
            guild.text_channels,
            name=self.alert_channel_name,
        )

        if alert_channel is None:
            print(
                "GUARDIAN ALERT ERROR: "
                f"#{self.alert_channel_name} was not found "
                f"in guild {guild.id}.",
                flush=True,
            )
            return False

        excerpt = message.content.strip()

        if not excerpt:
            excerpt = "[No text content]"

        if len(excerpt) > 900:
            excerpt = excerpt[:897] + "..."

        embed = discord.Embed(
            title="Quasar Guardian: Spam Incident",
            description=(
                "A new spam incident was detected. "
                "Review the evidence before taking further action."
            ),
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="Incident ID",
            value=str(incident_id),
            inline=True,
        )

        embed.add_field(
            name="Member",
            value=f"{message.author} (`{message.author.id}`)",
            inline=False,
        )

        embed.add_field(
            name="Channel",
            value=message.channel.mention,
            inline=True,
        )

        embed.add_field(
            name="Incident type",
            value=result["type"],
            inline=True,
        )

        embed.add_field(
            name="Incident count",
            value=str(violation_count),
            inline=True,
        )

        embed.add_field(
            name="Reason",
            value=result["reason"][:1024],
            inline=False,
        )

        embed.add_field(
            name="Message excerpt",
            value=excerpt,
            inline=False,
        )

        embed.add_field(
            name="Message",
            value=f"[Jump to message]({message.jump_url})",
            inline=True,
        )

        embed.add_field(
            name="Spam deletion",
            value=delete_status,
            inline=True,
        )

        embed.set_footer(
            text=f"Server: {guild.name} | Server ID: {guild.id}"
        )

        try:
            await alert_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )

            print(
                "GUARDIAN ALERT SENT: "
                f"guild={guild.id}, "
                f"user={message.author.id}, "
                f"incident={incident_id}, "
                f"type={result['type']}",
                flush=True,
            )

            return True

        except discord.Forbidden:
            print(
                "GUARDIAN ALERT ERROR: Quasar cannot send "
                f"messages in #{self.alert_channel_name}.",
                flush=True,
            )

        except discord.HTTPException as error:
            print(
                f"GUARDIAN ALERT ERROR: {error}",
                flush=True,
            )

        return False

    async def handle_message(self, message):
        if message.author.bot:
            return

        if message.guild is None:
            return

        if not message.content.strip():
            return

        result = self.detector.check_message(
            guild_id=message.guild.id,
            user_id=message.author.id,
            content=message.content,
        )

        if not result["is_spam"]:
            return

        guild_id = message.guild.id
        user_id = message.author.id

        if result["new_incident"]:
            violation_count = violation_tracker.add_violation(
                guild_id=guild_id,
                user_id=user_id,
            )
        else:
            violation_count = violation_tracker.get_violations(
                guild_id=guild_id,
                user_id=user_id,
            )

        delete_request = ActionRequest(
            action="delete_spam",
            target_id=message.id,
            target_name=message.author.name,
            reason=result["reason"],
            data={
                "guild_id": guild_id,
                "channel_id": message.channel.id,
                "message_id": message.id,
                "spam_type": result["type"],
                "violation_count": violation_count,
            },
        )

        delete_status = "Not attempted"

        if can_execute_automatically(delete_request):
            delete_result = await execute_action(
                delete_request,
                message=message,
            )

            if delete_result["success"]:
                delete_status = "Success"
            else:
                delete_status = (
                    f"Failed: {delete_result['error']}"
                )
        else:
            delete_status = "Blocked by security policy"

        if not result["new_incident"]:
            print(
                "GUARDIAN: Spam continued within an existing "
                "incident; no duplicate alert. "
                f"guild={guild_id}, user={user_id}, "
                f"type={result['type']}, "
                f"delete={delete_status}",
                flush=True,
            )
            return

        incident_id = record_guardian_incident(
            guild_id=guild_id,
            user_id=user_id,
            channel_id=message.channel.id,
            message_id=message.id,
            incident_type=result["type"],
            reason=result["reason"],
            message_excerpt=message.content.strip()[:500],
            message_url=message.jump_url,
            violation_count=violation_count,
            deletion_status=delete_status,
            detected_at=time.time(),
        )

        print("----------------------------------------", flush=True)
        print("QUASAR GUARDIAN INCIDENT", flush=True)
        print(f"Incident ID: {incident_id}", flush=True)
        print(f"Guild: {message.guild.name} ({guild_id})", flush=True)
        print(f"User: {message.author} ({user_id})", flush=True)
        print(f"Channel: {message.channel.name}", flush=True)
        print(f"Type: {result['type']}", flush=True)
        print(f"Reason: {result['reason']}", flush=True)
        print(f"Incident count: {violation_count}", flush=True)
        print(f"Spam deletion: {delete_status}", flush=True)

        await self.send_incident_alert(
            message=message,
            result=result,
            violation_count=violation_count,
            delete_status=delete_status,
            incident_id=incident_id,
        )

        if violation_count == 2:
            try:
                warning_message = await message.channel.send(
                    f"⚠️ {message.author.mention}, "
                    "Quasar detected another spam incident. "
                    "Please slow down and avoid repeating messages."
                )

                asyncio.create_task(
                    self.cleanup_warning(warning_message)
                )

                print(
                    "GUARDIAN: Second-incident warning sent.",
                    flush=True,
                )

            except discord.Forbidden:
                print(
                    "GUARDIAN WARNING ERROR: "
                    "Missing permission to send messages.",
                    flush=True,
                )

            except discord.HTTPException as error:
                print(
                    f"GUARDIAN WARNING ERROR: {error}",
                    flush=True,
                )

        elif violation_count >= 3:
            print(
                "GUARDIAN REVIEW REQUIRED: Repeated incidents "
                "detected. No automatic timeout was issued.",
                flush=True,
            )

        print("----------------------------------------", flush=True)


moderation_manager = ModerationManager()