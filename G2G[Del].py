import discord
import asyncio
import os
import sqlite3
from datetime import datetime, timedelta, date
import pytz

# ================================
# CONFIG
# ================================
TARGET_CHANNEL_ID = 1442370325831487608
COMMAND_CHANNEL_ID = 1442370326116827259
TARGET_EMOJI_ID = 1443112156693397534

DB_FILE = "wins.db"
BOT_DELETE_AFTER_SECONDS = 220
BOT_CLEANUP_INTERVAL = 15

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.UTC

TOKEN = os.getenv("DISCORD_TOKEN_4")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN_4 not set")

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS processed_messages (
    msg_id INTEGER PRIMARY KEY
)
""")

db.commit()

def today():
    return date.today().isoformat()

# ================================
# DAILY RESET
# ================================
async def daily_reset_task():
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.now(IST)
        next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_midnight - now).total_seconds())
        cursor.execute("DELETE FROM wins")
        cursor.execute("DELETE FROM daily_messages")
        cursor.execute("DELETE FROM processed_messages")
        db.commit()

# ================================
# IST :55 HOURLY SYNC (24H)
# ================================
async def ist_55_sync_task():
    await client.wait_until_ready()
    while not client.is_closed():
        now = datetime.now(IST)
        next_run = now.replace(minute=55, second=0, microsecond=0)
        if now.minute >= 55:
            next_run += timedelta(hours=1)
        await asyncio.sleep((next_run - now).total_seconds())
        await sync_last_24h()  # Only DB update, no message

# ================================
# SYNC LAST 24 HOURS (no double-count)
# ================================
async def sync_last_24h():
    channel = client.get_channel(TARGET_CHANNEL_ID)
    if not channel:
        return
    cutoff = datetime.now(UTC) - timedelta(hours=24)

    async for msg in channel.history(after=cutoff, limit=None):
        # Skip already processed messages
        cursor.execute("SELECT 1 FROM processed_messages WHERE msg_id = ?", (msg.id,))
        if cursor.fetchone():
            continue

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

        # Mark message as processed
        cursor.execute("INSERT OR IGNORE INTO processed_messages (msg_id) VALUES (?)", (msg.id,))

    db.commit()

# ================================
# BOT MESSAGE CLEANUP
# ================================
async def delete_bot_messages_task():
    await client.wait_until_ready()
    while not client.is_closed():
        channel = client.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            await asyncio.sleep(BOT_CLEANUP_INTERVAL)
            continue

        now = datetime.now(UTC)
        try:
            async for msg in channel.history(limit=50):
                if msg.author.bot:
                    age = (now - msg.created_at).total_seconds()
                    if age >= BOT_DELETE_AFTER_SECONDS:
                        try:
                            await msg.delete()
                            await asyncio.sleep(0.4)
                        except:
                            pass
        except:
            pass

        await asyncio.sleep(BOT_CLEANUP_INTERVAL)

# ================================
# EVENTS
# ================================
@client.event
async def on_message(message):
    if message.author.bot:
        return

    # Only track messages in TARGET_CHANNEL_ID
    if message.channel.id == TARGET_CHANNEL_ID:
        cursor.execute("""
        INSERT INTO daily_messages (user_id, msg_date, count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, msg_date)
        DO UPDATE SET count = count + 1
        """, (message.author.id, today()))
        db.commit()

    # Commands only in COMMAND_CHANNEL_ID
    if message.channel.id != COMMAND_CHANNEL_ID:
        return

    # !check_wins
    if message.content.lower().startswith("!check_wins"):
        target = message.mentions[0] if message.mentions else message.author

        cursor.execute("SELECT win_count FROM wins WHERE user_id = ?", (target.id,))
        wins = cursor.fetchone()
        wins = wins[0] if wins else 0

        cursor.execute("SELECT count FROM daily_messages WHERE user_id = ? AND msg_date = ?", (target.id, today()))
        msgs = cursor.fetchone()
        msgs = msgs[0] if msgs else 0

        await message.reply(
            f"🏆 **{target.display_name} - `{wins} wins`**\n"
            f"📊 Messages today: `{msgs}`",
            mention_author=True
        )

    # !winslb
    if message.content.lower() == "!winslb":
        await post_leaderboard(message.guild)

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
# LEADERBOARD POSTER
# ================================
async def post_leaderboard(guild):
    cursor.execute("SELECT user_id, win_count FROM wins ORDER BY win_count DESC LIMIT 10")
    rows = cursor.fetchall()
    channel = client.get_channel(COMMAND_CHANNEL_ID)
    if not channel:
        return

    if not rows:
        await channel.send("📭 **Leaderboard is empty.**")
        return

    lines = []
    for rank, (uid, count) in enumerate(rows, start=1):
        member = guild.get_member(uid) or await guild.fetch_member(uid)
        name = member.display_name if member else f"User {uid}"
        lines.append(f"{rank}. {name} - `{count} wins`")

    await channel.send("🏆 **Leaderboard (Last 24h)**\n" + "\n".join(lines))

# ================================
# READY
# ================================
@client.event
async def on_ready():
    print(f"✅ Bot logged in as {client.user}")

    # Immediately update DB silently
    await sync_last_24h()

    # Start background tasks
    client.loop.create_task(daily_reset_task())
    client.loop.create_task(ist_55_sync_task())
    client.loop.create_task(delete_bot_messages_task())

# ================================
# RUN
# ================================
client.run(TOKEN)
