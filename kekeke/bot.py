import asyncio
import html
import json
import logging
import time
from datetime import datetime
from queue import Queue

import aiohttp
import tzlocal

from .message import Message, MessageType
from .user import User


class Bot():
    _square_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _vote_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/voteService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    subchannel=[]
    message_queue=dict()
    @classmethod
    async def CreateBot(cls,ghost=False):
        self=cls()
        self._log=logging.getLogger(cls.__name__)
        self.session:aiohttp.ClientSession=None
        self.ws:aiohttp.ClientWebSocketResponse=None
        await self.Connect(ghost)
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        async def _CleanUp(exception_type, exception_value, traceback):
            await self._ws_obj.__aexit__(exception_type, exception_value, traceback)
            await self._s_obj.__aexit__(exception_type, exception_value, traceback)
        asyncio.new_event_loop().run_until_complete(_CleanUp(exception_type, exception_value, traceback))

    async def Connect(self,ghost=False):
        if not self.session:
            self._s_obj=aiohttp.ClientSession()
            self.session=await self._s_obj.__aenter__()
        if not self.ws:
            self._ws_obj=self.session.ws_connect(url=r"wss://ws.kekeke.cc/com.liquable.hiroba.websocket",heartbeat=120)
            self.ws=await self._ws_obj.__aenter__()
            asyncio.get_event_loop().create_task(self.Listen())
            if not ghost:
                await self.Login()
            
    
    async def Login(self):
        login_payload={"accessToken":await self.GetToken(),"nickname":"Test#Bot"}
        LOGIN='CONNECT\nlogin:'+json.dumps(login_payload)
        await self.ws.send_str(LOGIN)

    async def Listen(self):
        while not self.ws.closed:
            msg =await self.ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._log.debug(msg.data)
                msg_list=list(filter(None,msg.data.split('\n')))
                if msg_list[0]=="MESSAGE":
                    if msg_list[2][len("publisher:"):]=="CLIENT_TRANSPORT":
                        m=Message.loadjson(msg_list[3])
                        if m:
                            channel=msg_list[1][len("destination:/topic/"):]
                            self.message_queue[channel].put(m)
                            if m.content[0]=="." and (m.user.ID in ["3b0f2a3a8a2a35a9c9727f188772ba095b239668","5df087e5e341f555b0401fb69f89b5937ae7e313"]):
                                await self._RunCommand(m,channel)

    async def _RunCommand(self,message:Message,channel:str):
        args=message.content[1:].split()
        if not args:
            return
        if args[0]=="talk" and len(args)>=2:
            content="<強制發送訊息>"
            onlines=await self.GetOnlineUsers(channel)
            senduser:User=None
            for onlineuser in onlines:
                for muser in message.metionUsers:
                    if onlineuser.ID==muser.ID:
                        senduser=onlineuser
                        break
                
                if senduser:
                    break
                else:
                    if onlineuser.nickname == args[1]:
                        senduser=onlineuser
            senduser.nickname=senduser.ID[:5]+"#"+senduser.nickname
            sendmsg=Message(mtype=MessageType.chat,time=tzlocal.get_localzone().localize(datetime.now()),user=senduser,content=content)
            await self.SendMessage(channel,sendmsg)
                    

    async def GetToken(self,first_channel:str="彩虹小馬實況"):
        _payload = r"7|0|7|https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/|53263EDF7F9313FDD5BD38B49D3A7A77|com.liquable.hiroba.gwt.client.square.IGwtSquareService|startSquare|com.liquable.hiroba.gwt.client.square.StartSquareRequest/2186526774|com.liquable.gwt.transport.client.Destination/2061503238|/topic/{0}|1|2|3|4|1|5|5|0|0|6|7|"
        resp=await self.post(payload=_payload.format(first_channel))
        if resp[:4]==r"//OK":
            token=json.loads(resp[4:])[-3][2]
            return token

    async def Close(self):
        if self.ws:
            self.ws.close()
            self.ws=None
        if self.session:
            self.session.close()
            self.session=None
    async def post(self,payload:str,url:str=None,header:dict=None) -> str:
        if not url:
            url=self._square_url
        if not header:
            header=self._header
        async with self.session.post(url=url,data=payload,headers=header) as r:
            return await r.text()
    async def ReceiveMessage(self,channel:str):
        while self.message_queue[channel].qsize()<1:
            await asyncio.sleep(0)
        return self.message_queue[channel].get()

    async def Subscribe(self,channel:str):
        if channel not in self.subchannel:
            self.subchannel.append(channel)
            self.message_queue[channel]=Queue()
            SUBSCRIBE_STR='SUBSCRIBE\ndestination:/topic/{0}'.format(channel)
            await self.ws.send_str(SUBSCRIBE_STR)
            self._log.info("subscribe "+channel)

    def IsSubscribe(self,channel:str):
        return channel in self.subchannel

    async def Unsubscribe(self,channel:str):
        try:
            self.subchannel.remove(channel)
            UNSUBSCRIBE_STR='UNSUBSCRIBE\ndestination:/topic/{0}'.format(channel)
            await self.ws.send_str(UNSUBSCRIBE_STR)
            self._log.info("unsubscribe "+channel)
        except ValueError:
            pass
    async def SendMessage(self,channel:str,message:Message):
        message_obj={
            "senderPublicId":message.user.ID,
            "senderNickName":message.user.nickname,
            "anchorUsername":"",
            "content":html.escape(message.content),
            "date":str(int(time.time()*1000)),
            "eventType":"CHAT_MESSAGE",
            "payload":{}}
        if message.user.color:
            message_obj["senderColorToken"]=message.user.color
        payload='SEND\ndestination:/topic/{0}\n\n'.format(channel)+json.dumps(message_obj)
        await self.ws.send_str(payload)

    async def GetOnlineUsers(self,channel:str):
        _payload = r"7|0|6|https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/|53263EDF7F9313FDD5BD38B49D3A7A77|com.liquable.hiroba.gwt.client.square.IGwtSquareService|getCrowd|com.liquable.gwt.transport.client.Destination/2061503238|/topic/{0}|1|2|3|4|1|5|5|6|"
        resp = await self.post(payload=_payload.format(channel))
        ans=[]
        if resp[:4]==r"//OK":
            j=json.loads(resp[4:])
            j.reverse()
            keys=j[2]
            for i in range(5,len(j),6):
                ans.append(User(name=keys[j[i+4]-1],ID=keys[j[i+3]-1],color=keys[j[i+2]-1] if j[i+2]>0 else ""))
        return ans
    async def GetChannelHistoryMessages(self,channel:str,start_from:datetime=None)->list:
        _payload = r"7|0|6|https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/|53263EDF7F9313FDD5BD38B49D3A7A77|com.liquable.hiroba.gwt.client.square.IGwtSquareService|getLeftMessages|com.liquable.gwt.transport.client.Destination/2061503238|/topic/{0}|1|2|3|4|1|5|5|6|"
        ans=[]
        resp=await self.post(payload=_payload.format(channel))
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
                self._log.info("Get history messages from channel "+channel+" successed")
            else:
                self._log.info("Get history messages from channel "+channel+" successed, but it's empty")
        else:
            self._log.warning("Parse history messages from channel "+channel+" failed, response:"+resp[:4])
        return ans
