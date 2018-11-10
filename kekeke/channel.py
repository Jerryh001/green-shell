import asyncio
import functools
import html
import inspect
import json
import logging
import os
import random
import re
import time
from datetime import datetime
from queue import Queue
import tzlocal
import aiohttp
import redis

from kekeke import command, red

from .GWTpayload import GWTPayload
from .jsonfile import JsonFile
from .media import Media
from .message import Message, MessageType
from .user import User


class Channel:
    _notwelcomes = JsonFile(os.path.join(os.getcwd(), "data/keyword.json"))

    def __init__(self, bot: "Bot", name: str):
        self.bot = bot
        self.name = name
        self._log = logging.getLogger(__name__+"@"+self.name)
        self.messages = list()
        self.message_queue = Queue()
        self.users = set()
        self.commends = dict()
        self.flags = set()
        self.medias = set()
        self.last_send = dict()
        self.mudaUsers = set()
        self.redisPerfix = "kekeke::bot::channel::"+self.name+"::"
        self.redis = redis.StrictRedis(connection_pool=red.pool())
        asyncio.get_event_loop().create_task(self.updateFlags(True))

    async def updateFlags(self, pull=False):
        if pull:
            self.flags = self.redis.smembers(self.redisPerfix+"flags")
        else:
            self.redis.delete(self.redisPerfix+"flags")
            self.redis.sadd(self.redisPerfix+"flags", self.flags)
        await self.rename(Message(user=self.bot.user), self.bot.user.nickname+"".join(self.flags))

    async def updateUsers(self)->set:
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getCrowd"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        resp = await self.bot.post(payload=_payload.string)
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
            if "⚡" in self.flags:
                for user in joined:
                    if user.ID not in self.last_send or self.last_send[user.ID] < self.messages[-1].time:
                        if self.isNotWelcome(user):
                            await self.sendMessage(Message(mtype=MessageType.chat, user=user, content="<我就是GS，快來Ban我>"))
                            self.last_send[user.ID]=tzlocal.get_localzone().localize(datetime.now())
                        elif re.match(r"(誰啊|unknown)", user.nickname):
                            await self.sendMessage(Message(mtype=MessageType.chat, user=user, content="<自動發送>"))
                            self.last_send[user.ID]=tzlocal.get_localzone().localize(datetime.now())
                        
            return joined

    def isNotWelcome(self, user: User)->bool:
        keywords = self._notwelcomes.json
        if user.ID in keywords["ID"]:
            return True

        for name in keywords["name"]:
            if re.search(name, user.nickname, re.IGNORECASE):
                return True

        return False

    async def setMessage(self, message_list: list):
        self.messages = message_list
        self.medias = set()
        await self.updateMedia(self.messages)

    async def updateMedia(self, messages: list, reverse=False):
        for message in messages:
            self.last_send[message.user.ID]=message.time
            if re.search(r"(^https://www\.youtube\.com/.+|^https?://\S+\.(jpe?g|png|gif)$)", message.url, re.IGNORECASE):
                media = Media(user=message.user, url=message.url, remove=(message.mtype == MessageType.deleteimage))
                if reverse != media.remove:
                    try:
                        self.medias.remove(media)
                    except KeyError:
                        pass
                else:
                    self.medias.add(media)
                    if message.user in self.mudaUsers:
                        user = media.user
                        user.nickname = self.bot.user.nickname
                        await self.sendMessage(Message(mtype=MessageType.deleteimage, user=user, content=random.choice(["muda", "沒用", "無駄"])+" "+media.url), showID=False)

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
                
                asyncio.get_event_loop().create_task(command.commends[args[0]](self, message, *(args[1:])))
                
            else:
                self._log.warning("命令"+args[0]+"不存在")

    async def sendMessage(self, message: Message, *, showID=True, escape=True):
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
        if flag in self.flags:
            self.flags.remove(flag)
            self.redis.srem(self.redisPerfix+"flags", flag)
        else:
            self.flags.add(flag)
            self.redis.sadd(self.redisPerfix+"flags", flag)
        await self.rename(Message(user=self.bot.user), self.bot.user.nickname+"".join(self.flags))

