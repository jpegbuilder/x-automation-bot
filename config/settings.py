""" Settings for the bot and Dashboard """
import os

# Server Configuration
PORT = int(os.getenv('PORT', 8080))

# Airtable Configuration
AIRTABLE_PERSONAL_ACCESS_TOKEN = os.getenv('AIRTABLE_PERSONAL_ACCESS_TOKEN', '')
AIRTABLE_BASE_ID = os.getenv('AIRTABLE_BASE_ID', '')
AIRTABLE_TABLE_NAME = os.getenv('AIRTABLE_TABLE_NAME', '')
AIRTABLE_VIEW_ID = os.getenv('AIRTABLE_VIEW_ID', '')
AIRTABLE_LINKED_TABLE_ID = os.getenv('AIRTABLE_LINKED_TABLE_ID', '')

# AdsPower Configuration
ADSPOWER_API_URL = os.getenv('ADSPOWER_API_URL', "http://local.adspower.net:50325")
ADSPOWER_API_KEY = os.getenv('ADSPOWER_API_KEY', '')

# Local constants
STATS_FILE = os.getenv('STATS_FILE', '')
STATUS_FILE = os.getenv('STATUS_FILE', '')
CONFIG_FILE = os.getenv('CONFIG_FILE', '')

# Profile Configuration
MAX_CONCURRENT_PROFILES = int(os.getenv('MAX_CONCURRENT_PROFILES', 50))


if __name__ != "__main__":
    from config.validate_settings import validate_settings
    validate_settings()