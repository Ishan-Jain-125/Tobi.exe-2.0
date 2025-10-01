import os
import sqlite3
import asyncio
from threading import Thread
from flask import Flask
from discord.ext import commands
import discord
from discord import app_commands
from aiohttp import web

# ================= CONFIG =================
PREFIX = "."
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

DB_PATH = "data.db"

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        messages INTEGER DEFAULT 0,
        bal INTEGER DEFAULT 0,
        claimed INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()

def add_user_if_not_exists(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

# ================= FLASK REAL SERVER =================
flask_app = Flask("main")

@flask_app.route("/")
def home():
    return "✅ Flask server running (real uptime)"

def run_flask():
    port = int(os.environ.get("PORT", 8080))  # Render uses $PORT
    flask_app.run(host="0.0.0.0", port=port)

# ================= AIOHTTP DUMMY SERVER =================
async def aiohttp_handle(request):
    return web.Response(text="👋 Dummy aiohttp server is alive!")

async def run_aiohttp():
    app = web.Application()
    app.router.add_get("/", aiohttp_handle)
    dummy_port = int(os.environ.get("DUMMY_PORT", 9090))  # default dummy 9090
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", dummy_port)
    await site.start()
    print(f"🚀 aiohttp dummy server running on port {dummy_port}")

# ================= DISCORD BOT EVENTS =================
@bot.event
async def on_ready():
    print(f"✅ Bot ready as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🌐 Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Slash sync failed: {e}")

    # create claims-log channel if not exists
    for guild in bot.guilds:
        log_channel = discord.utils.get(guild.text_channels, name="claims-log")
        if not log_channel:
            await guild.create_text_channel("claims-log")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    add_user_if_not_exists(message.author.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET messages = messages + 1 WHERE user_id = ?", (message.author.id,))
    conn.commit()
    conn.close()
    await bot.process_commands(message)

# ================= ADMIN COMMANDS =================
@bot.command()
@commands.has_permissions(administrator=True)
async def addbal(ctx, amount: int, user: discord.Member):
    add_user_if_not_exists(user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET bal = bal + ? WHERE user_id = ?", (amount, user.id))
    conn.commit()
    conn.close()
    await ctx.send(f"✅ Added {amount} PC to {user.mention}'s account!")
    try:
        await user.send(f"💰 You have been credited with {amount} PC in your account!")
    except:
        pass

# ================= USER COMMANDS =================
@bot.command()
async def inv(ctx, user: discord.Member = None):
    if user is None:
        user = ctx.author
    add_user_if_not_exists(user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT messages, bal, claimed FROM users WHERE user_id = ?", (user.id,))
    result = c.fetchone()
    conn.close()

    if result:
        messages, bal, claimed = result
    else:
        messages, bal, claimed = 0, 0, 0

    embed = discord.Embed(
        title=f"📊 Inventory for {user.display_name}",
        color=discord.Color.green()
    )
    embed.add_field(name="📩 Messages", value=messages, inline=True)
    embed.add_field(name="💰 Balance", value=f"{bal} PC", inline=True)
    embed.add_field(name="📦 Claimed", value=claimed, inline=True)

    await ctx.send(embed=embed)

# ================= CLAIM PANEL =================
class ClaimPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Check Balance", style=discord.ButtonStyle.green)
    async def check_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        add_user_if_not_exists(interaction.user.id)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT bal FROM users WHERE user_id = ?", (interaction.user.id,))
        result = c.fetchone()
        conn.close()
        balance = result[0] if result else 0
        await interaction.response.send_message(f"💰 You have {balance} PC!", ephemeral=True)

    @discord.ui.button(label="Claim PC", style=discord.ButtonStyle.blurple)
    async def claim_pc(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ClaimModal()
        await interaction.response.send_modal(modal)

class ClaimModal(discord.ui.Modal, title="Claim Pokémon"):
    market_id = discord.ui.TextInput(label="Market ID", placeholder="Enter Pokémon Market ID")
    price = discord.ui.TextInput(label="Price", placeholder="Enter Pokémon Price in PC")

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        add_user_if_not_exists(user.id)

        try:
            price = int(self.price.value)
        except ValueError:
            await interaction.response.send_message("❌ Invalid price!", ephemeral=True)
            return

        log_channel = discord.utils.get(interaction.guild.text_channels, name="claims-log")
        if not log_channel:
            log_channel = await interaction.guild.create_text_channel("claims-log")

        embed = discord.Embed(
            title="New Claim",
            color=discord.Color.blue()
        )
        embed.add_field(name="User", value=user.mention, inline=False)
        embed.add_field(name="Market ID", value=self.market_id.value, inline=True)
        embed.add_field(name="Price", value=f"{price} PC", inline=True)

        await log_channel.send(embed=embed)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET claimed = claimed + 1, bal = bal + ? WHERE user_id = ?", (price, user.id))
        conn.commit()
        conn.close()

        try:
            await user.send(f"✅ You have claimed your Pokémon (Market ID: {self.market_id.value}) for {price} PC. Now vouch!")
        except:
            pass

        await interaction.response.send_message("✅ Claim submitted successfully!", ephemeral=True)

# ================= PANEL COMMAND =================
@bot.command()
async def panel(ctx):
    embed = discord.Embed(
        title="🎯 Claim Panel",
        description="Use the buttons below to check balance or claim PC.",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed, view=ClaimPanel())

# ================= SLASH COMMANDS =================
@bot.tree.command(name="ping", description="Check bot latency")
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!")

# ================= MAIN RUN =================
async def main():
    init_db()
    asyncio.create_task(run_aiohttp())
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("❌ No DISCORD_TOKEN set in environment variables")
        return
    await bot.start(TOKEN)

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    asyncio.run(main())
