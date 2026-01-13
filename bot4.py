import discord
import asyncio
import os
import re
from datetime import datetime, timezone, timedelta
from itertools import product

# ================================
# CONFIG
# ================================
SOURCE_CHANNEL_ID = 1442370325831487608
TARGET_CHANNEL_ID = 1449692284596523068

MAX_AGE_SECONDS = 225
TOGGLE_INTERVAL = 28

NO_TOGGLE_USER_IDS = {
    1252645184777359391,
    906546198754775082
}

VARIANT_ROLE_ID = 1460446818407022785
MAX_VARIANTS = 16

# ================================
# BOT SETUP
# ================================
TOKEN = os.getenv("DISCORD_TOKEN_3")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN_3 not set")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

AGGREGATE_MESSAGE_ID = None
emoji_state = "⏳"

# oldest → newest
code_entries = []

# ================================
# HELPERS
# ================================
def has_variant_role(member: discord.Member) -> bool:
    return any(role.id == VARIANT_ROLE_ID for role in member.roles)

AMBIGUOUS_SETS = {
    "I": ["I", "l"],
    "l": ["l", "I"],
}

def generate_all_variants(code: str) -> list[str]:
    pools = [AMBIGUOUS_SETS.get(c, [c]) for c in code]
    variants = ["".join(p) for p in product(*pools)]

    unique = []
    for v in variants:
        if v not in unique:
            unique.append(v)

    if code in unique:
        unique.remove(code)
    unique.insert(0, code)

    return unique[:MAX_VARIANTS]

def relative_from(ts: datetime) -> str:
    return f"<t:{int(ts.timestamp())}:R>"

# ================================
# MESSAGE BUILD (ONE MESSAGE ONLY)
# ================================
def build_message() -> str:
    if not code_entries:
        return "no codes as of rn"

    lines = []
    total = len(code_entries)

    # newest → oldest (oldest = #1)
    for idx, entry in enumerate(reversed(code_entries)):
        rank = total - idx

        code_text = (
            entry["codes"][0]
            if len(entry["codes"]) == 1
            else " / ".join(entry["codes"])
        )

        timer = (
            relative_from(entry["created_at"] + timedelta(seconds=MAX_AGE_SECONDS))
            if entry["show_timer"]
            else ""
        )

        lines.append(f"{rank}) `{code_text}` {timer}")

    return f"{emoji_state}\n\n" + "\n".join(lines)

# ================================
# CORE UPDATE (EDIT ONLY)
# ================================
async def ensure_message():
    global AGGREGATE_MESSAGE_ID

    channel = client.get_channel(TARGET_CHANNEL_ID)
    if not channel:
        return None

    if AGGREGATE_MESSAGE_ID:
        try:
            return await channel.fetch_message(AGGREGATE_MESSAGE_ID)
        except discord.NotFound:
            AGGREGATE_MESSAGE_ID = None

    msg = await channel.send("no codes as of rn")
    AGGREGATE_MESSAGE_ID = msg.id
    return msg

async def update_message():
    msg = await ensure_message()
    if not msg:
        return

    try:
        await msg.edit(content=build_message())
    except discord.HTTPException:
        pass

# ================================
# LOOPS
# ================================
async def emoji_toggle_loop():
    global emoji_state
    await client.wait_until_ready()

    while not client.is_closed():
        if code_entries:
            emoji_state = "🔚" if emoji_state == "⏳" else "⏳"
            await update_message()
        await asyncio.sleep(TOGGLE_INTERVAL)

async def expiry_loop():
    await client.wait_until_ready()

    while not client.is_closed():
        now = datetime.now(timezone.utc)

        while code_entries and (now - code_entries[0]["created_at"]).total_seconds() >= MAX_AGE_SECONDS:
            code_entries.pop(0)

        await update_message()
        await asyncio.sleep(1)

# ================================
# EVENTS
# ================================
@client.event
async def on_ready():
    global AGGREGATE_MESSAGE_ID

    print(f"✅ Logged in as {client.user}")

    # 🔥 DELETE ALL OLD BOT MESSAGES
    channel = client.get_channel(TARGET_CHANNEL_ID)
    if channel:
        async for msg in channel.history(limit=100):
            if msg.author.id == client.user.id:
                try:
                    await msg.delete()
                except discord.HTTPException:
                    pass

    AGGREGATE_MESSAGE_ID = None

    await update_message()

    client.loop.create_task(emoji_toggle_loop())
    client.loop.create_task(expiry_loop())

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

    codes = (
        [code]
        if not has_variant_role(message.author)
        else generate_all_variants(code)
    )

    code_entries.append({
        "source_id": message.id,
        "codes": codes,
        "created_at": message.created_at,
        "show_timer": message.author.id not in NO_TOGGLE_USER_IDS
    })

    await update_message()

@client.event
async def on_message_edit(before, after):
    if after.channel.id != SOURCE_CHANNEL_ID:
        return

    match = re.search(r"\b[a-zA-Z0-9]{5,6}\b", after.content)
    if not match:
        return

    for entry in code_entries:
        if entry["source_id"] == after.id:
            code = match.group(0)
            entry["codes"] = (
                [code]
                if not has_variant_role(after.author)
                else generate_all_variants(code)
            )
            break

    await update_message()

@client.event
async def on_message_delete(message):
    global AGGREGATE_MESSAGE_ID, code_entries

    # source deleted → remove code
    if message.channel.id == SOURCE_CHANNEL_ID:
        code_entries = [
            e for e in code_entries
            if e["source_id"] != message.id
        ]
        await update_message()
        return

    # aggregate deleted → recreate
    if message.id == AGGREGATE_MESSAGE_ID:
        AGGREGATE_MESSAGE_ID = None
        await update_message()

# ================================
# RUN
# ================================
client.run(TOKEN)
