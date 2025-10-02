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

# ----------------CLAIM PANEL ----------------------

class ClaimView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # permanent buttons

    @discord.ui.button(label="💰 Check Balance", style=discord.ButtonStyle.green)
    async def check_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        c.execute("SELECT balance FROM users WHERE discord_id = ?", (interaction.user.id,))
        row = c.fetchone()
        balance = row[0] if row else 0

        embed = discord.Embed(
            title=f"{interaction.user.name}'s Balance",
            description=f"💰 You currently have **{balance} PC**",
            color=discord.Color.green()
        )
        embed.set_footer(text=FOOTER_TEXT, icon_url=bot.user.avatar.url if bot.user.avatar else None)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="📦 Claim PC", style=discord.ButtonStyle.blurple)
    async def claim_pc(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Example claim logic (customize later with market ID input etc.)
        c.execute("INSERT OR IGNORE INTO users (discord_id) VALUES (?)", (interaction.user.id,))
        c.execute("UPDATE users SET claimed = claimed + 1 WHERE discord_id = ?", (interaction.user.id,))
        conn.commit()

        log_channel = discord.utils.get(interaction.guild.text_channels, name="claims-log")
        if log_channel is None:
            log_channel = await interaction.guild.create_text_channel("claims-log")

        embed = discord.Embed(
            title="📦 New Claim Submitted",
            description=f"User: {interaction.user.mention}\nMarket ID: *(to be added by user)*\nValue: *(pending)*",
            color=discord.Color.purple()
        )
        embed.set_footer(text=FOOTER_TEXT, icon_url=bot.user.avatar.url if bot.user.avatar else None)
        await log_channel.send(embed=embed)

        await interaction.response.send_message("✅ Your claim has been recorded and is pending admin review.", ephemeral=True)
@bot.command()
async def claimpanel(ctx):
    # ✅ Sirf tu (Ishan Jain ka Discord ID)
    if ctx.author.id != 1364880828949336088:
        await ctx.send("❌ Only Bot Owners Can Use This.")
        return

    embed = discord.Embed(
        title="Poketwo Claim Panel",
        description=(
            "📦 **Welcome to Poketwo Claim Panel**\n\n"
            "👋 Hello Trainer! This Is Claim System To Claim Your Collected Pokecoins (PC) .\n"
            
            "⚙️ **How it works:**\n"
            "1. **💰 Check Balance** → See How Many Pokecoins Yiu Have In Your Account .\n"
            "2. **📦 Claim PC** → Send  Your Market ID + Price To Submit For Admin Inspection .\n"
            
            "🛠 **Admin Process:**\n"
             "You Will Be Notified By The Bot In DM About Your Request.\n"
            
            
            "📜 **Additional Info:**\n"
            
            "- Integration with **Tobi.exe style**: Yiu Will Get A Mystry Box Per 100 Messages.\n"
            
            "⚡ Use the buttons below to get started!"
        ),
        color=discord.Color.purple()
    )

    # Bot avatar thumbnail
    if bot.user.avatar:
        embed.set_thumbnail(url=bot.user.avatar.url)

    # Footer
    embed.set_footer(
        text="Made By Kabir Juneja and Ishan Jain",
        icon_url=bot.user.avatar.url if bot.user.avatar else None
    )

    # Send panel with ClaimView (buttons)
    await ctx.send(embed=embed, view=ClaimView())

# -----------------------------
# Flask Thread
# -----------------------------
threading.Thread(target=run_flask).start()

# -----------------------------
# Run Bot
# -----------------------------
bot.run(os.getenv("DISCORD_TOKEN"))
