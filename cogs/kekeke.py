
import discord
from discord.ext import commands


class Kekeke(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.load_extension('cogs.detector')


def setup(bot: commands.Bot):
    bot.add_cog(Kekeke(bot))
