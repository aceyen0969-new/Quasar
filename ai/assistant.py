import re

import discord

from ai.manager import ask_ai
from utils.messages import send_long_message


async def setup(bot):
    pass


def build_server_context(guild: discord.Guild) -> str:
    member_count = guild.member_count

    channels = list(guild.channels)

    text_channel_count = sum(
        isinstance(channel, discord.TextChannel)
        for channel in channels
    )

    voice_channel_count = sum(
        isinstance(channel, discord.VoiceChannel)
        for channel in channels
    )

    category_count = sum(
        isinstance(channel, discord.CategoryChannel)
        for channel in channels
    )

    role_count = len(guild.roles)

    return (
        "CURRENT DISCORD SERVER FACTS\n"
        "Use these facts as the source of truth. "
        "Never invent or estimate values that are provided here.\n"
        f"Server name: {guild.name}\n"
        f"Server ID: {guild.id}\n"
        f"Total members: "
        f"{member_count if member_count is not None else 'Unknown'}\n"
        f"Total channels: {len(channels)}\n"
        f"Text channels: {text_channel_count}\n"
        f"Voice channels: {voice_channel_count}\n"
        f"Categories: {category_count}\n"
        f"Roles including @everyone: {role_count}\n"
    )


def is_total_member_count_question(prompt: str) -> bool:
    normalized = " ".join(prompt.lower().split())
    normalized = re.sub(r"[?!.,]+$", "", normalized)

    excluded_terms = (
        "active",
        "activity",
        "online",
        "offline",
        "this week",
        "last week",
        "this month",
        "last month",
        "today",
        "yesterday",
        "analytics",
        "growth",
        "joined",
        "left",
        "messages",
        "in the past",
        "during the",
    )

    if any(term in normalized for term in excluded_terms):
        return False

    patterns = (
        r"\bhow many members\b",
        r"\bhow many users\b",
        r"\bmember count\b",
        r"\btotal members\b",
        r"\btotal number of members\b",
        r"\bhow many people are in (?:this|the) server\b",
        r"\bhow many people (?:do we have|are here)\b",
        r"\bhow many members (?:do we have|are there|we have|we got)\b",
        r"\bwhat is (?:the )?(?:server )?member count\b",
        r"\bwhat(?:'s| is) (?:our|the) (?:total )?member count\b",
        r"\bilan(?: ang)? members\b",
        r"\bilan ang miyembro\b",
        r"\bpila ka members\b",
    )

    return any(re.search(pattern, normalized) for pattern in patterns)


def remember_message(
    channel_history: list,
    prompt: str,
    answer: str,
) -> None:
    channel_history.append({
        "role": "user",
        "content": prompt,
    })

    channel_history.append({
        "role": "assistant",
        "content": answer,
    })

    if len(channel_history) > 20:
        del channel_history[:-20]


async def handle_message(message: discord.Message):
    if message.author.bot:
        return

    guild = message.guild

    if guild is None:
        return

    if message.channel.name != "ai-assistant":
        return

    prompt = message.content.strip()

    if not prompt:
        return

    if not hasattr(handle_message, "history"):
        handle_message.history = {}

    channel_history = handle_message.history.setdefault(
        message.channel.id,
        [],
    )

    if is_total_member_count_question(prompt):
        member_count = guild.member_count

        if member_count is None:
            answer = (
                "I couldn't retrieve the current member count "
                "from Discord right now. Please try again shortly."
            )
        else:
            member_label = "member" if member_count == 1 else "members"
            answer = (
                f"This server currently has "
                f"**{member_count:,} {member_label}**."
            )

        await message.channel.send(answer)

        remember_message(
            channel_history,
            prompt,
            answer,
        )

        print("----------------------------------------")
        print("Response source: Discord API")
        print(f"Server: {guild.name}")
        print(f"Member count: {member_count}")
        print("----------------------------------------")
        return

    server_context = build_server_context(guild)

    full_prompt = (
        f"{server_context}\n"
        "When answering questions about this server, use the "
        "provided facts. If a fact is unknown, say so instead "
        "of guessing. Distinguish total server members from "
        "members active during an analytics period.\n\n"
        f"USER QUESTION:\n{prompt}"
    )

    result = await ask_ai(
        full_prompt,
        history=channel_history,
    )

    answer = result.get("answer")
    provider = result.get("provider")

    if not answer:
        await message.channel.send(
            "❌ All AI providers are currently unavailable."
        )
        return

    await send_long_message(
        message.channel,
        answer,
    )

    remember_message(
        channel_history,
        prompt,
        answer,
    )

    print("----------------------------------------")
    print(f"AI Provider used: {provider}")
    print(f"Conversation memory: {len(channel_history)} messages")
    print(f"Server context supplied: {guild.id}")
    print("----------------------------------------")