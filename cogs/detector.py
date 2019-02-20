import asyncio
import logging
import typing
from datetime import datetime
from os import getenv

import discord
import tzlocal
from discord.ext import commands

from kekeke import detector, message
from kekeke.red import redis


class Detector():
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.detectEvent: asyncio.Task = None
        self.detecttime = 30
        self.stdout: discord.TextChannel = None
        self.reportout: discord.TextChannel = None
        self._log: logging.RootLogger = logging.getLogger(self.__class__.__name__)
        self.lastMessages: typing.Dict[str, message.Message] = dict()

    async def on_ready(self):
        self.stdout = self.bot.get_channel(483242913807990806)
        self.reportout = self.bot.get_channel(483268806072991794)
        if redis.exists("kekeke::detecttime"):
            self.detecttime = int(redis.get("kekeke::detecttime"))
        if getenv("DISCORD_PREFIX") != ".":
            return
        await self.detect()

    @commands.command(name="dtime")
    async def _dtime(self, ctx: commands.Context, time: int):
        if redis.set("kekeke::detecttime", time):
            self.detecttime = time
            await self.stdout.send(f"首頁偵測時間更新為`{time}`秒")
            self._log.info(f"首頁偵測時間更新為{time}秒")

    @commands.command(name="detect")
    async def _detect(self, ctx: commands.Context):
        await self.stdout.send("開始進行kekeke首頁監視")
        self._log.info("開始進行kekeke首頁監視")
        await self.detect()

    async def detect(self):
        if self.detectEvent:
            self.detectEvent.cancel()
        self.detectEvent = self.bot.loop.create_task(self._detectRunner())

    async def _detectRunner(self):
        while True:
            result = await detector.Detect()
            if result:
                await self._sendReport(result)
                self._log.info("kekeke首頁已更新")
            else:
                self._log.debug("kekeke首頁無資料更新")
            await asyncio.sleep(self.detecttime)

    async def _sendReport(self, report: typing.List[detector.Channel]):
        for c in report:  # type:detector.Channel
            lastmessage: message.Message = self.lastMessages.get(c.name)
            if not c.messages or (lastmessage and lastmessage.time > c.messages[0].time):
                continue
            embed = discord.Embed(timestamp=tzlocal.get_localzone().localize(datetime.now()))
            embed.set_footer(text=f"kekeke.cc/{c.name}")
            if c.thumbnail:
                embed.set_thumbnail(url=c.thumbnail)
            embed.set_author(name=c.name, url=f"https://kekeke.cc/{c.name}")
            embed.add_field(name="上線人數", value=c.population)
            for m in reversed(c.messages):  # type:message.Message
                if not lastmessage or lastmessage.time < m.time:
                    embed.add_field(name=f"{m.user.ID[:5]}@{m.user.nickname}", value=f"`{m.time.strftime('%d %H:%M')}` {m.content}", inline=False)
            if len(embed.fields):
                self.lastMessages[c.name] = c.messages[0]
                await self.reportout.send(embed=embed)


def setup(bot: commands.Bot):
    bot.add_cog(Detector(bot))
