import asyncio
import base64
import copy
import functools
import hashlib
import html
import inspect
import json
import logging
import math
import os
import random
import re
import time
import typing
from datetime import datetime
from queue import Queue
from shutil import copyfile
from zipfile import ZipFile

import aiofiles
import aiohttp
import discord
import tzlocal
from PIL import Image, ImageDraw, ImageFont

from kekeke import command, flag

from .GWTpayload import GWTPayload
from .jsonfile import JsonFile
from .message import *
from .red import redis
from .user import User


class Channel:
    from enum import Enum

    class BotType(Enum):
        training = 0
        observer = 1
        defender = 2

    _square_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _vote_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/voteService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    commendPrefix = os.getenv("DISCORD_PREFIX")

    redisGlobalPerfix = "kekeke::bot::global::"

    def __init__(self, name: str, mode: BotType = BotType.observer):
        self.mode = mode
        self.name = name
        self.user = User(f'{("小小綠盾" if self.mode == self.BotType.training else "綠盾防禦系統")}#Bot', anchorUsername="__BOT__")
        self._log = logging.getLogger((f"{__name__}@{self.name}"))
        self._session: aiohttp.ClientSession = None
        self.ws: aiohttp.ClientWebSocketResponse = None
        self.messages = list()
        self.message_queue = Queue()
        self.users = set()
        self.flags = set()
        self.medias = dict()
        self.last_send_IDs = dict()
        self.last_send_Nicknames = dict()
        self.redisPerfix = f"kekeke::bot::channel::{self.name}::"
        self.connectEvents = None
        self.pauseMessage = None
        self.pauseCounter = 0
        self.closed = False
        self.GUID = self.getGUID()
        self.kerma = 0
        self.mudacounter = 0
        self.mudaValue = 0
        self.firstmuda = True
        self.mudausers = list()
        self.timeout = None
        self.pandingCommands = []

        self.loginstr = ""
        self.waterID = 1

    async def initial(self):
        if self.mode == self.BotType.training:
            self._log = logging.getLogger((__name__ + "#????????"))
        while True:
            try:
                self._session = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))
                self.ws = await self._session.ws_connect(url=r"wss://ws.kekeke.cc/com.liquable.hiroba.websocket", heartbeat=120)
                break
            except Exception as e:
                self._log.error("對伺服器建立連線失敗，5秒後重試")
                self._log.error(e, exc_info=True)
                await self.Close(stop=False)
                await asyncio.wait(5)

        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.home.gwt.HomeModule/", "C1A6986483E70154FE9652945962D18F", "com.liquable.hiroba.gwt.client.square.IGwtAnchorSquareService", "isAnchorSquareExist"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])
        res = await self.post(payload=_payload.string, url="https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/anchorSquareService")
        if res[0] == 1:  # AnchorSquare
            raise ValueError()

        await self.subscribe()
        if self.mode == self.BotType.training:
            self._log = logging.getLogger((__name__ + "#" + self.GUID[:8]))
        if self.mode != self.BotType.training:
            await self.updateFlags(True)
            await self.initMessages(self.name)
            await self.updateUsers()
            asyncio.get_event_loop().create_task(self.showLogo())

        if self.mode == self.BotType.defender:
            self.timeout = asyncio.get_event_loop().create_task(self.SelfTimeout())

        self.connectEvents = asyncio.get_event_loop().create_task(asyncio.wait({self.listen(), self.keepAlive()}))

    async def SelfTimeout(self):
        try:
            await asyncio.sleep(900)
            if self.mudaValue:

                def isValid(m: Message) -> bool:
                    return m.user.ID and m.user.ID not in self.mudausers

                self._log.info("有殘餘洗版訊息，自動清除")
                await self.resetMessages(isValid)
                return
            else:
                await self.Close()
        except asyncio.CancelledError:
            pass

    async def Close(self, stop=True):
        if stop:
            self.closed = True
            if self.mode == self.BotType.training:
                redis.smove("kekeke::bot::training::GUIDs::using", "kekeke::bot::training::GUIDs", self.GUID)
            elif self.mode == self.BotType.defender:
                redis.smove("kekeke::bot::GUIDpool::using", "kekeke::bot::GUIDpool", self.GUID)
        if self.connectEvents and not self.connectEvents.done():
            self.connectEvents.cancel()
            try:
                await self.connectEvents
            except asyncio.CancelledError:
                pass
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

    async def reConnect(self):
        await self.Close(stop=False)
        if not self.closed:
            asyncio.get_event_loop().create_task(self.initial())

    async def keepAlive(self):
        while not self._session.closed:
            await self.updateKerma()
            if self.mode == self.BotType.training and self.kerma >= 80:
                redis.smove("kekeke::bot::training::GUIDs::using", "kekeke::bot::GUIDpool", self.GUID)
                self._log.info(f"GUID:{self.GUID}的KERMA已達80，尋找新GUID並重新連線")
                self.GUID = self.getGUID()
                break
            if self.mode == self.BotType.defender and self.kerma < 80:
                redis.smove("kekeke::bot::GUIDpool::using", "kekeke::bot::training::GUIDs", self.GUID)
                self._log.error(f"GUID:{self.GUID}的KERMA不足80，尋找新GUID並重新連線")
                self.GUID = self.getGUID()
                break
            await asyncio.sleep(300)
        asyncio.get_event_loop().create_task(self.reConnect())

    async def updateKerma(self):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "0C66C7C6100D68542CF7FADBCA36808D", "com.liquable.hiroba.gwt.client.anonymous.IGwtAnonymousService", "tryExtendsKerma"])
        _payload.AddPara("java.lang.String/2004016611", [self.GUID], regonly=True)
        j = await self.post(payload=_payload.string, url="https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/anonymousService")
        kerma = int(j[0])
        if self.kerma != kerma:
            if self.kerma > kerma:
                self._log.info(f"kerma減少了:{self.kerma}->{kerma}")
            self.kerma = kerma
            if self.mode != self.BotType.observer:
                await self.updateUsername()

    def getGUID(self) -> str or None:
        if self.mode == self.BotType.training:
            while True:
                guid = redis.srandmember("kekeke::bot::training::GUIDs")
                if not guid:
                    return None
                if redis.smove("kekeke::bot::training::GUIDs", "kekeke::bot::training::GUIDs::using", guid):
                    return guid
        elif self.mode == self.BotType.defender:
            while True:
                guid = redis.srandmember("kekeke::bot::GUIDpool")
                if not guid:
                    return None
                if redis.smove("kekeke::bot::GUIDpool", "kekeke::bot::GUIDpool::using", guid):
                    return guid
        else:
            return redis.get(self.redisPerfix + "botGUID")

    async def subscribe(self):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "startSquare"])
        _payload.AddPara("com.liquable.hiroba.gwt.client.square.StartSquareRequest/2186526774", [self.GUID if self.GUID else None, None, "com.liquable.gwt.transport.client.Destination/2061503238", f"/topic/{self.name}"])
        while True:
            data = await self.post(payload=_payload.string)
            if data:
                break
            else:
                await asyncio.sleep(5)
        data = data[-3]
        if not self.GUID:
            self.GUID = data[1]
            if self.mode == self.BotType.training:
                redis.sadd("kekeke::bot::training::GUIDs::using", self.GUID)
            else:
                if self.mode == self.BotType.defender:
                    self._log.error("沒有足夠Kerma的GUID可用，隨便創建一個")
                redis.set(self.redisPerfix + "botGUID", self.GUID)
        self.waterID = 1
        self.user.ID = data[-1]
        self.loginstr = json.dumps({"accessToken": data[2], "nickname": self.user.nickname}, ensure_ascii=False, separators=(', ', ':'))
        await self.ws.send_str(f'CONNECT\nlogin:{self.loginstr}')
        await self.ws.send_str(f'SUBSCRIBE\ndestination:/topic/{self.name}')
        self._log.info(f"subscribe {self.name}")

    async def initMessages(self, channel: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getLeftMessages"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])

        data = await self.post(payload=_payload.string)
        if data:
            data = list(x for x in data[-3] if x[0] == '{')
            messages: list = Message.loadjsonlist(data)
            if messages:
                await self.setMessage(messages)
                self.initMudaValue()
            self._log.info("更新歷史訊息成功")
        else:
            self._log.warning("更新歷史訊息失敗")

    @property
    def pauseListen(self):
        return bool(self.pauseCounter or self.pauseMessage)

    async def listen(self):
        while not self.ws.closed:
            msg = await self.ws.receive()
            if self.mode == self.BotType.training:
                continue
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            msg_list = list(filter(None, msg.data.split('\n')))
            if msg_list[0] == "CONNECTED":
                continue
            if msg_list[0] != "MESSAGE":
                self._log.info(f"未知的websocket訊息種類：\n{msg.data}")
                continue
            publisher = msg_list[2][len("publisher:"):]
            m = Message.loadjson(msg_list[3])
            if not m:
                self._log.warning(f"無法解析訊息：\n{msg.data}")
                continue
            if self.pauseListen:
                if self.pauseCounter:
                    self.pauseCounter = self.pauseCounter - 1
                    if self.pauseCounter == 0:
                        if self.firstmuda and self.mode == self.BotType.defender:
                            self.firstmuda = False
                            asyncio.get_event_loop().create_task(self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=redis.srandmember("kekeke::bot::cool")), showID=False))
                if m == self.pauseMessage:
                    self.pauseMessage = None
                    if self.firstmuda and self.mode == self.BotType.defender:
                        self.firstmuda = False
                        asyncio.get_event_loop().create_task(self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=redis.srandmember("kekeke::bot::cool")), showID=False))
                continue
            if m.user.nickname.endswith("#Bot") and m.content[:3] == "###":
                match = re.match(r"###DISABLE#BOT#RECORD#(\d+)###", m.content)
                if match:
                    self.pauseCounter = int(match.group(1))
                    continue
            if publisher == "CLIENT_TRANSPORT":
                asyncio.get_event_loop().create_task(self.receiveMessage(m))
            elif publisher == "SERVER":
                if m.mtype == Message.MessageType.population:
                    asyncio.get_event_loop().create_task(self.updateUsers())
                elif m.mtype == Message.MessageType.vote:
                    if m.payload["votingState"] == "CREATE":
                        if m.payload["title"] == "__i18n_voteForbidTitle":
                            asyncio.get_event_loop().create_task(self.vote(m.payload["votingId"], "__i18n_forbid"))
                        elif m.payload["title"] == "__i18n_voteBurnTitle":
                            asyncio.get_event_loop().create_task(self.vote(m.payload["votingId"], "__i18n_burn"))
                        elif m.payload["title"] == "__i18n_voteMinKermaTitle":
                            asyncio.get_event_loop().create_task(self.vote(m.payload["votingId"], "__i18n_agree"))
                    elif m.payload["votingState"] == "COMPLETE":
                        if m.payload["title"] == "__i18n_voteForbidTitle":
                            asyncio.get_event_loop().create_task(self.banCommit(m.payload["votingId"]))
                        elif m.payload["title"] == "__i18n_voteBurnTitle":
                            asyncio.get_event_loop().create_task(self.burnoutCommit(m.payload["votingId"]))
                elif m.mtype == Message.MessageType.system:
                    self._log.warn(f"天之聲發言：{msg_list[3]}")
                    await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=f'【天之聲】{m.payload["message"]}', metionUsers=list(self.users)), showID=False)
                elif m.mtype == Message.MessageType.euro:
                    await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=f'{m.payload["sucker"]["nickname"]} 吸了大家的歐氣', metionUsers=list(self.users)), showID=False)

        asyncio.get_event_loop().create_task(self.reConnect())

    async def post(self, payload, url: str = _square_url, header: dict = _header) -> typing.Dict[str, typing.Any]:
        for i in range(3):
            async with self._session.post(url=url, data=payload, headers=header) as r:
                if r.status != 200:
                    self._log.warning(f"<第{i+1}次post失敗> payload={str(payload)} url={url} header={str(header)}")
                    await asyncio.sleep(1)
                else:
                    text = await r.text()
                    if text[:4] == "//OK":
                        text = text[4:]
                    return json.loads(text)
        return None

    async def updateUsername(self):
        newname = self.user.nickname

        if self.mode == self.BotType.training:
            newname = newname + f"({self.kerma})"

        newname = newname + "".join(self.flags)

        if self.mode == self.BotType.defender:
            newname = ""

        await self.rename(self.user, newname)

    async def updateFlags(self, pull=False):
        if pull:
            self.flags = redis.smembers(f"{self.redisPerfix}flags")
        else:
            redis.delete(f"{self.redisPerfix}flags")
            redis.sadd(f"{self.redisPerfix}flags", self.flags)
        await self.updateUsername()

    async def updateUsers(self) -> typing.Set[User]:
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getCrowd"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])
        j = await self.post(payload=_payload.string)
        new_users = set()
        if j:
            j.reverse()
            keys = j[2]
            for i in range(5, len(j), 6):
                new_users.add(User(name=keys[j[i + 4] - 1], ID=keys[j[i + 3] - 1], color=keys[j[i + 2] - 1] if j[i + 2] > 0 else ""))
            joined = new_users - self.users
            self.users = new_users
            if flag.talk in self.flags:
                for user in joined:
                    if user.color and redis.hexists("kekeke::bot::users::discordid", user.ID):
                        discordid = redis.hget("kekeke::bot::users::discordid", user.ID)
                        redis.hset("discordbot::users::kekekecolor", discordid, user.color)

                    if user.ID in redis.sunion(self.redisPerfix + "ignores", self.redisGlobalPerfix + "ignores", self.redisPerfix + "members", self.redisPerfix + "auth", self.redisGlobalPerfix + "auth"):
                        continue
                    if not self.messages:
                        continue
                    basemessage = self.messages[-10] if len(self.messages) > 10 else self.messages[0]
                    if not ((user.ID in self.last_send_IDs and self.last_send_IDs[user.ID] >= basemessage.time) or (user.nickname in self.last_send_Nicknames and self.last_send_Nicknames[user.nickname] >= basemessage.time)):
                        if re.match(r"^(誰啊|unknown)#", user.nickname):
                            await self.sendMessage(Message(mtype=Message.MessageType.chat, user=user, content=f"<哈囉@{user.nickname}，本版目前管制中，請取個好名稱方便大家認識你喔>", metionUsers=[user]))
                            self.last_send_Nicknames[user.nickname] = self.last_send_IDs[user.ID] = tzlocal.get_localzone().localize(datetime.now())
            return joined

    def initMudaValue(self):
        self.mudacounter = 0
        self.mudaValue = 0
        self.mudausers: list = redis.smembers(self.redisGlobalPerfix + "silentUsers")
        for message in self.messages:  # type:Message
            if message.user.ID in self.mudausers:
                self.mudacounter = self.mudacounter + 1
                self.mudaValue = self.mudaValue + 1
            self.mudaValue = self.mudaValue + 0.2 * self.mudacounter

    async def setMessage(self, message_list: list):
        self.messages = message_list
        self.medias = dict()
        self.last_send_Nicknames = dict()
        self.last_send_IDs = dict()
        await self.updateMedia(self.messages)

    async def updateMedia(self, messages: list, pop=False):
        for message in messages:
            self.last_send_Nicknames[message.user.nickname] = self.last_send_IDs[message.user.ID] = message.time
            media = Media.loadMeaaage(message)
            if media:
                if media.remove and not pop:
                    try:
                        self.medias.pop(media)
                    except KeyError:
                        pass
                elif pop:
                    try:
                        self.medias[media] = self.medias[media] - 1
                        if self.medias[media] == 0:
                            self.medias.pop(media)
                    except KeyError:
                        pass
                else:
                    self.medias[media] = self.medias[media] + 1 if media in self.medias else 1

    def isForbiddenMessage(self, message: Message) -> bool:
        if message.user.ID in redis.sunion(f"{self.redisGlobalPerfix}auth", f"{self.redisPerfix}auth", f"{self.redisPerfix}members"):
            return False
        else:
            return bool(Media.loadMeaaage(message))

    def isVisibleMessage(self, message: Message):
        return message.mtype == Message.MessageType.chat or message.mtype == Message.MessageType.keke or message.mtype == Message.MessageType.deleteimage

    async def receiveMessage(self, message: Message):
        if not self.isVisibleMessage(message):
            return
        self.messages.append(message)
        await self.updateMedia([message])
        if len(self.messages) > 100:
            await self.updateMedia([self.messages[-101]], True)
        if len(self.messages) > 200:
            self.messages = self.messages[-150:]
        if not message.user.ID:
            return

        self.message_queue.put(message)

        if flag.muda in self.flags and message.mtype == Message.MessageType.chat:
            if not redis.sismember(f"{self.redisGlobalPerfix}silentUsers", message.user.ID) and self.isForbiddenMessage(message):
                await self.muda(Message(mtype=Message.MessageType.chat, user=self.user, metionUsers=[message.user]), message.user.nickname)

        if message.user.ID in self.mudausers:
            self.mudacounter = self.mudacounter + 1
            self.mudaValue = self.mudaValue + 1
        self.mudaValue = self.mudaValue + 0.2 * self.mudacounter

        for media in self.medias:
            if media.user.ID in self.mudausers:
                user = copy.deepcopy(self.user)
                user.ID = media.user.ID
                await self.sendMessage(Message(mtype=Message.MessageType.deleteimage, user=user, content=random.choice(["muda", "沒用", "無駄"]) + " " + media.url, metionUsers=[media.user]), showID=False)
                asyncio.get_event_loop().create_task(self.showLogo())

        if redis.scard(f"{self.redisGlobalPerfix}silentUsers") != len(self.mudausers):
            self.initMudaValue()

        if self.mudaValue >= 5:

            def isValid(m: Message) -> bool:
                return m.user.ID and m.user.ID not in self.mudausers

            self._log.info("偵測到已知洗版，自動清除")
            await self.resetMessages(isValid)

        if message.user != self.user:
            if re.search(r"^這是.{2,}攻擊$", message.content) and message.user.ID in redis.sunion(f"{self.redisGlobalPerfix}auth", f"{self.redisPerfix}auth", f"{self.redisPerfix}members"):
                await self.isSomethingAttack(message)
            for key in redis.smembers(f"{self.redisPerfix}reactionkeywords"):
                if re.search(key, message.content):
                    await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=redis.srandmember(f"{self.redisPerfix}reactionkeywords::{key}"), metionUsers=[message.user]), showID=False)
            if message.content[0:len(self.commendPrefix)] == self.commendPrefix:
                args = message.content[len(self.commendPrefix):].split()
                if args:
                    if args[0] in command.commands:
                        asyncio.get_event_loop().create_task(command.commands[args[0]](self, message, *(args[1:])))

    def getSomethingAttackText(self, text: str):
        t = f"{text}！"
        length = len(t)
        lines = math.ceil(len(t) / 7)
        result = ""
        for i in range(7):
            for j in reversed(range(lines)):
                pos = i + j * 7
                result += t[pos] if pos < length else "　"
            result += "\n"
        return result

    async def isSomethingAttack(self, message: Message):
        font = ImageFont.truetype(font=os.path.join(os.getcwd(), "kekeke/NotoSansCJKtc-Black.otf"), size=40)
        img = Image.open(os.path.join(os.getcwd(), 'kekeke/standattack.jpg'))
        d = ImageDraw.Draw(img)
        text = self.getSomethingAttackText(message.content)
        d.text((450, 30), text, fill=(0, 0, 0), font=font)
        filepath = os.path.join(os.getcwd(), f"data/{message.user.ID}.jpg")
        img.save(filepath)
        text = await self.postImage(filepath)
        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=message.user, content=f"{self.commendPrefix}{text['url']}"), showID=False)
        self._log.info(f"{message.user}->{message.content}")
        try:
            os.remove(filepath)
        except Exception as e:
            self._log.error("刪除檔案失敗")
            self._log.error(e, exc_info=True)

    async def sendMessage(self, message: Message, *, showID=True, escape=True):
        message_obj = {"senderPublicId": message.user.ID, "senderNickName": (f"{message.user.ID[:5]}#" if showID else "") + message.user.nickname, "anchorUsername": message.user.anchorUsername, "content": html.escape(message.content) if escape else message.content, "date": str(int(message.time.timestamp() * 1000)), "eventType": message.mtype.value, "payload": message.payload}
        if message.user.color:
            message_obj["senderColorToken"] = message.user.color
        message_obj["payload"]["replyPublicIds"] = []
        if message.metionUsers:
            for muser in message.metionUsers:
                message_obj["payload"]["replyPublicIds"].append(muser.ID)
        message_str = json.dumps(message_obj, ensure_ascii=False, separators=(', ', ':'))
        payload = f'SEND\ndestination:/topic/{self.name}\n_sig:{self.getMessageHash(message_str,self.waterID)}\n\n{message_str}'
        self.waterID = self.waterID + 1
        await self.ws.send_str(payload)

    def getMessageHash(self, messagejson: str, waterID: int):
        fullstr = f"{self.loginstr}{messagejson}/topic/{self.name}{waterID}"
        b64 = base64.b64encode(fullstr.encode('utf8'), altchars=b'-_')
        md5 = hashlib.md5(b64).hexdigest()
        return md5

    async def waitMessage(self) -> Message:
        while self.message_queue.qsize() < 1:
            if self.closed:
                return None
            await asyncio.sleep(0)
        return self.message_queue.get()

    async def toggleFlag(self, flag: str):
        if redis.sismember(f"{self.redisPerfix}flags", flag):
            redis.srem(f"{self.redisPerfix}flags", flag)
            self.flags.remove(flag)
        else:
            redis.sadd(f"{self.redisPerfix}flags", flag)
            self.flags.add(flag)
        await self.updateUsername()
        # await self.updateFlags(pull=True)

    async def say(self, content: str):
        message = Message(Message.MessageType.chat, content=content, user=self.user)
        await self.sendMessage(message, showID=False)

    async def anonSend(self, message: discord.Message):
        user = copy.deepcopy(self.user)
        kid = redis.hget("discordbot::users::kekekeid", message.author.id)
        if kid:
            user.nickname = message.author.display_name
            user.ID = kid
            kcolor = redis.hget("discordbot::users::kekekecolor", message.author.id)
            user.color = kcolor if kcolor else ""
        else:
            user.nickname = f"{message.author.display_name}#Bot"

        content = message.clean_content

        for attach in message.attachments:
            filepath = os.path.join(os.getcwd(), f"data/{attach.id}{attach.filename}")
            with open(filepath, 'wb') as f:
                await attach.save(f)
            content += (await self.postImage(filepath))["url"]
            os.remove(filepath)

        message = Message(Message.MessageType.chat, content=content, user=user, payload={"discordID": message.author.id})
        await self.sendMessage(message, showID=False)

    async def sendTextImage(self, text: str, user: User = None):
        font = ImageFont.truetype(font=os.path.join(os.getcwd(), "kekeke/NotoSansCJKtc-Regular.otf"), size=20)
        img = Image.new('RGB', (1, 1), (255, 255, 255))
        d = ImageDraw.Draw(img)
        w, h = d.multiline_textsize(text=text, font=font)
        img = img.resize((w + 20, h + 20))
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, fill=(0, 0, 0), font=font)
        filepath = os.path.join(os.getcwd(), "data/image.jpg")
        img.save(filepath)
        text = await self.postImage(filepath)
        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=user if user else self.user, content=text["url"]), showID=False)
        try:
            os.remove(filepath)
        except Exception as e:
            self._log.error("刪除檔案失敗")
            self._log.error(e, exc_info=True)

    async def postImage(self, filepath: str):
        with open(filepath, 'rb') as f:
            async with self._session.post(url="https://kekeke.cc/com.liquable.hiroba.springweb/storage/upload-media", data={'file': f}) as r:
                return json.loads(await r.text())

    async def convertToThumbnail(self, url: str) -> object:
        thumb = await self.postJson({"url": url}, url="https://kekeke.cc/com.liquable.hiroba.springweb/storage/store-thumbnail")
        for k, v in thumb.items():
            redis.hset(f"{self.redisGlobalPerfix}logothumbnailurl", k, v)
        redis.expire(f"{self.redisGlobalPerfix}logothumbnailurl", 518400)
        return thumb

    async def updateThumbnail(self, url: str):
        thumb = redis.hgetall(f"{self.redisGlobalPerfix}logothumbnailurl")
        if not thumb:
            thumb = await self.convertToThumbnail(url)
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "updateSquareThumb"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])
        _payload.AddPara("com.liquable.hiroba.gwt.client.square.SquareThumb/3372091550", [int(thumb["height"]), thumb["url"], int(thumb["width"])])
        await self.post(payload=_payload.string)

    async def showLogo(self):
        url = redis.get(f"{self.redisGlobalPerfix}logourl")
        if not url:
            logopath = os.path.join(os.getcwd(), "green.png")
            image = await self.postImage(logopath)
            url = image["url"]
            redis.set(f"{self.redisGlobalPerfix}logourl", url, ex=518400)
        await self.updateThumbnail(url)

    async def postJson(self, json_, url: str = _square_url, header: dict = {"content-type": "application/json"}) -> typing.Dict[str, typing.Any]:
        for i in range(3):
            async with self._session.post(url=url, json=json_, headers=header) as r:
                if r.status != 200:
                    self._log.warning(f"<第{i+1}次post失敗> payload={str(json_)} url={url} header={str(header)}")
                    await asyncio.sleep(1)
                else:
                    text = await r.text()
                    if text[:4] == "//OK":
                        text = text[4:]
                    return json.loads(text)
        return None

    async def rename(self, user: User, newname: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "updateNickname"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", user.color if user.color != "" else None, user.ID, newname, user.ID])
        await self.post(payload=_payload.string)

    def getUserLevel(self, user: User) -> str:
        if re.search("#Bot", user.nickname):
            return "bot"
        if redis.sismember(f"{self.redisGlobalPerfix}auth", user.ID):
            return "gauth"
        if redis.sismember(f"{self.redisPerfix}auth", user.ID):
            return "auth"
        if redis.sismember(f"{self.redisPerfix}members", user.ID):
            return "member"
        if redis.sismember(f"{self.redisGlobalPerfix}silentUsers", user.ID):
            return "silent"
        return "unknown"


# ###########################################commands#######################################

    @command.command(safe=True, help=".help\n顯示這個訊息")
    async def help(self, message: Message, *args):
        texts = []
        for com in command.commands:
            if com == "bind" or com == "muda" or com == "automuda" or com == "protect":
                continue
            dangertext = "是" if not command.commands[com].safe else "否"
            authonlytext = "是" if command.commands[com].authonly else "否"
            texts.append(f"{command.commands[com].help}\n危險：{dangertext}\n認證成員限定：{authonlytext}\n")
        await self.sendTextImage("\n".join(texts), message.user)

    @command.command(safe=True, help=".status\n顯示目前在線上的成員列表")
    async def status(self, message: Message, *args):
        texts = []
        gauth = redis.smembers(self.redisGlobalPerfix + "auth")
        auths = redis.smembers(self.redisPerfix + "auth")
        members = redis.smembers(self.redisPerfix + "members")
        authtext = []
        membertext = []
        unknowntext = []
        for user in self.users:
            if re.search("#Bot", user.nickname):
                continue
            if user.ID in gauth or user.ID in auths:
                authtext.append(f"({user.ID[:5]}){user.nickname}")
            elif user.ID in members:
                membertext.append(f"({user.ID[:5]}){user.nickname}")
            else:
                unknowntext.append(f"({user.ID[:5]}){user.nickname}")
        if authtext:
            texts.append("認證成員：")
            texts.extend(authtext)
        if membertext:
            texts.append("一般成員：")
            texts.extend(membertext)
        if unknowntext:
            texts.append("未知使用者：")
            texts.extend(unknowntext)
        await self.sendTextImage("\n".join(texts), message.user)

    @command.command(safe=True, help=".whois <使用者>\n分辨對象的身分類型")
    async def whois(self, message: Message, *args):
        if (len(message.metionUsers) == 1):
            level = self.getUserLevel(message.metionUsers[0])
            result = f"({message.metionUsers[0].ID[:5]}){message.metionUsers[0].nickname}是"
            if level == "bot":
                result += "機器人"
            elif level == "gauth" or level == "auth":
                result += "認證成員"
            elif level == "member":
                result += "一般成員"
            elif level == "silent":
                result += "洗版仔"
            else:
                result += "未知使用者"
            await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=result, metionUsers=[message.metionUsers[0], message.user]), showID=False)

    @command.command(safe=True, help=".stop\n強制終止未執行的危險指令")
    async def stop(self, message: Message, *args):
        for command in self.pandingCommands:
            command.cancel()
        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=f"✔️強制終止了{len(self.pandingCommands)}條未執行的指令", metionUsers=[message.user]), showID=False)
        self.pandingCommands = []

    @command.command(safe=True, help=".remove <使用者> <檔案>\n移除特定使用者所發出的檔案\n如果不指定檔名，則移除所有該使用者發出的所有檔案")
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
            user = copy.deepcopy(self.user)
            user.ID = media.user.ID
            await self.sendMessage(Message(mtype=Message.MessageType.deleteimage, user=user, content=f"delete {media.url}"), showID=False)

    @command.command(safe=True, alias="rename", help=".rename <新名稱>\n修改自己的使用者名稱，只在使用者列表有效")
    async def command_rename(self, message: Message, *args):
        await self.rename(message.user, args[0])

    @command.command(safe=True, help=".member (add/remove) <使用者>\n將特定使用者從本頻道一般成員新增/移除，成為成員後才可使用指令\n一般成員不可修改認證成員身分\n若不指定add/remove則自動判斷")
    async def member(self, message: Message, *args):
        ismember = redis.sismember(f"{self.redisPerfix}members", message.metionUsers[0].ID)
        result = ""
        usertext = str(message.metionUsers[0])
        if ismember:
            if len(args) == 1 or (len(args) == 2 and args[0] == "remove"):
                redis.srem(f"{self.redisPerfix}members", message.metionUsers[0].ID)
                result = f"✔️成功將{usertext}從一般成員移除"
        else:
            if len(args) == 1 or (len(args) == 2 and args[0] == "add"):
                if redis.sismember(f"{self.redisPerfix}auth", message.metionUsers[0].ID):
                    if redis.sismember(f"{self.redisPerfix}auth", message.user.ID):
                        redis.srem(f"{self.redisPerfix}auth", message.metionUsers[0].ID)
                        redis.sadd(f"{self.redisPerfix}members", message.metionUsers[0].ID)
                        result = f"✔️成功將{usertext}從認證成員變為一般成員"
                    else:
                        result = f"❌不能將{usertext}從認證成員變為一般成員，對方擁有較高的權限"
                else:
                    redis.sadd(self.redisPerfix + "members", message.metionUsers[0].ID)
                    result = f"✔️成功將{usertext}變為一般成員"

        if not result:
            result = f"❌操作錯誤，{usertext}維持原身分"

        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=result, metionUsers=[message.metionUsers[0], message.user]), showID=False)

    @command.command(safe=True, help='.cls\n消除所有以"."作為開頭的訊息以及機器人的訊息')
    async def cls(self, message: Message, *args):
        def isValid(m: Message) -> bool:
            return m.user.ID != self.user.ID and m.content[0:len(self.commendPrefix)] != self.commendPrefix

        await self.resetMessages(isValid)

    @command.command(safe=True, help='.cina\n刪掉訂閱哥的訊息')
    async def cina(self, message: Message, *args):
        forbidden_list = redis.sunion("kekeke::bot::detector::youtube::video", "kekeke::bot::detector::youtube::channel", "kekeke::bot::detector::youtube::playlist")
        forbidden_IDs = set()
        for message in self.messages:
            for keyword in forbidden_list:
                if keyword in message.content:
                    forbidden_IDs.add(message.user.ID)

        def isValid(m: Message) -> bool:
            return m.user.ID not in forbidden_IDs

        await self.resetMessages(isValid)

    @command.command(help=".ban <使用者>\n發起封鎖特定使用者投票")
    async def ban(self, message: Message, *args):
        target: User = message.metionUsers[0]
        if target.ID in redis.sunion(f"{self.redisGlobalPerfix}auth", f"{self.redisPerfix}auth", f"{self.redisPerfix}members"):
            await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=f"❌使用者{target}具有成員以上身分，無法執行", metionUsers=[message.user]), showID=False)
            return
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "createVotingForForbid"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", None, self.user.ID, self.user.nickname, self.user.ID])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", target.color if target.color else None, target.ID, target.nickname, target.ID])
        _payload.AddPara("java.lang.String/2004016611", [f"【由{message.user.nickname}發起，本投票通過時自動封鎖】"], regonly=True)
        await self.post(payload=_payload.string, url=self._vote_url)

    @command.command(help='.burn <使用者>\n發起燒毀特定使用者10 KERMA的投票')
    async def burn(self, message: Message, *args):
        if len(message.metionUsers) > 0:
            target: User = message.metionUsers[0]
            if target.ID in redis.sunion(f"{self.redisGlobalPerfix}auth", f"{self.redisPerfix}auth", f"{self.redisPerfix}members"):
                await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=f"❌使用者{target}具有成員以上身分，無法執行", metionUsers=[message.user]), showID=False)
                return
            _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "createVotingForBurn"])
            _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])
            _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", None, self.user.ID, self.user.nickname, self.user.ID])
            _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", target.color if target.color else None, target.ID, target.nickname, target.ID])
            _payload.AddPara("java.lang.String/2004016611", [f"【由{message.user.nickname}發起，本投票通過時自動燒毀KERMA】"], regonly=True)
            await self.post(payload=_payload.string, url=self._vote_url)

    @command.command(safe=True, help=".autotalk\n啟用/停用自動發送訊息功能")
    async def autotalk(self, message: Message, *args):
        await self.toggleFlag(flag.talk)

    @command.command(help=".bind <DiscordID>\n指定一個Discord帳號與目前帳號綁定，用於Discord發話")
    async def bind(self, message: Message, *args):
        if len(args) >= 1:
            try:
                kid = int(args[0])
                redis.hset("kekeke::bot::users::discordid", message.user.ID, str(kid))
                redis.hset("discordbot::users::kekekeid", str(kid), message.user.ID)
                if message.user.color:
                    redis.hset("discordbot::users::kekekecolor", str(kid), message.user.color)
                await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content="✔️已綁定到Discord", metionUsers=[message.user]), showID=False)
            except ValueError:
                await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content="❌參數錯誤", metionUsers=[message.user]), showID=False)

    @command.command(authonly=True, help=".auth (add/remove) <使用者>\n將特定使用者從本頻道認證成員新增/移除，成為成員後可使用所有指令\n若不指定add/remove則自動判斷")
    async def auth(self, message: Message, *args):
        isauth = redis.sismember(self.redisPerfix + "auth", message.metionUsers[0].ID)
        result = ""
        usertext = str(message.metionUsers[0])
        if isauth:
            if len(args) == 1 or (len(args) == 2 and args[0] == "remove"):
                redis.srem(self.redisPerfix + "auth", message.metionUsers[0].ID)
                result = f"✔️成功將{usertext}從認證成員移除"
        else:
            if len(args) == 1 or (len(args) == 2 and args[0] == "add"):
                redis.sadd(self.redisPerfix + "auth", message.metionUsers[0].ID)
                if redis.sismember(self.redisPerfix + "members", message.metionUsers[0].ID):
                    redis.srem(self.redisPerfix + "members", message.metionUsers[0].ID)
                    result = f"✔️成功將{usertext}從一般成員變為認證成員"
                else:
                    result = f"✔️成功將{usertext}變為認證成員"
        if not result:
            result = f"❌操作錯誤，{usertext}維持原身分"

        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=result, metionUsers=[message.metionUsers[0], message.user]), showID=False)

    @command.command(authonly=True, help=".clear <目前頻道名稱> X\n【危險】送出X條空白訊息\nX最多為100")
    async def clear(self, message: Message, *args):
        if len(args) >= 2 and args[0] == self.name:
            times = clip(int(args[1], 0), 0, 100)
            for _ in range(times):
                await self.sendMessage(Message(), showID=False)
            self._log.info(f"發送{times}則空白訊息")

    @command.command(authonly=True, help=".muda <使用者>\n【危險】該使用者全站禁止發送任何訊息\n注：只能對洗版仔使用，嚴禁亂玩")
    async def muda(self, message: Message, *args):
        if len(args) >= 1 and self.mode == self.BotType.defender:
            for user in message.metionUsers:  # type: User
                if user.ID in redis.sunion(f"{self.redisGlobalPerfix}auth", f"{self.redisPerfix}auth", f"{self.redisPerfix}members"):
                    await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=f"❌使用者{user}具有成員以上身分，無法執行", metionUsers=[message.user]), showID=False)
                elif redis.sismember(f"{self.redisGlobalPerfix}silentUsers", user.ID):
                    redis.srem(f"{self.redisGlobalPerfix}silentUsers", user.ID)
                    await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=f"✔️將使用者{user}移出靜音成員", metionUsers=[user, message.user]), showID=False)
                else:
                    redis.sadd(f"{self.redisGlobalPerfix}silentUsers", user.ID)
                    await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=f"✔️{user}洗版狗可以滾了", metionUsers=[user, message.user]), showID=False)

    @command.command(authonly=True, help='.automuda\n啟用/停用當非已知使用者發送圖片或影片時，自動進行"muda"指令')
    async def automuda(self, message: Message, *args):
        if self.mode == self.BotType.defender:
            await self.toggleFlag(flag.muda)

    @command.command(authonly=True, help='.clearup <人名>\n消除所有該使用者的訊息')
    async def clearup(self, message: Message, *args):
        if len(message.metionUsers) >= 1:

            def isValid(m: Message) -> bool:
                return m.user not in message.metionUsers

            await self.resetMessages(isValid)

    @command.command(authonly=True, help='.protect\n將在場有發言的人加為成員並開啟automuda')
    async def protect(self, message: Message, *args):
        if self.mode == self.BotType.defender:
            for m in self.messages:
                if self.getUserLevel(m.user) == "unknown":
                    redis.sadd(f"{self.redisPerfix}members", m.user.ID)
            self.flags.add(flag.muda)

    @command.command(authonly=True, help='.zawarudo <目前頻道名稱>\n【危險】消除所有非成員的訊息')
    async def zawarudo(self, message: Message, *args):
        if len(args) >= 1 and args[0] == self.name:
            vaildusers: typing.Set[User] = redis.sunion(self.redisPerfix + "members", self.redisPerfix + "auth", self.redisGlobalPerfix + "auth")

            def isValid(m: Message) -> bool:
                return m.user.ID in vaildusers and m.content[0:len(self.commendPrefix)] != self.commendPrefix

            await self.resetMessages(isValid)

    @command.command(safe=True, help='.save\n製作出當前對話訊息存檔')
    async def save(self, message: Message, *args):
        messageslist = []
        for m in self.messages:  # type: Message
            message_obj = {"senderPublicId": m.user.ID, "senderNickName": m.user.nickname, "anchorUsername": "", "content": html.escape(m.content), "date": str(int(m.time.timestamp() * 1000)), "eventType": m.mtype.value, "payload": m.payload}
            if m.user.color:
                message_obj["senderColorToken"] = m.user.color
            message_obj["payload"]["replyPublicIds"] = []
            if m.metionUsers:
                for muser in m.metionUsers:
                    message_obj["payload"]["replyPublicIds"].append(muser.ID)
            messageslist.append(message_obj)

        name_safe = html.escape(self.name)
        chatjsonpath = os.path.join(os.getcwd(), f"data/{name_safe}-chat.json")
        imagepath = os.path.join(os.getcwd(), f"data/{name_safe}-green.png")
        copyfile(os.path.join(os.getcwd(), "green.png"), imagepath)

        with open(chatjsonpath, 'w') as f:
            f.write(json.dumps(messageslist, ensure_ascii=False))
        with ZipFile(imagepath, mode='a') as z:
            z.write(chatjsonpath, "chat.json")

        text = await self.postImage(imagepath)
        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=message.user, content=text["url"]), showID=False)

        try:
            os.remove(imagepath)
        except Exception as e:
            self._log.error(f"刪除檔案{imagepath}失敗")
            self._log.error(e, exc_info=True)
        try:
            os.remove(chatjsonpath)
        except Exception as e:
            self._log.error(f"刪除檔案{chatjsonpath}失敗")
            self._log.error(e, exc_info=True)

    @command.command(alias="load", authonly=True, help='.load <目前頻道名稱> <訊息存檔位置>\n【危險】以存檔來重置所有訊息')
    async def command_load(self, message: Message, *args):
        if args[0] != self.name or len(args) < 2:
            return
        name_safe = html.escape(self.name)
        imagepath = os.path.join(os.getcwd(), f"data/{name_safe}-green-load.png")
        async with self._session.get(args[1]) as resp:
            if resp.status != 200:
                return
            async with aiofiles.open(imagepath, mode='wb') as f:
                await f.write(await resp.read())
        with ZipFile(imagepath) as z:
            with z.open("chat.json") as c:
                j = json.loads(c.read().decode("utf-8"))
                self.messages = [Message.loadjson(json.dumps(m)) for m in j]
                await self.resetMessages(lambda m: True)
        try:
            os.remove(imagepath)
        except Exception as e:
            self._log.error(f"刪除檔案{imagepath}失敗")
            self._log.error(e, exc_info=True)

    @command.command(safe=True, help='.pluscheck\n用一種不科學的方法檢查有幾個人裝kekeke plus')
    async def pluscheck(self, message: Message, *args):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "createVotingForNormal"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])
        _payload.AddPara("com.liquable.hiroba.gwt.client.vote.NormalConfig/2691735772", ["com.liquable.hiroba.gwt.client.vote.NormalConfig$DurationConfig/1199471335", 0, "com.liquable.hiroba.gwt.client.vote.MultipleChoiceConfig/1007198302", 0])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", None, self.user.ID, self.user.nickname, self.user.ID])
        _payload.AddPara("java.lang.String/2004016611", ["你有裝kekeke plus嗎？"], regonly=True)
        _payload.AddPara("java.util.List", ["java.util.ArrayList/4159755760", 3, "java.lang.String/2004016611", "我是智障", "java.lang.String/2004016611", "沒有", "java.lang.String/2004016611", "有"], regonly=True)
        await self.post(payload=_payload.string, url=self._vote_url)

    async def resetMessages(self, vaildRule):
        while self.pauseListen:
            await asyncio.sleep(0)
        validmessages = list(filter(vaildRule, self.messages))
        if len(validmessages) >= 1:
            oldest = validmessages[0]
            self.pauseMessage = validmessages[-1]
            if len(validmessages) < 100:
                validmessages = list(Message(time=oldest.time) for _ in range(100 - len(validmessages))) + validmessages
            await self.setMessage(validmessages)
        else:
            validmessages = list(Message() for _ in range(100))

        validmessages = validmessages[-100:]
        medias = self.medias.copy()
        mudatext = random.choice(["muda", "沒用", "無駄"])
        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=f"###DISABLE#BOT#RECORD#{len(validmessages)+len(medias)}###"), showID=False)
        for media in medias:
            user = copy.deepcopy(self.user)
            user.ID = media.user.ID
            await self.sendMessage(Message(mtype=Message.MessageType.deleteimage, user=user, content=f"{mudatext} {media.url}"), showID=False)

        for m in validmessages:
            await self.sendMessage(m, showID=False)

        self.initMudaValue()

        if self.timeout:
            self.timeout.cancel()
            try:
                await self.timeout
            except asyncio.CancelledError:
                pass
            self.timeout = asyncio.get_event_loop().create_task(self.SelfTimeout())

    async def vote(self, voteid: str, voteoption: str = "__i18n_forbid"):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "voteByPermission"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])
        _payload.AddPara("java.lang.String/2004016611", [voteid], regonly=True)
        _payload.AddPara("java.util.Set", ["java.util.HashSet/3273092938", "https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "java.lang.String/2004016611", voteoption], regonly=True)
        await self.post(payload=_payload.string, url=self._vote_url)

    async def banCommit(self, voteid: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "applyForbidByVoting"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])
        _payload.AddPara("java.lang.String/2004016611", [voteid], regonly=True)
        _payload.AddPara("com.liquable.hiroba.gwt.client.vote.ForbidOption/647536008", [0], rawpara=True)
        await self.post(payload=_payload.string, url=self._vote_url)

    async def burnoutCommit(self, voteid: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "applyBurnByVoting"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", [f"/topic/{self.name}"])
        _payload.AddPara("java.lang.String/2004016611", [voteid], regonly=True)
        for _ in range(10):
            await self.post(payload=_payload.string, url=self._vote_url)


def clip(num: int, a: int, b: int) -> int:
    return min(max(num, a), b)
