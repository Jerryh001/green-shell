import asyncio
import json
import logging

import aiohttp

from .channel import Channel


class Bot:
    def __init__(self):
        self.channels = dict()

    async def subscribe(self, channel: str):
        if channel not in self.channels:
            self.channels[channel] = Channel(channel)

    def isSubscribe(self, channel: str):
        return channel in self.channels

    async def unSubscribe(self, channel: str):
        try:
            self.channels.pop(channel)
        except KeyError:
            pass
