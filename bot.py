import discord
from discord.ext import commands
import sqlite3, os, asyncio
from flask import Flask
import threading

# ---------- CONFIG ----------
TOKEN = os.getenv("DISCORD_TOKEN")  # apna token env me daalo
GUILD_ID = int(os.getenv("GUILD_ID", "YOUR_GUILD_ID"))  # apna guild id
DB_PATH = "database.db"

# ---------- INTENTS ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=".", intents=intents)

# ---------- FLASK SERVER ----------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

threading.Thread(target=run_flask).start()

# ---------- DATABASE ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Users table
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        discord_id INTEGER PRIMARY KEY,
        balance INTEGER DEFAULT 0,
        messages INTEGER DEFAULT 0,
        claimed INTEGER DEFAULT 0
    )
    """)
    # Claims table
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
    conn.close()

def get_user(discord_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE discord_id=?", (discord_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (discord_id) VALUES (?)", (discord_id,))
        conn.commit()
        conn.close()
        return (discord_id, 0, 0, 0)
    conn.close()
    return row

def update_balance(discord_id, amount):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    get_user(discord_id)
    c.execute("UPDATE users SET balance = balance + ? WHERE discord_id=?", (amount, discord_id))
    conn.commit()
    conn.close()

def update_claimed(discord_id, count=1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    get_user(discord_id)
    c.execute("UPDATE users SET claimed = claimed + ? WHERE discord_id=?", (count, discord_id))
    conn.commit()
    conn.close()

def add_claim(discord_id, market_id, value):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO claims (discord_id, market_id, value, status) VALUES (?, ?, ?, 'pending')",
              (discord_id, market_id, value))
    conn.commit()
    conn.close()

def set_claim_status(claim_id, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE claims SET status=? WHERE id=?", (status, claim_id))
    conn.commit()
    conn.close()

# ---------- CLAIM PANEL ----------
class ClaimPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Check Balance", style=discord.ButtonStyle.primary, custom_id="check_balance")
    async def check_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(interaction.user.id)
        balance, messages, claimed = user[1], user[2], user[3]
        embed = discord.Embed(
            title=f"{interaction.user.name} ka Inventory",
            color=discord.Color.green(),
            description="📌 Aapki account ki details niche di gayi hai."
        )
        embed.add_field(name="Balance", value=f"{balance} PC", inline=False)
        embed.add_field(name="Messages", value=f"{messages}", inline=True)
        embed.add_field(name="Claimed", value=f"{claimed}", inline=True)
        embed.set_footer(text="Made By Kabir Juneja and Ishan Jain", icon_url=interaction.client.user.avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Claim PC", style=discord.ButtonStyle.success, custom_id="claim_pc")
    async def claim_pc(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ClaimModal()
        await interaction.response.send_modal(modal)

# ---------- CLAIM MODAL ----------
class ClaimModal(discord.ui.Modal, title="Claim Pokecoins"):
    market_id = discord.ui.TextInput(label="Market ID", style=discord.TextStyle.short, required=True)
    value = discord.ui.TextInput(label="Value (PC)", style=discord.TextStyle.short, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(self.value.value)
        except:
            await interaction.response.send_message("❌ Invalid value!", ephemeral=True)
            return

        user = get_user(interaction.user.id)
        balance = user[1]
        if value > balance:
            await interaction.response.send_message("⚠️ Invalid Price! Tumhare paas itna balance nahi hai.", ephemeral=True)
            return

        # Save claim in DB
        add_claim(interaction.user.id, self.market_id.value, value)

        # Send embed to claim-log channel
        guild = interaction.client.get_guild(GUILD_ID)
        if guild:
            channel = discord.utils.get(guild.text_channels, name="claims-log")
            if not channel:
                channel = await guild.create_text_channel("claims-log")

            embed = discord.Embed(title="New Claim Request", color=discord.Color.orange())
            embed.add_field(name="User", value=f"{interaction.user.mention}", inline=False)
            embed.add_field(name="Market ID", value=self.market_id.value, inline=True)
            embed.add_field(name="Value", value=f"{value} PC", inline=True)
            embed.set_footer(text="Made By Kabir Juneja and Ishan Jain", icon_url=interaction.client.user.avatar.url)

            await channel.send(embed=embed, view=ClaimApprovalView(interaction.user.id, self.market_id.value, value))

        await interaction.response.send_message("✅ Tumhari claim request pending hai. Admin review karenge.", ephemeral=True)

# ---------- ADMIN APPROVAL ----------
class ClaimApprovalView(discord.ui.View):
    def __init__(self, user_id, market_id, value):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.market_id = market_id
        self.value = value

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="accept_claim")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        update_balance(self.user_id, -self.value)
        update_claimed(self.user_id, 1)
        await interaction.response.send_message("✅ Claim Accepted!", ephemeral=True)
        user = await bot.fetch_user(self.user_id)
        await user.send(f"🎉 Tumhara claim (Market ID: {self.market_id}, Value: {self.value} PC) ACCEPT ho gaya hai!")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="reject_claim")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Claim Rejected!", ephemeral=True)
        user = await bot.fetch_user(self.user_id)
        await user.send(f"⚠️ Tumhara claim (Market ID: {self.market_id}, Value: {self.value} PC) REJECT ho gaya hai! Invalid Market ID or Price.")

# ---------- COMMANDS ----------
@bot.command()
@commands.has_permissions(administrator=True)
async def addbal(ctx, value: int, member: discord.Member):
    update_balance(member.id, value)
    embed = discord.Embed(title="Balance Credited", color=discord.Color.blue())
    embed.add_field(name="User", value=member.mention)
    embed.add_field(name="Amount", value=f"{value} PC")
    embed.set_footer(text="Made By Kabir Juneja and Ishan Jain", icon_url=ctx.bot.user.avatar.url)
    await ctx.send(embed=embed)
    try:
        await member.send(f"💰 Tumhare account me {value} PC credit kiye gaye hai!")
    except:
        pass

@bot.command()
async def inv(ctx):
    user = get_user(ctx.author.id)
    balance, messages, claimed = user[1], user[2], user[3]
    embed = discord.Embed(title=f"{ctx.author.name} ka Inventory", color=discord.Color.green())
    embed.add_field(name="Balance", value=f"{balance} PC")
    embed.add_field(name="Messages", value=str(messages))
    embed.add_field(name="Claimed", value=str(claimed))
    embed.set_footer(text="Made By Kabir Juneja and Ishan Jain", icon_url=ctx.bot.user.avatar.url)
    await ctx.send(embed=embed)

@bot.slash_command(name="ping", description="Check bot latency")
async def ping(ctx: discord.ApplicationContext):
    await ctx.respond(f"🏓 Pong! Latency: {round(bot.latency*1000)}ms")

# ---------- EVENTS ----------
@bot.event
async def on_ready():
    init_db()
    bot.add_view(ClaimPanel())
    print(f"✅ Bot online as {bot.user}")

# ---------- RUN ----------
bot.run(TOKEN)
