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
from discord.ext import commands

from kekeke import red
from kekeke.bot import Bot as KBot
from kekeke.monitor import Monitor

CUBENAME = re.search(r"(?<=/)[^/]+$", os.getenv("CLOUDCUBE_URL"), re.IGNORECASE).group(0)
bot = commands.Bot(command_prefix=os.getenv("DISCORD_PREFIX"), owner_id=152965086951112704)
kbot: KBot = None
overseeing_list = {}
redis = red.redis

bot.load_extension('cogs.kekeke')


def DownloadAllFiles():
    s3 = boto3.resource("s3")
    for obj in s3.Bucket("cloud-cube").objects.filter(Prefix=CUBENAME+"/"):
        if obj.key[-1] != "/":
            dirname = os.path.dirname(__file__)
            filename = re.search(r"(?<=\/)[^\/]+$", obj.key).group(0)
            filepath = os.path.join(dirname, "data/"+filename)

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
    filename = "data/"+filemessage.filename
    filepath = os.path.join(dirname, filename)
    try:
        await filemessage.save(filepath)
        s3 = boto3.resource("s3")
        s3.Bucket("cloud-cube").put_object(Key=CUBENAME+"/"+filename, Body=open(filepath, 'rb'))
        logging.info("更新 "+filename+" 成功")
        await ctx.send("更新`"+filename+"`成功")
    except:
        logging.error("更新 "+filename+" 失敗")
        await ctx.send("更新`"+filename+"`失敗")


@bot.check_once
async def _IsAllowRun(ctx: commands.Context):
    return ((await bot.is_owner(ctx.author)) or ctx.author == ctx.me) and ctx.channel.id == 483242913807990806


@bot.event
async def on_ready():
    DownloadAllFiles()
    logging.info(f"Logged in as {bot.user.name}({bot.user.id})")
    await bot.get_channel(483242913807990806).send(f"{bot.user.name}已上線{bot.command_prefix}")
    if bot.command_prefix != ".":
        return
    redis.sunionstore("kekeke::bot::GUIDpool", "kekeke::bot::GUIDpool", "kekeke::bot::GUIDpool::using")
    redis.delete("kekeke::bot::GUIDpool::using")
    for channelname in redis.smembers("discordbot::overseechannels"):
        bot.loop.create_task(oversee(channelname))
    try:
        bot.loop.create_task(train(int(redis.get("kekeke::bot::training::number"))))
    except ValueError:
        pass


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    user: discord.User = bot.get_user(payload.user_id)
    if user == bot.user:
        return
    channel: discord.TextChannel = bot.get_channel(payload.channel_id)
    message: discord.Message = await channel.fetch_message(payload.message_id)
    if channel.id == 483268806072991794 and payload.emoji.name == r"🛡" and await bot.is_owner(user):
        name = ""
        try:
            name = message.embeds[0].author.name
            bot.loop.create_task(oversee(name, True))
        except:
            await bot.get_channel(483242913807990806).send(f"無法對`{name}`進行防禦")


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    user: discord.User = bot.get_user(payload.user_id)
    if user == bot.user:
        return
    channel: discord.TextChannel = bot.get_channel(payload.channel_id)
    message: discord.Message = await channel.fetch_message(payload.message_id)
    if channel.id == 483268806072991794 and payload.emoji.name == r"🛡" and await bot.is_owner(user):
        name = ""
        try:
            name = message.embeds[0].author.name
            overseeing_list[name].cancel()
        except:
            await bot.get_channel(483242913807990806).send(f"無法停止對`{name}`的防禦")


@bot.event
async def on_message(message: discord.Message):
    # if message.author.bot:
    #     return

    if not message.author.bot and message.channel.category and message.channel.category.id == 483268757884633088:
        if message.channel.id != 483268806072991794 and redis.sismember("discordbot::overseechannels", message.channel.name):
            try:
                await kbot.channels[message.channel.name].anonSend(message)
            except KeyError:
                logging.warning(message.channel.name+"不在監視中，無法發送訊息")
        await message.delete()
    else:
        await bot.process_commands(message)


@bot.command()
async def sendall(ctx: commands.Context, *, content: str):
    for channel in kbot.channels.values():
        await channel.say(content)


@bot.command(name="train")
async def _train(ctx: commands.Context, *, num: int):
    redis.set("kekeke::bot::training::number", num)
    bot.loop.create_task(train(num))


async def train(num: int):
    global kbot
    if not kbot:
        kbot = KBot()
    await kbot.train(num)


