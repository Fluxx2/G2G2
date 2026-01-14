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

MAX_AGE_SECONDS = 210
TOGGLE_INTERVAL = 18
EXPIRY_CHECK_INTERVAL = 3

MAX_EDIT_AGE_SECONDS = 55 * 60  # rotate before Discord 1h edit limit

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
AGGREGATE_MESSAGE_CREATED_AT = None

emoji_state = "⏳"
last_rendered_content = None

code_entries = []  # oldest → newest
message_lock = asyncio.Lock()

# ================================
# HELPERS
# ================================
def has_variant_role(member):
    return any(r.id == VARIANT_ROLE_ID for r in member.roles)

AMBIGUOUS_SETS = {"I": ["I", "l"], "l": ["l", "I"]}

def generate_all_variants(code):
    pools = [AMBIGUOUS_SETS.get(c, [c]) for c in code]
    out = []
    for p in product(*pools):
        v = "".join(p)
        if v not in out:
            out.append(v)
    if code in out:
        out.remove(code)
    out.insert(0, code)
    return out[:MAX_VARIANTS]

def relative_from(ts):
    return f"<t:{int(ts.timestamp())}:R>"

# ================================
# MESSAGE BUILD
# ================================
def build_message():
    if not code_entries:
        return "no codes as of rn"

    lines = []
    total = len(code_entries)

    for idx, entry in enumerate(reversed(code_entries)):
        rank = total - idx

        if len(entry["codes"]) == 1:
            codestr = f"`   {entry['codes'][0]}   `"
        else:
            codestr = "  ".join(f"`   {c}   `" for c in entry["codes"])

        timer = (
            relative_from(entry["created_at"] + timedelta(seconds=MAX_AGE_SECONDS))
            if entry["show_timer"]
            else ""
        )

        lines.append(f"# {rank}) {codestr} {timer}")

    return f"{emoji_state}\n\n" + "\n".join(lines)

# ================================
# MESSAGE CONTROL (ROTATION SAFE)
# ================================
async def get_or_create_message():
    global AGGREGATE_MESSAGE_ID, AGGREGATE_MESSAGE_CREATED_AT

    async with message_lock:
        channel = client.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            return None

        if AGGREGATE_MESSAGE_ID:
            try:
                msg = await channel.fetch_message(AGGREGATE_MESSAGE_ID)
                age = (datetime.now(timezone.utc) - msg.created_at).total_seconds()
                if age >= MAX_EDIT_AGE_SECONDS:
                    await msg.delete()
                    AGGREGATE_MESSAGE_ID = None
                    AGGREGATE_MESSAGE_CREATED_AT = None
                else:
                    return msg
            except discord.NotFound:
                AGGREGATE_MESSAGE_ID = None
                AGGREGATE_MESSAGE_CREATED_AT = None

        async for msg in channel.history(limit=5):
            if msg.author.id == client.user.id:
                AGGREGATE_MESSAGE_ID = msg.id
                AGGREGATE_MESSAGE_CREATED_AT = msg.created_at
                return msg

        msg = await channel.send("no codes as of rn")
        AGGREGATE_MESSAGE_ID = msg.id
        AGGREGATE_MESSAGE_CREATED_AT = msg.created_at
        return msg

async def update_message(force=False):
    global last_rendered_content

    content = build_message()
    if not force and content == last_rendered_content:
        return

    msg = await get_or_create_message()
    if not msg:
        return

    try:
        await msg.edit(content=content)
        last_rendered_content = content
    except discord.NotFound:
        last_rendered_content = None

# ================================
# LOOPS (OPTIMIZED)
# ================================
async def emoji_loop():
    global emoji_state
    await client.wait_until_ready()
    while True:
        if code_entries:
            emoji_state = "🔚" if emoji_state == "⏳" else "⏳"
            await update_message()
        await asyncio.sleep(TOGGLE_INTERVAL)

async def expiry_loop():
    await client.wait_until_ready()
    while True:
        now = datetime.now(timezone.utc)
        changed = False

        while code_entries and (now - code_entries[0]["created_at"]).total_seconds() >= MAX_AGE_SECONDS:
            code_entries.pop(0)
            changed = True

        if changed:
            await update_message(force=True)

        await asyncio.sleep(EXPIRY_CHECK_INTERVAL)

# ================================
# EVENTS
# ================================
@client.event
async def on_ready():
    global AGGREGATE_MESSAGE_ID, last_rendered_content
    print(f"✅ Logged in as {client.user}")

    channel = client.get_channel(TARGET_CHANNEL_ID)
    if channel:
        async for msg in channel.history(limit=100):
            if msg.author.id == client.user.id:
                await msg.delete()

    AGGREGATE_MESSAGE_ID = None
    last_rendered_content = None

    await update_message(force=True)

    client.loop.create_task(emoji_loop())
    client.loop.create_task(expiry_loop())

@client.event
async def on_message(message):
    if message.author.bot or message.channel.id != SOURCE_CHANNEL_ID:
        return

    match = re.search(r"\b[a-zA-Z0-9]{5,6}\b", message.content)
    if not match:
        return

    code_entries.append({
        "source_id": message.id,
        "codes": generate_all_variants(match.group(0))
        if has_variant_role(message.author)
        else [match.group(0)],
        "created_at": message.created_at,
        "show_timer": message.author.id not in NO_TOGGLE_USER_IDS
    })

    await update_message(force=True)

@client.event
async def on_message_edit(before, after):
    if after.channel.id != SOURCE_CHANNEL_ID:
        return

    match = re.search(r"\b[a-zA-Z0-9]{5,6}\b", after.content)
    if not match:
        return

    for e in code_entries:
        if e["source_id"] == after.id:
            e["codes"] = (
                generate_all_variants(match.group(0))
                if has_variant_role(after.author)
                else [match.group(0)]
            )
            await update_message(force=True)
            break

@client.event
async def on_message_delete(message):
    global AGGREGATE_MESSAGE_ID, last_rendered_content

    if message.channel.id == SOURCE_CHANNEL_ID:
        before = len(code_entries)
        code_entries[:] = [e for e in code_entries if e["source_id"] != message.id]
        if len(code_entries) != before:
            await update_message(force=True)
        return

    if message.id == AGGREGATE_MESSAGE_ID:
        AGGREGATE_MESSAGE_ID = None
        last_rendered_content = None
        await update_message(force=True)

# ================================
# RUN
# ================================
client.run(TOKEN)

