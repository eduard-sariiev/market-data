import pickle

from discord.ext import commands
from discord import app_commands, Embed, Interaction, ButtonStyle, ChannelType, SelectOption, Thread, ui as discord_ui
from typing import Optional
from logging import getLogger
from cogs.parsers.ebay_parser import EbayParser
from traceback import format_exc
from os import path
from random import randint
from asyncio import create_task, sleep as aio_sleep
from datetime import datetime
from config import Config

class SmolEbayDropdown(discord_ui.Select):
    def __init__(self, cog, view, options):
        self._cog = cog
        self._view = view
        print(self._cog.queries)
        super().__init__(placeholder='Select queries you want to remove..', min_values=1, max_values=len(options), options=options, row=0)

    async def callback(self, interaction: Interaction):
        for val in self.values:
            self._cog.queries[interaction.channel_id]['kwargs'].pop(int(val))
        await interaction.response.send_message(f"**{len(self.values)}** {('queries' if len(self.values) > 1 else 'query')} {('were' if len(self.values) > 1 else 'was')} removed", ephemeral=True)
        self._cog.save_queries_to_file()
        self._view.stop()


class SmolEbayManageView(discord_ui.View):
    def __init__(self, cog, options):
        super().__init__()
        self.value = True
        self.add_item(SmolEbayDropdown(cog, self, options))

    @discord_ui.button(label='Cancel', style=ButtonStyle.danger, row=1)
    async def cancel(self, interaction: Interaction, button: discord_ui.Button):
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self):
        pass


class SmolEbayCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = getLogger('market_bot.kleinanzeigen')
        self.queries = {} # thread id : {name, kwargs, jump_url}
        self.filepath = f'{Config.CACHE_PATH}/ebay_queries.json'
        self.guild = None
        self.manage_msg = None
        self.load_queries_from_file()

    def _set_essentials(self, session):
        self._session = session
        self.parser = EbayParser(self._session)
        self.worker = create_task(self.keep_updated())

    def set_guild(self, guild):
        self.guild = guild
    
    @app_commands.command(
            name='sebay_search',
            description='Create thread for specified query')
    @app_commands.describe(text='Search terms', exclude='Keywords in title to exclude from results', min_price='Minimum price', max_price='Maximum price')
    async def sebay_search(self, interaction: Interaction, text : str, exclude: Optional[str] = '', min_price: Optional[int] = 0, max_price: Optional[int] = 350):
        search_args = {
                    'query' : text,
                    'minPrice' : min_price,
                    'maxPrice' : max_price,
                    'exclude' : exclude
                }
        channel = interaction.channel
        if channel.type == ChannelType.text and channel.id == Config.CHANNEL_ID['SmolEbayCommands']:
            try:
                new_thread = await channel.create_thread(name=text[:30], type=ChannelType.public_thread, reason='Kleinanzeigen Parser')
                self.queries[new_thread.id] = {
                    'name' : new_thread.name,
                    'kwargs' : [search_args],
                    'jump_url' : new_thread.jump_url
                }
                await interaction.response.send_message(f'Subscribed to {new_thread.jump_url}')
                self.save_queries_to_file()
            except Exception as e:
                self.logger.error(f'Failed to create thread with {search_args} due to: {format_exc()}')
                await interaction.response.send_message('Failed to create thread, check logs', ephemeral=True)
        elif channel.type == ChannelType.public_thread and channel.id in self.queries.keys():
            self.queries[channel.id]['kwargs'].append(search_args)
            await interaction.response.send_message(f'`{text}`[{min_price}:{max_price}] was added to {self.queries[channel.id]["jump_url"]}', ephemeral=True)
        else:
            await interaction.response.send_message('Queries cannot be submitted from here', ephemeral=True)

    async def delete_thread(self, thread: Thread):
        if thread.id in self.queries.keys():
            del self.queries[thread.id]
            self.save_queries_to_file()
        else:
            self.logger.warning(f'Was asked to delete thread `{thread.name}` but it was not found in cache')
        await thread.delete()

    async def manage(self, interaction: Interaction):
        thread = interaction.channel
        thread_args = self.queries.get(thread.id, None)
        if thread_args:
            options = [SelectOption(label=f"{el['query']} ({el['exclude']}) [{el['minPrice']}:{el['maxPrice']}]", value=f'{idx}') for idx, el in enumerate(thread_args['kwargs'])]
            view = SmolEbayManageView(self, options)
            await interaction.response.send_message('Select queries you want to remove..', view=view)
            await view.wait()
            await interaction.delete_original_response()
        else:
            await interaction.response.send_message('This thread is not managed by market bot', ephemeral=True)

    def save_queries_to_file(self):
        with open(self.filepath, 'wb') as f:
            pickle.dump(self.queries, f)

    def load_queries_from_file(self):
        if path.isfile(self.filepath):
            with open(self.filepath, 'rb') as f:
                self.queries = pickle.load(f)
                print(f'Loaded queries: {self.queries}')

    def get_ebay_embed(self, ad_id):
        ad = self.parser.cached_ads[ad_id]
        if type(ad['publish_date']) != datetime:
            ad['publish_date'] = datetime.fromisoformat(ad['publish_date'])
        price_text = ' '.join([f'{ad["price"]}€', ad['vb'], ('✅' if ad['safe_payment'] else '')])
        embed = Embed(title=ad['title'], description=ad['description'], timestamp=ad['publish_date'], url=ad['link']) \
        .set_footer(text=ad['address']).set_author(name=ad['sellerName']) \
        .add_field(name='Price', value=price_text) \
        .add_field(name='Shipping', value=('Moglich' if ad['versand'] else 'Nur Abholdung'))
        if ad['averageRating']:
            embed.add_field(name='User Score', value=round(ad['averageRating'], 2))
        if ad.get('img', None):
            embed.set_image(url=ad['img'])
        return ad['title'], price_text, embed
            
    async def keep_updated(self):
        await self.bot.wait_until_ready()
        while True:
            if self.guild:
                to_delete = []
                for thread_id, v in self.queries.items():
                    try:
                        thread = self.guild.get_channel_or_thread(thread_id)
                        if thread:
                            for kwargs in v['kwargs']:
                                await self.parser.search(**kwargs)
                                for ad_id in self.parser.non_announced:
                                    title, price, embed = self.get_ebay_embed(ad_id)
                                    await thread.send(content=f'<@&{Config.SMOL_EBAY_MENTION_ROLE}> {title} **{price}**', embed=embed)
                                    await aio_sleep(0.5)
                                self.parser.non_announced = []   
                        else:
                            to_delete.append(thread_id)
                            continue
                        await aio_sleep(2)
                    except Exception as e:
                        self.logger.error(f'Error during update: {format_exc()}')
                await self.parser.save_ads_to_file()
                for id in to_delete:
                    del self.queries[id]
                self.save_queries_to_file()
            await aio_sleep(randint(Config.SMOL_EBAY_UPDATE_INTERVAL*0.5, Config.SMOL_EBAY_UPDATE_INTERVAL*1.5))

    def cog_unload(self):
        self.worker.cancel()


async def setup(bot):
    await bot.add_cog(SmolEbayCommands(bot))