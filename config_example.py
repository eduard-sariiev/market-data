class Config:
    TOKEN = 'DISCORD_TOKEN'
    class BIG_EBAY_AUTH_TOKEN:
         # Rotates every 15 days
        USER = 'EBAY_USER_TOKEN',
         # Rotates every 24 hours
        ANON = 'EBAY_GUEST_TOKEN',
        APP = 'EBAY_4APP_KEY',
        AUTH_DEBUG = 'EBAY_AUTH_DEBUG_KEY' # optional
    class SMOL_EBAY_KEYS:
        APP = 'KLEINANZEIGEN_4APP_KEY'
        KEY = 'KLEINANZEIGEN_TOKEN'
    SMOL_EBAY_MENTION_ROLE = 1234567890123456789
    EBAY_MENTION_ROLE = 1234567890123456789
    CHANNEL_ID = {
        'SmolEbayCommands' : 1234567890123456789,
        'BigEbayCommands' : 1234567890123456789
    }
    SMOL_EBAY_UPDATE_INTERVAL = 60
    EBAY_UPDATE_INTERVAL = 120
    CACHE_PATH = 'cache'
    LOG_FILE = 'logs/bot.log'
    LOG_SIZE = 32 * 1024 * 1024 # 32 MiB
