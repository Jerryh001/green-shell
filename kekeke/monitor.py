from kekeke import *
import websockets
from .message import Message,MessageType

class Monitor(object):
    _url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    _log=logging.getLogger(__name__)
    
    def __init__(self,channel:str,stdout):
        self.channel=channel
        self.stdout=stdout
        self._last_time:datetime=None
        
        

    async def GetChannelHistoryMessages(self,start_from:datetime=None)->list:
        _payload = r"7|0|6|https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/|53263EDF7F9313FDD5BD38B49D3A7A77|com.liquable.hiroba.gwt.client.square.IGwtSquareService|getLeftMessages|com.liquable.gwt.transport.client.Destination/2061503238|/topic/{0}|1|2|3|4|1|5|5|6|"
        ans=list()
        try:
            async with aiohttp.request("POST",self._url, data=_payload.format(self.channel),headers=self._header) as r:
                resp = await r.text()
        except:
            self._log.error("Fetch history messages from channel "+self.channel+" failed")
        if resp[:4]==r"//OK":
            data=json.loads(resp[4:])[-3]
            for message_raw in reversed(data):
                if message_raw[0]!='{':
                    break
                m_output=Message.loadjson(message_raw)
                if start_from is not None and start_from>=m_output.time:
                    break
                self._log.debug(m_output)
                ans.append(m_output)

            if ans:
                self._log.debug("Get history messages from channel "+self.channel+" successed")
            else:
                self._log.debug("Get history messages from channel "+self.channel+" successed, but it's empty")
        else:
            self._log.warning("Parse history messages from channel "+self.channel+" failed, response:"+resp[:4])
        return ans

    async def SendReport(self,data:list):
        if self._last_time is None:
            self._last_time=await self.GetLastMessageTime()
        for message in reversed(data):
            embed=discord.Embed(description=message.content,timestamp=message.time)
            embed.set_footer(text=message.ID)
            embed.set_author(name=message.ID[:5]+"@"+message.nickname)
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

    async def PeriodRun(self,period:int):
        self._log.info("Starting monitor "+self.channel+" ......")
        self._last_time=await self.GetLastMessageTime()
        while True:
            self._log.info("Checking "+self.channel+" ......")
            data=await self.GetChannelHistoryMessages(start_from=self._last_time)
            if len(data)>0:
                async with self.stdout.typing():
                    await self.SendReport(data)
                self._log.info(self.channel+" updated!")
            else:
                self._log.info(self.channel+" has nothing to update")
            await asyncio.sleep(period)
        self._log.info("stopped "+self.channel+" moniter")

    async def GetToken(self):
        _payload = r"7|0|7|https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/|53263EDF7F9313FDD5BD38B49D3A7A77|com.liquable.hiroba.gwt.client.square.IGwtSquareService|startSquare|com.liquable.hiroba.gwt.client.square.StartSquareRequest/2186526774|com.liquable.gwt.transport.client.Destination/2061503238|/topic/{0}|1|2|3|4|1|5|5|0|0|6|7|"
        async with aiohttp.request("POST",self._url, data=_payload.format(self.channel),headers=self._header) as r:
            resp = await r.text()
        if resp[:4]==r"//OK":
            token=json.loads(resp[4:])[-3][2]
            return token
    async def Oversee(self):
        self._log.info("開始監視 "+self.channel)
        self._last_time=await self.GetLastMessageTime()
        self._log.info("取得 "+self.channel+" 的歷史訊息")
        data=await self.GetChannelHistoryMessages(start_from=self._last_time)
        if len(data)>0:
            async with self.stdout.typing():
                await self.SendReport(data)
            self._log.info("更新了 "+self.channel+" 的 "+str(len(data))+" 條訊息")
        self._log.info("開始常駐監聽 "+self.channel)
        SUBSCRIBE=r"""SUBSCRIBE
destination:/topic/{0}""".format(self.channel)
        LOGIN=r"""CONNECT
login:{{"accessToken":"{0}", "nickname":"DiscordBot"}}""".format(await self.GetToken())
        async with websockets.connect("wss://ws.kekeke.cc/com.liquable.hiroba.websocket") as ws:
            await ws.send(LOGIN)
            await ws.send(SUBSCRIBE)
            while not ws.closed:
                try:
                    data=await asyncio.wait_for(ws.recv(), timeout=60)
                    self._log.debug(data)
                    if data[:7]=="MESSAGE":
                        m_raw=re.search(r"{.+",data,re.IGNORECASE).group(0)
                        m=Message.loadjson(m_raw)
                        if m:
                            async with self.stdout.typing():
                                await self.SendReport([m])
                except asyncio.TimeoutError:
                    self._log.info("PING "+self.channel)
                    await ws.ping(data="PING")
        

            

if __name__=="__main__":
    asyncio.get_event_loop().run_until_complete(Monitor("ffrk",None).GetChannelHistoryMessages())
