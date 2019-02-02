import asyncio
import json
import logging

import aiohttp
import redis

from kekeke import red

from .channel import Channel


class Bot:
    def __init__(self):
        self.channels = dict()
        self.trainings = list()
        self.redis = redis.StrictRedis(connection_pool=red.pool())

    async def train(self,num:int):
        size=len(self.trainings)
        if not size:
            self.redis.sunionstore("kekeke::bot::training::GUIDs","kekeke::bot::training::GUIDs","kekeke::bot::training::GUIDs::using")
            self.redis.delete("kekeke::bot::training::GUIDs::using")
        if size<num:
            for _ in range(num-size):
                c=Channel("測試123",True)
                self.trainings.append(c)
                await c.initial()
        elif  size>num:
            for _ in range(size-num):
                c=self.trainings.pop()
                await c.Close()

    async def subscribe(self, channel: str):
        if channel not in self.channels:
            self.channels[channel] = Channel(channel)
            await self.channels[channel].initial()

    def isSubscribe(self, channel: str):
        return channel in self.channels

    async def unSubscribe(self, channel: str):
        try:
            c: Channel = self.channels.pop(channel)
            await c.Close()
        except KeyError:
            pass
