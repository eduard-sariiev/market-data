import discord
import pickle

from discord.ext import commands, tasks
from discord import app_commands, Embed, ui
from typing import Optional
from logging import getLogger

from discord.utils import MISSING
from cogs.parsers.big_ebay_parser import BigEbayParser
from traceback import format_exc
from os import path
from random import randint
from asyncio import sleep as aio_sleep, create_task, CancelledError, TimeoutError
from datetime import datetime
from config import Config
from time import time

# class ListExistingView(ui.View):
#     def __init__(self, options):
#         super().__init__()
#         self.cancelled = False
#         self.listingView = SearchCreateDropdown('Select queries to manage..', min_values=1, max_values=1, options=options)

#     @ui.Button(label='Cancel', style=discord.ButtonStyle.danger, row=1)
#     async def cancel(self, interaction: discord.Interaction, button: ui.Button):
#         self.cancelled = True
#         await interaction.defer()
#         self.stop()

class TargetModal(ui.Modal, title="Target this listing"):
    maxPrice = ui.TextInput(
        label="Maximum price",
        style=discord.TextStyle.short,
        placeholder="Maximum price..",
        required=True)
    
    bidTime = ui.TextInput(
        label="Bid at (in seconds)",
        style=discord.TextStyle.short,
        default=2,
        required=True)
    
    
    async def on_submit(self, interaction: discord.Interaction):
        self.maxPrice = self.maxPrice.value
        self.bidTime = self.bidTime.value
        self.formInteraction = interaction
        self.stop()

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await interaction.response.send_message(f'Error occured during targeting: {error.with_traceback()}', ephemeral=True)

class SearchModal(ui.Modal, title="Create new search"):
    query = ui.TextInput(
        label="Text",
        style=discord.TextStyle.short,
        placeholder="Text to search here..",
        required=True)
    
    minPrice = ui.TextInput(
        label="Minimum price",
        style=discord.TextStyle.short,
        placeholder="Minimum price..",
        required=False,
        row=1)
    maxPrice = ui.TextInput(
        label="Maximum price",
        style=discord.TextStyle.short,
        placeholder="Maximum price..",
        required=False,
        row=2)

    async def on_submit(self, interaction: discord.Interaction):
        self.query = self.query.value
        self.minPrice = self.minPrice.value
        self.maxPrice = self.maxPrice.value
        self.formInteraction = interaction
        self.stop()
    
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await interaction.response.send_message(f'Error occured during search creation: {error.with_traceback()}', ephemeral=True)

