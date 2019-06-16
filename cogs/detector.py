import asyncio
import logging
import os
import typing
from datetime import datetime

import discord
import googleapiclient.discovery
import tzlocal
from discord.ext import commands, tasks

from kekeke import detector, message
from kekeke.red import redis


class Detector(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.detectEvent: asyncio.Task = None
        self._log: logging.RootLogger = logging.getLogger(self.__class__.__name__)
        self.lastMessages: typing.Dict[str, message.Message] = dict()
        if self.bot.command_prefix != ".":
            return
        self.updateYoutube()
        self.detect.start()

    def cog_unload(self):
        self.detect.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        self.monitor = self.bot.get_cog('Monitor')
        self.stdout = self.bot.get_channel(483242913807990806)
        self.reportout = self.bot.get_channel(483268806072991794)

    @commands.command()
    async def dtime(self, ctx: commands.Context, time: int):
        if redis.set("kekeke::detecttime", time):
            self.detect.change_interval(seconds=time)
            await self.stdout.send(f"首頁偵測時間更新為`{time}`秒")
            self._log.info(f"首頁偵測時間更新為{time}秒")

    @commands.command(name="detect")
    async def _detect(self, ctx: commands.Context):
        self.detect.start()
        self._log.info("開始進行kekeke首頁監視")
        await self.stdout.send("開始進行kekeke首頁監視")

    @commands.command()
    async def dstop(self, ctx: commands.Context):
        self.detect.stop()
        self._log.info("停止kekeke首頁監視")
        await self.stdout.send("停止kekeke首頁監視")

    def updateYoutube(self):
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=os.getenv("GOOGLE_API_KEY"), cache_discovery=False)

        pagetoken = None
        while True:
            response = youtube.channels().list(part="contentDetails", id=",".join(redis.smembers("kekeke::bot::detector::youtube::channel")), maxResults=50, pageToken=pagetoken).execute()
            for channel in response["items"]:
                redis.sadd("kekeke::bot::detector::youtube::playlist::temp", channel["contentDetails"]["relatedPlaylists"]["uploads"])
            if "nextPageToken" in response:
                pagetoken = response["nextPageToken"]
            else:
                break
        try:
            redis.rename("kekeke::bot::detector::youtube::playlist::temp", "kekeke::bot::detector::youtube::playlist")
        except Exception:
            return

        for playlist in redis.smembers("kekeke::bot::detector::youtube::playlist"):
            pagetoken = None
            while True:
                response = youtube.playlistItems().list(part="contentDetails", playlistId=playlist, maxResults=50, pageToken=pagetoken).execute()
                for video in response["items"]:
                    redis.sadd("kekeke::bot::detector::youtube::video::temp", video["contentDetails"]["videoId"])
                if "nextPageToken" in response:
                    pagetoken = response["nextPageToken"]
                else:
                    break

        try:
            redis.rename("kekeke::bot::detector::youtube::video::temp", "kekeke::bot::detector::youtube::video")
        except Exception:
            return

    @tasks.loop()
    async def detect(self):
        result = await detector.Detect()
        if result:
            await self._sendReport(result)
        else:
            self._log.debug("kekeke首頁無資料更新")

    @detect.before_loop
    async def before_detect(self):
        await self.bot.wait_until_ready()
        detecttime = 30
        if redis.exists("kekeke::detecttime"):
            detecttime = int(redis.get("kekeke::detecttime"))
        self.detect.change_interval(seconds=detecttime)

    @detect.after_loop
    async def after_detect(self):
        if self.detect.is_being_cancelled():
            self._log.info("發生錯誤，強制終止監視kekeke首頁")
            await self.stdout.send("發生錯誤，強制終止監視kekeke首頁")

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
                embedlist.append(embed)

            for embed in embedlist:
                self.lastMessages[c.name] = c.messages[0]
                if redis.sismember("kekeke::bot::global::silentUsers", embed.footer.text):
                    self._log.info(f"偵測到洗版仔{embed.footer.text}，但是沒空上線")
                    # asyncio.get_event_loop().create_task(self.autoDefend(embed.author.name))
                else:
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
