#!/usr/bin/env python3
"""Script to upload existing already_followed data to Airtable"""

import os
from config import AIRTABLE_PERSONAL_ACCESS_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME
from pyairtable import Api

def upload_profile_data(profile_number):
    """Upload already followed data for a specific profile"""
    file_path = f'already_followed/{profile_number}_already_followed.txt'

    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return False

    # Read file content
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()

    if not content:
        print(f"File is empty: {file_path}")
        return False

    # Connect to Airtable
    api = Api(AIRTABLE_PERSONAL_ACCESS_TOKEN)
    table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

    # Find record by profile number
    records = table.all(formula=f"{{Profile}} = '{profile_number}'")

    if not records:
        print(f"Profile {profile_number} not found in Airtable")
        return False

    record_id = records[0]['id']
    print(f"Found profile {profile_number} (record {record_id})")

    # Upload data
    try:
        update_data = {
            'Already Followed': content
        }
        result = table.update(record_id, update_data)
        username_count = len(content.strip().split('\n'))
        print(f"✅ Uploaded {username_count} usernames to Airtable for profile {profile_number}")
        return True
    except Exception as e:
        print(f"❌ Error uploading: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Upload profile 250 (k16q2qq3)
    print("Uploading profile 250 (k16q2qq3) data to Airtable...")
    upload_profile_data('250')
