import discord
from discord.ext import commands
import importlib
import signal
import asyncio
import concurrent.futures
import logging
import os
from kekeke import monitor as km,detector as kd
import boto3
import re

TOKEN=os.getenv("DISCORD_TOKEN") or open("data/TOKEN","r").read()
PREFIX=os.getenv("DISCORD_PREFIX") or "!"
CUBENAME="dc1rgs6wmts7"

bot = commands.Bot(command_prefix=PREFIX,owner_id=152965086951112704)

def DownloadAllFiles():
    s3 = boto3.resource("s3")
    for obj in s3.Bucket("cloud-cube").objects.filter(Prefix=CUBENAME+"/"):
        if obj.key[-1]!="/":
            dirname = os.path.dirname(__file__)
            filename=re.search(r"(?<=\/)[^\/]+$",obj.key).group(0)
            filepath = os.path.join(dirname, "data/"+filename)
            
            s3.Bucket("cloud-cube").download_file(obj.key, filepath)


class DataFile(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            message=await bot.get_channel(485322302603657218).get_message(argument)
            if message.attachments:
                return message.attachments[0]
        except discord.NotFound:
            pass#not found
        return None

@bot.command()
async def update(ctx,filemessage:DataFile):
    if not filemessage:
        logging.warning("找不到檔案")
        await ctx.send("找不到檔案")
        return
    dirname = os.path.dirname(__file__)
    filename = "data/"+filemessage.filename
    filepath=os.path.join(dirname, filename)
    try:
        await filemessage.save(filepath)
        s3 = boto3.resource("s3")
        s3.Bucket("cloud-cube").put_object(Key=CUBENAME+"/"+filename, Body=open(filepath, 'rb'))
        logging.info("更新 "+filename+" 成功")
        await ctx.send("更新`"+filename+"`成功")
    except:
        logging.error("更新 "+filename+" 失敗")
        await ctx.send("更新`"+filename+"`失敗")
        


@bot.event
async def on_ready():
    DownloadAllFiles()
    logging.info("Logged in as {0.user.name}({0.user.id})".format(bot))
    await bot.get_channel(483242913807990806).send(bot.user.name+"已上線"+PREFIX)

@bot.event
async def on_message(message:discord.Message):
    if await (bot.is_owner(message.author) or message.author==bot.user) and message.channel.id==483242913807990806:
        await bot.process_commands(message)
       
@bot.command()
async def kekeke(ctx:commands.Context):
    detector=kd.KWDetector(bot.get_channel(483268806072991794))
    try:
        await detector.PeriodRun(30)
        await ctx.send("stopped kekeke HP moniter")
    except:
        logging.error("moniter kekeke HP stopped unexcept")
        await ctx.send("moniter kekeke HP stopped unexcept")

overseeing_list={}

@bot.command()
async def oversee(ctx:commands.Context,channel:discord.TextChannel):
    monitor=km.KekekeMonitor(channel.name,channel)
    url=r"https://kekeke.cc/"+channel.name
    if channel.topic != url:
        await channel.edit(topic=url)
    task=bot.loop.create_task(monitor.Oversee())
    overseeing_list[channel.name]=task
    try:
        await task
    except concurrent.futures.CancelledError:
        logging.info("已停止監視 "+channel.name)
        await ctx.send("已停止監視`"+channel.name+"`")
    except:
        overseeing_list.pop(channel.name)
        logging.error("監視 "+channel.name+" 時發生錯誤")
        await ctx.send("監視`"+channel.name+"`時發生錯誤")
    

@bot.command()
async def stop(ctx:commands.Context,channel:discord.TextChannel):
    try:
        future=overseeing_list.pop(channel.name)
        future.cancel()
    except KeyError:
        logging.warning(channel.name+" 不在監視中")
        await ctx.send("`"+channel.name+"`"+"不在監視中")
    except:
        logging.error("停止監視 "+channel.name+" 失敗")
        await ctx.send("停止監視`"+channel.name+"`失敗")

@bot.command()
async def on_oversee(ctx:commands.Context):
    if overseeing_list:
        await ctx.send("監視中頻道：\n```"+"\n".join(overseeing_list)+"```")
    else:
        await ctx.send("沒有頻道監視中")

@bot.command()
async def hi(ctx:commands.Context):
    await ctx.send("Hello")

@bot.command(name="eval")
async def _eval(ctx:commands.Context, *, cmd:str):
    try:
        ret=eval(cmd)
        logging.info("eval({0})成功，返回:\n{1}".format(cmd,ret))
        await ctx.send("`{0}`".format(ret))
    except:
        logging.warning("eval({0}) 失敗".format(cmd))
        await ctx.send("`eval({0})`失敗".format(cmd))

@bot.command()
async def loglevel(ctx, level:str,logger_name:str="" ):
    try:
        logger=logging.getLogger(logger_name)
        level_old=logger.level
        logger.setLevel(eval("logging."+level.upper()))
        logging.debug("logger {0} 's level changed from {1} to {0.level}({2})".format(logger,level_old,level.upper()))
        await ctx.send("change success")
    except:
        logging.warning("change {0}'s level to {1} failed".format(logger,level))
        await ctx.send("change failed")

@bot.command()
async def download(ctx,message_id:int,target:str=None):
    message:discord.Message
    try:
        message=await bot.get_channel(485322302603657218).get_message(message_id)
    except discord.NotFound:
        #not found
        return
    if not message.attachments:
        #no attach
        return
    if not target:
        target="data/"
    dirname = os.path.dirname(__file__)
    filename = os.path.join(dirname, target+message.attachments[0].filename)
    try:
        await message.attachments[0].save(filename)
        await ctx.send("save "+filename+" successful")
    except:
        await ctx.send("save "+filename+" failed")
        pass #fail

async def SIGTERM_exit():
    await bot.get_channel(483242913807990806).send(bot.user.name+" has stopped by SIGTERM")
    logging.warning(bot.user.name+" has stopped by SIGTERM")

def SIG_EXIT():
    logging.warning(bot.user.name+" has stopped by SIGTERM-")
    print("bye")
if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    bot.remove_command('help')
    try:
        bot.loop.add_signal_handler(signal.SIGTERM,SIG_EXIT)
        #asyncio.get_event_loop().add_signal_handler(signal.SIGTERM,lambda: asyncio.ensure_future(SIGTERM_exit()))
    except NotImplementedError:
        pass #run in windows

    bot.run(TOKEN)