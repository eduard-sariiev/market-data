import discord
import logging
import asyncio

from discord.ext import commands
from typing import List, Optional
from aiohttp import ClientSession
from config import Config

from traceback import format_exc
from color_format import ColorFormatter
from logging.handlers import RotatingFileHandler

# Logging setup
log = logging.getLogger("market_bot")
log.setLevel(logging.DEBUG)

fh = RotatingFileHandler(
        filename=Config.LOG_FILE,
        encoding='utf-8',
        maxBytes=Config.LOG_SIZE,  
        backupCount=5,  # Rotate through 5 files
)
fh.setLevel(logging.INFO)
fh.setFormatter(logging.Formatter('[{asctime}] [{levelname}] {name}: {message}', '%Y-%m-%d %H:%M:%S', style='{'))

# create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(ColorFormatter())

log.addHandler(fh)
log.addHandler(ch)

MY_GUILD_ID = 890577646998667275
MY_GUILD = discord.Object(id=MY_GUILD_ID)  # replace with your guild id

class Daikon(commands.Bot):
    def __init__(self, *args, initial_exts: List[str], session:ClientSession, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial_exts = initial_exts
        self.session = session

    # In this basic example, we just synchronize the app commands to one guild.
    # Instead of specifying a guild to every command, we copy over our global commands instead.
    # By doing so, we don't have to wait up to an hour until they are shown to the end-user.
    async def setup_hook(self):
        # Load all supplied cogs
        for ext in self.initial_exts:
            await self.load_extension(ext)

        for cog_name, cog in self.cogs.items():
            log.info(f'Loaded {cog_name}')
            cog._set_essentials(self.session)

        # This copies the global commands over to your guild.
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)

    async def on_ready(self):
        log.info(f'Logged in as {self.user} (ID: {self.user.id})')
        guild = self.get_guild(MY_GUILD_ID)
        for _, cog in self.cogs.items():
            if hasattr(cog, 'set_guild') and callable(cog.set_guild):
                cog.set_guild(guild)

    async def on_command_error(self, context: commands.Context, exception: commands.CommandError) -> None:
        log.error(f'{context} {exception}')


async def main():
    exts = ['cogs.ebay_commands', 'cogs.misc_commands', 'cogs.big_ebay_commands']
    intents = discord.Intents.default()
    intents.message_content = True
    async with ClientSession(trust_env=True) as s:
        async with Daikon(
            commands.when_mentioned,
            initial_exts=exts,
            session=s,
            intents=intents
        ) as bot:
            await bot.start(Config.TOKEN)

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print('Shutting down')
    