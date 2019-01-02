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
import redis
import tzlocal
from PIL import Image, ImageDraw, ImageFont

from kekeke import command, flag, red

from .GWTpayload import GWTPayload
from .jsonfile import JsonFile
from .message import *
from .user import User


class Channel:
    _notwelcomes = JsonFile(os.path.join(os.getcwd(), "data/keyword.json"))
    _square_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService"
    _vote_url = "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/voteService"
    _header = {"content-type": "text/x-gwt-rpc; charset=UTF-8"}
    commendPrefix = os.getenv("DISCORD_PREFIX")

    redisGlobalPerfix = "kekeke::bot::global::"

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
        self.last_send_IDs = dict()
        self.last_send_Nicknames = dict()
        self.redisPerfix = "kekeke::bot::channel::"+self.name+"::"
        self.redis = redis.StrictRedis(connection_pool=red.pool())
        self.connectEvents = None
        self.pauseListen = False
        self.pauseMessage = Message()
        self.closed = False

    async def initial(self):
        while True:
            try:
                self._session: aiohttp.ClientSession = await aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)).__aenter__()
                self.ws: aiohttp.ClientWebSocketResponse = await self._session.ws_connect(url=r"wss://ws.kekeke.cc/com.liquable.hiroba.websocket", heartbeat=120).__aenter__()
                break
            except:
                self._log.error("對伺服器建立連線失敗，5秒後重試")
                self.Close(stop=False)
                await asyncio.wait(5)
        await self.subscribe()
        await self.updateFlags(True)
        await self.initMessages(self.name)
        await self.updateUsers()
        self.connectEvents = asyncio.get_event_loop().create_task(asyncio.wait({self.listen(), self.keepAlive()}))

    async def Close(self, stop=True):
        if stop:
            self.closed = True
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
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "B2BDD9C0DA93926EAB57F7F9D7B941D3", "com.liquable.hiroba.gwt.client.account.IGwtAccountService", "tryExtendsKerma"])
        while not self._session.closed:
            await self.post(payload=_payload.string, url="https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/accountService")
            await asyncio.sleep(300)
        asyncio.get_event_loop().create_task(self.reConnect())

    async def subscribe(self):
        GUID = self.redis.get(self.redisPerfix+"botGUID")
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "startSquare"])
        _payload.AddPara("com.liquable.hiroba.gwt.client.square.StartSquareRequest/2186526774", [GUID if GUID else None, None, "com.liquable.gwt.transport.client.Destination/2061503238", "/topic/{0}".format(self.name)])
        while True:
            data = await self.post(payload=_payload.string)
            if data:
                break
            else:
                await asyncio.sleep(5)
        data = data[-3]
        self.redis.set(self.redisPerfix+"botGUID", data[1])
        self.user.ID = data[-1]
        await self.ws.send_str('CONNECT\nlogin:'+json.dumps({"accessToken": data[2], "nickname": self.user.nickname}))
        await self.ws.send_str('SUBSCRIBE\ndestination:/topic/{0}'.format(self.name))
        self._log.info("subscribe "+self.name)

    async def initMessages(self, channel: str):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getLeftMessages"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        messages: list = list()
        data = await self.post(payload=_payload.string)
        if data:
            data = data[-3]
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
            self._log.info("更新歷史訊息成功")
        else:
            self._log.warning("更新歷史訊息失敗")

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
            if not m:
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
                    if m.payload["title"] == "__i18n_voteForbidTitle":
                        if m.payload["votingState"] == "CREATE":
                            asyncio.get_event_loop().create_task(self.vote(m.payload["votingId"]))
                        elif m.payload["votingState"] == "COMPLETE":
                            asyncio.get_event_loop().create_task(self.banCommit(m.payload["votingId"]))
                        else:
                            asyncio.get_event_loop().create_task(self.banCommit(m.payload["votingId"]))
        asyncio.get_event_loop().create_task(self.reConnect())

    async def post(self, payload, url: str = _square_url, header: dict = _header) -> typing.Dict[str, typing.Any]:
        for i in range(3):
            async with self._session.post(url=url, data=payload, headers=header) as r:
                if r.status != 200:
                    self._log.warning("<第"+str(i)+"次post失敗> payload="+str(payload)+" url="+url+" header="+str(header))
                else:
                    text = await r.text()
                    if text[:4] == "//OK":
                        text = text[4:]
                    return json.loads(text)
        return None

    async def updateFlags(self, pull=False):
        if pull:
            self.flags = self.redis.smembers(self.redisPerfix+"flags")
        else:
            self.redis.delete(self.redisPerfix+"flags")
            self.redis.sadd(self.redisPerfix+"flags", self.flags)
        await self.rename(Message(user=self.user), self.user.nickname+"".join(self.flags))

    async def updateUsers(self)->typing.Set[User]:
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
                    if user.ID in self.redis.sunion(self.redisPerfix+"ignores", self.redisGlobalPerfix+"ignores", self.redisPerfix+"members", self.redisPerfix+"auth", self.redisGlobalPerfix+"auth"):
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
        if not pop and self.redis.sismember(self.redisPerfix+"flags", flag.muda):
            for media in self.medias:
                if media.remove:
                    continue
                issilent = self.redis.sismember(self.redisPerfix+"silentUsers", media.user.ID)
                if not issilent and self.isForbiddenMessage(message):
                    await self.muda(Message(mtype=Message.MessageType.chat, user=self.user, metionUsers=[message.user]), message.user.nickname)
                if issilent:
                    user = copy.deepcopy(media.user)
                    user.nickname = self.user.nickname
                    await self.sendMessage(Message(mtype=Message.MessageType.deleteimage, user=user, content=random.choice(["muda", "沒用", "無駄"])+" "+media.url), showID=False)

    def isForbiddenMessage(self, message: Message)->bool:
        if self.redis.sismember(self.redisPerfix+"auth", message.user.ID) or self.redis.sismember(self.redisGlobalPerfix+"auth", message.user.ID):
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
        if message.user != self.user and message.content[0:len(self.commendPrefix)] == self.commendPrefix:
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
            "payload": message.payload}
        if message.user.color:
            message_obj["senderColorToken"] = message.user.color
        if message.metionUsers:
            message_obj["payload"]["replyPublicIds"] = []
            for muser in message.metionUsers:
                message_obj["payload"]["replyPublicIds"].append(muser.ID)
        payload = 'SEND\ndestination:/topic/{0}\n\n'.format(self.name)+json.dumps(message_obj, ensure_ascii=False)
        await self.ws.send_str(payload)

    async def waitMessage(self)->Message:
        while self.message_queue.qsize() < 1:
            await asyncio.sleep(0)
        return self.message_queue.get()

    async def toggleFlag(self, flag: str):
        if self.redis.sismember(self.redisPerfix+"flags", flag):
            self.redis.srem(self.redisPerfix+"flags", flag)
        else:
            self.redis.sadd(self.redisPerfix+"flags", flag)
        await self.updateFlags(pull=True)
        await self.rename(Message(user=self.user), self.user.nickname+"".join(self.flags))

    async def anonSend(self, text: str, author: str, discordID: int):
        user = copy.deepcopy(self.user)
        kid=self.redis.hget("discordbot::users::kekekeid",discordID)
        if kid:
            user.nickname = author
            user.ID=kid
            kcolor=self.redis.hget("discordbot::users::kekekecolor",discordID)
            user.color=kcolor if kcolor else ""
        else:
            user.nickname = author+"#Bot"
        message = Message(Message.MessageType.chat, content=text, user=user, payload={"discordID": discordID})
        await self.sendMessage(message, showID=False)

    async def sendTextImage(self, text: str):
        font = ImageFont.truetype(font=os.path.join(os.getcwd(), "kekeke/NotoSansCJKtc-Regular.otf"), size=20)
        img = Image.new('RGB', (1, 1), (255, 255, 255))
        d = ImageDraw.Draw(img)
        size = d.multiline_textsize(text=text, font=font)
        img = img.resize(size)
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, fill=(0, 0, 0), font=font)
        filepath = os.path.join(os.getcwd(), "data/image.jpg")
        img.save(filepath)
        with open(filepath, 'rb') as f:
            async with self._session.post(url="https://kekeke.cc/com.liquable.hiroba.springweb/storage/upload-media", data={'file': f}) as r:
                text = json.loads(await r.text())
                await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=text["url"]), showID=False)


