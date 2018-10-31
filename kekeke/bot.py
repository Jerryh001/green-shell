import asyncio
import json
import logging

import aiohttp

from .channel import Channel
from .GWTpayload import GWTPayload
from .message import Message, MessageType
from .user import User


class Bot:
    _square_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    #_vote_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/voteService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}

    def __init__(self):
        self._log = logging.getLogger(__name__)
        self._session: aiohttp.ClientSession = None
        self._ws: aiohttp.ClientWebSocketResponse = None
        self.user = User("Discord#New#Bot")
        self.channels = dict()
        #asyncio.ensure_future(self.Connect())

    async def connect(self):
        if not self._session:
            self._s_obj = aiohttp.ClientSession()
            self._session = await self._s_obj.__aenter__()
        if not self._ws:
            self._ws_obj = self._session.ws_connect(url=r"wss://ws.kekeke.cc/com.liquable.hiroba.websocket", heartbeat=120)
            self._ws = await self._ws_obj.__aenter__()
            asyncio.get_event_loop().create_task(self.listen())
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "startSquare"])
        _payload.AddPara("com.liquable.hiroba.gwt.client.square.StartSquareRequest/2186526774", [None, None, "com.liquable.gwt.transport.client.Destination/2061503238", "/topic/{0}".format("彩虹小馬實況")])
        while True:
            resp = await self.post(payload=_payload.String())
            if resp[:4] == r"//OK":
                break
            else:
                await asyncio.sleep(5)
        data = json.loads(resp[4:])[-3]
        self.user.ID = data[-1]
        LOGIN = 'CONNECT\nlogin:'+json.dumps({"accessToken": data[2], "nickname": self.user.nickname})
        await self._ws.send_str(LOGIN)

    async def post(self, payload: str, url: str = _square_url, header: dict = _header) -> str:
        async with self._session.post(url=url, data=payload, headers=header) as r:
            text= await r.text()
        return text

    async def subscribe(self, channel: str):
        if channel not in self.channels:
            self.channels[channel] = Channel(self, channel)
            self.channels[channel].updateUsers()
            SUBSCRIBE_STR = 'SUBSCRIBE\ndestination:/topic/{0}'.format(channel)
            await self._ws.send_str(SUBSCRIBE_STR)
            self._log.info("subscribe "+channel)
            await self.initMessages(channel)

    def isSubscribe(self, channel: str):
        return channel in self.channels

    async def unSubscribe(self, channel: str):
        try:
            self.channels.pop(channel)
            UNSUBSCRIBE_STR = 'UNSUBSCRIBE\ndestination:/topic/{0}'.format(channel)
            await self._ws.send_str(UNSUBSCRIBE_STR)
            self._log.info("unsubscribe "+channel)
        except KeyError:
            pass

    async def listen(self):
        while not self._ws.closed:
            msg = await self._ws.receive()
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            self._log.debug(msg.data)
            msg_list = list(filter(None, msg.data.split('\n')))
            if msg_list[0] != "MESSAGE":
                continue
            publisher = msg_list[2][len("publisher:"):]
            m = Message.loadjson(msg_list[3])
            channel: Channel = self.channels[msg_list[1][len("destination:/topic/"):]]
            if publisher == "CLIENT_TRANSPORT":
                if m and m.user.ID:
                    await channel.receiveMessage(m)
            elif publisher == "SERVER":
                if m and m.mtype == MessageType.population:
                    await channel.updateUsers()
    async def initMessages(self,channel:str):
        _payload=GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/","53263EDF7F9313FDD5BD38B49D3A7A77","com.liquable.hiroba.gwt.client.square.IGwtSquareService","getLeftMessages"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238",["/topic/{0}".format(channel)])
        messages:list=self.channels[channel].messages
        resp=await self.post(payload=_payload.String())
        if resp[:4]==r"//OK":
            data=json.loads(resp[4:])[-3]
            for message_raw in data:
                if message_raw[0]!='{':
                    continue
                m=Message.loadjson(message_raw)
                if(not m.user.ID):
                    continue
                self._log.debug(m)
                messages.append(m)
            if messages:
                self._log.info("Get history messages from channel "+channel+" successed")
            else:
                self._log.info("Get history messages from channel "+channel+" successed, but it's empty")
        else:
            self._log.warning("Parse history messages from channel "+channel+" failed, response:"+resp[:4])
