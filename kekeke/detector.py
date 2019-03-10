import asyncio
import copy
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import List

import aiohttp
import discord
import tzlocal
from discord.ext import commands

from kekeke import GWTpayload

from .message import Message
from .red import redis

_log = logging.getLogger(__name__)


class Channel(object):

    def __init__(self):
        self.name = ""
        self.messages = list()
        self.thumbnail = ""
        self.population = 0


_HP_message_payload = GWTpayload.GWTPayload(["https://kekeke.cc/com.liquable.hiroba.home.gwt.HomeModule/", "53263EDF7F9313FDD5BD38B49D3A7A77", "com.liquable.hiroba.gwt.client.square.IGwtSquareService", "getLatestSquares"])


async def GetHPMessages()->List[Channel]:
    output: List[Channel] = list()
    resp = ""
    try:
        async with aiohttp.request("POST", "https://kekeke.cc/com.liquable.hiroba.gwt.server.GWTHandler/squareService", data=_HP_message_payload.string, headers={"content-type": "text/x-gwt-rpc; charset=UTF-8"}) as r:
            resp = await r.text()
    except:
        # self._log.error("Fetch kekeke HP failed")
        return output

    if resp[:4] == r"//OK":
        data = json.loads(resp[4:])
        strings: List[str] = [None]+data[-3]
        values: list = data[:-3]
        if values.pop():  # java.util.ArrayList/4159755760
            csize = values.pop()
            for _ in range(csize):
                ch = Channel()

                values.pop()  # com.liquable.hiroba.gwt.client.square.SquareView/274684774
                if values.pop():  # java.util.ArrayList/4159755760
                    msize = values.pop()
                    for _ in range(msize):
                        values.pop()  # java.lang.String/2004016611
                        ch.messages.append(Message.loadjson(strings[values.pop()]))
                    ch.population = int(values.pop())  # 人數
                if values.pop():  # com.liquable.hiroba.gwt.client.square.SquareThumb/3372091550
                    values.pop()  # height
                    ch.thumbnail = strings[values.pop()]  # url
                    values.pop()  # width
                values.pop()  # com.liquable.gwt.transport.client.Destination/2061503238
                ch.name = strings[values.pop()][len("/topic/"):]  # /topic/???
                output.append(ch)
        if values:
            _log.warning("values不是空的：")
            _log.warning(values)
    _log.debug("成功取得所有訊息")
    return output


_detect_username_list = list()

_detect_message_list = list()

_detect_last_update: datetime = None


def updateKeywords():
    global _detect_message_list, _detect_username_list, _detect_last_update
    updatetime = datetime.fromisoformat(redis.get("kekeke::bot::detector::lastupdate"))
    if not _detect_last_update or _detect_last_update < updatetime:
        _detect_last_update = updatetime
        _detect_username_list = list(map(re.compile, redis.sunion("kekeke::bot::detector::nickname", "kekeke::bot::detector::keyword")))
        _detect_message_list = list(map(re.compile, redis.sunion("kekeke::bot::detector::message", "kekeke::bot::detector::keyword")))


def CheckMessage(message: Message)->bool:
    global _detect_message_list, _detect_username_list
    updateKeywords()
    for regex in _detect_message_list:
        if regex.match(message.content):
            return True
    for regex in _detect_username_list:
        if regex.match(message.user.nickname):
            return True
    return False


async def Detect():
    channels = await GetHPMessages()
    result: List[Channel] = []
    for c in channels:  # type: Channel
        messages: List[Message] = list(filter(CheckMessage, c.messages))
        if messages:
            ch = copy.deepcopy(c)
            ch.messages = messages
            result.append(ch)
    return result