############################################commands#######################################


    @command.command(help=".help\n顯示這個訊息")
    async def help(self, message: Message, *args):
        texts = []
        for com in command.commands:
            texts.append(command.commands[com].help+"\n認證成員限定："+("是" if command.commands[com].authonly else "否")+"\n")
        await self.sendTextImage("\n".join(texts))

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
            user = media.user
            user.nickname = self.user.nickname
            await self.sendMessage(Message(mtype=Message.MessageType.deleteimage, user=user, content="delete "+media.url), showID=False)

    @command.command(help=".rename <新名稱>\n修改自己的使用者名稱，只在使用者列表有效")
    async def rename(self, message: Message, *args):
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "updateNickname"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", message.user.color if message.user.color != "" else None, message.user.ID, args[0], message.user.ID])
        await self.post(payload=_payload.string)

    @command.command(help=".member (add/remove) <使用者>\n將特定使用者從本頻道一般成員新增/移除，成為成員後才可使用指令\n一般成員不可修改認證成員身分\n若不指定add/remove則自動判斷")
    async def member(self, message: Message, *args):
        ismember = self.redis.sismember(self.redisPerfix+"members", message.metionUsers[0].ID)
        success = False
        if ismember:
            if len(args) == 1 or (len(args) == 2 and args[0] == "remove"):
                self.redis.srem(self.redisPerfix+"members", message.metionUsers[0].ID)
                success = True
        else:
            if len(args) == 1 or (len(args) == 2 and args[0] == "add"):
                if self.redis.sismember(self.redisPerfix+"auth", message.metionUsers[0].ID):
                    if self.redis.sismember(self.redisPerfix+"auth", message.user.ID):
                        self.redis.srem(self.redisPerfix+"auth", message.metionUsers[0].ID)
                        self.redis.sadd(self.redisPerfix+"members", message.metionUsers[0].ID)
                        success = True
                else:
                    self.redis.sadd(self.redisPerfix+"members", message.metionUsers[0].ID)
                    success = True
        result = ("✔️" if success else "❌")+"使用者("+message.metionUsers[0].ID[:5]+")"+message.metionUsers[0].nickname+("是" if ismember != success else "不是")+"一般的使用者"
        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=result), showID=False)

    @command.command(help=".ban <使用者>\n發起封鎖特定使用者投票")
    async def ban(self, message: Message, *args):
        target: User = message.metionUsers[0]
        _payload = GWTPayload(["https://kekeke.cc/com.liquable.hiroba.square.gwt.SquareModule/", "C8317665135E6B272FC628F709ED7F2C", "com.liquable.hiroba.gwt.client.vote.IGwtVoteService", "createVotingForForbid"])
        _payload.AddPara("com.liquable.gwt.transport.client.Destination/2061503238", ["/topic/{0}".format(self.name)])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", None, self.user.ID, self.user.nickname, self.user.ID])
        _payload.AddPara("com.liquable.hiroba.gwt.client.chatter.ChatterView/4285079082", ["com.liquable.hiroba.gwt.client.square.ColorSource/2591568017", None, target.ID, target.nickname, target.ID])
        _payload.AddPara("java.lang.String/2004016611", [""], regonly=True)
        await self.post(payload=_payload.string, url=self._vote_url)

    @command.command(help=".autotalk\n啟用/停用自動發送訊息功能")
    async def autotalk(self, message: Message, *args):
        await self.toggleFlag(flag.talk)

    @command.command(help=".bind <DiscordID>\n指定一個Discord帳號與目前帳號綁定，用於Discord發話")
    async def bind(self, message: Message, *args):
        if len(args)>=1:
            self.redis.hset("kekeke::bot::users::discordid",message.user.ID,args[0])
            self.redis.hset("discordbot::users::kekekeid",args[0],message.user.ID)
            if message.user.color:
                self.redis.hset("discordbot::users::kekekecolor",args[0],message.user.color)
            await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content="✔️已綁定到Discord",metionUsers=[message.user]), showID=False)
        
    @command.command(help=".member (add/remove) <使用者>\n將特定使用者從本頻道認證成員新增/移除，成為成員後可使用所有指令\n若不指定add/remove則自動判斷")
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
                if self.redis.sismember(self.redisPerfix+"members", message.metionUsers[0].ID):
                    self.redis.srem(self.redisPerfix+"members", message.metionUsers[0].ID)
                success = True
        result = ("✔️" if success else "❌")+"使用者("+message.metionUsers[0].ID[:5]+")"+message.metionUsers[0].nickname+("是" if ismember != success else "不是")+"認證的使用者"
        await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=result,metionUsers=[message.metionUsers[0].ID]), showID=False)

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
            if not self.redis.sismember(self.redisPerfix+"silentUsers", user.ID):
                self.redis.sadd(self.redisPerfix+"silentUsers", user.ID)
                await self.remove(message, args[0])
                await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content=user.nickname+"你洗再多次也沒用沒用沒用沒用沒用"), showID=False)

    @command.command(authonly=True, help='.automuda\n啟用/停用當使用者發送特定關鍵字時，自動進行"muda"指令')
    async def automuda(self, message: Message, *args):
        await self.toggleFlag(flag.muda)

    @command.command(authonly=True, help='.zawarudo <目前頻道名稱>\n消除所有非成員的訊息')
    async def zawarudo(self, message: Message, *args):
        if args[0] == self.name:
            self.pauseListen = True
            vaildusers: typing.Set[User] = self.redis.sunion(self.redisPerfix+"members", self.redisPerfix+"auth", self.redisGlobalPerfix+"auth")

            def isValid(m: Message)->bool:
                return m.user.ID in vaildusers and m.content[0:len(self.commendPrefix)] != self.commendPrefix
            validmessages = list(filter(isValid, self.messages))
            self.pauseMessage = validmessages[-1]
            oldest = validmessages[0]
            if len(validmessages) < 100:
                validmessages = list(Message(time=oldest.time) for _ in range(100-len(validmessages)))+validmessages
            medias = self.medias.copy()

            await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content="ZA WARUDO 時間暫停!"), showID=False)
            await asyncio.sleep(1)

            for media in medias:
                user = copy.deepcopy(media.user)
                user.nickname = self.user.nickname
                await self.sendMessage(Message(mtype=Message.MessageType.deleteimage, user=user, content=random.choice(["muda", "沒用", "無駄"])+" "+media.url), showID=False)
                await asyncio.sleep(0.2)

            await asyncio.sleep(1)
            await self.sendMessage(Message(mtype=Message.MessageType.chat, user=self.user, content="時間繼續"), showID=False)
            await asyncio.sleep(1)

            for m in validmessages:
                await self.sendMessage(m, showID=False)

            await self.setMessage(validmessages)

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


def clip(num: int, a: int, b: int)->int:
    return min(max(num, a), b)
