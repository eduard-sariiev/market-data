import asyncio
import json

from os import name, path
from datetime import datetime, timezone
from time import time
from html import unescape
from traceback import format_exc
from logging import getLogger
from config import Config

TIMEOUT_PERIOD = 5

class EbayParser:
	def __init__(self, session):
		self.session = session
		self.base_uri = 'https://api.kleinanzeigen.de/api/'
		self.base_testuri = 'https://127.0.0.1'
		self.filepath = f'{Config.CACHE_PATH}/ebay_ads.json'

		self.base_headers = {
			'Accept': '*/*',
			'Accept-Encoding': 'br;q=1.0, gzip;q=0.9, deflate;q=0.8',
			'Accept-Language': 'de-DE;q=1.0, uk-UA;q=0.8, vi-US;q=0.7, ja-US;q=0.6',
			'User-Agent': 'Kleinanzeigen/14.2.1 (com.ebaykleinanzeigen.ebc; build:134462; iOS 15.0) Alamofire/5.6.2',
			'X-EBAYK-APP': Config.SMOL_EBAY_KEYS.APP,
			'X-EBAYK-GROUPS': 'BIPHONE-6269_POST_AD_DIA_A|BIPHONE-6518_ATT_12_11_1_A|BIPHONE-6518_ATT_12_12_0_A|BIPHONE-6518_ATT_C|BIPHONE-6827_Message_Ads_A|BIPHONE-7261_KYC_triggers_B|BIPHONE-7483_ComFlag_A|BIPHONE-7678_oauth_B|BIPHONE-7710_SHIP_POST_AD_B|BIPHONE-8000_BuyNow_Final_A|BIPHONE-8101_MyAdsC2b_B|BIPHONE-8174_TooltipC2b_B|BIPHONE-8577_post_ph_kill_B|BIPHONE5645_SaSe_SRP_R|BIPHONE5709_ENRICHSRP_v2_E|BIPHONE7754-make_offer_B|BIPHONE7792_SellerRefund2_A|BIPHONE7799_Seller_Refund_B|BIPHONE8444-BuyNowCheckou_B|BLN-19260-cis-login_B|EBAYK1592_PostAd_Category_B|FeedbackCenter_A|filter_ux_part1_E|iOS_Payment_SRP_B|liberty_gcp_ios_B|typo_ios_A',
			'X-ECG-USER-AGENT': 'ebayk-iphone-app-134462',
			'X-ECG-VER': '1.16',
			'Authorization' : f'Basic {Config.SMOL_EBAY_KEYS.KEY}',
		}
		self.cached_ads = {}
		self.non_announced = []
		self.starting_datetime = datetime.now(timezone.utc)
		self.logger = getLogger('market_bot.kleinanzeigen_parser')
		#self.load_ads_from_file()

	async def search(self, query, city=0, radius=25, size=30, maxPrice=350, minPrice=100, exclude=''):
		headers = self.base_headers.copy()
		headers['X-ECG-IN'] = 'ad-address,ad-source-id,ad-status,ad-type,ads-search-suggested-category,attributes,category,displayoptions,features-active,id,link,locations.location.id,locations.location.regions.region.localized-name,medias.media.media-link,otherAttributes.partner-contact-display-name,phone,pictures,poster-type,price,search-distance,seller-account-type,start-date-time,title,user-id,user-rating'
		headers['X-EBAYK-USECASE'] = 'results-search'
		filters = {
			'histograms' : 'CATEGORY',
			'includeTopAds' : 'true',
			'limitTotalResultCount' : 'true',
			'pictureRequired' : 'true',
			'locationId' : city,
			'maxPrice' : maxPrice,
			'minPrice' : minPrice,
			'q' : query,
			'size' : size,
		}
		if city:
			filters['distance'] = radius
		url = self.base_uri + 'ads.json'
		async with self.session.get(url, headers=headers, params=filters) as response:
			if response.status == 200:
				content = await response.json()
				await self.parse_search_result(content, exclude=exclude)
			else:
				self.logger.error(f'Failed getting search results: {response.status}')

	async def search_by_user(self, store_id, size=30):
		headers = self.base_headers.copy()
		headers['X-ECG-IN'] = 'ad-address,ad-source-id,ad-status,ad-type,ads-search-suggested-category,attributes,category,displayoptions,features-active,id,link,locations.location.id,locations.location.regions.region.localized-name,medias.media.media-link,otherAttributes.partner-contact-display-name,phone,pictures,poster-type,price,search-distance,seller-account-type,start-date-time,title,user-id,user-rating'
		headers['X-EBAYK-USECASE'] = 'other-ads'
		filters = {
			'histograms' : 'CATEGORY',
			'includeTopAds' : 'true',
			'limitTotalResultCount' : 'true',
			'size' : size,
			'storeIds' : store_id,
		}
		url = self.base_uri + 'ads.json'
		async with self.session.get(url, headers=headers, params=filters) as response:
			if response.status == 200:
				content = await response.json()
				await self.parse_search_result(content, False)
			else:
				self.logger.error(f'Failed getting search results: {response.status}')

	async def parse_search_result(self, result, get_detailed=True, exclude=''):
		searchOptions = result['searchOptions']
		if not 'ad' in result['{http://www.ebayclassifiedsgroup.com/schema/ad/v1}ads']['value'].keys():
			return
		ads = result['{http://www.ebayclassifiedsgroup.com/schema/ad/v1}ads']['value']['ad']
		for ad in ads:
			price = ad['price']['amount'].get('value', '')
			price_vb = 'VB' if ad['price']['price-type'].get('value', '') == 'PLEASE_CONTACT' else ''
			title = ad['title']['value']
			state = ad['locations']['location'][0]['regions']['region'][0]['localized-name'].get('value', '')
			try:
				address_data = {k:v.get('value', '') for k, v in ad['ad-address'].items()}
				address_text = '{} {}, {}'.format(address_data['zip-code'], address_data['state'], state)
			except Exception as e:
				address_text = 'No address'
				self.logger.error(f'Error getting address data, {e}, {ad["ad-address"]}')
			distance_in_km = None
			try:
				if 'search-distance' in ad.keys():
					distance_data = {k:v.get('value', '') for k, v in ad['search-distance'].items()}
					distance_in_km = distance_data['display-distance']
			except Exception as e:
				self.logger.error(f'Error getting distance data, {e}')
			status = ad['ad-status']
			publish_date = datetime.strptime(ad['start-date-time']['value'], '%Y-%m-%dT%H:%M:%S.%f%z')
			versand = False
			try:
				for value in ad['attributes']['attribute']:
					if value.get('localized-tag', '') == 'Versand möglich':
						versand = True
						break
			except Exception:
				pass
			safe_payment = True if ad['displayoptions']['secure-payment-possible'].get('value', '') == 'true' else False
			link = ad['link'][1]['href']
			try:
				img = ad['pictures']['picture'][0]['link'][2]['href']
			except Exception as e:
				img = None
			id = ad['id']
			# diff = time.time() - publish_date
			# ago_text = utcnow().shift(seconds=-diff).humanize()
			if exclude and exclude.lower() in title.lower():
				continue

			if not id in self.cached_ads.keys() and publish_date > self.starting_datetime:
				self.cached_ads[id] = {
						'title' : title,
						'price' : price,
						'vb' : price_vb,
						'address' : address_text,
						'distance_in_km' : distance_in_km,
						'status' : status,
						'publish_date' : publish_date,
						'state' : state,
						'versand' : versand,
						'safe_payment' : safe_payment,
						'link' : link,
						'img' : img,
					}
				if get_detailed:
					self.logger.info(f'Getting details for {title}')
					await self.get_single_ad(id)
					await asyncio.sleep(TIMEOUT_PERIOD)
				if self.cached_ads[id].get('description', None):
					self.non_announced.append(id)

	async def get_single_ad(self, id):
		headers = self.base_headers.copy()
		headers['X-EBAYK-USECASE'] = 'vip'
		headers['X-ECG-IN'] = 'ad-address,ad-external-reference-id,ad-guid,ad-source-id,ad-status,ad-type,attributes,buy-now,category,contact-name,contact-name-initials,description,displayoptions,documents,features-active,id,imprint,link,locations.location.id,locations.location.regions.region.localized-name,medias,otherAttributes,partnership,phone,pictures,poster-type,price,search-distance,seller-account-type,shipping-options,start-date-time,store-id,title,user-id,user-rating,user-since-date-time,userBadges'
		url = self.base_uri + f'ads/{id}.json'
		async with self.session.get(url, headers=headers) as response:
			if response.status == 200:
				content = await response.json()
				await self.parse_ad_details(content)
			else:
				self.logger.error('Failed to retrieve ad details')

	async def parse_ad_details(self, result):
		ad = result['{http://www.ebayclassifiedsgroup.com/schema/ad/v1}ad']['value']
		desc = unescape(ad['description'].get('value', '')).replace('<br />', '\n')
		name = ad['contact-name']['value']
		userId = ad['user-id']['value']
		averageRating = None
		if 'user-rating' in ad.keys():
			averageRating = ad['user-rating']['averageRating'].get('value', None)
		userScore = {}
		if 'userBadges' in ad.keys():
			for badge in ad['userBadges']['badges']: # ['rating', 'friendliness', 'reliability', 'replySpeed', 'followers']
				userScore[badge['name']] = badge['level'] if badge['value'] == '' else badge['value']
		accountCreated = datetime.strptime(ad['user-since-date-time']['value'], '%Y-%m-%dT%H:%M:%S.%f%z')
		accountCreated_text = accountCreated.strftime('%Y-%m-%d %H:%M:%S')
		id = ad['id']
		self.cached_ads[id].update({
			'description' : desc,
			'sellerName' : name,
			'averageRating' : averageRating,
			'userScore' : userScore,
			'accountCreated' : accountCreated,
			'userId' : userId,
			'lastUpdated' : int(time())
			})
		await self.get_view_counter(id, userId)

	async def get_view_counter(self, id, userId):
		headers = self.base_headers.copy()
		data = {'userId' : userId}
		url = self.base_uri + f'v2/counters/ads/vip/{id}'
		async with self.session.post(url, headers=headers, json=data) as response:
			if response.status == 200:
				content = await response.json()
				self.cached_ads[id].update({
					'views' : content['value']
					})
			else:
				self.logger.error('Failed to retrieve view counter')

	async def resolve_cities(self, query):
		headers = self.base_headers.copy()
		headers['X-ECG-IN'] = 'id,localized-name,longitude,latitude,radius'
		url = self.base_uri + 'locations.json'
		params = {
			'depth' : 1,
			'q' : query,
		}
		async with self.session.get(url, headers=headers, params=params) as response:
			if response.status == 200:
				content = await response.json()
				try:
					cities = {}
					for city in content['{http://www.ebayclassifiedsgroup.com/schema/location/v1}locations']['value']['location']:
						cities[city['id']] = city['localized-name']['value']
					if len(cities.keys()) > 1:
						choice = -1
						while choice < 0:
							print('\n'.join([f'{idx}. {x}' for idx, x  in enumerate(cities.values())]))
							t = input('Choose: ')
							try:
								t = int(t)
							except Exception as e:
								print('Wrong value')
							if t < len(cities.keys()):
								choice = t
					else:
						choice = 0
					print('{} - {}'.format(list(cities.keys())[choice], cities[list(cities.keys())[choice]]))
				except Exception as e:
					self.logger.error('No city with such name was found', e)	
			else:
				self.logger.error('Failed getting cities list')
			return '13819'

	async def save_ads_to_file(self):
		with open(self.filepath, 'w', encoding='utf8') as f:
			json.dump(self.cached_ads, f, indent = 2, default=str)
		self.logger.debug('Wrote data to file')


	def load_ads_from_file(self):
		if path.isfile(self.filepath):
			with open(self.filepath, 'r', encoding='utf8') as f:
				self.cached_ads = json.load(f)
			self.logger.debug('Read data from file')
