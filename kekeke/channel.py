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

import aiohttp
import redis
import tzlocal

from kekeke import command, flag, red

from .GWTpayload import GWTPayload
from .jsonfile import JsonFile
from .media import Media
from .message import Message, MessageType
from .user import User


class Channel:
    _notwelcomes = JsonFile(os.path.join(os.getcwd(), "data/keyword.json"))
    _square_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _vote_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/voteService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    commendPrefix = os.getenv("DISCORD_PREFIX")

    def __init__(self, name: str):
        self.name = name
        self.user = User("Discord#Bot")
        self._log = logging.getLogger(__name__+"@"+self.name)
        self.session: aiohttp.ClientSession = None
        self.ws: aiohttp.ClientWebSocketResponse = None
        self.messages = list()
        self.message_queue = Queue()
        self.users = set()
        self.flags = set()
        self.medias = dict()
        self.last_send = dict()
        self.redisPerfix = "kekeke::bot::channel::"+self.name+"::"
        self.redis = redis.StrictRedis(connection_pool=red.pool())
        asyncio.get_event_loop().create_task(self.initial())

    async def initial(self):
        self._session = await aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)).__aenter__()
        self.ws = await self._session.ws_connect(url=r"wss://ws.kekeke.cc/com.liquable.hiroba.websocket", heartbeat=120).__aenter__()
        await self.subscribe()
        await self.updateFlags(True)
        await self.updateUsers()
        await self.initMessages(self.name)
        asyncio.get_event_loop().create_task(self.listen())

    async def subscribe(self):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "startSquare"])
        _payload.AddPara("com.liquable.hiroba.gwt.client.square.StartSquareRequest/2186526774", [None, None, "com.liquable.gwt.transport.client.Destination/2061503238", "/topic/{0}".format(self.name)])
        while True:
            resp = await self.post(payload=_payload.string)
            if resp[:4] == r"//OK":
                break
            else:
                await asyncio.sleep(5)
        data = json.loads(resp[4:])[-3]
        self.user.ID = data[-1]
        await self.ws.send_str('CONNECT\nlogin:'+json.dumps({"accessToken": data[2], "nickname": self.user.nickname}))
        await self.ws.send_str('SUBSCRIBE\ndestination:/topic/{0}'.format(self.name))
        self._log.info("subscribe "+self.name)

    async def initMessages(self, channel: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getLeftMessages"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        messages: list = list()
        resp = await self.post(payload=_payload.string)
        if resp[:4] == r"//OK":
            data = json.loads(resp[4:])[-3]
            for message_raw in data:
                if message_raw[0] != '{':
                    continue
                m = Message.loadjson(message_raw)
                if(not m or not m.user.ID):
                    continue
                self._log.debug(m)
                messages.append(m)
            if messages:
                await self.setMessage(messages)
                self._log.info("Get history messages from channel "+self.name+" successed")
            else:
                self._log.info("Get history messages from channel "+self.name+" successed, but it's empty")
        else:
            self._log.warning("Parse history messages from channel "+self.name+" failed, response:"+resp[:4])

    async def listen(self):
        while not self.ws.closed:
            msg = await self.ws.receive()
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            self._log.debug(msg.data)
            msg_list = list(filter(None, msg.data.split('\n')))
            if msg_list[0] != "MESSAGE":
                continue
            publisher = msg_list[2][len("publisher:"):]
            m = Message.loadjson(msg_list[3])
            if publisher == "CLIENT_TRANSPORT":
                if m and m.user.ID:
                    asyncio.get_event_loop().create_task(self.receiveMessage(m))
            elif publisher == "SERVER":
                if m:
                    if m.mtype == MessageType.population:
                        asyncio.get_event_loop().create_task(self.updateUsers())
                    elif m.mtype == MessageType.vote:
                        if m.payload["title"] == "__i18n_voteForbidTitle":
                            if m.payload["votingState"] == "CREATE":
                                asyncio.get_event_loop().create_task(self.vote(m.payload["votingId"]))
                            elif m.payload["votingState"] == "COMPLETE":
                                asyncio.get_event_loop().create_task(self.banCommit(m.payload["votingId"]))

    async def post(self, payload: str, url: str = _square_url, header: dict = _header) -> str:
        async with self._session.post(url=url, data=payload, headers=header) as r:
            text = await r.text()
            if r.status != 200:
                self._log.warning("<post error> payload="+payload+"url="+url+"header="+str(header))
        return text

    async def updateFlags(self, pull=False):
        if pull:
            self.flags = self.redis.smembers(self.redisPerfix+"flags")
        else:
            self.redis.delete(self.redisPerfix+"flags")
            self.redis.sadd(self.redisPerfix+"flags", self.flags)
        await self.rename(Message(user=self.user), self.user.nickname+"".join(self.flags))

    async def updateUsers(self)->set:
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getCrowd"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        resp = await self.post(payload=_payload.string)
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
            if flag.talk in self.flags:
                for user in joined:
                    if user.ID not in self.last_send or self.last_send[user.ID] < self.messages[-1].time:
                        if self.isNotWelcome(user):
                            await self.sendMessage(Message(mtype=MessageType.chat, user=user, content="<我就是GS，快來Ban我>"))
                            self.last_send[user.ID] = tzlocal.get_localzone().localize(datetime.now())
                        elif re.match(r"(誰啊|unknown)", user.nickname):
                            await self.sendMessage(Message(mtype=MessageType.chat, user=user, content="<自動發送>"))
                            self.last_send[user.ID] = tzlocal.get_localzone().localize(datetime.now())

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
        self.medias = dict()
        await self.updateMedia(self.messages)

    async def updateMedia(self, messages: list, pop=False):
        for message in messages:
            self.last_send[message.user.ID] = message.time
            if re.search(r"(^https://www\.youtube\.com/.+|^https?://\S+\.(jpe?g|png|gif)$)", message.url, re.IGNORECASE):
                media = Media(user=message.user, url=message.url, remove=(message.mtype == MessageType.deleteimage))
                if media.remove and not pop:
                    try:
                        self.medias.pop(media)
                    except KeyError:
                        pass
                elif pop:
                    try:
                        self.medias[media] = self.medias[media]-1
                        if self.medias[media] == 0:
                            self.medias.pop(media)
                    except KeyError:
                        pass
                else:
                    self.medias[media] = self.medias[media]+1 if media in self.medias else 1
        if not pop and self.redis.sismember(self.redisPerfix+"flags", "🤐"):
            for media in self.medias:
                issilent = self.redis.sismember(self.redisPerfix+"silentUsers", media.user.ID)
                if not issilent and self.isForbiddenMessage(message):
                    await self.muda(Message(mtype=MessageType.chat, user=self.user, metionUsers=[message.user]), message.user.nickname)
                if issilent:
                    user = media.user
                    user.nickname = self.user.nickname
                    await self.sendMessage(Message(mtype=MessageType.deleteimage, user=user, content=random.choice(["muda", "沒用", "無駄"])+" "+media.url), showID=False)

    def isForbiddenMessage(self, message: Message)->bool:
        if self.redis.sismember(self.redisPerfix+"auth", message.user.ID) or self.redis.sismember("kekeke::bot::global::auth", message.user.ID):
            return False
        else:
            for keyword in self.redis.smembers(self.redisPerfix+"keyword"):
                if re.search(keyword, message.content, re.IGNORECASE):
                    return True
            return False

    async def receiveMessage(self, message: Message):
        self.messages.append(message)
        self.message_queue.put(message)
        await self.updateMedia([message])
        if len(self.messages) > 100:
            await self.updateMedia(self.messages[:-100], True)
            self.messages = self.messages[-100:]
        if message.content[0:len(self.commendPrefix)] == self.commendPrefix:
            args = message.content[len(self.commendPrefix):].split()
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
        await self.ws.send_str(payload)

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
        await self.rename(Message(user=self.user), self.user.nickname+"".join(self.flags))

############################################commands#######################################

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
            user.nickname = self.user.nickname
            await self.sendMessage(Message(mtype=MessageType.deleteimage, user=user, content="delete "+media.url), showID=False)

    @command.command()
    async def rename(self, message: Message, *args):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "updateNickname"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", message.user.color if message.user.color != "" else None, message.user.ID, args[0], message.user.ID])
        await self.post(payload=_payload.string)

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
        await self.sendMessage(Message(mtype=MessageType.chat, user=self.user, content=result), showID=False)

    @command.command(authonly=True)
    async def clear(self, message: Message, *args):
        if len(args) >= 2 and args[0] == self.name:
            times = clip(int(args[1], 0), 0, 100)
            for _ in range(times):
                await self.sendMessage(Message(), showID=False)
            self._log.info("發送"+str(times)+"則空白訊息")

    @command.command(authonly=True)
    async def muda(self, message: Message, *args):
        if len(args) >= 1:
            user: User = message.metionUsers[0]

            if self.redis.sismember(self.redisPerfix+"silentUsers", user.ID):
                self.redis.srem(self.redisPerfix+"silentUsers", user.ID)
            else:
                self.redis.sadd(self.redisPerfix+"silentUsers", user.ID)
                await self.remove(message, args[0])
                await self.sendMessage(Message(mtype=MessageType.chat, user=self.user, content=user.nickname+"你洗再多次也沒用沒用沒用沒用沒用"), showID=False)

    @command.command(authonly=True)
    async def autotalk(self, message: Message, *args):
        await self.toggleFlag(flag.talk)

    @command.command(authonly=True)
    async def automuda(self, message: Message, *args):
        await self.toggleFlag(flag.muda)

    @command.command(authonly=True)
    async def test(self, message: Message, *args):
        _payload = "7|0|14|https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/|C8317665135E6B272FC628F709ED7F2C|com.liquable.hiroba.gwt.client.vote.IGwtVoteService|createVotingForForbid|com.liquable.gwt.transport.client.Destination/2061503238|/topic/測試123|com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082|com.liquable.hiroba.gwt.client.square.ColorSource/2591568017|5c6917815a0fff1c474740f3afc70db0d4ef3a1a|DiscordBot|3b0f2a3a8a2a35a9c9727f188772ba095b239668|Jerryh001|java.lang.String/2004016611||1|2|3|4|4|5|7|7|13|5|6|7|8|0|9|10|9|7|8|0|11|12|11|14|"
        await self.post(payload=_payload, url="https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/voteService")

    @command.command(authonly=True)
    async def ban(self, message: Message, *args):
        target: User = message.metionUsers[0]
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "createVotingForForbid"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", None, self.user.ID, self.user.nickname, self.user.ID])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", None, target.ID, target.nickname, target.ID])
        _payload.AddPara("java.lang.String/2004016611", [""], regonly=True)
        await self.post(payload=_payload.string, url=self._vote_url)

    async def vote(self, voteid: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "voteByPermission"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("java.lang.String/2004016611", [voteid], regonly=True)
        _payload.AddPara("java.util.Set", ["java.util.HashSet/3273092938", "https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "java.lang.String/2004016611", "__i18n_forbid"], regonly=True)
        await self.post(payload=_payload.string, url=self._vote_url)

    async def banCommit(self, voteid: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "applyForbidByVoting"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("java.lang.String/2004016611", [voteid], regonly=True)
        _payload.AddPara("com.liquable.hiroba.gwt.client.vote.ForbidOption/647536008", [0], rawpara=True)
        await self.post(payload=_payload.string, url=self._vote_url)


def clip(num: int, a: int, b: int):
    return min(max(num, a), b)
