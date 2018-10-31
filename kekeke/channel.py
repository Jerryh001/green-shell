import asyncio
import html
import json
import logging
import time
from queue import Queue

import aiohttp

from .GWTpayload import GWTPayload
from .message import Message, MessageType
from .user import User


class Channel:
    def __init__(self, bot, name: str):
        self.bot = bot
        self.name = name
        self.messages = list()
        self.message_queue = Queue()
        self.users = set()
        #asyncio.get_event_loop().run_until_complete(self.updateUsers())

    async def updateUsers(self)->set:
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/","53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getCrowd"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238",["/topic/{0}".format(self.name)])
        resp = await self.bot.post(payload=_payload.String())
        new_users = set()
        if resp[:4] == r"//OK":
            j = json.loads(resp[4:])
            j.reverse()
            keys = j[2]
            for i in range(5, len(j), 6):
                new_users.add(User(
                    name=keys[j[i+4]-1], ID=keys[j[i+3]-1], color=keys[j[i+2]-1] if j[i+2] > 0 else ""))
            joined = new_users-self.users
            self.users = new_users
            return joined

    async def receiveMessage(self, message: Message):
        self.messages.append(message)
        self.message_queue.put(message)
        if len(self.messages) > 100:
            self.messages = self.messages[-100:]
        if message.content[0] == ".":
            pass

    async def sendMessage(self, message: Message, escape=True):
        message_obj = {
            "senderPublicId": message.user.ID,
            "senderNickName": message.user.nickname,
            "anchorUsername": "",
            "content": html.escape(message.content) if escape else message.content,
            "date": str(int(time.time()*1000)),
            "eventType": message.mtype.value,
            "payload": {}}
        if message.user.color:
            message_obj["senderColorToken"] = message.user.color
        payload = 'SEND\ndestination:/topic/{0}\n\n'.format(self.name)+json.dumps(message_obj)
        await self.bot.ws.send_str(payload)

    async def waitMessage(self)->Message:
        while self.message_queue.qsize() < 1:
            await asyncio.sleep(0)
        return self.message_queue.get()
