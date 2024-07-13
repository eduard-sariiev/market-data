import asyncio
import json

from datetime import datetime, timezone
from random import choices
from traceback import format_exc
from string import ascii_letters, digits
from time import time
from logging import getLogger
from config import Config

TIMEOUT_PERIOD = 5
UPDATE_INTERVAL = 500

class BigEbayParser:
    def __init__(self, session):
        self.session = session
        self.base_uri = 'https://apisd.ebay.com/experience/'
        self.graph_uri = 'https://apisd.ebay.com/graphql'
        self.item_uri = 'https://www.ebay.de/itm/'
        self.user_uri = 'https://www.ebay.de/usr/'
        self.endpoints = {
            'search' : 'search/v1/search_results',
            'commit_bid' : 'auction/v2/bid/module_provider/commit_bid',
            'view_item' : 'listing_details/v2/view_item'
        }
        self.get_uri = lambda x: f'{self.base_uri}{self.endpoints[x]}'
        self.base_testuri = 'https://127.0.0.1'
        self.headers = {
            'User-Agent' : 'eBayiPhone/6.148.0',
            'x-ebay-advertising' : 'deviceAdvertisingIdentifier=00000000-0000-0000-0000-000000000000,deviceTargetedAdvertisingOptOut=true',
            'Accept-Encoding' : 'gzip, deflate, br',
            'X-EBAY-C-REQUEST-AUTH-DEBUG' : Config.BIG_EBAY_AUTH_TOKEN.AUTH_DEBUG,
            'X-EBAY-C-TERRITORY-ID' : 'DE',
            'X-EBAY-C-REQUEST-ID' : 'rci=rhWU4epbCxbTx/kf', # Gen random?
            'X-EBAY-4PP' : Config.BIG_EBAY_AUTH_TOKEN.APP,
            'Authorization' : f'Bearer {Config.BIG_EBAY_AUTH_TOKEN.USER}',
            'X-EBAY-C-ENDUSERCTX' : 'contextualLocation=country%3DDE%2Czip%3D10249,deviceId=18dff968226.ab8f0ba.3b9ef.fffeb35c,deviceIdType=IDREF,userAgent=ebayUserAgent/eBayIOS;6.148.0;iOS;16.4.1;Apple;iPhone10_4;--;375x667;2.0',
            'Accept-Language' : 'en-US',
            'X-EBAY-C-CULTURAL-PREF' : 'Currency=EUR,Timezone=Europe/Paris,Units=Metric',
            'Accept' : 'application/json;presentity=inline',
            'Content-Type' : 'application/json',
            'X-EBAY-C-MARKETPLACE-ID' : 'EBAY-DE',
            'ebay-ets-api-intent' : 'foreground',
            'ebay-ets-device-theme' : 'dark',
        }
        self._add_headers = {
            'search' : {
                'X-EBAY-VI-PREFETCH-MODULES' : 'modules=VLS',
                'X-EBAY-VI-PREFETCH-SUPPORTED-UX-COMPONENTS' : 'supported_ux_components=ALERT%2CALERT_FITMENT%2CALERT_GUIDANCE%2CALERT_INLINE%2CAT_A_GLANCE%2CBANNER_IMAGE%2CBUYING_FLOW%2CBUY_BOX%2CBUY_BOX_CTA%2CCOMPARE_CONTRAST%2CCONDITION%2CCONDITION_CONTAINER%2CCUSTOMIZATION%2CEBAY_PLUS_PROMO%2CEDUCATION_MODULE%2CFINDERS%2CHAZMAT%2CHEADER_AND_OVERLAY%2CITEM_CARD%2CITEM_CONDENSED%2CITEM_CONDENSED_CONTAINER%2CITEM_STATUS_MESSAGE%2CMSKU_PICKER%2CPICTURES%2CPRICE_DETAILS%2CQUANTITY%2CSECTIONS%2CSECTIONS_GROUPED%2CSECTIONS_MIN_SPACE%2CSECTIONS_PROGRESSIVE%2CSEMANTIC_DATA%2CSME%2CSURVEY%2CTITLE%2CVALIDATE%2CVAS_HUB_V2%2CVAS_SPOKE_V2%2CVEHICLE_HISTORY%2CVLS%2CMERCH_ASPECT_SELECTION_BANNER%2CMERCH_CAROUSEL%2CMERCH_DISCOVERY%2CMERCH_GRID%2CMERCH_GROUPED_CAROUSEL%2CMERCH_NAVIGATION_LIST_GROUPED_CAROUSEL%2CMERCH_PAGED_GRID%2CAD_PD_S3%2CVOLUME_PRICING%2CFEEDBACK_DETAIL_LIST%2CFEEDBACK_DETAIL_LIST_V2%2CFEEDBACK_DETAIL_LIST_TABBED%2CFEEDBACK_DETAIL_LIST_TABBED_V2%2CFEEDBACK_DETAILED_SELLER_RATING_SUMMARY',
                'X-EBAY-VI-PREFETCH-OPTS' : 'quantity=1&enableVIM=true&supportedPartialModules=VOLUME_PRICING'
            },
            'auth' : {
                'Authorization' : f'Bearer {Config.BIG_EBAY_AUTH_TOKEN.USER}',
                'Accept' : 'application/json;presentity=split'
            },
            'details' : {
                'Accept' : 'application/json;presentity=split'
            },
            'watchlist' : {
                'Accept': 'application/json'
            }
        }
        self.cached_ads = {}
        self.non_announced = []
        self.starting_datetime = datetime.now(timezone.utc)
        self.logger = getLogger('market_bot.ebay_parser')
        self.BID_OFFSET = 2
        self.INCREASE_BID_BY = 2

    def get_headers(self, area=None):
        temp_headers = {**self.headers, 'X-EBAY-C-REQUEST-ID' : f"rci={''.join(choices(ascii_letters + digits, k=16))}"}
        if not area:
            return temp_headers
        return {**temp_headers, **self._add_headers[area]}
            


    async def get_details(self, itemId):
        params = {
            'itemId' : itemId,
            'modules' : 'VLS',
            'supportedPartialModules' : 'VOLUME_PRICING',
            'supported_ux_components' : 'ALERT,ALERT_FITMENT,ALERT_GUIDANCE,ALERT_INLINE,AT_A_GLANCE,BANNER_IMAGE,BUYING_FLOW,BUY_BOX,BUY_BOX_CTA,COMPARE_CONTRAST,CONDITION,CONDITION_CONTAINER,CUSTOMIZATION,EBAY_PLUS_PROMO,EDUCATION_MODULE,FINDERS,HAZMAT,HEADER_AND_OVERLAY,ITEM_CARD,ITEM_CONDENSED,ITEM_CONDENSED_CONTAINER,ITEM_STATUS_MESSAGE,MSKU_PICKER,PICTURES,PRICE_DETAILS,QUANTITY,SECTIONS,SECTIONS_GROUPED,SECTIONS_MIN_SPACE,SECTIONS_PROGRESSIVE,SEMANTIC_DATA,SME,SURVEY,TITLE,VALIDATE,VAS_HUB_V2,VAS_SPOKE_V2,VEHICLE_HISTORY,VLS,MERCH_ASPECT_SELECTION_BANNER,MERCH_CAROUSEL,MERCH_DISCOVERY,MERCH_GRID,MERCH_GROUPED_CAROUSEL,MERCH_NAVIGATION_LIST_GROUPED_CAROUSEL,MERCH_PAGED_GRID,AD_PD_S3,VOLUME_PRICING,FEEDBACK_DETAIL_LIST,FEEDBACK_DETAIL_LIST_V2,FEEDBACK_DETAIL_LIST_TABBED,FEEDBACK_DETAIL_LIST_TABBED_V2,FEEDBACK_DETAILED_SELLER_RATING_SUMMARY',
            'quantity' : '1',
            'enableVIM' : 'true',
            'supported_gadget_ux_components' : 'BEST_OFFER_TOOL_TIP,TOOL_TIP_WITH_DISMISS,FIXED_COUPON_BANNER_V3,DRAWER_COUPON_BANNER,REWARDS_ENROLLMENT_MODAL,REWARDS_ACTIVATION_MODAL,REWARDS_REDEMPTION_MODAL,WIDGET_RESPONSE_MODAL,COUPONS_LAYER,EBAY_PLUS_BANNER',
        }
        async with self.session.get(url=self.get_uri('view_item'), headers=self.get_headers('details'), params=params) as resp:
            if resp.status == 200:
                ad = await resp.json()
                listing_prop = ad['modules']['VLS']['listing']
                startDate = int(datetime.strptime(listing_prop['listingLifecycle']['scheduledStartDate']['value'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp())
                endDate = int(datetime.strptime(listing_prop['listingLifecycle']['scheduledEndDate']['value'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp())
                format = listing_prop['format']
                sid = ad['modules']['SEMANTIC_DATA']['bidPrefetch']['tracking']['eventProperty']['sid'] if format == 'AUCTION' else None

                self.cached_ads[itemId] = {
                    'title' : listing_prop['title']['content'],
                    'startDate' : startDate,
                    'endDate' : endDate,
                    'sid' : sid,
                    'isAuction' : True if format == 'AUCTION' else False
                }
            else:
                self.logger.error(f'Error during getting details: {await resp.text()}')

    def parse_results(self, query_result, firstTime=False):
        if query_result.get('deferred_modules', None):
            listings = {**query_result['deferred_modules'][0], **query_result['modules']}
        else:
            listings = {**query_result['modules']}
        for key, item in listings.items():
            if key.startswith('listing'):
                try:
                    itemId = item['listingId']
                    isTrueResult = False
                    for trackingItem in item['action']['trackingList']: # avoid recommended listings
                        if trackingItem['eventProperty'].get('sid'):
                            if int(trackingItem['eventProperty']['sid'].split('.l')[-1]) == 7400:
                                isTrueResult = True
                    if not isTrueResult:
                        continue
                    if not itemId in self.cached_ads:
                        ended = item.get('ended', False)
                        sellerName = item['__search']['sellerInfo']['text']['textSpans'][0]['text']
                        itemProperties = [x[0] for x in item['itemPropertyOrdering']['DEFAULT']['primary']]
                        if '__search.freeXDays' in itemProperties:
                            shipping = 'Free Shipping'
                        elif 'logisticsCost' in itemProperties:
                            shipping  = item['logisticsCost']['textSpans'][0]['text']
                        isAuction = 'bidCount' in itemProperties
                        self.cached_ads[itemId] = {
                            'title' : item['title']['textSpans'][0]['text'],
                            'price' : item['displayPrice']['value']['value'],
                            'isAuction' : isAuction,
                            'condition' : item['__search']['normalizedCondition']['text'],
                            'sellerName' : sellerName,
                            'sellerType' : item['__search']['sellerAccountType']['text'],
                            'shipping' : shipping,
                            'img' : item['image']['URL'] if item.get('image') else '',
                            'url' : f'{self.item_uri}{itemId}',
                            'userUrl' : f'{self.user_uri}{sellerName.split(" (")[0]}',
                        }
                        if not ended and isAuction:
                            self.cached_ads[itemId]['buyNow'] = '__search.formatBuyItNow' in itemProperties
                            self.cached_ads[itemId]['priceSuggestion'] = '__search.formatBestOfferEnabled' in itemProperties
                            try:
                                self.cached_ads[itemId]['endDate'] = int(datetime.strptime(item['displayTime']['value']['value'], '%Y-%m-%dT%H:%M:%S.000Z').replace(tzinfo=timezone.utc).timestamp()),
                            except Exception:
                                pass
                        if not firstTime:
                            self.non_announced.append(itemId)
                except Exception as e:
                    self.logger.error(f'Error during parsing: {format_exc()}\n{item}')

    async def get_category(self, params):
        suggestedCategory = 0
        suggestedCategoryName = ''
        priceRanges = []
        async with self.session.get(url=self.get_uri('search'), headers=self.get_headers('search'), params=params) as resp:
            try:
                if resp.status == 200:
                    search_data = await resp.json()
                    for group in search_data['deferred_modules'][0]['SEARCH_REFINEMENTS_MODEL_V2']['group']:
                        try:
                            if group.get('paramKey') == '_sacat':
                                for entry in group['entries']:
                                    if entry.get('expandInline') and entry.get('entries'):
                                        for sub_entry in entry['entries']:
                                            if sub_entry.get('selected'):
                                                suggestedCategory = int(sub_entry['paramValue'])
                                                suggestedCategoryName = sub_entry['label']['textSpans'][0]['text']
                            if group.get('fieldId') == 'price':
                                for entry in group['entries']:
                                    if entry.get('fieldId') == 'priceGraph':
                                        priceRanges = [{k: v for k, v in ranges.items() if not k == '_type'} for ranges in entry['priceDistributionInfo']]
                        except Exception:
                            pass
                else:
                    self.logger.error(f'Got {resp.status} during search: {await resp.text()}')
            except Exception as e:
                self.logger.error(f'Error on guessCategory search: {format_exc()}')
            
        return suggestedCategory, suggestedCategoryName

    def get_params(self, query='', minPrice=0, maxPrice=0, sellerType=0, sold=False, location=0, zip=10249, radius=100, sortBy=12, condition=[], listingType=0, category=0, full=True):
        """
        LH_Auction : 1 # Only auctions
        LH_BIN : 1 # Only buy now
        LH_BO : 1 # Best offer
        None of above = all listings
        
        LH_ItemCondition
        10 - Not specified
        1000 - New
        1500 - New (see details)
        2000 - Refurb certified
        2010 - Refurb like bew 
        2020 - Refurb very good 
        2030 - Refurb good 
        2500 - Refurb by seller
        3000 - Used
        7000 - For parts
        Separated by |
        
        LH_SellerType
        1 - Private
        2 - Business
        
        _udlo - min price
        _udhi - max price

        LH_Sold: 1 - Sold Items
        LH_Complete: 1 - Completed Items
        """

        """
        listingType:
        0 - All
        1 - Auction
        2 - Buy Now
        4 - Best Offer
        """
        params = {
                'answersVersion' : 1,
                '_pgn' : 1, # Always present
                'async' : 'false',
                '_nkw' : query, # Text to match
                '_vs' : 1, # Always present
                '_sop' : sortBy, # Sort by: 16 - Highest price, 15 - Lowest price, 12 - Best Match, 10 - Newly listed, 7 - Nearest first, 1 - Ending soonest
                'supportedUxComponentNames' : 'ITEM_CARD,DENSE_ITEM_CARD,REWRITES_ITEMS,REWRITE_START,BASIC_MESSAGE,TWO_LINE_MESSAGE,BASIC_USER_MESSAGE,BASIC_SELLER_HEADER,PROMOTED_ITEM_CARD,VEHICLE_PARTS_FINDER,MOTORS_TIRE_FINDER,TOP_OF_PAGE_FINDER,TOP_OF_PAGE_WITH_VEHICLE,TOP_OF_PAGE_TIRE,GARAGE_ONE_CLICK_FINDER,UNIVERSAL_FINDER,STATUS_BAR_V2,ICON_MESSAGE,TOGGLE_MESSAGE,STORE_INFORMATION,PRESENCE_INFORMATION_V3,FIRST_PARTY_ADS_BANNER,ITEMS_CAROUSEL_V3,NAVIGATION_ANSWER_PILL_CAROUSEL,NAVIGATION_IMAGE_ANSWER_CAROUSEL,NAVIGATION_ANSWER_TEXT_LIST,IMAGE_ANSWER_GUIDANCE_CAROUSEL,PAGE_TITLE_BAR,ASPECTS_IN_RIVER,ITEM_CAROUSEL_BOS,GRID_VIEW_ITEM_CAROUSEL_BOS,COLD_START_BOTTOM_DRAWER_FINDER,SAVE_CARD,ICON_TOGGLE_MESSAGE,SPECTRUM_OF_VALUE_CAROUSEL,EEK_ICON,SPONSORED_BADGE,ITEMS_CAROUSEL_WITH_COLOR,SELLER_OFFER_TAPPABLE_HEADER,BOS_PLACEHOLDER,SEEK_FEEDBACK_COMPONENT,SEARCH_PRICE_TRENDS,MODEL_PRICE_GUIDANCE',
                'config' : 'SearchServiceDictionary.OsrExperienceEnabled:false',
                'requestedPageLayoutsForMultiLayoutRegion' : 'LIST_1_COLUMN,LARGE_1_COLUMN,GRID_2_COLUMN',
                'enableDeferredModules' : 1,
            }
        
        if full: # Populate the rest of params from function's arguments
            if location:
                params['LH_PrefLoc'] = location, # 0 - Standard, 1 - Germany, 3 - EU, 6 - Europe, 2 - Worldwide, 99 - in radius _stpos within _sadis km
            if sold:
                params['LH_Sold'] = 1
                params['LH_Complete'] = 1
            if category:
                params['_sacat'] = category
                params['_oaa'] = 1
                params['_fsrp'] = 1
            params['_stpos'] = zip # zipcode
            params['_sadis'] = radius # radius (in km)
            if minPrice:
                params['_udlo'] = minPrice
            if maxPrice:
                params['_udhi'] = maxPrice
            if sellerType:
                params['LH_SellerType'] = sellerType
            if listingType:
                if listingType & 1:
                    params['LH_Auction'] = 1
                if listingType & 2:
                    params['LH_BIN'] = 1
                if listingType & 4:
                    params['LH_BO'] = 1
            if condition:
                params['LH_ItemCondition'] = '|'.join([str(x) for x in condition])
        return params

    async def search_offers(self, params, firstTime):
        try:
            async with self.session.get(url=self.get_uri('search'), headers=self.get_headers('search'), params=params) as resp:
                try:
                    if resp.status == 200:
                        data = await resp.json()
                        self.parse_results(data, firstTime)
                    else:
                        self.logger.error(f'Got {resp.status} during search: {await resp.text()}')
                except Exception as e:
                    self.logger.error(f'Error during search: {format_exc()}')
        except Exception as e:
            self.logger.error(f'{format_exc()}')

    async def place_bid(self, itemId, price, sid=None, tryOverbid=False):
        params = {
            'modules_group' : 'POWER_BID_LAYER',
            'ocv' : 0,
        }
        if sid: # tracking stuff
            params['sid'] = sid
        payload = {
            'elvisWarningShown' : "false",
            'price' : {
                'currency' : 'EUR',
                'value' : str(price)
            },
            'itemId' : itemId,
            'decimalPrecision': 2,
        }
        async with self.session.post(url=self.get_uri('commit_bid'), headers=self.get_headers('auth'), params=params, json=payload) as resp:
            try:
                if resp.status == 200:
                    data = await resp.json()
                    isHighBidder = data['modules']['AUCTION_META']['isHighBidder']
                    currentPrice = data['modules']['AUCTION_META']['currentPrice']['value']
                    if isHighBidder:
                        text = f'Placed highest bid {currentPrice}€ for {itemId}'
                    else:
                        bidder = data['modules']['AUCTION_META']['highBidder']['name']
                        text = f'Outbid for {currentPrice}€ for {itemId} by {bidder}'
                        if tryOverbid:
                            newAmount = float(currentPrice) + self.INCREASE_BID_BY
                            return await self.place_bid(itemId, newAmount, sid)
                    self.logger.info(text)
                    return isHighBidder, text
                else:
                    print(await resp.text())
            except Exception as e:
                self.logger.error(f'Error on bid {format_exc()}')
            return False, ''

    async def watchlist(self, itemId, follow=True):
        if follow:
            payload = {
                "operationName":"StopWatchingOnList",
                "query":"mutation StopWatchingOnList($stopWatchingOnListInput: StopWatchingOnListInput!) { stopWatchingOnList(stopWatchingOnListInput: $stopWatchingOnListInput) { __typename result { __typename ... on StopWatchingOnListFailure { debugMessage } ... on StopWatchingOnListSuccess { numberOfListingsUnwatched } } } }",
                "variables":{
                    "stopWatchingOnListInput":{
                        "listingsToStopWatching":[
                            {
                            "listingId":itemId,
                            "variationId":'null'
                            }
                        ],
                        "watchListId":"WATCH_LIST"
                    }
                }
            }
        else:
            payload = {
                "operationName":"StartWatchingOnList",
                "query":"mutation StartWatchingOnList($startWatchingOnListInput: StartWatchingOnListInput!) { startWatchingOnList(startWatchingOnListInput: $startWatchingOnListInput) { __typename result { __typename ... on AddToWatchListSuccess { numberOfListingsWatched } ... on ExpiredListing { debugMessage } ... on StartWatchingOnListFailure { debugMessage } ... on WatchListIsFull { debugMessage } ... on WatchingQuotaReached { debugMessage } ... on DuplicateListing { debugMessage } } } }",
                "variables":{
                    "startWatchingOnListInput":{
                        "listingsToStartWatching":[
                            {
                            "listingId":itemId,
                            "variationId":'null'
                            }
                        ],
                        "watchListId":"WATCH_LIST"
                    }
                }
            }
        async with self.session.post(self.graph_uri, headers=self.get_headers('watchlist'), json=payload) as resp:
            if resp.status == 200:
                data = await resp.json()
                if follow:
                    done = (data['data']['result']['__typename'] == 'AddToWatchListSuccess')
                else:
                    done = (data['data']['result']['__typename'] == 'StopWatchingOnListSuccess')
                return done
            else:
                print(await resp.text())

    async def getAuction(self, itemId):
        await self.get_details(itemId)
        return self.cached_ads.get(itemId, None)