class SearchCreateDropdown(ui.Select):
    def __init__(self, placeholder, min_values=0, max_values=0, options=[]):
        max_values = max_values if max_values else len(options)-1
        super().__init__(placeholder=placeholder, min_values=min_values, max_values=max_values, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

class SearchCreateView(ui.View):
    def __init__(self, condTypes, listTypes, sellerTypes, sortTypes, locTypes, catName):
        super().__init__()
        self.catName = catName
        self.skipCategory = False
        self.submitted = False
        self.conditionView = SearchCreateDropdown('Select item condition..', options=condTypes)
        self.listingTypeView = SearchCreateDropdown('Select listing format..', options=listTypes)
        self.sellerTypeView = SearchCreateDropdown('Private or Business..', options=sellerTypes)
        self.sortTypeView = SearchCreateDropdown('Sort by..', max_values=1, options=sortTypes)
        #self.locTypeView = SearchCreateDropdown('Location..', max_values=1, options=locTypes)
        self.add_item(self.conditionView)
        self.add_item(self.listingTypeView)
        self.add_item(self.sellerTypeView)
        #self.add_item(self.sortTypeView)
        #self.add_item(self.locTypeView)

    @ui.button(label='Submit', style=discord.ButtonStyle.success, row=3)
    async def submit(self, interaction: discord.Interaction, button: ui.Button):
        self.selectedConditions = self.conditionView.values
        self.selectedListingTypes = self.listingTypeView.values
        self.selectedSellerTypes = self.sellerTypeView.values
        self.selectedSortTypes = self.sortTypeView.values
        #self.selectedPrefLocTypes = self.locTypeView.values
        self.submitted = True
        await interaction.response.defer()
        self.stop()

    @ui.button(label='Toggle Category', style=discord.ButtonStyle.gray, row=3)
    async def toggle(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        self.skipCategory = not self.skipCategory
        if self.skipCategory:
            await interaction.edit_original_response(content='`Suggested category was discarded`', view=self)
        else:
            await interaction.edit_original_response(content=f'Category: `{self.catName}`', view=self)

    @ui.button(label='Cancel', style=discord.ButtonStyle.danger, row=4)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message('Search submission was canceled by user')
        self.stop()
    
class BigEbayCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = getLogger('market_bot.ebay')
        self.queries = {} # thread id : {name, params, jump_url}
        self.targets = {}
        self.targetTasks = {}
        self.filepath = f'{Config.CACHE_PATH}/big_ebay_queries.json'
        self.guild = None
        self.manage_msg = None
        self.parser = None
        self.prepare_options()
        self.load_queries_from_file()
        self.worker = create_task(self.keep_updated())
        self.ctx_menu_target = app_commands.ContextMenu(
            name='Target',
            callback=self.target_menu,
        )
        self.bot.tree.add_command(self.ctx_menu_target)

    def _set_essentials(self, session):
        self.parser: BigEbayParser = BigEbayParser(session)

    def cog_unload(self):
        self.worker.cancel()
        self.bot.tree.remove_command(self.ctx_menu_target.name, type=self.ctx_menu_target.type)

    def prepare_options(self):
        conditions = {
            10: "Not specified",
            1000: "New",
            1500: "New (see details)",
            2000: "Certified - Refurbished",
            2010: "Excellent - Refurbished",
            2020: "Very good - Refurbished",
            2030: "Good - Refurbished",
            2500: "Refurb by seller",
            3000: "Used",
            7000: "For parts"
        }
        self.conditionOptions = [discord.SelectOption(label=v, value=k) for k, v in conditions.items()]
        
        listingTypes = {
            1: "Auction",
            2: "Buy Now",
            4: "Best Offer"
        }
        self.listingOptions = [discord.SelectOption(label=v, value=k) for k, v in listingTypes.items()]

        sellerTypes = {
            1: 'Private',
            2: 'Business'
        }
        self.sellerOptions = [discord.SelectOption(label=v, value=k) for k, v in sellerTypes.items()]

        sortTypes = {
            1: 'Ending Soonest',
            7: 'Nearest first',
            10: 'Newly Listed',
            12: 'Best Match',
            15: 'Lowest Price',
            16: 'Highest Price'
        }
        self.sortOptions = [discord.SelectOption(label=v, value=k) for k, v in sortTypes.items()]

        prefLocTypes = {
            0: 'Standard',
            1: 'Germany',
            3: 'EU',
            6: 'Europe',
            2: 'Worldwide',
            #99: 'In Range'
        }
        self.prefLocOptions = [discord.SelectOption(label=v, value=k) for k, v in prefLocTypes.items()]



    def set_guild(self, guild):
        self.guild = guild
    
    @app_commands.command(
            name='ebay_search',
            description='Create thread for specified query')
    async def ebay_search(self, interaction: discord.Interaction):
        channel = interaction.channel
        if channel.type == discord.ChannelType.text and channel.id == Config.CHANNEL_ID['BigEbayCommands']:
            try:
                searchModal = SearchModal()
                await interaction.response.send_modal(searchModal)
                await searchModal.wait()
                params = self.parser.get_params(query=searchModal.query, sortBy=10, full=False)
                try:
                    if searchModal.minPrice:
                        searchModal.minPrice = int(searchModal.minPrice)
                        assert searchModal.minPrice >= 0
                    if searchModal.maxPrice:
                        searchModal.maxPrice = int(searchModal.maxPrice)
                        assert searchModal.maxPrice >= 1
                except Exception as e:
                    await searchModal.formInteraction.response.send_message(f'Error during form submission, try again\n{e}')
                    return
                catCode, catName = await self.parser.get_category(params)
                searchView = SearchCreateView(self.conditionOptions, self.listingOptions, self.sellerOptions, self.sortOptions, self.prefLocOptions, catName)
                await searchModal.formInteraction.response.send_message(f'Category: `{catName}`', view=searchView, delete_after=120, ephemeral=True)
                await searchView.wait()
                if searchView.submitted:
                    listingTypes = sum([int(x) for x in searchView.selectedListingTypes])
                    sellerTypes = int(searchView.selectedSellerTypes[0]) if searchView.selectedSellerTypes else 0
                    catCode = 0 if searchView.skipCategory else catCode
                    sortType = int(searchView.selectedSortTypes[0]) if searchView.selectedSortTypes else 10
                    #prefLocType = int(searchView.selectedPrefLocTypes[0]) if searchView.selectedPrefLocTypes else 0
                    params = self.parser.get_params(query=searchModal.query, minPrice=searchModal.minPrice, maxPrice=searchModal.maxPrice, sellerType=sellerTypes, location=1, condition=searchView.selectedConditions, listingType=listingTypes, category=catCode, sortBy=sortType)
                    new_thread = await channel.create_thread(name=searchModal.query[:30], type=discord.ChannelType.public_thread, reason='Ebay Scrapper')
                    await new_thread.send(f'`{searchModal.query}` with price range from `{searchModal.minPrice}`€ to `{searchModal.maxPrice}`€')
                    self.queries[new_thread.id] = {
                        'name' : new_thread.name,
                        'params' : params,
                        'jump_url' : new_thread.jump_url,
                        'firstTime' : True,
                        'mention' : interaction.user.mention
                    }
                    self.save_queries_to_file()
            except Exception as e:
                self.logger.error(f'{format_exc()}')
        else:
            await interaction.response.send_message('Queries cannot be submitted from here', ephemeral=True)

    async def delete_thread(self, thread: discord.Thread):
        if thread.id in self.queries.keys():
            del self.queries[thread.id]
            self.save_queries_to_file()
        else:
            self.logger.warning(f'Was asked to delete thread `{thread.name}` but it was not found in cache')
        await thread.delete()

    async def manage(self, interaction: discord.Interaction):       
        await interaction.response.send_message('Not implemented', ephemeral=True)

    async def wait_until(self, until_ts):
        # sleep until the specified datetime
        await aio_sleep(until_ts-time())

    async def run_at(self, ts, coro, listing_id):
        try:
            await self.wait_until(ts)
            return await coro
        except CancelledError:
            self.logger.info('Cancelled task')
            if listing_id in self.targets.keys():
                self.targets.pop(listing_id)
            await coro
            self.targetTasks.pop(listing_id)

    async def targetListing(self, listing_id, price, sid=None):
        if listing_id in self.targets.keys():
            highest, text = await self.parser.place_bid(listing_id, price, sid)
            channel : discord.Thread = await self.bot.fetch_channel(self.targets[listing_id]['threadId'])
            if channel:
                await channel.send(text)
            infoMsg = await channel.fetch_message(self.targets[listing_id]['infoMsgId'])
            if infoMsg:
                await infoMsg.delete()
            if highest:
                listings_id_to_delete = []
                targetThreadId = self.targets[listing_id]['threadId']
                for k, v in self.targets:
                    if k != listing_id:
                        if v['threadId'] == targetThreadId:
                            infoMsg = await channel.fetch_message(self.targets[listing_id]['infoMsgId'])
                            if infoMsg:
                                await infoMsg.delete()
                            listings_id_to_delete.append(k)
                for listingid in listings_id_to_delete:
                    self.targets.pop(listing_id)
                    if listingid in self.targetTasks.keys():
                        self.targetTasks[listingid].cancel()
                await channel.send('All other targets were unscheduled')

            self.targets.pop(listing_id)
            self.targetTasks.pop(listing_id)


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload : discord.RawReactionActionEvent):
        if payload.channel_id in self.queries.keys() and str(payload.emoji) == '🎯':
            channel = await self.bot.fetch_channel(payload.channel_id)
            message : discord.Message = await channel.fetch_message(payload.message_id)
            user :discord.User = await self.bot.fetch_user(payload.user_id)
            if user.id != self.bot.user.id:
                try:
                    listing_id = int(message.content.split('ebay.de/itm/')[1].split(')')[0])
                    if listing_id in self.targets.keys():
                        targetTask = self.targetTasks[listing_id]
                        infoMsg = await channel.fetch_message(self.targets[listing_id]['infoMsgId'])
                        if infoMsg:
                            await infoMsg.delete()
                        targetTitle = self.targets[listing_id]['targetTitle']
                        self.targets.pop(listing_id, None)
                        targetTask.cancel()
                        await channel.send(f'{user.mention}, listing **{targetTitle}** was removed from schedule', delete_after=60)
                except Exception as e:
                    self.logger.info(f'{format_exc()}')

    async def target_menu(self, interaction: discord.Interaction, message: discord.Message):
        if len(message.embeds) > 0 and message.channel.id in self.queries.keys():
            try:
                listingEmbed = message.embeds[0]
                listingId = int(listingEmbed.url.split('/')[-1])
                listingName = listingEmbed.title
                if listingId in self.targets.keys():
                    await interaction.response.send_message(f'Selected listing is already targeted', ephemeral=True)
                else:
                    listing = await self.parser.getAuction(listingId)
                    if listing:
                        if listing.get('isAuction'):
                            targetModal = TargetModal()
                            await interaction.response.send_modal(targetModal)
                            await targetModal.wait()
                            try:
                                price = float(targetModal.maxPrice)
                                bidOffset = int(targetModal.bidTime)
                                targetTime = listing['endDate']-bidOffset
                                msgText = f"Auction started at <t:{listing['startDate']}>\nAuction ends at <t:{listing['endDate']}>\nWill bid **{price:.2f}**€ <t:{targetTime}:R>"
                                listingUrl = f'https://www.ebay.de/itm/{listingId}'
                                await targetModal.formInteraction.response.send_message(f'{interaction.user.mention},\n[{listingName}]({listingUrl})\n\n{msgText}', suppress_embeds=True)
                                infoMsg = await targetModal.formInteraction.original_response()
                                self.targets[listingId] = {
                                    'targetTime' : targetTime,
                                    'sid' : listing['sid'],
                                    'infoMsgId' : infoMsg.id,
                                    'threadId' : message.channel.id,
                                    'targetTitle' : listing['title'],
                                }
                                self.targetTasks[listingId] = create_task(self.run_at(targetTime, self.targetListing(listingId, price, listing['sid']), listingId))
                                await infoMsg.add_reaction('🎯')
                            except Exception as e:
                                await interaction.channel.send(f'{interaction.user.mention}, error during bid scheduling: {format_exc()}', delete_after=60)
                        else:
                            await interaction.response.send_message(f'Listing isn\'t an auction', ephemeral=True)    
                    else:
                        await interaction.response.send_message(f'Listing with id **{listingId}** doesn\'t exist', ephemeral=True)
            except Exception as e:
                self.logger.error(f'{format_exc()}')
        else:
            await interaction.response.send_message("App can't be called from here", ephemeral=True)

    @app_commands.command(
            name='target',
            description='Target listing with ID'
    )
    @app_commands.describe(listing_id="ID of listing to target", price="Price to target", target_at="Target at")
    async def target(self, interaction: discord.Interaction, listing_id: int, price:float, target_at:int=2):
        if listing_id in self.targets.keys():
            await interaction.response.send_message('Selected listing is already targeted', ephemeral=True)
            return
        try:
            listing = await self.parser.getAuction(listing_id)
            if listing:
                if listing.get('isAuction'):
                    targetTime = listing['endDate']-target_at
                    msgText = f"Auction started at <t:{listing['startDate']}>\nAuction ends at <t:{listing['endDate']}>\nWill bid **{price:.2f}**€ <t:{targetTime}:R>"
                    listingUrl = f'https://www.ebay.de/itm/{listing_id}'
                    await interaction.response.send_message(f'{interaction.user.mention},\n[{listing["title"]}]({listingUrl})\n\n{msgText}', suppress_embeds=True)
                    infoMsg = await interaction.original_response()
                    self.targets[listing_id] = {
                        'targetTime' : targetTime,
                        'sid' : listing['sid'],
                        'infoMsgId' : infoMsg.id,
                        'threadId' : interaction.channel_id,
                        'targetTitle' : listing['title'],
                    }
                    self.targetTasks[listing_id] = create_task(self.run_at(targetTime, self.targetListing(listing_id, price, listing['sid']), listing_id))
                    await infoMsg.add_reaction('🎯')
                else:
                    await interaction.response.send_message(f'Listing isn\'t an auction', ephemeral=True)    
            else:
                await interaction.response.send_message(f'Listing with id **{listing_id}** doesn\'t exist', ephemeral=True)
        except Exception as e:
            await interaction.channel.send(f'{interaction.user.mention}, Error during targeting: {format_exc()}', delete_after=60)

    @app_commands.command(
            name='untarget',
            description='Untarget listing with ID'
    )
    @app_commands.describe(listing_id="ID of listing to untarget")
    async def untarget(self, interaction: discord.Interaction, listing_id: int):
        try:
            if listing_id in self.targets.keys():
                targetTask = self.targetTasks[listing_id]
                infoMsg = await interaction.channel.fetch_message(self.targets[listing_id]['infoMsgId'])
                if infoMsg:
                    await infoMsg.delete()
                targetTitle = self.targets[listing_id]['targetTitle']
                self.targets.pop(listing_id, None)
                targetTask.cancel()
                #self.targetTasks.pop(listingId, None)
                await interaction.response.send_message(f'Listing **{targetTitle}** was removed from schedule', delete_after=60)
        except Exception as e:
            self.logger.error(f'{format_exc()}')

    def save_queries_to_file(self):
        with open(self.filepath, 'wb') as f:
            pickle.dump(self.queries, f)

    def load_queries_from_file(self):
        if path.isfile(self.filepath):
            with open(self.filepath, 'rb') as f:
                self.queries = pickle.load(f)
                print(f'Loaded queries: {self.queries}')
            for _, v in self.queries.items():
                v['firstTime'] = True

    def get_auction_left_time(self, endDate):
        diff = datetime.now() - endDate
        days = diff.days
        diff_seconds = diff.total_seconds()
        hours = divmod(diff_seconds, 60*60)[0]
        minutes = divmod(diff_seconds, 60)[0]
        return f"{days}d {hours}h {minutes}m"

    def get_ebay_embed(self, ad_id):
        ad = self.parser.cached_ads[ad_id]
        price_text = f"{ad['price']}€ {ad['shipping']}"
        embed = Embed(title=ad['title'], url=ad['url']) \
        .set_author(name=f"{ad['sellerName']}, {ad['sellerType']}", url=ad['userUrl']) \
        .add_field(name=f'{("Current price" if ad["isAuction"] else "Price")}', value=price_text) \
        .add_field(name='Condition', value=ad['condition'])
        if ad['isAuction']:
            # embed.timestamp = datetime.fromtimestamp(ad['startDate'])
            if ad.get('endDate'):
                embed.add_field(name='Ends in', value=self.get_auction_left_time(datetime.fromtimestamp(ad['endDate'])))
            buyNowText = f'Buy Now\n' if ad['buyNow'] else ''
            priceSuggestionText = f'Preisvorschlag' if ad['priceSuggestion'] else ''
            embed.add_field(name='Auction', value=f'{buyNowText}{priceSuggestionText}')
        if ad.get('img'):
            embed.set_image(url=ad['img'])
        return ad['title'], price_text, embed, ad['isAuction']

    async def keep_updated(self):
        await self.bot.wait_until_ready()
        while True:
            if self.guild and self.parser:
                to_delete = []
                for thread_id, v in self.queries.items():
                    try:
                        thread = self.guild.get_channel_or_thread(thread_id)
                        if thread:
                            await self.parser.search_offers(v['params'], v['firstTime'])
                            if v['firstTime']:
                                v['firstTime'] = False
                            for ad_id in self.parser.non_announced:
                                title, price, embed, isAuction = self.get_ebay_embed(ad_id)
                                listingMsg = await thread.send(content=f'{v["mention"]} {title} **{price}**', embed=embed)
                                await aio_sleep(0.5)
                            self.parser.non_announced = []   
                        else:
                            to_delete.append(thread_id)
                            continue
                        await aio_sleep(2)
                    except Exception as e:
                        self.logger.error(f'Error during update: {format_exc()}')
                #await self.parser.save_ads_to_file()
                for id in to_delete:
                    del self.queries[id]
                self.save_queries_to_file()
            await aio_sleep(randint(Config.EBAY_UPDATE_INTERVAL*0.5, Config.EBAY_UPDATE_INTERVAL*1.5))
            #self.keep_updated.change_interval(seconds=randint(Config.EBAY_UPDATE_INTERVAL*0.5, Config.EBAY_UPDATE_INTERVAL*1.5))

    def cog_unload(self):
        self.worker.cancel()


async def setup(bot):
    await bot.add_cog(BigEbayCommands(bot))