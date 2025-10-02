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
# ================================
# Claim Modal (User submits claim)
# ================================
class ClaimModal(discord.ui.Modal, title="Claim Your Pokecoins"):
    market_id = discord.ui.TextInput(label="Market ID", placeholder="Enter the Market ID", required=True)
    price = discord.ui.TextInput(label="Price (in PC)", placeholder="Enter the price", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        # ✅ User ne claim submit kiya
        log_channel = discord.utils.get(interaction.guild.text_channels, name="claims-log")
        if not log_channel:
            log_channel = await interaction.guild.create_text_channel("claims-log")

        embed = discord.Embed(
            title="📦 New Claim Submitted",
            description=(
                f"👤 User: {interaction.user.mention}\n"
                f"🆔 Market ID: `{self.market_id.value}`\n"
                f"💰 Price: **{self.price.value} PC**"
            ),
            color=discord.Color.orange()
        )
        if interaction.user.avatar:
            embed.set_thumbnail(url=interaction.user.avatar.url)

        embed.set_footer(
            text="Made By Kabir Juneja and Ishan Jain",
            icon_url=interaction.client.user.avatar.url if interaction.client.user.avatar else None
        )

        # Send claim to logs with Accept/Reject buttons
        await log_channel.send(embed=embed, view=ClaimApprovalView(interaction.user, self.market_id.value, self.price.value))

        await interaction.response.send_message("✅ Claim submitted! Pending admin review.", ephemeral=True)


# ================================
# Claim Approval Buttons (Admin)
# ================================
class ClaimApprovalView(discord.ui.View):
    def __init__(self, user, market_id, price):
        super().__init__(timeout=None)
        self.user = user
        self.market_id = market_id
        self.price = price

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.user.send(f"🎉 Your claim has been **accepted**!\n🆔 Market ID: `{self.market_id}`\n💰 Price: {self.price} PC")
            await interaction.response.send_message("✅ Claim accepted.", ephemeral=True)
        except:
            await interaction.response.send_message("⚠️ Could not DM the user.", ephemeral=True)

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.user.send(f"❌ Your claim has been **rejected**.\n🆔 Market ID: `{self.market_id}`\n💰 Price: {self.price} PC")
            await interaction.response.send_message("❌ Claim rejected.", ephemeral=True)
        except:
            await interaction.response.send_message("⚠️ Could not DM the user.", ephemeral=True)


# ================================
# Claim Panel Buttons (Main View)
# ================================
class ClaimView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 Check Balance", style=discord.ButtonStyle.primary)
    async def check_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Yaha baad me DB balance system connect karna
        await interaction.response.send_message("💳 Your balance is: **0 PC**", ephemeral=True)

    @discord.ui.button(label="📦 Claim PC", style=discord.ButtonStyle.success)
    async def claim_pc(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ClaimModal())
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
