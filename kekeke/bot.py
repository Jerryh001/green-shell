import asyncio
import html
import json
import logging
import time
from datetime import datetime
from queue import Queue

import aiohttp
import tzlocal

from .GWTpayload import GWTPayload
from .message import Message, MessageType
from .user import User


class Bot():
    _square_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _vote_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/voteService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    subchannel=[]
    message_queue=dict()
    online_users=dict()
    last_forcetalk=dict()
    @classmethod
    async def CreateBot(cls,ghost=False):
        self=cls()
        self._log=logging.getLogger(cls.__name__)
        self.session:aiohttp.ClientSession=None
        self.ws:aiohttp.ClientWebSocketResponse=None
        self.lightning=False
        self.ghost=ghost
        self.user=User("Test#Bot")
        await self.Connect()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        async def _CleanUp(exception_type, exception_value, traceback):
            await self._ws_obj.__aexit__(exception_type, exception_value, traceback)
            await self._s_obj.__aexit__(exception_type, exception_value, traceback)
        asyncio.new_event_loop().run_until_complete(_CleanUp(exception_type, exception_value, traceback))

    async def Connect(self):
        if not self.session:
            self._s_obj=aiohttp.ClientSession()
            self.session=await self._s_obj.__aenter__()
        if not self.ws:
            self._ws_obj=self.session.ws_connect(url=r"wss://ws.kekeke.cc/com.liquable.hiroba.websocket",heartbeat=120)
            self.ws=await self._ws_obj.__aenter__()
            asyncio.get_event_loop().create_task(self.Listen())
            await self.Login()
            
    
    async def Login(self):
        _payload=GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/","53263EDF7F9313FDD5BD38B49D3A7A77","com.liquable.hiroba.gwt.client.square.IGwtSquareService","startSquare"])
        _payload.AddPara("com.liquable.hiroba.gwt.client.square.StartSquareRequest/2186526774",[None,None,"com.liquable.gwt.transport.client.Destination/2061503238","/topic/{0}".format("彩虹小馬實況")])
        while True:
            resp=await self.post(payload=_payload.String())
            if resp[:4]==r"//OK":
                break
            else:
                await asyncio.sleep(5)
        data=json.loads(resp[4:])[-3]
        self.user.ID=data[-1]
        login_payload={"accessToken":data[2],"nickname":self.user.nickname if not self.ghost else ""}
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
                            if m.content[0]==".":
                                asyncio.get_event_loop().create_task(self._RunCommand(m,channel))
                    elif msg_list[2][len("publisher:"):]=="SERVER":
                        m=Message.loadjson(msg_list[3])
                        if m and m.mtype==MessageType.population:
                            await self.UpdateOnlineUsers(msg_list[1][len("destination:/topic/"):])


    async def UpdateOnlineUsers(self,channel:str):
        onlines=await self.GetOnlineUsers(channel)
        history=await self.GetChannelHistoryMessages(channel)
        last_time:datetime=history[-1].time
        if channel not in self.last_forcetalk:
            self.last_forcetalk[channel]=dict()
        if channel in self.online_users:
            onlines_old=self.online_users[channel]
            if self.lightning:
                for user in onlines:
                    if user not in onlines_old and (user.nickname.find("誰啊")>=0 or user.nickname.find("unknown")>=0):
                        if user.ID not in self.last_forcetalk[channel] or self.last_forcetalk[channel][user.ID]<last_time:
                            self.last_forcetalk[channel][user.ID]=tzlocal.get_localzone().localize(datetime.now())
                            await self.Talk(user,channel)
        self.online_users[channel]=onlines
            

    async def Talk(self,user:User,channel:str,content:str="<強制發送訊息>"):
        user.nickname=user.ID[:5]+"#"+user.nickname
        msg=Message(mtype=MessageType.chat,time=tzlocal.get_localzone().localize(datetime.now()),user=user,content=content)
        await self.SendMessage(channel,msg)

    async def _RunCommand(self,message:Message,channel:str):
        args=message.content[1:].split()
        if not args:
            return
        if message.user.ID in ["3b0f2a3a8a2a35a9c9727f188772ba095b239668","5df087e5e341f555b0401fb69f89b5937ae7e313"]:
            if args[0]=="talk" and len(args)>=2:
                senduser:User=None
                for muser in message.metionUsers:
                    senduser=await self.findUserByID(channel,muser.ID)
                    if senduser:
                        break
                if not senduser:
                    senduser=await self.findUserByName(channel,args[1])
                if senduser:
                    await self.Talk(senduser,channel)
                return
            elif args[0]=="autotalk":
                self.lightning=not self.lightning
                await self.Rename(channel,self.user,self.user.nickname+("⚡" if self.lightning else ""))
        if args[0]=="rename" and len(args)>=2:
            await self.Rename(channel,message.user,args[1])
            return
                    
    async def Rename(self,channel:str,user:User,name:str):
        _payload=GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/","53263EDF7F9313FDD5BD38B49D3A7A77","com.liquable.hiroba.gwt.client.square.IGwtSquareService","updateNickname"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238",["/topic/{0}".format(channel)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082",["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017",user.color if user.color!="" else None,user.ID,name,user.ID])
        await self.post(payload=_payload.String())

    async def findUserByID(self,channel:str,ID:str):
        user=next((x for x in self.online_users[channel] if x.ID==ID),None)
        if not user:
            history=await self.GetChannelHistoryMessages(channel)
            for message in history:
                if message.user.ID==ID:
                    user=message.user
                    break
        return user

    async def findUserByName(self,channel:str,name:str):
        user=next((x for x in self.online_users[channel] if x.nickname==name),None)
        if not user:
            history=await self.GetChannelHistoryMessages(channel)
            for message in history:
                if message.user.nickname==name:
                    user=message.user
                    break
        return user



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
    async def SendMessage(self,channel:str,message:Message,escape:bool=True):
        message_obj={
            "senderPublicId":message.user.ID,
            "senderNickName":message.user.nickname,
            "anchorUsername":"",
            "content":html.escape(message.content) if escape else message.content,
            "date":str(int(time.time()*1000)),
            "eventType":"CHAT_MESSAGE",
            "payload":{}}
        if message.user.color:
            message_obj["senderColorToken"]=message.user.color
        payload='SEND\ndestination:/topic/{0}\n\n'.format(channel)+json.dumps(message_obj)
        await self.ws.send_str(payload)

    async def GetOnlineUsers(self,channel:str):
        _payload=GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/","53263EDF7F9313FDD5BD38B49D3A7A77","com.liquable.hiroba.gwt.client.square.IGwtSquareService","getCrowd"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238",["/topic/{0}".format(channel)])
        resp = await self.post(payload=_payload.String())
        ans=[]
        if resp[:4]==r"//OK":
            j=json.loads(resp[4:])
            j.reverse()
            keys=j[2]
            for i in range(5,len(j),6):
                ans.append(User(name=keys[j[i+4]-1],ID=keys[j[i+3]-1],color=keys[j[i+2]-1] if j[i+2]>0 else ""))
        return ans
    async def GetChannelHistoryMessages(self,channel:str,start_from:datetime=None)->list:
        _payload=GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/","53263EDF7F9313FDD5BD38B49D3A7A77","com.liquable.hiroba.gwt.client.square.IGwtSquareService","getLeftMessages"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238",["/topic/{0}".format(channel)])
        ans=[]
        resp=await self.post(payload=_payload.String())
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
