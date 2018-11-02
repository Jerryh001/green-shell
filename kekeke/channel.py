import asyncio
import functools
import html
import inspect
import json
import logging
import re
import time
from queue import Queue

import aiohttp

from kekeke import command

from .GWTpayload import GWTPayload
from .media import Media
from .message import Message, MessageType
from .user import User


class Channel:
    def __init__(self, bot: "Bot", name: str):
        self.bot = bot
        self.name = name
        self._log = logging.getLogger(__name__+"@"+self.name)
        self.messages = list()
        self.message_queue = Queue()
        self.users = set()
        self.commends = dict()
        self.flag = set()
        self.medias = set()

    async def updateUsers(self)->set:
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getCrowd"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
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
            if "⚡" in self.flag:
                for user in joined:
                    if re.match(r"(誰啊|unknown)", user.nickname):
                        await self.sendMessage(Message(mtype=MessageType.chat, user=user, content="<自動發送>"), showID=True)
            return joined

    async def setMessage(self, message_list: list):
        self.messages = message_list
        self.medias = set()
        await self.updateMedia(self.messages)

    async def updateMedia(self, messages: list, reverse=False):
        for message in messages:
            if re.search(r"(^https://www\.youtube\.com/.+|^https?://\S+\.(jpe?g|png|gif)$)", message.url, re.IGNORECASE):
                media = Media(user=message.user, url=message.url, remove=(message.mtype == MessageType.deleteimage))
                if reverse != media.remove:
                    try:
                        self.medias.remove(media)
                    except KeyError:
                        pass
                else:
                    self.medias.add(media)

    async def receiveMessage(self, message: Message):
        self.messages.append(message)
        self.message_queue.put(message)
        await self.updateMedia([message])
        if len(self.messages) > 100:
            await self.updateMedia(self.messages[:-100], True)
            self.messages = self.messages[-100:]
        if message.content[0] == ".":
            args = message.content[1:].split()
            if(args[0] in command.commends):
                self._log.info("命令"+args[0]+":開始執行")
                asyncio.create_task(command.commends[args[0]](self, message, *(args[1:])))
                self._log.info("命令"+args[0]+":執行完成")
            else:
                self._log.warning("命令"+args[0]+"不存在")

    async def sendMessage(self, message: Message, *, showID=False, escape=True):
        message_obj = {
            "senderPublicId": message.user.ID,
            "senderNickName": (message.user.ID[:5]+"#" if showID else "")+message.user.nickname,
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

    async def toggleFlag(self, flag: str):
        if flag in self.flag:
            self.flag.remove(flag)
        else:
            self.flag.add(flag)
        await self.rename(Message(user=self.bot.user), self.bot.user.nickname+"".join(self.flag))

############################################commands#######################################
    @command.command(authonly=True)
    async def clear(self, message: Message, *args):
        if(len(args) >= 2 and args[0] == self.name):
            times = clip(int(args[1], 0), 0, 100)
            for _ in range(times):
                await self.sendMessage(Message())
            self._log.info("發送"+str(times)+"則空白訊息")

    @command.command(authonly=True)
    async def remove(self, message: Message, *args):
        medias_to_remove=set()
        if len(args) == 1:
            for media in self.medias:
                if media.user.ID == message.metionUsers[0].ID:
                    medias_to_remove.add(media)
        elif len(args) >= 2:
            media = Media(user=message.metionUsers[0], url=args[1])
            medias_to_remove.add(media)
        for media in medias_to_remove:
            user=media.user
            user.nickname=self.bot.user.nickname
            await self.sendMessage(Message(mtype=MessageType.deleteimage, user=user, content="delete "+media.url))


    @command.command(authonly=True)
    async def autotalk(self, message: Message, *args):
        await self.toggleFlag("⚡")

    @command.command()
    async def rename(self, message: Message, *args):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "updateNickname"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", message.user.color if message.user.color != "" else None, message.user.ID, args[0], message.user.ID])
        await self.bot.post(payload=_payload.String())


def clip(num: int, a: int, b: int):
    return min(max(num, a), b)
