import asyncio
import html
import json
import logging
import re
import time
from datetime import datetime, timezone

import aiohttp
import discord
import tzlocal
import websockets

from .bot import Bot as KBot
from .channel import Channel
from .GWTpayload import GWTPayload
from .message import Message
from .user import User


class Monitor(object):
    _url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    _log=logging.getLogger(__name__)
    
    def __init__(self,name:str,stdout:discord.TextChannel,bot:KBot):
        self.name=name
        self.stdout=stdout
        self._last_time:datetime=None
        self.bot:KBot=bot
        


    async def SendReport(self,data:list):
        if self._last_time is None:
            self._last_time=await self.GetLastMessageTime()
        for message in data:
            embed=discord.Embed(description=message.content,timestamp=message.time)
            embed.set_footer(text=message.user.ID)
            embed.set_author(name=message.user.ID[:5]+"@"+message.user.nickname)
            self._last_time=message.time
            if message.url:
                if re.search(r"^https?://\S+\.(jp[e]?g|png|gif)$",message.url,re.IGNORECASE):
                    if message.mtype==Message.MessageType.deleteimage:
                        embed.set_thumbnail(url=message.url)
                    else:
                        embed.set_image(url=message.url)
                else:
                    await self.stdout.send(content=message.url)
                
            await self.stdout.send(embed=embed)
            
    
    async def GetLastMessageTime(self):
        try:
            last_messages=await self.stdout.history(limit=1).flatten()
            if last_messages:        
                if last_messages[0].embeds:
                    return last_messages[0].embeds[0].timestamp.replace(tzinfo=timezone.utc)
                else:
                    return last_messages[0].created_at().replace(tzinfo=timezone.utc)
        except:
            return tzlocal.get_localzone().localize(datetime.min)

    async def Oversee(self):
        self._log.info("開始監視 "+self.name)
        await self.bot.subscribe(self.name)
        self.channel:Channel=self.bot.channels[self.name]
        last_time=await self.GetLastMessageTime()
        self._log.info("取得 "+self.name+" 的歷史訊息")
        data=[m for m in self.channel.messages if m.time>last_time]
        if len(data)>0:
            async with self.stdout.typing():
                await self.SendReport(data)
            self._log.info("更新了 "+self.name+" 的 "+str(len(data))+" 條訊息")
        self._log.info("開始常駐監聽 "+self.name)
        while self.bot.isSubscribe(self.name):
            m=await self.channel.waitMessage()
            self._log.debug(m)
            async with self.stdout.typing():
                await self.SendReport([m])
    async def Stop(self):
        await self.bot.unSubscribe(self.name)
