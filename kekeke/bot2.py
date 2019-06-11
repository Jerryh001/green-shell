import asyncio
import json
import logging

import aiohttp

from .bot.channel import Channel
from .red import redis


class Bot:
    def __init__(self):
        self.channels = dict()
        self.trainings = list()
        asyncio.get_event_loop().create_task(self.Cleaner())

    async def Cleaner(self):
        while True:
            stopped = []
            for channel in self.channels:
                if self.channels[channel].closed:
                    stopped.append(channel)
            for channel in stopped:
                self.channels.pop(channel)
            await asyncio.sleep(0)

    async def train(self, num: int):
        size = len(self.trainings)
        if not size:
            redis.sunionstore("kekeke::bot::training::GUIDs", "kekeke::bot::training::GUIDs", "kekeke::bot::training::GUIDs::using")
            redis.delete("kekeke::bot::training::GUIDs::using")
        if size < num:
            for _ in range(num - size):
                c = Channel("測試123", Channel.BotType.training)
                self.trainings.append(c)
                await c.initial()
        elif size > num:
            for _ in range(size - num):
                c = self.trainings.pop()
                await c.Close()

    async def subscribe(self, channel: str, defender=False):
        if channel not in self.channels:
            self.channels[channel] = Channel(channel, Channel.BotType.defender if defender else Channel.BotType.observer)
            await self.channels[channel].initial()

    def isSubscribe(self, channel: str):
        return channel in self.channels

    async def unSubscribe(self, channel: str):
        try:
            await self.channels[channel].Close()
        except KeyError:
            pass
