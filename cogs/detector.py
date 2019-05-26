import asyncio
import logging
import typing
from concurrent import futures
from datetime import datetime

import discord
import tzlocal
from discord.ext import commands

from kekeke import detector, message
from kekeke.red import redis


class Detector(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.detectEvent: asyncio.Task = None
        self.detecttime = 30
        self._log: logging.RootLogger = logging.getLogger(self.__class__.__name__)
        self.lastMessages: typing.Dict[str, message.Message] = dict()

    @commands.Cog.listener()
    async def on_ready(self):
        self._log.info("READY")
        self.monitor = self.bot.get_cog('Monitor')
        self.stdout = self.bot.get_channel(483242913807990806)
        self.reportout = self.bot.get_channel(483268806072991794)
        asyncio.get_event_loop().create_task(self.autoDetect())

    @commands.Cog.listener()
    async def on_resumed(self):
        self._log.info("RESUME")
        asyncio.get_event_loop().create_task(self.autoDetect())

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

    async def autoDetect(self):
        if redis.exists("kekeke::detecttime"):
            self.detecttime = int(redis.get("kekeke::detecttime"))
        if self.bot.command_prefix != ".":
            return
        await self.detect()

    async def detect(self):
        if self.detectEvent:
            self.detectEvent.cancel()
            try:
                await self.detectEvent
            except futures.CancelledError:
                pass
        self.detectEvent = asyncio.get_event_loop().create_task(self._detectRunner())

    async def _detectRunner(self):
        while True:
            result = await detector.Detect()
            if result:
                await self._sendReport(result)
            else:
                self._log.debug("kekeke首頁無資料更新")
            await asyncio.sleep(self.detecttime)

    async def _sendReport(self, report: typing.List[detector.Channel]):
        for c in report:  # type:detector.Channel
            lastmessage: message.Message = self.lastMessages.get(c.name)
            if not c.messages or (lastmessage and lastmessage.time >= c.messages[0].time):
                continue
            lastuserID = None
            embed = None
            embedlist = []
            for m in filter(lambda m: not lastmessage or lastmessage.time < m.time, reversed(c.messages)):  # type:message.Message
                if not lastuserID or lastuserID != m.user.ID:
                    if embed:
                        if redis.sismember("kekeke::bot::global::silentUsers", embed.footer.text):
                            asyncio.get_event_loop().create_task(self.autoDefend(embed.author.name))
                        else:
                            embedlist.append(embed)
                    embed = discord.Embed(timestamp=tzlocal.get_localzone().localize(datetime.now()))
                    embed.set_footer(text=m.user.ID)
                    if c.thumbnail:
                        embed.set_thumbnail(url=c.thumbnail)
                    embed.set_author(name=c.name, url=f"https://kekeke.cc/{c.name}")
                    embed.add_field(name="上線人數", value=c.population)
                    lastuserID = m.user.ID
                embed.add_field(name=f"{m.user.ID[:5]}@{m.user.nickname}", value=f"`{m.time.strftime('%d %H:%M')}` {discord.utils.escape_markdown(m.content)}", inline=False)
            if embed:
                if redis.sismember("kekeke::bot::global::silentUsers", embed.footer.text):
                    asyncio.get_event_loop().create_task(self.autoDefend(embed.author.name))
                else:
                    embedlist.append(embed)
            for embed in embedlist:
                self.lastMessages[c.name] = c.messages[0]
                if redis.sismember("discordbot::overseechannels", embed.author.name):
                    embed.color = discord.Color.dark_green()
                elif embed.author.name in self.monitor.overseeing_list:
                    embed.color = discord.Color.green()
                mess: discord.Message = await self.reportout.send(embed=embed)
                await mess.add_reaction(r"🛡")
                await mess.add_reaction(r"🇲")
            if embedlist:
                self._log.info("kekeke首頁已更新")
            else:
                self._log.debug("已發送過，略過所有舊資料")

    async def autoDefend(self, name: str):
        if name not in self.monitor.overseeing_list:
            await self.monitor.oversee(name, True)


def setup(bot: commands.Bot):
    bot.add_cog(Detector(bot))
