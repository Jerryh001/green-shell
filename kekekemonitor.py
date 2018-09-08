import aiohttp
import asyncio
import json
import re
import html
from datetime import datetime
from datetime import timezone
import tzlocal
import logging
import discord
from discord.ext import commands

class Message(object):
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
    _last_time:datetime=None
    def __init__(self,channel:str,stdout):
        self.channel=channel
        self.stdout=stdout
        self._log=logging.getLogger(self.__class__.__name__)

    async def GetChannelMessages(self,start_from:datetime=None,max_size:int=0)->list:
        ans=list()
        try:
            async with aiohttp.request("POST",self._url, data=self._payload.format(self.channel),headers=self._header) as r:
                resp = await r.text()
        except:
            self._log.error("Fetch messages from channel "+self.channel+" failed")
        if resp[:4]==r"//OK":
            data=json.loads(resp[4:])[-3]
            for message_raw in reversed(data):
                if message_raw[0]!='{':
                    break
                message=json.loads(message_raw)
                for key in message:
                    message[key]=html.unescape(message[key])
                ts=datetime.fromtimestamp(int(message["date"])/1000)
                message_time=tzlocal.get_localzone().localize(ts)
                if start_from is not None and start_from>=message_time:
                    break
                ex=re.search(r'https?://\S+',message["content"], re.IGNORECASE)
                m_output=Message(time=message_time,ID=message["senderPublicId"],nickname=message["senderNickName"],content=message["content"])
                self._log.debug(m_output)
                if ex:
                    m_output.extra=ex.group(0)
                ans.append(m_output)
                if max_size>0 and len(ans)>=max_size:
                    break

            if ans:
                self._log.debug("Get messages from channel "+self.channel+" successed")
            else:
                self._log.debug("Get messages from channel "+self.channel+" successed, but it's empty")
        else:
            self._log.warning("Parse messages from channel "+self.channel+" failed, response:"+resp[:4])
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
        if last_messages:        
            if last_messages[0].embeds:
                return last_messages[0].embeds[0].timestamp.replace(tzinfo=timezone.utc)
            else:
                return last_messages[0].created_at().replace(tzinfo=timezone.utc)
        else:
            return tzlocal.get_localzone().localize(datetime.min)

    async def PeriodRun(self,period:int):
        self._log.info("Starting monitor "+self.channel+" ......")
        self._last_time=await self.GetLastMessageTime()
        while True:
            self._log.info("Checking "+self.channel+" ......")
            data=await self.GetChannelMessages(start_from=self._last_time)
            if len(data)>0:
                async with self.stdout.typing():
                    await self.SendReport(data)
                self._log.info(self.channel+" updated!")
            else:
                self._log.info(self.channel+" has nothing to update")
            await asyncio.sleep(period)
        self._log.info("stopped "+self.channel+" moniter")

if __name__=="__main__":
    asyncio.get_event_loop().run_until_complete(KekekeMonitor("彩虹小馬實況",None).GetChannelMessages())