import discord
from discord.ext import commands
import importlib
import logging
import os
import kwdetector as kd
import kekekemonitor as km

TOKEN="NDgzMjQxMTQzODM2OTk5Njkx.DmQmDg.9YVzFdm_zE3ulbKCN1YULe_phlA"

bot = commands.Bot(command_prefix='$',owner_id=152965086951112704)

@bot.event
async def on_ready():
    logging.info("Logged in as {0.user.name}({0.user.id})".format(bot))
    await bot.get_channel(483242913807990806).send(bot.user.name+" is ONLINE now")

@bot.event
async def on_message(message:discord.Message):
    if await (bot.is_owner(message.author) or message.author==bot.user) and message.channel.id==483242913807990806:
        await bot.process_commands(message)
       
@bot.command()
async def kekeke(ctx):
    detector=kd.KWDetector(bot.get_channel(483268806072991794))
    try:
        await detector.PeriodRun(30)
        await ctx.send("stopped kekeke HP moniter")
    except:
        logging.error("moniter kekeke HP stopped unexcept")
        await ctx.send("moniter kekeke HP stopped unexcept")


@bot.command()
async def moniter(ctx,kchannel:str):
    monitor=km.KekekeMonitor(kchannel,bot,483925945494011906)
    try:
        await monitor.PeriodRun(30)
        await ctx.send("stopped "+kchannel+" moniter")
    except:
        logging.error("moniter "+kchannel+" stopped unexcept")
        await ctx.send("moniter "+kchannel+" stopped unexcept")
    

@bot.command()
async def hi(ctx):
    await ctx.send("Hello")

@bot.command()
async def cmd(ctx, *, cmd:str):
    try:
        ret=eval(cmd)
        logging.debug("eval({0}) successed ,return:\n{1}".format(cmd,ret))
        await ctx.send("`{0}`".format(ret))
    except:
        logging.warning("eval({0}) failed".format(cmd))
        await ctx.send("`eval({0})` failed".format(cmd))

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



if __name__=="__main__":
    logging.basicConfig(level=logging.WARNING)
    bot.remove_command('help')

    bot.run(TOKEN)