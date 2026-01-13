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
                                continue

                except DiscordServerError:
                    print(f"⚠️ Discord 503 in channel {channel_id}")
                    await asyncio.sleep(15)

        except Exception as e:
            print(f"🔥 Background task error: {e}")
            await asyncio.sleep(20)

        await asyncio.sleep(CHECK_INTERVAL)

# ================================
# COMMAND: !check_wins
# ================================
@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.lower() != "!check_wins":
        return

    channel = client.get_channel(TARGET_CHANNEL_ID)
    if not channel:
        await message.channel.send("❌ Target channel not found.")
        return

    wins = 0
    user = message.author

    async for msg in channel.history(limit=MAX_HISTORY_SCAN):
        for reaction in msg.reactions:
            if getattr(reaction.emoji, "id", None) == TARGET_EMOJI_ID:
                async for reactor in reaction.users():
                    if reactor.id == user.id:
                        wins += 1
                        break

    await message.channel.send(
        f"🏆 **{user.display_name}**, you have **{wins} wins**!"
    )

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