############################################commands#######################################

    @command.command(authonly=True)
    async def auth(self, message: Message, *args):
        ismember = self.redis.sismember(self.redisPerfix+"auth", message.metionUsers[0].ID)
        success = False
        if ismember:
            if len(args) == 1 or (len(args) == 2 and args[0] == "remove"):
                self.redis.srem(self.redisPerfix+"auth", message.metionUsers[0].ID)
                success = True
        else:
            if len(args) == 1 or (len(args) == 2 and args[0] == "add"):
                self.redis.sadd(self.redisPerfix+"auth", message.metionUsers[0].ID)
                success = True
        result = "操作"+("完成" if success else "失敗")+"，使用者("+message.metionUsers[0].ID[:5]+")"+message.metionUsers[0].nickname+'目前於"'+self.name+'"'+("是" if ismember != success else "不是")+"認證的使用者"
        await self.sendMessage(Message(mtype=MessageType.chat, user=self.bot.user, content=result), showID=False)

    @command.command(authonly=True)
    async def clear(self, message: Message, *args):
        if len(args) >= 2 and args[0] == self.name:
            times = clip(int(args[1], 0), 0, 100)
            for _ in range(times):
                await self.sendMessage(Message(), showID=False)
            self._log.info("發送"+str(times)+"則空白訊息")

    @command.command()
    async def remove(self, message: Message, *args):
        medias_to_remove = set()
        if len(args) == 1:
            for media in self.medias:
                if media.user.ID == message.metionUsers[0].ID:
                    medias_to_remove.add(media)
        elif len(args) >= 2:
            medias_to_remove.add(Media(user=message.metionUsers[0], url=args[1]))
            if message.user != message.metionUsers[0]:
                medias_to_remove.add(Media(user=message.user, url=args[1]))
        for media in medias_to_remove:
            user = media.user
            user.nickname = self.bot.user.nickname
            await self.sendMessage(Message(mtype=MessageType.deleteimage, user=user, content="delete "+media.url), showID=False)

    @command.command(authonly=True)
    async def muda(self, message: Message, *args):
        if len(args) >= 1:
            user: User = message.metionUsers[0]
            if user in self.mudaUsers:
                self.mudaUsers.remove(user)
            else:
                self.mudaUsers.add(user)
                await self.remove(message, args[0])
                await self.sendMessage(Message(mtype=MessageType.chat, user=self.bot.user, content=user.nickname+"你洗再多次也沒用沒用沒用沒用沒用"), showID=False)

    @command.command(authonly=True)
    async def autotalk(self, message: Message, *args):
        await self.toggleFlag("⚡")

    @command.command()
    async def rename(self, message: Message, *args):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "updateNickname"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", message.user.color if message.user.color != "" else None, message.user.ID, args[0], message.user.ID])
        await self.bot.post(payload=_payload.string)

    @command.command(authonly=True)
    async def ban(self, message: Message, *args):
        target: User = message.metionUsers[0]
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "createVotingForForbid"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", None, self.bot.user.ID, self.bot.user.nickname, self.bot.user.ID])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", args[1] if args[1] else None, target.ID, target.nickname, target.ID])
        _payload.AddPara("java.lang.String/2004016611", [""], True)
        await self.bot.post(payload=_payload.string, url="https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/voteService")

    async def vote(self, voteid: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "voteByPermission"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("java.lang.String/2004016611", [voteid], True)
        _payload.AddPara("java.util.Set", ["java.util.HashSet/3273092938", "https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "java.lang.String/2004016611", "__i18n_forbid"], True)
        _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8", "cookie": "_ga=GA1.2.1273363991.1536654382; __cfduid=d2fd9578e93e5caf352c6744cbbb60eaa1536654643; _gid=GA1.2.25204363.1541384012; JSESSIONID=34D11AD105724DFD1FC3E69CA7935DAB", "referer": "https://kekeke.cc/{0}".format(self.name)}
        await self.bot.post(payload=_payload.string, url="https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/voteService")


def clip(num: int, a: int, b: int):
    return min(max(num, a), b)
