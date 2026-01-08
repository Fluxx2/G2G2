import discord
import asyncio
import os
from datetime import datetime
import pytz

# ================================
# CONFIG
# ================================
CHANNEL_IDS = {
    1449692284596523068,
    1442370325831487608
}

DELETE_AFTER_SECONDS = 220
CHECK_INTERVAL = 15
MAX_MESSAGES_TO_CHECK = 40

# ================================
# BOT SETUP
# ================================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set")

intents = discord.Intents.default()
client = discord.Client(intents=intents)

UTC = pytz.UTC

# ================================
# BACKGROUND TASK
# ================================
async def delete_old_bot_messages():
    await client.wait_until_ready()

    while not client.is_closed():
        now = datetime.now(tz=UTC)

        for channel_id in CHANNEL_IDS:
            channel = client.get_channel(channel_id)
            if not channel:
                continue

            async for msg in channel.history(limit=MAX_MESSAGES_TO_CHECK):
                if not msg.author.bot:
                    continue

                age = (now - msg.created_at).total_seconds()
                if age >= DELETE_AFTER_SECONDS:
                    try:
                        await msg.delete()
                        await asyncio.sleep(0.4)  # rate-limit safety
                    except:
                        pass

        await asyncio.sleep(CHECK_INTERVAL)

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
