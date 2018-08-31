import discord
from discord.ext import commands
import importlib
import logging

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

@bot.command()
async def cmd(ctx, *, cmd:str):
    try:
        ret=eval(cmd)
        logging.info("eval({0}) successed ,return:\n{1}".format(cmd,ret))
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
        logging.info("logger {0} 's level changed from {1} to {0.level}({2})".format(logger,level_old,level.upper()))
        await ctx.send("change success")
    except:
        logging.warning("change {0}'s level to {1} failed".format(logger,level))
        await ctx.send("change failed")

if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    bot.remove_command('help')

    bot.run(TOKEN)