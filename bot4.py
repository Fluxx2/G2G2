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
CODE_COUNTDOWN_SECONDS = 240

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
toggle_tasks = {}

# ================================
# HELPERS
# ================================
def discord_relative_timestamp(seconds_from_now: int) -> str:
    unix = int(datetime.now(timezone.utc).timestamp()) + seconds_from_now
    return f"<t:{unix}:R>"

def build_content(source_id: int) -> str:
    data = code_data[source_id]

    # ✅ ONLY CODE FORMAT FOR SPECIFIC USERS
    if data["only_code"]:
        return f"# `     {data['code']}     `"

    # Normal format
    return (
        f"# `     {data['code']}     `\n"
        f"{data['emoji']} {data['timer']}"
    )

async def toggle_code_emoji(source_message_id: int):
    while True:
        data = code_data.get(source_message_id)
        msg = mirrored_messages.get(source_message_id)

        if not data or not msg or data["only_code"]:
            return

        data["emoji"] = "🔚" if data["emoji"] == "⏳" else "⏳"
        try:
            await msg.edit(content=build_content(source_message_id))
        except:
            pass

        await asyncio.sleep(28)

# ================================
# EVENTS
# ================================
@client.event
async def on_ready():
    print(f"✅ Code Bot logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.id != SOURCE_CHANNEL_ID:
        return

    match = re.search(r"\b[a-zA-Z0-9]{5,6}\b", message.content)
    if not match:
        return

    code = match.group(0)
    only_code = message.author.id in NO_TOGGLE_USER_IDS

    timer = (
        discord_relative_timestamp(CODE_COUNTDOWN_SECONDS)
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

    # 🚫 No emoji toggle for specific users
    if not only_code:
        toggle_tasks[message.id] = client.loop.create_task(
            toggle_code_emoji(message.id)
        )

@client.event
async def on_message_edit(before, after):
    if after.channel.id != SOURCE_CHANNEL_ID:
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
    except:
        pass

@client.event
async def on_message_delete(message):
    if message.channel.id != SOURCE_CHANNEL_ID:
        return

    msg = mirrored_messages.pop(message.id, None)
    code_data.pop(message.id, None)

    task = toggle_tasks.pop(message.id, None)
    if task:
        task.cancel()

    if msg:
        try:
            await msg.delete()
        except:
            pass

# ================================
# RUN
# ================================
client.run(TOKEN)
