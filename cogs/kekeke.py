import asyncio

import discord
from discord.ext import commands

from kekeke.bot import Bot as KBot
from kekeke.red import redis


class Kekeke(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.load_extension('cogs.detector')
        self.bot.load_extension('cogs.monitor')
        self.kbot = KBot()

    @commands.Cog.listener()
    async def on_ready(self):
        self.detector = self.bot.get_cog('Detector')
        self.monitor = self.bot.get_cog('Monitor')
        self.stdout = self.bot.get_channel(483242913807990806)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        user: discord.User = self.bot.get_user(payload.user_id)
        if user == self.bot.user:
            return
        channel: discord.TextChannel = self.bot.get_channel(payload.channel_id)
        message: discord.Message = await channel.fetch_message(payload.message_id)
        if channel.id == 483268806072991794 and await self.bot.is_owner(user):
            if payload.emoji.name == r"🛡":
                name = ""
                try:
                    name = message.embeds[0].author.name
                    asyncio.get_event_loop().create_task(self.monitor.oversee(name, True))
                except Exception:
                    await self.stdout.send(f"無法對`{name}`進行防禦")
            if payload.emoji.name == r"🇲":
                userid = message.embeds[0].footer.text
                if len(userid) != 40:
                    await self.stdout.send(f"無法把`{userid}`加入靜音成員")
                    return
                if redis.sadd("kekeke::bot::global::silentUsers", userid):
                    await message.add_reaction(r"🇺")
                    await message.add_reaction(r"🇩")
                    await message.add_reaction(r"🇦")
                    return
                else:
                    await self.stdout.send(f"`{userid}`已經加入過了")
                    return

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        return
        user: discord.User = self.bot.get_user(payload.user_id)
        if user == self.bot.user:
            return
        channel: discord.TextChannel = self.bot.get_channel(payload.channel_id)
        message: discord.Message = await channel.fetch_message(payload.message_id)
        if channel.id == 483268806072991794 and payload.emoji.name == r"🛡" and await self.bot.is_owner(user):
            name = ""
            try:
                name = message.embeds[0].author.name
                redis.srem("discordbot::overseechannels", name)
                self.monitor.overseeing_list[name].cancel()
                self.monitor.overseeing_list.pop(name)
            except Exception:
                await self.stdout.send(f"無法停止對`{name}`的防禦")


def setup(bot: commands.Bot):
    bot.add_cog(Kekeke(bot))
