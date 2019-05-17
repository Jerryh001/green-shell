
import asyncio
import logging
from concurrent import futures

import discord
from discord.ext import commands

from kekeke.monitor import Monitor as KMonitor
from kekeke.red import redis


class Monitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.overseeing_list = dict()

    @commands.Cog.listener()
    async def on_ready(self):
        self.kekeke = self.bot.get_cog('Kekeke')
        self.stdout = self.bot.get_channel(483242913807990806)
        if self.bot.command_prefix != ".":
            return
        redis.sunionstore("kekeke::bot::GUIDpool", "kekeke::bot::GUIDpool", "kekeke::bot::GUIDpool::using")
        redis.delete("kekeke::bot::GUIDpool::using")
        for channelname in redis.smembers("discordbot::overseechannels"):
            asyncio.get_event_loop().create_task(self.oversee(channelname))
        try:
            asyncio.get_event_loop().create_task(self.train(int(redis.get("kekeke::bot::training::number"))))
        except ValueError:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.author.bot and message.channel.category and message.channel.category.id == 483268757884633088:
            if message.channel.id != 483268806072991794 and redis.sismember("discordbot::overseechannels", message.channel.name):
                try:
                    await self.kekeke.kbot.channels[message.channel.name].anonSend(message)
                except KeyError:
                    logging.warning(message.channel.name+"不在監視中，無法發送訊息")
            await message.delete()

    @commands.command(name="train")
    async def _train(self, ctx: commands.Context, *, num: int):
        redis.set("kekeke::bot::training::number", num)
        asyncio.get_event_loop().create_task(self.train(num))

    async def train(self, num: int):
        await self.kekeke.kbot.train(num)

    async def oversee(self, name: str, defender=False):
        if name in self.overseeing_list:
            logging.warning(f"{name}已在監視中")
            await self.stdout.send(f"`{name}`已在監視中")
            return

        if defender:
            logging.info(f"對{name}進行防禦")
            await self.stdout.send(f"對`{name}`進行防禦")
            self.overseeing_list[name] = asyncio.get_event_loop().create_task(KMonitor(name, None, self.kekeke.kbot).Oversee(True))
        else:
            channel: discord.TextChannel = next((c for c in self.bot.get_channel(483268757884633088).channels if c.name == name), None)
            if not channel:
                logging.warning(f"{name}頻道不存在")
            self.overseeing_list[name] = asyncio.get_event_loop().create_task(KMonitor(name, channel, self.kekeke.kbot).Oversee())
            redis.sadd("discordbot::overseechannels", name)

        try:
            await self.overseeing_list[name]
        except futures.CancelledError:
            await self.kekeke.kbot.unSubscribe(name)
        except ValueError as e:
            await self.kekeke.kbot.unSubscribe(name)
            logging.info(f"{name}可能為主播廣場")
            await self.stdout.send(f"`{name}`可能為主播廣場")
        except Exception as e:
            logging.error(f"監視{name}時發生錯誤:")
            logging.error(e, exc_info=True)
            await self.stdout.send(f"監視`{name}`時發生錯誤")
        logging.info(f"已停止監視{name}")
        await self.stdout.send(f"已停止監視`{name}`")  # workaround: if stopped by heroku, channel won't pop
        redis.srem("discordbot::overseechannels", name)
        self.overseeing_list.pop(name)

    @commands.command()
    async def sendall(self, ctx: commands.Context, *, content: str):
        for channel in self.kekeke.kbot.channels.values():
            await channel.say(content)

    @commands.command(name="oversee", aliases=["o"])
    async def _oversee(self, ctx: commands.Context, *, channelname: str):
        asyncio.get_event_loop().create_task(self.oversee(channelname))

    @commands.command(aliases=["d"])
    async def defend(self, ctx: commands.Context, *, channelname: str):
        asyncio.get_event_loop().create_task(self.oversee(channelname, True))

    @_oversee.before_invoke
    async def _BeforeOversee(self, ctx: commands.Context):
        channel: discord.TextChannel = next((c for c in self.bot.get_channel(483268757884633088).channels if c.name == ctx.kwargs["channelname"]), None)
        if channel:
            url = r"https://kekeke.cc/"+channel.name
            if channel.topic != url:
                await channel.edit(topic=url)

    @commands.command()
    async def stop(self, ctx: commands.Context, *, channelname: str):
        try:
            self.overseeing_list[channelname].cancel()
        except KeyError:
            logging.warning(f"{channelname}不在監視中")
            await ctx.send(f"`{channelname}`不在監視中")
        except Exception as e:
            logging.error(f"停止監視{channelname}失敗")
            logging.error(e, exc_info=True)
            await ctx.send(f"停止監視`{channelname}`失敗")

    @commands.command()
    async def on_oversee(self, ctx: commands.Context):
        listtext = '\n'.join(self.overseeing_list)
        if listtext:
            await ctx.send(f"監視中頻道：\n```{listtext}```")
        else:
            await ctx.send("沒有頻道監視中")


def setup(bot: commands.Bot):
    bot.add_cog(Monitor(bot))
