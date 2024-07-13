import discord
import pickle

from discord.ext import commands
from discord import app_commands
from typing import Optional
from logging import getLogger
from traceback import format_exc
#from aiofile import async_open
from os import path
from random import randint
from asyncio import create_task, sleep as aio_sleep
from datetime import datetime
from config import Config

class MiscCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = getLogger('market_bot.misc')
        self.queries = {}
        self.guild = None

    def _set_essentials(self, session):
        pass

    def set_guild(self, guild_id):
        self.guild = self.bot.get_guild(guild_id)

    @app_commands.command(
        name='delete',
        description='Delete the thread from which it was called'
    )
    async def delete(self, interaction: discord.Interaction):
        channel = interaction.channel
        if channel.type == discord.ChannelType.public_thread and channel.parent_id in Config.CHANNEL_ID.values():
            cogName = [k for k, v in Config.CHANNEL_ID.items() if v == channel.parent_id][0]
            cog = self.bot.get_cog(cogName)
            await cog.delete_thread(channel)
        else:
            await interaction.response.send_message('This thread is not managed by market bot', ephemeral=True)

    @app_commands.command(
        name='manage',
        description='Manage queries assigned to current thread'
    )
    async def manage(self, interaction: discord.Interaction):
        channel = interaction.channel
        if channel.type == discord.ChannelType.public_thread and channel.parent_id in Config.CHANNEL_ID.values():
            cogName = [k for k, v in Config.CHANNEL_ID.items() if v == channel.parent_id][0]
            cog = self.bot.get_cog(cogName)
            await cog.manage(interaction)
        else:
            await interaction.response.send_message('This thread is not managed by market bot', ephemeral=True)

    @app_commands.command(
        name='cleanup',
        description='Removes last n messages from channel'
    )
    @app_commands.describe(amount='Number of messages to purge')
    async def cleanup(self, interaction: discord.Interaction, amount: int):
        try:
            await interaction.response.defer()
            await interaction.channel.purge(limit=amount+1)
        except Exception as e:
            self.logger.info(f'Failed to purge messages: {format_exc()}')

            
async def setup(bot):
    await bot.add_cog(MiscCommands(bot))