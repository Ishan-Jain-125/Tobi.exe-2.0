# chatmode.py
# Chat mode Cog for discord.py (v2.x)
# - Continuous conversation when bot is mentioned or when user replies to bot
# - Uses OpenAI ChatCompletion + Moderation
# - Conversation history persisted to chat_conversations.json
# - Flagged attempts persisted to chat_flagged.json for owner review
# - Requires: pip install openai discord.py requests
#
# Environment variables:
#   OPENAI_API_KEY  -> your OpenAI secret key (sk-...)
#   OWNER_ID        -> your Discord user id (for owner-only review commands)
#
# Load this file as an extension (cog) into your main bot.

import os
import json
import time
import asyncio
from datetime import datetime
from typing import Dict, List, Any

import discord
from discord.ext import commands
import openai
import requests

# -----------------------------
# CONFIG
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None

# Filenames for persistence
CONV_FILE = "chat_conversations.json"
FLAG_FILE = "chat_flagged.json"

# Conversation trimming
MAX_MESSAGES_PER_CONV = 20   # keep last 20 messages (user+assistant pairs)
SYSTEM_PROMPT = "You are a helpful, friendly assistant inside a Discord bot. Keep replies concise and appropriate."

# Moderation fallback keywords (simple)
NSFW_KEYWORDS = {
    "sex","porn","xxx","naked","fuck","blowjob","cum","intercourse","hardcore","oral sex",
    "masturbate","penetrate","erotic","fetish","bdsm","rape","incest","child","minor"
}

# OpenAI model
MODEL_NAME = "gpt-3.5-turbo"

# Rate limiting (per-user cooldown seconds)
USER_COOLDOWN = 2.0

# -----------------------------
# Setup OpenAI
# -----------------------------
if not OPENAI_API_KEY:
    print("Warning: OPENAI_API_KEY is not set. Chat mode will not work without it.")
else:
    openai.api_key = OPENAI_API_KEY

