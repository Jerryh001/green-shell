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
from .message import Message, MessageType
from .user import User


class Monitor(object):
    _url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    _log=logging.getLogger(__name__)
    
    def __init__(self,channel:str,stdout:discord.TextChannel,bot:KBot):
        self.channel=channel
        self.stdout=stdout
        self._last_time:datetime=None
        self.bot:KBot=bot
        


    async def SendReport(self,data:list):
        if self._last_time is None:
            self._last_time=await self.GetLastMessageTime()
        for message in reversed(data):
            embed=discord.Embed(description=message.content,timestamp=message.time)
            embed.set_footer(text=message.user.ID)
            embed.set_author(name=message.user.ID[:5]+"@"+message.user.nickname)
            self._last_time=message.time
            if message.url:
                if re.search(r"^https?://\S+\.(jpe?g|png|gif)$",message.url,re.IGNORECASE):
                    if message.mtype==MessageType.deleteimage:
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


    async def GetToken(self):
        _payload = r"7|0|7|https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/|53263EDF7F9313FDD5BD38B49D3A7A77|com.liquable.hiroba.gwt.client.square.IGwtSquareService|startSquare|com.liquable.hiroba.gwt.client.square.StartSquareRequest/2186526774|com.liquable.gwt.transport.client.Destination/2061503238|/topic/{0}|1|2|3|4|1|5|5|0|0|6|7|"
        async with aiohttp.request("POST",self._url, data=_payload.format(self.channel),headers=self._header) as r:
            resp = await r.text()
        if resp[:4]==r"//OK":
            token=json.loads(resp[4:])[-3][2]
            return token
    async def Oversee(self,ghost:bool=False):
        self._log.info("開始監視 "+self.channel)
        await self.bot.Subscribe(self.channel)
        self._last_time=await self.GetLastMessageTime()
        self._log.info("取得 "+self.channel+" 的歷史訊息")
        data=await self.bot.GetChannelHistoryMessages(channel=self.channel,start_from=self._last_time)
        if len(data)>0:
            async with self.stdout.typing():
                await self.SendReport(data)
            self._log.info("更新了 "+self.channel+" 的 "+str(len(data))+" 條訊息")
        self._log.info("開始常駐監聽 "+self.channel)
        while self.bot.IsSubscribe(self.channel):
            m=await self.bot.ReceiveMessage(self.channel)
            self._log.debug(data)
            async with self.stdout.typing():
                await self.SendReport([m])
