import asyncio
import importlib
import logging
import os
import re
import signal
import time
from concurrent import futures

import boto3
import discord
import ptvsd
from discord.ext import commands

from kekeke.bot import Bot as KBot
from kekeke.monitor import Monitor
from kekeke.red import redis

ptvsd.enable_attach(address=('localhost', 5678), redirect_output=True)

CUBENAME = re.search(r"(?<=/)[^/]+$", os.getenv("CLOUDCUBE_URL"), re.IGNORECASE).group(0)
bot = commands.Bot(command_prefix=os.getenv("DISCORD_PREFIX"), owner_id=152965086951112704)

bot.load_extension('cogs.kekeke')


def DownloadAllFiles():
    s3 = boto3.resource("s3")
    for obj in s3.Bucket("cloud-cube").objects.filter(Prefix=f"{CUBENAME}/"):
        if obj.key[-1] != "/":
            dirname = os.path.dirname(__file__)
            filename = re.search(r"(?<=\/)[^\/]+$", obj.key).group(0)
            filepath = os.path.join(dirname, f"data/{filename}")

            s3.Bucket("cloud-cube").download_file(obj.key, filepath)


class DataFile(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            message = await bot.get_channel(485322302603657218).fetch_message(argument)
            if message.attachments:
                return message.attachments[0]
        except discord.NotFound:
            pass  # not found
        return None


@bot.command()
async def update(ctx, filemessage: DataFile):
    if not filemessage:
        logging.warning("找不到檔案")
        await ctx.send("找不到檔案")
        return
    dirname = os.path.dirname(__file__)
    filename = f"data/{filemessage.filename}"
    filepath = os.path.join(dirname, filename)
    try:
        await filemessage.save(filepath)
        s3 = boto3.resource("s3")
        s3.Bucket("cloud-cube").put_object(Key=f"{CUBENAME}/{filename}", Body=open(filepath, 'rb'))
        logging.info(f"更新{filename}成功")
        await ctx.send(f"更新`{filename}`成功")
    except:
        logging.error(f"更新{filename}失敗")
        await ctx.send(f"更新`{filename}`失敗")


@bot.check_once
async def _IsAllowRun(ctx: commands.Context):
    return ((await bot.is_owner(ctx.author)) or ctx.author == ctx.me) and ctx.channel.id == 483242913807990806


@bot.event
async def on_ready():
    DownloadAllFiles()
    logging.info(f"{bot.user.name}({bot.user.id})已上線")
    await bot.get_channel(483242913807990806).send(f"{bot.user.name}已上線{bot.command_prefix}")


@bot.event
async def on_message(message: discord.Message):
    await bot.process_commands(message)


@bot.command()
async def hi(ctx: commands.Context):
    await ctx.send("Hello")


@bot.command(name="eval")
async def _eval(ctx: commands.Context, *, cmd: str):
    try:
        ret = eval(cmd)
        logging.info(f"eval({cmd})成功，返回：{ret}")
        await ctx.send(f"`{ret}`")
    except:
        logging.warning(f"eval({cmd}) 失敗")
        await ctx.send(f"`eval({cmd})`失敗")


@bot.command()
async def loglevel(ctx, level: str, logger_name: str = ""):
    logger = logging.getLogger(logger_name)
    level_new = level.upper()
    try:
        logger.setLevel(eval(f"logging.{level_new}"))
        logging.debug(f"logger{logger_name}的等級修改為{level_new}")
        await ctx.send(f"logger`{logger_name}`的等級修改為`{level_new}`")
    except:
        logging.warning(f"無法把{logger_name}的等級修改為{level}")
        await ctx.send(f"無法把`{logger_name}`的等級修改為`{level}`")


async def SIGTERM_exit():
    await bot.get_channel(483242913807990806).send(f"{bot.user.name} has stopped by SIGTERM")
    logging.warning(f"{bot.user.name} has stopped by SIGTERM")


def SIG_EXIT(signum, frame):
    time.sleep(5)
    logging.warning(f"{bot.user.name} has stopped by SIGTERM")
    print("bye")
    time.sleep(5)
    for task in asyncio.Task.all_tasks():
        task.cancel()
    raise KeyboardInterrupt


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        signal.signal(signal.SIGTERM, SIG_EXIT)
        asyncio.get_event_loop().add_signal_handler(signal.SIGTERM, SIG_EXIT)
        bot.loop.add_signal_handler(signal.SIGTERM, SIG_EXIT)
    except NotImplementedError:
        pass  # run in windows

    bot.run(os.getenv("DISCORD_TOKEN"))
