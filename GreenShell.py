import asyncio
import logging
import os
import re
import signal
import time
from datetime import datetime

import boto3
import discord
import ptvsd
import tzlocal
from discord.ext import commands

ptvsd.enable_attach(address=('localhost', 5678), redirect_output=True)

CUBENAME = re.search(r"(?<=/)[^/]+$", os.getenv("CLOUDCUBE_URL"), re.IGNORECASE).group(0)


def DownloadAllFiles():
    s3 = boto3.resource("s3")
    for obj in s3.Bucket("cloud-cube").objects.filter(Prefix=f"{CUBENAME}/"):
        if obj.key[-1] != "/":
            dirname = os.path.dirname(__file__)
            filename = re.search(r"(?<=\/)[^\/]+$", obj.key).group(0)
            filepath = os.path.join(dirname, f"data/{filename}")

            s3.Bucket("cloud-cube").download_file(obj.key, filepath)


class GreenShell(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.load_extension('cogs.kekeke')

    @commands.Cog.listener()
    async def on_ready(self):
        self.stdout = self.bot.get_channel(483242913807990806)
        logging.info(f"{self.bot.user.name}({self.bot.user.id})已上線")
        await self.stdout.send(f"{self.bot.user.name}已上線{self.bot.command_prefix}")

    @commands.command()
    async def hi(self, ctx: commands.Context):
        await ctx.send("Hello")

    @commands.command(name="eval")
    async def _eval(self, ctx: commands.Context, *, cmd: str):
        try:
            ret = eval(cmd)
            resstr = ""
            try:
                resstr = str(ret)
            except expression as identifier:
                resstr = repr(ret)

            if len(resstr) > 1018:
                resstr = f"{resstr[:1015]}..."

            embed = discord.Embed(timestamp=tzlocal.get_localzone().localize(datetime.now()), color=discord.Color.green())
            embed.set_author(name=ctx.message.author.display_name, icon_url=ctx.message.author.avatar_url)
            embed.add_field(name=f"{cmd}", value=f"```{resstr}```")
            embed.set_footer(text=self.bot.user.display_name, icon_url=self.bot.user.avatar_url)
            logging.info(f"eval({cmd})成功，返回：{resstr}")
            await ctx.send(embed=embed)
        except Exception:
            logging.warning(f"eval({cmd}) 失敗或無法顯示")
            await ctx.send(f"`eval({cmd})`失敗或無法顯示")

    @commands.command()
    async def loglevel(self, ctx: commands.Context, level: str, logger_name: str = ""):
        logger = logging.getLogger(logger_name)
        level_new = level.upper()
        try:
            logger.setLevel(eval(f"logging.{level_new}"))
            logging.debug(f"logger{logger_name}的等級修改為{level_new}")
            await ctx.send(f"logger`{logger_name}`的等級修改為`{level_new}`")
        except Exception:
            logging.warning(f"無法把{logger_name}的等級修改為{level}")
            await ctx.send(f"無法把`{logger_name}`的等級修改為`{level}`")

    async def bot_check_once(self, ctx: commands.Context):
        return await self.bot.is_owner(ctx.author) and ctx.channel.id == self.stdout.id


bot = commands.Bot(command_prefix=os.getenv("DISCORD_PREFIX"), owner_id=152965086951112704)


async def SIGTERM_exit():
    await self.stdout.send(f"{bot.user.name} has stopped by SIGTERM")
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
    bot.add_cog(GreenShell(bot))
    try:
        signal.signal(signal.SIGTERM, SIG_EXIT)
        asyncio.get_event_loop().add_signal_handler(signal.SIGTERM, SIG_EXIT)
        bot.loop.add_signal_handler(signal.SIGTERM, SIG_EXIT)
    except NotImplementedError:
        pass  # run in windows

    bot.run(os.getenv("DISCORD_TOKEN"))
