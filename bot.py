import discord
from discord.ext import commands
import sqlite3
import os
from flask import Flask
import threading

# -----------------------------
# Flask server (for Render uptime)
# -----------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

# -----------------------------
# Database Setup (SQLite)
# -----------------------------
conn = sqlite3.connect("database.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users (
    discord_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    messages INTEGER DEFAULT 0,
    claimed INTEGER DEFAULT 0
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id INTEGER,
    market_id TEXT,
    value INTEGER,
    status TEXT DEFAULT 'pending'
)
""")

conn.commit()

# -----------------------------
# Discord Bot Setup
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix=".", intents=intents)

FOOTER_TEXT = "Made By Kabir Juneja and Ishan Jain"

# -----------------------------
# Bot Events
# -----------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()  # Global sync only
    print(f"✅ Logged in as {bot.user}")

# -----------------------------
# Slash Commands
# -----------------------------
@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! 🏓", ephemeral=True)

# -----------------------------
# Prefix Commands
# -----------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def addbal(ctx, value: int, member: discord.Member):
    c.execute("INSERT OR IGNORE INTO users (discord_id) VALUES (?)", (member.id,))
    c.execute("UPDATE users SET balance = balance + ? WHERE discord_id = ?", (value, member.id))
    conn.commit()

    embed = discord.Embed(
        title="Balance Updated",
        description=f"💰 {value} Pokecoins credited to {member.mention}",
        color=discord.Color.green()
    )
    embed.set_footer(text=FOOTER_TEXT, icon_url=bot.user.avatar.url if bot.user.avatar else None)

    await ctx.send(embed=embed)
    try:
        await member.send(f"✅ You have been credited with {value} PC in your account.")
    except:
        pass

@bot.command()
async def inv(ctx):
    c.execute("SELECT balance, messages, claimed FROM users WHERE discord_id = ?", (ctx.author.id,))
    row = c.fetchone()
    if not row:
        balance, messages, claimed = 0, 0, 0
    else:
        balance, messages, claimed = row

    embed = discord.Embed(
        title=f"{ctx.author.name}'s Inventory",
        color=discord.Color.blue()
    )
    embed.add_field(name="💰 Balance", value=f"{balance} PC", inline=False)
    embed.add_field(name="💬 Messages", value=str(messages), inline=False)
    embed.add_field(name="📦 Claimed", value=str(claimed), inline=False)
    embed.set_footer(text=FOOTER_TEXT, icon_url=bot.user.avatar.url if bot.user.avatar else None)

    await ctx.send(embed=embed)

# Example claim panel placeholder (can be extended later)
@bot.command()
async def claimpanel(ctx):
    embed = discord.Embed(
        title="Poketwo Claim Panel",
        description="Use the buttons below to claim Pokecoins or check your balance.",
        color=discord.Color.purple()
    )
    embed.set_footer(text=FOOTER_TEXT, icon_url=bot.user.avatar.url if bot.user.avatar else None)
    await ctx.send(embed=embed)

# -----------------------------
# Flask Thread
# -----------------------------
threading.Thread(target=run_flask).start()

# -----------------------------
# Run Bot
# -----------------------------
bot.run(os.getenv("DISCORD_TOKEN"))
