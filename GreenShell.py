import discord
import os
import json
import pytz
import time
import asyncio
import importlib
from datetime import datetime
from datetime import timezone
from discord.ext import commands
import kekekemonitor as km

TOKEN="NDgzMjQxMTQzODM2OTk5Njkx.DmQmDg.9YVzFdm_zE3ulbKCN1YULe_phlA"

bot = commands.Bot(command_prefix='$',owner_id=152965086951112704)

@bot.event
async def on_ready():
    print('Logged in as '+bot.user.name)
    print(bot.user.id)
    print('------')

@bot.event
async def on_message(message:discord.Message):
    if await bot.is_owner(message.author) and message.channel.id==483242913807990806:
        await bot.process_commands(message)
       

@bot.command()
async def moniter(ctx,kchannel:str):
    monitor=km.KekekeMonitor(kchannel,bot,483925945494011906)
    await monitor.PeriodRun(30)

@bot.command()
async def hi(ctx):
    await ctx.send("Hello")

bot.remove_command('help')

bot.run(TOKEN)