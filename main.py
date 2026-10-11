import os
import asyncio

import discord
from discord.ext import commands
from dotenv import load_dotenv

from commands import ping
from commands import serverinfo
from commands import serverstats
from commands import channels
from commands import organize
from commands import aistatus
from commands import approvaltest
from commands import cleanup
from commands import analytics
from commands import objective
from commands import analytics_access

from onboarding import register_onboarding

from moderation.moderator import moderation_manager

from ai import assistant

from analytics import observer
from analytics.database import initialize_database
from analytics.scheduler import analytics_scheduler

from api.dashboard_api import (
    start_dashboard_api,
    stop_dashboard_api,
)

from language_engine.detector_bridge import (
    detect_message,
    learn_unknown_words,
)

from conflict_detection.detector import (
    detect_conflict_signals,
)


load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)

scheduler_task = None


async def load_features():
    await ping.setup(bot)
    await serverinfo.setup(bot)
    await serverstats.setup(bot)
    await channels.setup(bot)
    await organize.setup(bot)
    await assistant.setup(bot)
    await aistatus.setup(bot)
    await approvaltest.setup(bot)
    await cleanup.setup(bot)
    await analytics.setup(bot)
    await objective.setup(bot)
    await analytics_access.setup(bot)


@bot.event
async def on_ready():
    global scheduler_task

    print("----------------------------------------")
    print(f"Logged in as {bot.user}")
    print(f"Connected to {len(bot.guilds)} server(s)")
    print("----------------------------------------")

    try:
        print(
            "COMMAND TREE:",
            [
                command.name
                for command in bot.tree.get_commands()
            ],
        )

        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")

    except Exception as error:
        print("COMMAND SYNC ERROR:")
        print(repr(error))

    if scheduler_task is None or scheduler_task.done():
        print("ANALYTICS SCHEDULER: Starting...")

        scheduler_task = asyncio.create_task(
            analytics_scheduler(bot)
        )


async def on_message(message):
    if message.guild is None:
        await bot.process_commands(message)
        return

    if message.author.bot:
        await bot.process_commands(message)
        return

    try:
        await observer.handle_message(message)

        print(
            "ANALYTICS MESSAGE RECORDED: "
            f"guild={message.guild.id}, "
            f"channel={message.channel.id}, "
            f"user={message.author.id}",
            flush=True,
        )

    except Exception as error:
        print("ANALYTICS OBSERVER ERROR:")
        print(repr(error))

    try:
        await moderation_manager.handle_message(message)

    except Exception as error:
        print("MODERATION HANDLER ERROR:")
        print(repr(error))

    if message.content.strip():
        try:
            language_result = detect_message(
                message.content
            )

            print(
                "LANGUAGE DETECTOR:",
                language_result,
            )

            unknown_words = language_result.get(
                "unknown_words",
                [],
            )

            if unknown_words:
                learning_results = learn_unknown_words(
                    language_result
                )

                print(
                    "LANGUAGE LEARNING:",
                    learning_results,
                )

            conflict_result = detect_conflict_signals(
                message.content
            )

            print(
                "CONFLICT SIGNALS:",
                conflict_result,
            )

        except Exception as error:
            print("MESSAGE ANALYSIS ERROR:")
            print(repr(error))

    try:
        await assistant.handle_message(message)

    except Exception as error:
        print("ASSISTANT HANDLER ERROR:")
        print(repr(error))

    finally:
        await bot.process_commands(message)


async def main():
    global scheduler_task

    initialize_database()
    register_onboarding(bot)

    bot.add_listener(
        on_message,
        "on_message",
    )

    dashboard_runner = await start_dashboard_api(bot)

    try:
        async with bot:
            await load_features()

            try:
                await bot.start(DISCORD_TOKEN)

            finally:
                if scheduler_task is not None:
                    scheduler_task.cancel()

                    try:
                        await scheduler_task
                    except asyncio.CancelledError:
                        pass

    finally:
        await stop_dashboard_api(dashboard_runner)


print("Starting AI Server Assistant...")

asyncio.run(main())