import discord
import asyncio
import os
import re
from datetime import datetime, timezone

# ================================
# CONFIG
# ================================
SOURCE_CHANNEL_ID = 1442370325831487608
TARGET_CHANNEL_ID = 1449692284596523068
MAX_AGE_SECONDS = 240  # 4 minutes
TOGGLE_INTERVAL = 28   # seconds
EDIT_THROTTLE = 1.2    # seconds between PATCH calls

NO_TOGGLE_USER_IDS = {
    1252645184777359391,
    906546198754775082
}

# ================================
# BOT SETUP
# ================================
TOKEN = os.getenv("DISCORD_TOKEN_3")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN_3 not set")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

mirrored_messages = {}
code_data = {}

# ================================
# HELPERS
# ================================
def is_fresh(msg: discord.Message) -> bool:
    age = (datetime.now(timezone.utc) - msg.created_at).total_seconds()
    return age <= MAX_AGE_SECONDS

def discord_relative_timestamp(seconds_from_now: int) -> str:
    unix = int(datetime.now(timezone.utc).timestamp()) + seconds_from_now
    return f"<t:{unix}:R>"

def build_content(source_id: int) -> str:
    data = code_data[source_id]

    if data["only_code"]:
        return f"# `     {data['code']}     `"

    return (
        f"# `     {data['code']}     `\n"
        f"{data['emoji']} {data['timer']}"
    )

async def expire_mirrored_message(source_id: int):
    await asyncio.sleep(MAX_AGE_SECONDS)

    msg = mirrored_messages.pop(source_id, None)
    code_data.pop(source_id, None)

    if msg:
        try:
            await msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

# ================================
# EMOJI TOGGLE LOOP (SINGLE LOOP)
# ================================
async def emoji_toggle_loop():
    await client.wait_until_ready()

    while not client.is_closed():
        for source_id, msg in list(mirrored_messages.items()):
            data = code_data.get(source_id)

            if not data or data["only_code"]:
                continue

            data["emoji"] = "🔚" if data["emoji"] == "⏳" else "⏳"

            try:
                await msg.edit(content=build_content(source_id))
                await asyncio.sleep(EDIT_THROTTLE)
            except (discord.NotFound, discord.HTTPException):
                pass

        await asyncio.sleep(TOGGLE_INTERVAL)

# ================================
# EVENTS
# ================================
@client.event
async def on_ready():
    print(f"✅ Code Bot logged in as {client.user}")
    client.loop.create_task(emoji_toggle_loop())

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.id != SOURCE_CHANNEL_ID:
        return

    if not is_fresh(message):
        return

    match = re.search(r"\b[a-zA-Z0-9]{5,6}\b", message.content)
    if not match:
        return

    code = match.group(0)
    only_code = message.author.id in NO_TOGGLE_USER_IDS

    timer = (
        discord_relative_timestamp(MAX_AGE_SECONDS)
        if not only_code
        else ""
    )

    code_data[message.id] = {
        "code": code,
        "timer": timer,
        "emoji": "⏳",
        "only_code": only_code
    }

    target_channel = client.get_channel(TARGET_CHANNEL_ID)
    if not target_channel:
        return

    mirrored_messages[message.id] = await target_channel.send(
        build_content(message.id)
    )

    client.loop.create_task(expire_mirrored_message(message.id))

@client.event
async def on_message_edit(before, after):
    if after.channel.id != SOURCE_CHANNEL_ID:
        return

    if not is_fresh(after):
        return

    data = code_data.get(after.id)
    msg = mirrored_messages.get(after.id)

    if not data or not msg:
        return

    match = re.search(r"\b[a-zA-Z0-9]{5,6}\b", after.content)
    if not match:
        return

    data["code"] = match.group(0)

    try:
        await msg.edit(content=build_content(after.id))
    except (discord.NotFound, discord.HTTPException):
        pass

@client.event
async def on_message_delete(message):
    if message.channel.id != SOURCE_CHANNEL_ID:
        return

    msg = mirrored_messages.pop(message.id, None)
    code_data.pop(message.id, None)

    if msg:
        try:
            await msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

# ================================
# RUN
# ================================
client.run(TOKEN)
