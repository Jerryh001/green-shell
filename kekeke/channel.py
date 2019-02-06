import asyncio
import copy
import functools
import html
import inspect
import json
import logging
import os
import random
import re
import time
import typing
from datetime import datetime

from queue import Queue

import aiohttp
import discord
import redis
import tzlocal
from PIL import Image, ImageDraw, ImageFont

from kekeke import command, flag, red

from .GWTpayload import GWTPayload
from .jsonfile import JsonFile
from .message import *
from .user import User


class Channel:
    from enum import Enum

    class BotType(Enum):
        training = 0
        observer = 1
        defender = 2

    _notwelcomes = JsonFile(os.path.join(os.getcwd(), "data/keyword.json"))
    _square_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _vote_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/voteService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    commendPrefix = os.getenv("DISCORD_PREFIX")

    redisGlobalPerfix = "kekeke::bot::global::"

    def __init__(self, name: str, mode: BotType = BotType.observer):
        self.mode = mode
        self.name = name
        self.user = User(("小小綠盾" if self.mode == self.BotType.training else "綠盾防禦系統")+"#Bot")
        self._log = logging.getLogger((__name__+"@"+self.name))
        self.session: aiohttp.ClientSession = None
        self.ws: aiohttp.ClientWebSocketResponse = None
        self.messages = list()
        self.message_queue = Queue()
        self.users = set()
        self.flags = set()
        self.medias = dict()
        self.last_send_IDs = dict()
        self.last_send_Nicknames = dict()
        self.redisPerfix = "kekeke::bot::channel::"+self.name+"::"
        self.redis = redis.StrictRedis(connection_pool=red.pool())
        self.connectEvents = None
        self.pauseListen = False
        self.pauseMessage = Message()
        self.closed = False
        self.GUID = self.getGUID()
        self.kerma = 0

    async def initial(self):
        if self.mode == self.BotType.training:
            self._log = logging.getLogger((__name__+"#????????"))
        while True:
            try:
                self._session: aiohttp.ClientSession = await aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)).__aenter__()
                self.ws: aiohttp.ClientWebSocketResponse = await self._session.ws_connect(url=r"wss://ws.kekeke.cc/com.liquable.hiroba.websocket", heartbeat=120).__aenter__()
                break
            except Exception as e:
                self._log.error("對伺服器建立連線失敗，5秒後重試")
                self._log.error(e, exc_info=True)
                self.Close(stop=False)
                await asyncio.wait(5)
        await self.subscribe()
        if self.mode == self.BotType.training:
            self._log = logging.getLogger((__name__+"#"+self.GUID[:8]))
        if self.mode != self.BotType.training:
            await self.updateFlags(True)
            await self.initMessages(self.name)
            await self.updateUsers()
            asyncio.get_event_loop().create_task(self.showLogo())

        self.connectEvents = asyncio.get_event_loop().create_task(asyncio.wait({self.listen(), self.keepAlive()}))

    async def Close(self, stop=True):
        if stop:
            self.closed = True
            self.redis.smove("kekeke::bot::training::GUIDs::using", "kekeke::bot::training::GUIDs", self.GUID)
        if self.connectEvents and not self.connectEvents.done():
            self.connectEvents.cancel()
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
                self.redis.smove("kekeke::bot::training::GUIDs::using", "kekeke::bot::GUIDpool", self.GUID)
                self._log.info("GUID:"+self.GUID+"的KERMA已達80，尋找新GUID並重新連線")
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
                self._log.info("kerma減少了:"+str(self.kerma)+"->"+str(kerma))
            self.kerma = kerma
            if self.mode != self.BotType.observer:
                await self.updateUsername()

    def getGUID(self) -> str or None:
        if self.mode == self.BotType.training:
            while True:
                guid = self.redis.srandmember("kekeke::bot::training::GUIDs")
                if not guid:
                    return None
                if self.redis.smove("kekeke::bot::training::GUIDs", "kekeke::bot::training::GUIDs::using", guid):
                    return guid
        elif self.mode == self.BotType.defender:
            while True:
                guid = self.redis.srandmember("kekeke::bot::GUIDpool")
                if not guid:
                    return None
                if self.redis.smove("kekeke::bot::GUIDpool", "kekeke::bot::GUIDpool::using", guid):
                    return guid
        else:
            return self.redis.get(self.redisPerfix+"botGUID")

    async def subscribe(self):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "startSquare"])
        _payload.AddPara("com.liquable.hiroba.gwt.client.square.StartSquareRequest/2186526774", [self.GUID if self.GUID else None, None, "com.liquable.gwt.transport.client.Destination/2061503238", "/topic/{0}".format(self.name)])
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
                self.redis.sadd("kekeke::bot::training::GUIDs::using", self.GUID)
            else:
                if self.mode == self.BotType.defender:
                    self._log.error("沒有足夠Kerma的GUID可用，隨便創建一個")
                self.redis.set(self.redisPerfix+"botGUID", self.GUID)
        self.user.ID = data[-1]
        await self.ws.send_str('CONNECT\nlogin:'+json.dumps({"accessToken": data[2], "nickname": self.user.nickname}))
        await self.ws.send_str('SUBSCRIBE\ndestination:/topic/{0}'.format(self.name))
        self._log.info("subscribe "+self.name)

    async def initMessages(self, channel: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getLeftMessages"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])

        data = await self.post(payload=_payload.string)
        if data:
            data = list(x for x in data[-3] if x[0] == '{')
            messages: list = Message.loadjsonlist(data)
            if messages:
                await self.setMessage(messages)
            self._log.info("更新歷史訊息成功")
        else:
            self._log.warning("更新歷史訊息失敗")

    async def listen(self):
        while not self.ws.closed:
            msg = await self.ws.receive()
            if self.mode == self.BotType.training:
                continue
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            self._log.debug(msg.data)
            msg_list = list(filter(None, msg.data.split('\n')))
            if msg_list[0] != "MESSAGE":
                self._log.info("ignored WS message type:\n"+msg.data)
                continue
            publisher = msg_list[2][len("publisher:"):]
            m = Message.loadjson(msg_list[3])
            if not m:
                self._log.warning("can't decode message:\n"+msg.data)
                continue
            if self.pauseListen:
                if m == self.pauseMessage:
                    self.pauseListen = False
                continue
            if publisher == "CLIENT_TRANSPORT":
                if m.user.ID:
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
                    elif m.payload["votingState"] == "COMPLETE":
                        if m.payload["title"] == "__i18n_voteForbidTitle":
                            asyncio.get_event_loop().create_task(self.banCommit(m.payload["votingId"]))
                        elif m.payload["title"] == "__i18n_voteBurnTitle":
                            asyncio.get_event_loop().create_task(self.burnoutCommit(m.payload["votingId"]))

        asyncio.get_event_loop().create_task(self.reConnect())

    async def post(self, payload, url: str = _square_url, header: dict = _header) -> typing.Dict[str, typing.Any]:
        for i in range(3):
            async with self._session.post(url=url, data=payload, headers=header) as r:
                if r.status != 200:
                    self._log.warning("<第"+str(i+1)+"次post失敗> payload="+str(payload)+" url="+url+" header="+str(header))
                    await asyncio.sleep(1)
                else:
                    text = await r.text()
                    if text[:4] == "//OK":
                        text = text[4:]
                    return json.loads(text)
        return None

    async def updateUsername(self):
        newname = self.user.nickname
        if self.mode != self.BotType.observer:
            newname += "({0})".format(self.kerma)
        newname += "".join(self.flags)
        await self.rename(self.user, newname)

    async def updateFlags(self, pull=False):
        if pull:
            self.flags = self.redis.smembers(self.redisPerfix+"flags")
        else:
            self.redis.delete(self.redisPerfix+"flags")
            self.redis.sadd(self.redisPerfix+"flags", self.flags)
        await self.updateUsername()

    async def updateUsers(self) -> typing.Set[User]:
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getCrowd"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        j = await self.post(payload=_payload.string)
        new_users = set()
        if j:
            j.reverse()
            keys = j[2]
            for i in range(5, len(j), 6):
                new_users.add(User(
                    name=keys[j[i+4]-1], ID=keys[j[i+3]-1], color=keys[j[i+2]-1] if j[i+2] > 0 else ""))
            joined = new_users-self.users
            self.users = new_users
            if flag.talk in self.flags:
                for user in joined:
                    if user.color and self.redis.hexists("kekeke::bot::users::discordid", user.ID):
                        discordid = self.redis.hget("kekeke::bot::users::discordid", user.ID)
                        self.redis.hset("discordbot::users::kekekecolor", discordid, user.color)

                    if user.ID in self.redis.sunion(self.redisPerfix+"ignores", self.redisGlobalPerfix+"ignores", self.redisPerfix+"members", self.redisPerfix+"auth", self.redisGlobalPerfix+"auth"):
                        continue
                    if not self.messages:
                        continue
                    basemessage = self.messages[-10] if len(self.messages) > 10 else self.messages[0]
                    if not ((user.ID in self.last_send_IDs and self.last_send_IDs[user.ID] >= basemessage.time) or (user.nickname in self.last_send_Nicknames and self.last_send_Nicknames[user.nickname] >= basemessage.time)):
                        if self.isNotWelcome(user):
                            await self.sendMessage(Message(mtype=Message.MessageType.chat, user=user, content="<GS出現了，小心，這是替身攻擊！>", metionUsers=list(self.users)))
                            self.last_send_Nicknames[user.nickname] = self.last_send_IDs[user.ID] = tzlocal.get_localzone().localize(datetime.now())
                        elif re.match(r"(誰啊|unknown)", user.nickname):
                            await self.sendMessage(Message(mtype=Message.MessageType.chat, user=user, content="<哈囉@"+user.nickname+"，本版目前管制中，請取個好名稱方便大家認識你喔>", metionUsers=[user]))
                            self.last_send_Nicknames[user.nickname] = self.last_send_IDs[user.ID] = tzlocal.get_localzone().localize(datetime.now())

            return joined

    def isNotWelcome(self, user: User) -> bool:
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
                        self.medias[media] = self.medias[media]-1
                        if self.medias[media] == 0:
                            self.medias.pop(media)
                    except KeyError:
                        pass
                else:
                    self.medias[media] = self.medias[media]+1 if media in self.medias else 1

    def isForbiddenMessage(self, message: Message) -> bool:
        if self.redis.sismember(self.redisPerfix+"auth", message.user.ID) or self.redis.sismember(self.redisGlobalPerfix+"auth", message.user.ID):
            return False
        else:
            for keyword in self.redis.smembers(self.redisGlobalPerfix+"keyword"):
                if re.search(keyword, message.content, re.IGNORECASE) or re.search(keyword, message.user.nickname, re.IGNORECASE):
                    return True
            return False

    async def receiveMessage(self, message: Message):
        self.messages.append(message)
        self.message_queue.put(message)
        await self.updateMedia([message])
        if len(self.messages) > 100:
            await self.updateMedia(self.messages[:-100], True)
            self.messages = self.messages[-100:]

        if self.redis.sismember(self.redisPerfix+"flags", flag.muda) and message.mtype == Message.MessageType.chat:
            if not self.redis.sismember(self.redisGlobalPerfix+"silentUsers", message.user.ID) and self.isForbiddenMessage(message):
                await self.muda(Message(mtype=Message.MessageType.chat, user=self.user, metionUsers=[message.user]), message.user.nickname)
        for media in self.medias:
            if self.redis.sismember(self.redisGlobalPerfix+"silentUsers", media.user.ID):
                user = copy.deepcopy(media.user)
                user.nickname = self.user.nickname
                await self.sendMessage(Message(mtype=Message.MessageType.deleteimage, user=user, content=random.choice(["muda", "沒用", "無駄"])+" "+media.url, metionUsers=[message.user]), showID=False)

        if message.user != self.user:
            for key in self.redis.smembers(self.redisPerfix+"reactionkeywords"):
                if re.search(key, message.content):
                    await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=self.redis.srandmember(self.redisPerfix+"reactionkeywords::"+key), metionUsers=[message.user]), showID=False)
            if message.content[0:len(self.commendPrefix)] == self.commendPrefix:
                args = message.content[len(self.commendPrefix):].split()
                if(args[0] in command.commands):
                    asyncio.get_event_loop().create_task(command.commands[args[0]](self, message, *(args[1:])))
                else:
                    self._log.warning("命令"+args[0]+"不存在")

    async def sendMessage(self, message: Message, *, showID=True, escape=True):
        message_obj = {
            "senderPublicId": message.user.ID,
            "senderNickName": (message.user.ID[:5]+"#" if showID else "")+message.user.nickname,
            "anchorUsername": "",
            "content": html.escape(message.content) if escape else message.content,
            "date":  str(int(message.time.timestamp()*1000)),
            "eventType": message.mtype.value,
            "payload": message.payload
        }
        if message.user.color:
            message_obj["senderColorToken"] = message.user.color
        message_obj["payload"]["replyPublicIds"] = []
        if message.metionUsers:
            for muser in message.metionUsers:
                message_obj["payload"]["replyPublicIds"].append(muser.ID)
        payload = 'SEND\ndestination:/topic/{0}\n\n'.format(self.name)+json.dumps(message_obj, ensure_ascii=False)
        await self.ws.send_str(payload)

    async def waitMessage(self) -> Message:
        while self.message_queue.qsize() < 1:
            await asyncio.sleep(0)
        return self.message_queue.get()

    async def toggleFlag(self, flag: str):
        if self.redis.sismember(self.redisPerfix+"flags", flag):
            self.redis.srem(self.redisPerfix+"flags", flag)
        else:
            self.redis.sadd(self.redisPerfix+"flags", flag)
        await self.updateFlags(pull=True)

    async def anonSend(self, message: discord.Message):
        user = copy.deepcopy(self.user)
        kid = self.redis.hget("discordbot::users::kekekeid", message.author.id)
        if kid:
            user.nickname = message.author.display_name
            user.ID = kid
            kcolor = self.redis.hget("discordbot::users::kekekecolor", message.author.id)
            user.color = kcolor if kcolor else ""
        else:
            user.nickname = message.author.display_name+"#Bot"

        content = message.clean_content

        for attach in message.attachments:
            filepath = os.path.join(os.getcwd(), "data/"+str(attach.id)+attach.filename)
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
        img = img.resize((w+20, h+20))
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
            self.redis.hset(self.redisGlobalPerfix+"logothumbnailurl", k, v)
        self.redis.expire(self.redisGlobalPerfix+"logothumbnailurl", 518400)
        return thumb

    async def updateThumbnail(self, url: str):
        thumb = self.redis.hgetall(self.redisGlobalPerfix+"logothumbnailurl")
        if not thumb:
            thumb = await self.convertToThumbnail(url)
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "updateSquareThumb"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.square.SquareThumb/3372091550", [int(thumb["height"]), thumb["url"], int(thumb["width"])])
        await self.post(payload=_payload.string)

    async def showLogo(self):
        url = self.redis.get(self.redisGlobalPerfix+"logourl")
        if not url:
            logopath = os.path.join(os.getcwd(), "green.png")
            image = await self.postImage(logopath)
            url = image["url"]
            self.redis.set(self.redisGlobalPerfix+"logourl", url, ex=518400)
        await self.updateThumbnail(url)

    async def postJson(self, json_, url: str = _square_url, header: dict = {"content-type": "application/json"}) -> typing.Dict[str, typing.Any]:
        for i in range(3):
            async with self._session.post(url=url, json=json_, headers=header) as r:
                if r.status != 200:
                    self._log.warning("<第"+str(i+1)+"次post失敗> payload="+str(json_)+" url="+url+" header="+str(header))
                    await asyncio.sleep(1)
                else:
                    text = await r.text()
                    if text[:4] == "//OK":
                        text = text[4:]
                    return json.loads(text)
        return None

    async def rename(self, user: User, newname: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "updateNickname"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", user.color if user.color != "" else None, user.ID, newname, user.ID])
        await self.post(payload=_payload.string)

############################################commands#######################################

    @command.command(help=".help\n顯示這個訊息")
    async def help(self, message: Message, *args):
        texts = []
        for com in command.commands:
            texts.append(command.commands[com].help+"\n認證成員限定："+("是" if command.commands[com].authonly else "否")+"\n")
        await self.sendTextImage("\n".join(texts), message.user)

    @command.command(help=".status\n顯示目前在線上的成員列表")
    async def status(self, message: Message, *args):
        texts = []
        gauth = self.redis.smembers(self.redisGlobalPerfix+"auth")
        auths = self.redis.smembers(self.redisPerfix+"auth")
        members = self.redis.smembers(self.redisPerfix+"members")
        authtext = []
        membertext = []
        unknowntext = []
        for user in self.users:
            if re.search("#Bot", user.nickname):
                continue
            if user.ID in gauth or user.ID in auths:
                authtext.append("("+user.ID[:5]+")"+user.nickname)
            elif user.ID in members:
                membertext.append("("+user.ID[:5]+")"+user.nickname)
            else:
                unknowntext.append("("+user.ID[:5]+")"+user.nickname)
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

    @command.command(help=".remove <使用者> <檔案>\n移除特定使用者所發出的檔案\n如果不指定檔名，則移除所有該使用者發出的所有檔案")
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
            user = copy.deepcopy(media.user)
            user.nickname = self.user.nickname
            await self.sendMessage(Message(mtype=Message.MessageType.deleteimage, user=user, content="delete "+media.url), showID=False)

    @command.command(alias="rename", help=".rename <新名稱>\n修改自己的使用者名稱，只在使用者列表有效")
    async def command_rename(self, message: Message, *args):
        await self.rename(message.user, args[0])

    @command.command(help=".member (add/remove) <使用者>\n將特定使用者從本頻道一般成員新增/移除，成為成員後才可使用指令\n一般成員不可修改認證成員身分\n若不指定add/remove則自動判斷")
    async def member(self, message: Message, *args):
        ismember = self.redis.sismember(self.redisPerfix+"members", message.metionUsers[0].ID)
        result = ""
        usertext = "使用者("+message.metionUsers[0].ID[:5]+")"+message.metionUsers[0].nickname
        if ismember:
            if len(args) == 1 or (len(args) == 2 and args[0] == "remove"):
                self.redis.srem(self.redisPerfix+"members", message.metionUsers[0].ID)
                result = "✔️成功將"+usertext+"從一般成員移除"
        else:
            if len(args) == 1 or (len(args) == 2 and args[0] == "add"):
                if self.redis.sismember(self.redisPerfix+"auth", message.metionUsers[0].ID):
                    if self.redis.sismember(self.redisPerfix+"auth", message.user.ID):
                        self.redis.srem(self.redisPerfix+"auth", message.metionUsers[0].ID)
                        self.redis.sadd(self.redisPerfix+"members", message.metionUsers[0].ID)
                        result = "✔️成功將"+usertext+"從認證成員變為一般成員"
                    else:
                        result = "❌不能將"+usertext+"從認證成員變為一般成員，對方擁有較高的權限"
                else:
                    self.redis.sadd(self.redisPerfix+"members", message.metionUsers[0].ID)
                    result = "✔️成功將"+usertext+"變為一般成員"

        if not result:
            result = "❌操作錯誤，"+usertext+"維持原身分"

        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=result, metionUsers=[message.metionUsers[0], message.user]), showID=False)

    @command.command(help='.cls\n消除所有以"."作為開頭的訊息以及機器人的訊息')
    async def cls(self, message: Message, *args):
        def isValid(m: Message) -> bool:
            return m.user.ID != self.user.ID and m.content[0:len(self.commendPrefix)] != self.commendPrefix
        await self.resetmessages(isValid)

    @command.command(help=".ban <使用者>\n發起封鎖特定使用者投票")
    async def ban(self, message: Message, *args):
        target: User = message.metionUsers[0]
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "createVotingForForbid"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", None, self.user.ID, self.user.nickname, self.user.ID])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", target.color if target.color else None, target.ID, target.nickname, target.ID])
        _payload.AddPara("java.lang.String/2004016611", ["【本投票通過時自動封鎖】"], regonly=True)
        await self.post(payload=_payload.string, url=self._vote_url)

    @command.command(help='.burn <使用者>\n發起燒毀特定使用者"全部"KERMA的投票')
    async def burn(self, message: Message, *args):
        if len(message.metionUsers) > 0:
            target: User = message.metionUsers[0]
            _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "createVotingForBurn"])
            _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
            _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", None, self.user.ID, self.user.nickname, self.user.ID])
            _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", target.color if target.color else None, target.ID, target.nickname, target.ID])
            _payload.AddPara("java.lang.String/2004016611", ["【本投票通過時自動燒毀全部KERMA】"], regonly=True)
            await self.post(payload=_payload.string, url=self._vote_url)

    @command.command(help=".autotalk\n啟用/停用自動發送訊息功能")
    async def autotalk(self, message: Message, *args):
        await self.toggleFlag(flag.talk)

    @command.command(help=".bind <DiscordID>\n指定一個Discord帳號與目前帳號綁定，用於Discord發話")
    async def bind(self, message: Message, *args):
        if len(args) >= 1:
            try:
                kid = int(args[0])
                self.redis.hset("kekeke::bot::users::discordid", message.user.ID, str(kid))
                self.redis.hset("discordbot::users::kekekeid", str(kid), message.user.ID)
                if message.user.color:
                    self.redis.hset("discordbot::users::kekekecolor", str(kid), message.user.color)
                await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content="✔️已綁定到Discord", metionUsers=[message.user]), showID=False)
            except ValueError:
                await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content="❌參數錯誤", metionUsers=[message.user]), showID=False)

    @command.command(authonly=True, help=".auth (add/remove) <使用者>\n將特定使用者從本頻道認證成員新增/移除，成為成員後可使用所有指令\n若不指定add/remove則自動判斷")
    async def auth(self, message: Message, *args):
        isauth = self.redis.sismember(self.redisPerfix+"auth", message.metionUsers[0].ID)
        result = ""
        usertext = "使用者("+message.metionUsers[0].ID[:5]+")"+message.metionUsers[0].nickname
        if isauth:
            if len(args) == 1 or (len(args) == 2 and args[0] == "remove"):
                self.redis.srem(self.redisPerfix+"auth", message.metionUsers[0].ID)
                result = "✔️成功將"+usertext+"從認證成員移除"
        else:
            if len(args) == 1 or (len(args) == 2 and args[0] == "add"):
                self.redis.sadd(self.redisPerfix+"auth", message.metionUsers[0].ID)
                if self.redis.sismember(self.redisPerfix+"members", message.metionUsers[0].ID):
                    self.redis.srem(self.redisPerfix+"members", message.metionUsers[0].ID)
                    result = "✔️成功將"+usertext+"從一般成員變為認證成員"
                else:
                    result = "✔️成功將"+usertext+"變為認證成員"
        if not result:
            result = "❌操作錯誤，"+usertext+"維持原身分"

        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=result, metionUsers=[message.metionUsers[0], message.user]), showID=False)

    @command.command(authonly=True, help=".clear <目前頻道名稱> X\n【危險】送出X條空白訊息\nX最多為100")
    async def clear(self, message: Message, *args):
        if len(args) >= 2 and args[0] == self.name:
            times = clip(int(args[1], 0), 0, 100)
            for _ in range(times):
                await self.sendMessage(Message(), showID=False)
            self._log.info("發送"+str(times)+"則空白訊息")

    @command.command(authonly=True, help=".muda <使用者>\n使特定使用者無法發送檔案並清除全部所發送檔案")
    async def muda(self, message: Message, *args):
        if len(args) >= 1:
            user: User = message.metionUsers[0]
            if not self.redis.sismember(self.redisGlobalPerfix+"silentUsers", user.ID):
                self.redis.sadd(self.redisGlobalPerfix+"silentUsers", user.ID)

    @command.command(authonly=True, help='.automuda\n啟用/停用當使用者發送特定關鍵字時，自動進行"muda"指令')
    async def automuda(self, message: Message, *args):
        await self.toggleFlag(flag.muda)

    @command.command(authonly=True, help='.clearup <人名>\n消除所有該使用者的訊息')
    async def clearup(self, message: Message, *args):
        if len(message.metionUsers) >= 1:
            def isValid(m: Message) -> bool:
                return m.user not in message.metionUsers
            await self.resetmessages(isValid)

    @command.command(authonly=True, help='.zawarudo <目前頻道名稱>\n【危險】消除所有非成員的訊息')
    async def zawarudo(self, message: Message, *args):
        if len(args) >= 1 and args[0] == self.name:
            vaildusers: typing.Set[User] = self.redis.sunion(self.redisPerfix+"members", self.redisPerfix+"auth", self.redisGlobalPerfix+"auth")

            def isValid(m: Message) -> bool:
                return m.user.ID in vaildusers and m.content[0:len(self.commendPrefix)] != self.commendPrefix
            await self.resetmessages(isValid)

    async def resetmessages(self, vaild):
        validmessages = list(filter(vaild, self.messages))
        if len(validmessages) >= 1:
            self.pauseListen = True
            self.pauseMessage = validmessages[-1]
            oldest = validmessages[0]
            if len(validmessages) < 100:
                validmessages = list(Message(time=oldest.time) for _ in range(100-len(validmessages)))+validmessages
            medias = self.medias.copy()

            for media in medias:
                user = copy.deepcopy(media.user)
                user.nickname = self.user.nickname
                await self.sendMessage(Message(mtype=Message.MessageType.deleteimage, user=user, content=random.choice(["muda", "沒用", "無駄"])+" "+media.url), showID=False)

            for m in validmessages:
                await self.sendMessage(m, showID=False)

            await self.setMessage(validmessages)

    async def vote(self, voteid: str, voteoption: str = "__i18n_forbid"):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "voteByPermission"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("java.lang.String/2004016611", [voteid], regonly=True)
        _payload.AddPara("java.util.Set", ["java.util.HashSet/3273092938", "https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "java.lang.String/2004016611", voteoption], regonly=True)
        await self.post(payload=_payload.string, url=self._vote_url)

    async def banCommit(self, voteid: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "applyForbidByVoting"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("java.lang.String/2004016611", [voteid], regonly=True)
        _payload.AddPara("com.liquable.hiroba.gwt.client.vote.ForbidOption/647536008", [0], rawpara=True)
        await self.post(payload=_payload.string, url=self._vote_url)

    async def burnoutCommit(self, voteid: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "applyBurnByVoting"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("java.lang.String/2004016611", [voteid], regonly=True)
        for _ in range(10):
            await self.post(payload=_payload.string, url=self._vote_url)


def clip(num: int, a: int, b: int) -> int:
    return min(max(num, a), b)
