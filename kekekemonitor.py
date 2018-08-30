import aiohttp
import asyncio
import json
import pytz
import re
from datetime import datetime
from datetime import timezone
import discord
from discord.ext import commands

class Message(object):
    time:datetime
    ID:int
    nickname:str
    content:str
    extra:str

    def __init__(self,time:datetime=datetime.now(),ID:int=0,nickname:str="",content:str="",extra:str=""):
        self.time=time
        self.ID=ID
        self.nickname=nickname
        self.content=content
        self.extra=extra

class KekekeMonitor(object):
    _url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    _payload = r"7|0|6|https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/|53263EDF7F9313FDD5BD38B49D3A7A77|com.liquable.hiroba.gwt.client.square.IGwtSquareService|getLeftMessages|com.liquable.gwt.transport.client.Destination/2061503238|/topic/{0}|1|2|3|4|1|5|5|6|"
    channel:str
    stdout_id:int
    bot:commands.Bot
    _last_time:datetime=None
    stdout=None
    def __init__(self,channel:str,bot:commands.Bot,stdout_id:int):
        self.channel=channel
        self.stdout_id=stdout_id
        self.bot=bot
        self.stdout=self.bot.get_channel(self.stdout_id)

    async def GetChannelMessages(self,start_from:datetime=None,max_size:int=0)->list:
        ans=[]
        async with aiohttp.request("POST",self._url, data=self._payload.format(self.channel),headers=self._header) as r:
            resp = await r.text()
        if resp[:4]==r"//OK":
            data=json.loads(resp[4:])[-3]
            for message_raw in reversed(data):
                if message_raw[0]!='{':
                    break
                message=json.loads(message_raw)
                tz=pytz.timezone("Asia/Taipei")
                ts=datetime.fromtimestamp(int(message["date"])/1000)
                message_time=tz.localize(ts)
                if start_from is not None and start_from>=message_time:
                    break
                ex=re.search(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+',message["content"], re.IGNORECASE)
                m_output=Message(time=message_time,ID=message["senderPublicId"],nickname=message["senderNickName"],content=message["content"])
                if ex:
                    m_output.extra=ex.group(0)
                ans.append(m_output)
                if max_size>0 and len(ans)>=max_size:
                    break
        return ans

    async def SendReport(self,data:list):
        if self._last_time is None:
            self._last_time=await self.GetLastMessageTime()
        for message in reversed(data):
            embed=discord.Embed(description=message.content,timestamp=message.time)
            embed.set_footer(text="kekeke.cc/"+self.channel)
            embed.set_author(name=message.ID[:5]+"@"+message.nickname)
            self._last_time=message.time
            if re.search(r".(jp[e]?g|png|gif)$",message.extra,re.IGNORECASE):
                embed.set_image(url=message.extra)
                await self.stdout.send(embed=embed)
            else:
                if message.extra:
                    await self.stdout.send(content=message.extra)
                await self.stdout.send(embed=embed)
            
    
    async def GetLastMessageTime(self):
        last_messages=await self.stdout.history(limit=1).flatten()
        if last_messages[0].embeds:
            return last_messages[0].embeds[0].timestamp.replace(tzinfo=timezone.utc)
        else:
            return last_messages[0].created_at().replace(tzinfo=timezone.utc)

    async def PeriodRun(self,period:int):
        print("Starting monitor "+self.channel+" ......")
        self._last_time=await self.GetLastMessageTime()
        while True:
            print("Checking "+self.channel+" ......")
            data=await self.GetChannelMessages(start_from=self._last_time)
            if len(data)>0:
                async with self.stdout.typing():
                    await self.SendReport(data)
                print(self.channel+" Updated!")
            await asyncio.sleep(period)