async def oversee(name: str, defender=False):
    if name in overseeing_list:
        logging.warning(f"{name}已在監視中")
        await bot.get_channel(483242913807990806).send(f"`{name}`已在監視中")
        return

    global kbot
    if not kbot:
        kbot = KBot()

    if defender:
        logging.info("對"+name+"進行防禦")
        await bot.get_channel(483242913807990806).send("對`"+name+"`進行防禦")
        overseeing_list[name] = bot.loop.create_task(Monitor(name, None, kbot).Oversee(True))
    else:
        channel: discord.TextChannel = next((c for c in bot.get_channel(483268757884633088).channels if c.name == name), None)
        if not channel:
            logging.warning(name+"頻道不存在")
            await bot.get_channel(483242913807990806).send(name+"頻道不存在，使用無頭模式監視")
        overseeing_list[name] = bot.loop.create_task(Monitor(name, channel, kbot).Oversee())
        redis.sadd("discordbot::overseechannels", name)
    try:
        await overseeing_list[name]
    except futures.CancelledError:
        await kbot.unSubscribe(name)
        logging.info("已停止監視 "+name)
        await bot.get_channel(483242913807990806).send("已停止監視`"+name+"`")
    except Exception as e:
        redis.srem("discordbot::overseechannels", name)
        overseeing_list.pop(name)
        logging.error("監視 "+name+" 時發生錯誤:")
        logging.error(e, exc_info=True)
        await bot.get_channel(483242913807990806).send("監視`"+name+"`時發生錯誤")


@bot.command(name="oversee", aliases=["o"])
async def _oversee(ctx: commands.Context, *, channelname: str):
    bot.loop.create_task(oversee(channelname))


@bot.command(aliases=["d"])
async def defend(ctx: commands.Context, *, channelname: str):
    bot.loop.create_task(oversee(channelname, True))


@_oversee.before_invoke
async def _BeforeOversee(ctx: commands.Context):
    global kbot
    if not kbot:
        kbot = KBot()
    channel: discord.TextChannel = next((c for c in bot.get_channel(483268757884633088).channels if c.name == ctx.kwargs["channelname"]), None)
    if channel:
        url = r"https://kekeke.cc/"+channel.name
        if channel.topic != url:
            await channel.edit(topic=url)


@bot.command()
async def stop(ctx: commands.Context, *, channelname: str):
    try:
        redis.srem("discordbot::overseechannels", channelname)
        overseeing_list[channelname].cancel()
        overseeing_list.pop(channelname)
    except KeyError:
        logging.warning(channelname+" 不在監視中")
        await ctx.send("`"+channelname+"`"+"不在監視中")
    except Exception as e:
        logging.error("停止監視 "+channelname+" 失敗")
        logging.error(e, exc_info=True)
        await ctx.send("停止監視`"+channelname+"`失敗")


@bot.command()
async def on_oversee(ctx: commands.Context):
    if overseeing_list:
        await ctx.send("監視中頻道：\n```"+"\n".join(overseeing_list)+"```")
    else:
        await ctx.send("沒有頻道監視中")


@bot.command()
async def hi(ctx: commands.Context):
    await ctx.send("Hello")


@bot.command(name="eval")
async def _eval(ctx: commands.Context, *, cmd: str):
    try:
        ret = eval(cmd)
        logging.info(f"eval({cmd})成功，返回:\n{ret}")
        await ctx.send(f"`{ret}`")
    except:
        logging.warning(f"eval({cmd}) 失敗")
        await ctx.send(f"`eval({cmd})`失敗")


@bot.command()
async def loglevel(ctx, level: str, logger_name: str = ""):
    try:
        logger = logging.getLogger(logger_name)
        level_old = logger.level
        logger.setLevel(eval("logging."+level.upper()))
        logging.debug(f"logger {logger} 's level changed from {level_old} to {logger.level}({level.upper()})")
        await ctx.send("change success")
    except:
        logging.warning(f"change {logger}'s level to {level} failed")
        await ctx.send("change failed")


async def SIGTERM_exit():
    await bot.get_channel(483242913807990806).send(bot.user.name+" has stopped by SIGTERM")
    logging.warning(bot.user.name+" has stopped by SIGTERM")


def SIG_EXIT(signum, frame):
    time.sleep(5)
    logging.warning(bot.user.name+" has stopped by SIGTERM-")
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
        logging.info("add handler success")
    except NotImplementedError:
        logging.warning("add handler failed")  # run in windows

    bot.run(os.getenv("DISCORD_TOKEN"))
