import discord
import asyncio
import os
from datetime import datetime
import pytz
from discord.errors import DiscordServerError, HTTPException

# ================================
# CONFIG
# ================================
CHANNEL_IDS = {
    1449692284596523068,
    1442370325831487608
}

TARGET_CHANNEL_ID = 1442370325831487608
TARGET_EMOJI_ID = 1443112156693397534

DELETE_AFTER_SECONDS = 220
CHECK_INTERVAL = 15
MAX_MESSAGES_TO_CHECK = 20
MAX_HISTORY_SCAN = 1000

# ================================
# BOT SETUP
# ================================
TOKEN = os.getenv("DISCORD_TOKEN_4")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN_4 not set")

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

client = discord.Client(intents=intents)

UTC = pytz.UTC

# ================================
# HELPERS
# ================================
async def count_user_messages_today(channel, user):
    start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    count = 0

    async for msg in channel.history(after=start, limit=None):
        if not msg.author.bot and msg.author.id == user.id:
            count += 1

    return count

# ================================
# BACKGROUND TASK
# ================================
async def delete_old_bot_messages():
    await client.wait_until_ready()

    while not client.is_closed():
        try:
            now = datetime.now(tz=UTC)

            for channel_id in CHANNEL_IDS:
                channel = client.get_channel(channel_id)
                if not channel:
                    continue

                try:
                    async for msg in channel.history(limit=MAX_MESSAGES_TO_CHECK):
                        if not msg.author.bot:
                            continue

                        age = (now - msg.created_at).total_seconds()
                        if age >= DELETE_AFTER_SECONDS:
                            try:
                                await msg.delete()
                                await asyncio.sleep(0.4)
                            except HTTPException:
                                pass

                except DiscordServerError:
                    await asyncio.sleep(15)

        except Exception:
            await asyncio.sleep(20)

        await asyncio.sleep(CHECK_INTERVAL)

# ================================
# COMMAND: !check_wins [@user]
# ================================
@client.event
async def on_message(message):
    if message.author.bot:
        return

    if not message.content.lower().startswith("!check_wins"):
        return

    target_user = message.mentions[0] if message.mentions else message.author
    channel = client.get_channel(TARGET_CHANNEL_ID)
    if not channel:
        return

    wins = 0

    try:
        async for msg in channel.history(limit=MAX_HISTORY_SCAN):
            for reaction in msg.reactions:
                if getattr(reaction.emoji, "id", None) == TARGET_EMOJI_ID:
                    try:
                        async for reactor in reaction.users():
                            if reactor.id == target_user.id:
                                wins += 1
                                break
                    except DiscordServerError:
                        continue
    except DiscordServerError:
        pass

    # ✅ USER-ONLY total wins today
    try:
        today_total = await count_user_messages_today(channel, target_user)
    except DiscordServerError:
        today_total = 0

    response = (
        f"🏆 **{target_user.display_name}** has **{wins} wins**!\n"
        f"📊 **Total wins today:** `{today_total}`"
        if target_user != message.author
        else
        f"🏆 **You** have **{wins} wins**!\n"
        f"📊 **Total wins today:** `{today_total}`"
    )

    try:
        await message.reply(response, mention_author=True)
    except HTTPException:
        await message.channel.send(response)

# ================================
# EVENTS
# ================================
@client.event
async def on_ready():
    print(f"✅ Cleanup Bot logged in as {client.user}")
    client.loop.create_task(delete_old_bot_messages())

# ================================
# RUN
# ================================
client.run(TOKEN)