# -----------------------------
# Utilities: load/save JSON
# -----------------------------
def _load_json(fname: str, default: Any):
    try:
        with open(fname, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        print(f"Error loading {fname}:", e)
        return default

def _save_json(fname: str, data: Any):
    try:
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving {fname}:", e)

# persistent structures
CONVERSATIONS: Dict[str, List[Dict[str, str]]] = _load_json(CONV_FILE, {})
FLAGGED: Dict[str, Dict[str, Any]] = _load_json(FLAG_FILE, {})

# simple per-user cooldown tracking
_last_message_time: Dict[int, float] = {}

# -----------------------------
# Moderation helpers
# -----------------------------
def contains_bad_keywords(text: str) -> bool:
    txt = (text or "").lower()
    for kw in NSFW_KEYWORDS:
        if kw in txt:
            return True
    return False

def openai_moderation_check(text: str) -> (bool, dict):
    """
    Returns (allowed: bool, details: dict).
    If no OPENAI_API_KEY or API error -> fall back to keyword scan.
    """
    if not OPENAI_API_KEY:
        return (not contains_bad_keywords(text), {"fallback": True})
    try:
        # Using OpenAI moderation endpoint via openai package
        resp = openai.Moderation.create(input=text)
        results = resp.get("results", [])
        if not results:
            # fallback to keyword scan
            return (not contains_bad_keywords(text), {"api": "no_results"})
        flagged = results[0].get("flagged", False)
        return (not flagged, {"api_result": results[0]})
    except Exception as e:
        # fallback
        return (not contains_bad_keywords(text), {"error": str(e)})

def log_flagged(author_id: int, guild_id: int, channel_id: int, content: str) -> str:
    fid = str(int(time.time() * 1000))
    entry = {
        "id": fid,
        "author_id": str(author_id),
        "guild_id": str(guild_id) if guild_id else None,
        "channel_id": str(channel_id) if channel_id else None,
        "content": content,
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }
    FLAGGED[fid] = entry
    _save_json(FLAG_FILE, FLAGGED)
    return fid

# -----------------------------
# Conversation helpers
# -----------------------------
def conv_key_for(message: discord.Message) -> str:
    """Use DM vs guild+user as key: guild_{guildid}_user_{userid} or dm_user_{userid}"""
    if message.guild:
        return f"guild_{message.guild.id}_user_{message.author.id}"
    return f"dm_user_{message.author.id}"

def trim_conversation(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # Keep last MAX_MESSAGES_PER_CONV entries
    if len(messages) <= MAX_MESSAGES_PER_CONV:
        return messages
    return messages[-MAX_MESSAGES_PER_CONV:]

def save_conversations():
    _save_json(CONV_FILE, CONVERSATIONS)

# -----------------------------
# OpenAI chat call (sync via openai lib)
# -----------------------------
async def get_openai_reply(messages: List[Dict[str, str]], max_tokens: int = 512) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    loop = asyncio.get_event_loop()
    def make_call():
        try:
            resp = openai.ChatCompletion.create(model=MODEL_NAME, messages=messages, max_tokens=max_tokens, temperature=0.7)
            # typical structure: resp.choices[0].message.content
            return resp
        except Exception as e:
            return {"error": str(e)}
    resp = await loop.run_in_executor(None, make_call)
    if isinstance(resp, dict) and resp.get("error"):
        raise RuntimeError(resp["error"])
    try:
        return resp.choices[0].message.content.strip()
    except Exception as e:
        raise RuntimeError(f"Invalid OpenAI response: {e}")

# -----------------------------
# Cog
# -----------------------------
class ChatModeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Owner-only administration for flagged logs
    @commands.group(name="flagged", invoke_without_command=True)
    @commands.is_owner()
    async def flagged_group(self, ctx):
        await ctx.send("Usage: `!flagged list` or `!flagged view <id>` or `!flagged remove <id>`")

    @flagged_group.command(name="list")
    @commands.is_owner()
    async def flagged_list(self, ctx):
        if not FLAGGED:
            return await ctx.send("No flagged messages logged.")
        items = sorted(FLAGGED.values(), key=lambda x: x["time"], reverse=True)[:20]
        lines = []
        for it in items:
            excerpt = (it["content"][:120] + "...") if len(it["content"]) > 120 else it["content"]
            gid = it.get("guild_id") or "DM"
            lines.append(f"`{it['id']}` • <@{it['author_id']}> • {gid} • `{excerpt}` • {it['time']}")
        await ctx.send(embed=discord.Embed(title="Flagged Messages (recent)", description="\n".join(lines), color=discord.Color.orange()))

    @flagged_group.command(name="view")
    @commands.is_owner()
    async def flagged_view(self, ctx, fid: str):
        entry = FLAGGED.get(fid)
        if not entry:
            return await ctx.send("ID not found.")
        # DM owner the full content (safer than posting publicly)
        emb = discord.Embed(title=f"Flagged — {fid}", description="Owner-only content (sensitive).", color=discord.Color.red())
        emb.add_field(name="Author", value=f"<@{entry['author_id']}>", inline=True)
        emb.add_field(name="Guild / Channel", value=f"{entry.get('guild_id') or 'DM'} / {entry.get('channel_id') or 'N/A'}", inline=True)
        emb.add_field(name="Timestamp (UTC)", value=entry.get("time"), inline=False)
        emb.add_field(name="Content", value=(entry.get("content")[:1900] if entry.get("content") else "Empty"), inline=False)
        await ctx.author.send(embed=emb)
        await ctx.send("✅ Sent flagged content to your DMs (owner only).")

    @flagged_group.command(name="remove")
    @commands.is_owner()
    async def flagged_remove(self, ctx, fid: str):
        if fid in FLAGGED:
            FLAGGED.pop(fid, None)
            _save_json(FLAG_FILE, FLAGGED)
            await ctx.send(f"✅ Removed flagged entry `{fid}`")
        else:
            await ctx.send("ID not found.")

    # Conversation reset for a user (owner/admin or self)
    @commands.command(name="convreset")
    async def convreset(self, ctx, member: discord.Member = None):
        # if member given but caller not owner/admin -> reject
        if member and not (ctx.author.guild_permissions.administrator or ctx.author.id == OWNER_ID):
            return await ctx.send("❌ Only server admins or owner can reset others' conversations.")
        target = member or ctx.author
        if ctx.guild:
            key = f"guild_{ctx.guild.id}_user_{target.id}"
        else:
            key = f"dm_user_{target.id}"
        if key in CONVERSATIONS:
            CONVERSATIONS.pop(key, None)
            save_conversations()
            await ctx.send(f"✅ Conversation reset for {target.mention}")
        else:
            await ctx.send("No conversation found for that user.")

    # Helper command to show conversation length (for debugging)
    @commands.command(name="convinfo")
    async def convinfo(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        key = f"guild_{ctx.guild.id}_user_{target.id}" if ctx.guild else f"dm_user_{target.id}"
        conv = CONVERSATIONS.get(key, [])
        await ctx.send(f"Conversation entries: {len(conv)} (key: `{key}`)")

    # Core: respond when bot mentioned OR when user replies to a bot message
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignore bots and DMs to avoid loops (we support DMs though)
        if message.author.bot:
            return

        # Determine trigger: mention OR reply to bot
        is_mention = self.bot.user in message.mentions
        is_reply_to_bot = False
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            ref = message.reference.resolved
            if ref.author and ref.author.id == self.bot.user.id:
                is_reply_to_bot = True

        if not (is_mention or is_reply_to_bot):
            return  # not a chat-mode trigger

        # simple per-user cooldown
        last = _last_message_time.get(message.author.id, 0)
        now = time.time()
        if now - last < USER_COOLDOWN:
            # ignore rapid repeats
            return
        _last_message_time[message.author.id] = now

        # check if in a guild and NSFW restrictions: (we allow anywhere but enforce moderation)
        user_input = (message.content or "").strip()
        if not user_input:
            return

        # Moderation check
        allowed, details = openai_moderation_check(user_input)
        if not allowed:
            fid = log_flagged(message.author.id, message.guild.id if message.guild else None, message.channel.id if message.channel else None, user_input)
            try:
                await message.reply("⚠️ I cannot help with that request. If you believe this is a mistake, the server owner can review it.")
            except Exception:
                pass
            # optionally notify owner via DM (best-effort)
            try:
                if OWNER_ID:
                    owner_user = await self.bot.fetch_user(OWNER_ID)
                    await owner_user.send(f"Flagged message logged (id `{fid}`) from <@{message.author.id}> in {message.guild.name if message.guild else 'DM'}:{message.channel.id if message.channel else 'N/A'}")
            except Exception:
                pass
            return

        # Build conversation history
        key = conv_key_for(message)
        conv = CONVERSATIONS.setdefault(key, [])
        # If new conversation, insert system prompt first
        if not conv:
            conv.append({"role": "system", "content": SYSTEM_PROMPT})

        # Append user message
        conv.append({"role": "user", "content": user_input})
        # Trim conversation
        conv = trim_conversation(conv)
        CONVERSATIONS[key] = conv
        save_conversations()

        # Inform typing
        try:
            await message.channel.trigger_typing()
        except Exception:
            pass

        # Call OpenAI (in executor)
        try:
            reply_text = await get_openai_reply(conv)
        except Exception as e:
            # Log and inform user
            print("OpenAI error:", e)
            await message.reply("⚠️ Error contacting AI. Try again later.")
            return

        # Append assistant reply to history and save
        CONVERSATIONS[key].append({"role": "assistant", "content": reply_text})
        CONVERSATIONS[key] = trim_conversation(CONVERSATIONS[key])
        save_conversations()

        # Reply publicly (as reply) — ensure not to mention the user again
        try:
            await message.reply(reply_text)
        except Exception:
            try:
                await message.channel.send(reply_text)
            except Exception:
                pass

# -----------------------------
# Extension setup
# -----------------------------
async def setup(bot: commands.Bot):
    await bot.add_cog(ChatModeCog(bot))
