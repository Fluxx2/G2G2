import discord
import asyncio
import os
import sqlite3
from datetime import datetime, date, timedelta
import pytz
from discord.errors import HTTPException

# ================================
# CONFIG
# ================================
TARGET_CHANNEL_ID = 1442370325831487608
COMMAND_CHANNEL_ID = 1442370326116827259
TARGET_EMOJI_ID = 1443112156693397534

DB_FILE = "wins.db"

TOKEN = os.getenv("DISCORD_TOKEN_4")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN_4 not set")

IST = pytz.timezone("Asia/Kolkata")

# ================================
# BOT SETUP
# ================================
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

client = discord.Client(intents=intents)

# ================================
# DATABASE
# ================================
db = sqlite3.connect(DB_FILE)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS wins (
    user_id INTEGER PRIMARY KEY,
    win_count INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_messages (
    user_id INTEGER,
    msg_date TEXT,
    count INTEGER,
    PRIMARY KEY (user_id, msg_date)
)
""")

db.commit()

def today():
    return date.today().isoformat()

# ================================
# DAILY RESET (IST MIDNIGHT)
# ================================
async def daily_reset_task():
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.now(IST)
        next_day = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        await asyncio.sleep((next_day - now).total_seconds())
        cursor.execute("DELETE FROM wins")
        cursor.execute("DELETE FROM daily_messages")
        db.commit()

# ================================
# HISTORY SYNC (LAST 24H)
# ================================
async def sync_last_24h():
    channel = client.get_channel(TARGET_CHANNEL_ID)
    if not channel:
        return

    cutoff = datetime.now(IST) - timedelta(hours=24)

    async for msg in channel.history(after=cutoff, limit=None):
        if not msg.author.bot:
            cursor.execute("""
            INSERT INTO daily_messages (user_id, msg_date, count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, msg_date)
            DO UPDATE SET count = count + 1
            """, (msg.author.id, today()))

        for reaction in msg.reactions:
            if getattr(reaction.emoji, "id", None) == TARGET_EMOJI_ID:
                async for user in reaction.users():
                    if not user.bot:
                        cursor.execute("""
                        INSERT INTO wins (user_id, win_count)
                        VALUES (?, 1)
                        ON CONFLICT(user_id)
                        DO UPDATE SET win_count = win_count + 1
                        """, (user.id,))

    db.commit()

# ================================
# :55 IST HOURLY SYNC
# ================================
async def ist_55_sync_task():
    await client.wait_until_ready()

    while not client.is_closed():
        now = datetime.now(IST)
        next_run = now.replace(minute=55, second=0, microsecond=0)

        if now.minute >= 55:
            next_run += timedelta(hours=1)

        await asyncio.sleep((next_run - now).total_seconds())

        try:
            await sync_last_24h()
        except:
            pass

# ================================
# EVENTS
# ================================
@client.event
async def on_message(message):
    if message.author.bot:
        return

    # Ignore all channels except command channel
    if message.channel.id != COMMAND_CHANNEL_ID:
        return

    # Track messages only in target channel
    if message.channel.id == TARGET_CHANNEL_ID:
        cursor.execute("""
        INSERT INTO daily_messages (user_id, msg_date, count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, msg_date)
        DO UPDATE SET count = count + 1
        """, (message.author.id, today()))
        db.commit()

    # ----------------------------
    # !check_wins
    # ----------------------------
    if message.content.lower().startswith("!check_wins"):
        target = message.mentions[0] if message.mentions else message.author

        cursor.execute("SELECT win_count FROM wins WHERE user_id = ?", (target.id,))
        wins = cursor.fetchone()
        wins = wins[0] if wins else 0

        cursor.execute("""
        SELECT count FROM daily_messages
        WHERE user_id = ? AND msg_date = ?
        """, (target.id, today()))
        msgs = cursor.fetchone()
        msgs = msgs[0] if msgs else 0

        text = (
            f"🏆 **{target.display_name} joined** - `{wins} wins`\n"
            f"📊 wins done today: `{msgs}`"
            if target != message.author
            else
            f"🏆 **You joined** - `{wins} wins`\n"
            f"📊 wins done today: `{msgs}`"
        )

        await message.reply(text, mention_author=True)

    # ----------------------------
    # !winslb
    # ----------------------------
    if message.content.lower() == "!winslb":
        cursor.execute("""
        SELECT user_id, win_count
        FROM wins
        ORDER BY win_count DESC
        LIMIT 10
        """)
        rows = cursor.fetchall()

        if not rows:
            await message.reply("📭 No wins yet today.", mention_author=True)
            return

        lines = []
        for rank, (uid, count) in enumerate(rows, start=1):
            member = message.guild.get_member(uid)
            if not member:
                try:
                    member = await message.guild.fetch_member(uid)
                except:
                    member = None

            name = member.display_name if member else f"User {uid}"
            lines.append(f"**{rank}. {name}** - `{count} wins`")

        await message.reply(
            "🏆 **Leaderboard (Last 24 Hours)**\n" + "\n".join(lines),
            mention_author=True
        )

@client.event
async def on_reaction_add(reaction, user):
    if (
        user.bot
        or reaction.message.channel.id != TARGET_CHANNEL_ID
        or getattr(reaction.emoji, "id", None) != TARGET_EMOJI_ID
    ):
        return

    cursor.execute("""
    INSERT INTO wins (user_id, win_count)
    VALUES (?, 1)
    ON CONFLICT(user_id)
    DO UPDATE SET win_count = win_count + 1
    """, (user.id,))
    db.commit()

# ================================
# READY
# ================================
@client.event
async def on_ready():
    print(f"✅ Bot logged in as {client.user}")
    client.loop.create_task(daily_reset_task())
    client.loop.create_task(ist_55_sync_task())

# ================================
# RUN
# ================================
client.run(TOKEN)
