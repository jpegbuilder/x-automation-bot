import os
import threading
import logging
import time
import requests
from config import (
    AIRTABLE_PERSONAL_ACCESS_TOKEN,
    AIRTABLE_BASE_ID,
    AIRTABLE_TABLE_NAME,
    AIRTABLE_VIEW_ID,
    AIRTABLE_LINKED_TABLE_ID,
    ADSPOWER_API_URL,
    ADSPOWER_API_KEY,
)

logger = logging.getLogger(__name__)

# Airtable integration
try:
    from pyairtable import Api

    AIRTABLE_AVAILABLE = True
except ImportError:
    AIRTABLE_AVAILABLE = False
    logging.warning("pyairtable not installed. Install with: pip install pyairtable")


class AirtableManager:
    """Manages Airtable operations"""

    # Connection pooling
    _api_instance = None
    _last_request_time = 0
    _request_cooldown = 1.0  # 1 second between requests
    _request_lock = threading.Lock()

    def __init__(self, *args, **kwargs):
        self._api = self._get_api()
        self.profiles_lock = kwargs.get('profiles_lock') or None
        self.profiles = kwargs.get('profiles')
        self.stats_manager = kwargs.get('stats_manager')

    def _get_api(self):
        """Get or create API instance"""
        if self._api_instance is None and AIRTABLE_AVAILABLE:
            self._api_instance = Api(AIRTABLE_PERSONAL_ACCESS_TOKEN)
        return self._api_instance

    def _rate_limit(self):
        """Simple rate limiting"""
        with self._request_lock:
            current_time = time.time()
            time_since_last = current_time - self._last_request_time
            if time_since_last < self._request_cooldown:
                time.sleep(self._request_cooldown - time_since_last)
            self._last_request_time = time.time()

    def update_profile_status(self, profile_number, status):
        """Update profile status in Airtable with retry logic"""
        if not AIRTABLE_AVAILABLE:
            return False

        max_retries = 2  # Reduced retries
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                self._rate_limit()
                table = self._api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

                if profile_number.isdigit():
                    records = table.all(formula=f"{{AdsPowerSerial}} = {profile_number}")
                else:
                    records = table.all(formula=f"{{AdsPower ID}} = '{profile_number}'")

                if records:
                    record_id = records[0]['id']
                    if status == 'Suspended':
                        current_status = records[0].get("fields", {}).get("Status")
                        current_status.append(status)
                        update_data = {'Status': current_status}
                    else:
                        update_data = {'Status': [status]}
                    result = table.update(record_id, update_data)
                    logger.info(f"✅ Updated profile {profile_number} status to '{status}' in Airtable")
                    return True
                else:
                    logger.warning(f"❌ Profile {profile_number} not found in Airtable")
                    return False

            except Exception as e:
                logger.error(f"❌ Error updating profile {profile_number} status: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    return False
        return False

    def update_profile_statistics(self, profile_number, last_run=None, follows_today=None, total_follows=None):
        """Update profile statistics in Airtable"""
        if not AIRTABLE_AVAILABLE:
            return False

        try:
            self._rate_limit()
            table = self._api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

            # Determine search field - use AdsPower ID for non-numeric IDs
            if str(profile_number).isdigit():
                # Numeric ID - could be Profile or AdsPowerSerial
                records = table.all(formula=f"{{AdsPowerSerial}} = {profile_number}")
                if not records:
                    # Try Profile field as fallback
                    records = table.all(formula=f"{{Profile}} = '{profile_number}'")
            else:
                # AdsPower ID (like k16q2qq3)
                records = table.all(formula=f"{{AdsPower ID}} = '{profile_number}'")

            if records:
                record_id = records[0]['id']
                update_data = {}

                if last_run is not None:
                    update_data['Last run'] = last_run
                if follows_today is not None:
                    update_data['Follows today'] = follows_today
                if total_follows is not None:
                    update_data['Total Follows'] = total_follows

                if update_data:
                    result = table.update(record_id, update_data)
                    logger.info(f"✅ Updated profile {profile_number} statistics in Airtable: {update_data}")
                    return True
                else:
                    return True
            else:
                logger.warning(f"❌ Profile {profile_number} not found in Airtable")
                return False

        except Exception as e:
            logger.error(f"❌ Error updating profile {profile_number} statistics: {e}")
            return False

    def update_profile_statistics_on_completion(self, profile_id):
        """Update statistics for a profile when it completes work - INCREMENTS Total Follows"""
        try:
            # Get stats from this run
            stats = self.stats_manager.get_profile_stats(profile_id)
            follows_this_run = stats['last_run']

            # Read current Total Follows from Airtable to increment it
            self._rate_limit()
            table = self._api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)

            # Find the profile record - use same logic as update_profile_statistics
            if str(profile_id).isdigit():
                # Numeric ID - try AdsPowerSerial first, then Profile
                records = table.all(formula=f"{{AdsPowerSerial}} = {profile_id}")
                if not records:
                    records = table.all(formula=f"{{Profile}} = '{profile_id}'")
            else:
                # AdsPower ID (like k16q2qq3)
                records = table.all(formula=f"{{AdsPower ID}} = '{profile_id}'")

            if not records:
                logger.warning(f"❌ Profile {profile_id} not found in Airtable for statistics update")
                return False

            record = records[0]
            current_total = record['fields'].get('Total Follows', 0)

            # Calculate new total (INCREMENT, not overwrite)
            new_total = current_total + follows_this_run

            logger.info(f"📊 Profile {profile_id}: Airtable had {current_total}, adding {follows_this_run} = {new_total} total follows")

            # Update ONLY Total Follows in Airtable
            success = self.update_profile_statistics(
                profile_id,
                total_follows=new_total  # Only update this field
            )

            if success:
                logger.info(f"✅ Profile {profile_id} statistics updated in Airtable (Total Follows: {new_total})")
            return success

        except Exception as e:
            logger.error(f"❌ Error updating profile {profile_id} statistics: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_target_records_for_profile(self, profile_record_id):
        """Get all Target records linked to a profile via the 'Accounts' field"""
        if not AIRTABLE_AVAILABLE:
            return []

        try:
            self._rate_limit()
            targets_table = self._api.table(AIRTABLE_BASE_ID, AIRTABLE_LINKED_TABLE_ID)

            # Fetch all Target records and filter manually
            # (Airtable formulas don't work well with linked record fields)
            all_targets = targets_table.all()

            linked_targets = []
            for target_record in all_targets:
                fields = target_record.get('fields', {})
                accounts = fields.get('Accounts', [])

                # Check if this profile is in the Accounts list
                if profile_record_id in accounts:
                    linked_targets.append(target_record)

            logger.info(f"Found {len(linked_targets)} target record(s) linked to profile {profile_record_id}")
            return linked_targets

        except Exception as e:
            logger.error(f"❌ Error getting target records for profile {profile_record_id}: {e}")
            import traceback
            traceback.print_exc()
            return []

    def upload_already_followed_file(self, profile_record_id, file_path):
        """Upload Already Followed file to Target records in Targets table"""
        if not AIRTABLE_AVAILABLE:
            return False

        try:
            if not file_path or not os.path.exists(file_path):
                logger.warning(f"Already followed file not found: {file_path}")
                return False

            # Get all Target records linked to this profile
            target_records = self.get_target_records_for_profile(profile_record_id)

            if not target_records:
                logger.warning(f"No target records found for profile {profile_record_id}")
                return False

            # Step 1: Upload file to tmpfiles.org to get a public URL
            with open(file_path, 'rb') as f:
                response = requests.post(
                    'https://tmpfiles.org/api/v1/upload',
                    files={'file': (os.path.basename(file_path), f, 'text/plain')}
                )

            if response.status_code != 200:
                logger.error(f"❌ tmpfiles.org upload failed: {response.status_code}")
                return False

            result = response.json()
            if result.get('status') != 'success':
                logger.error(f"❌ tmpfiles.org upload failed: {result}")
                return False

            # Get the URL and modify it for direct download
            file_url = result['data']['url'].replace('tmpfiles.org/', 'tmpfiles.org/dl/')

            # Step 2: Update each Target record with the file URL
            targets_table = self._api.table(AIRTABLE_BASE_ID, AIRTABLE_LINKED_TABLE_ID)
            success_count = 0

            for target_record in target_records:
                target_record_id = target_record['id']
                target_username = target_record.get('fields', {}).get('Username', 'Unknown')

                try:
                    self._rate_limit()

                    update_data = {
                        'Already Followed': [{
                            'url': file_url,
                            'filename': os.path.basename(file_path)
                        }]
                    }

                    targets_table.update(target_record_id, update_data)
                    logger.info(f"✅ Uploaded 'Already Followed' to Target '{target_username}' ({target_record_id})")
                    success_count += 1

                except Exception as e:
                    logger.error(f"❌ Error uploading to Target '{target_username}': {e}")

            return success_count > 0

        except Exception as e:
            logger.error(f"❌ Error uploading 'Already Followed' file: {e}")
            import traceback
            traceback.print_exc()
            return False

    def update_all_remaining_targets(self):
        """Update Remaining Targets for ALL Target records in Targets table"""
        if not AIRTABLE_AVAILABLE:
            return False

        try:
            logger.info("🔄 Updating Remaining Targets for all Target records...")

            self._rate_limit()
            targets_table = self._api.table(AIRTABLE_BASE_ID, AIRTABLE_LINKED_TABLE_ID)

            # Fetch all Target records
            all_target_records = targets_table.all()
            logger.info(f"Found {len(all_target_records)} Target records to process")

            success_count = 0
            skip_count = 0
            error_count = 0

            for target_record in all_target_records:
                target_record_id = target_record['id']
                target_username = target_record.get('fields', {}).get('Username', 'Unknown')
                fields = target_record.get('fields', {})

                try:
                    # Get Filtered Followers attachments (the targets to follow)
                    filtered_followers_attachments = fields.get('Filtered Followers', [])
                    if not filtered_followers_attachments:
                        logger.debug(f"No Filtered Followers for Target '{target_username}', skipping")
                        skip_count += 1
                        continue

                    # Count lines in all Filtered Followers files
                    targets_count = 0
                    for attachment in filtered_followers_attachments:
                        url = attachment.get('url')
                        if url:
                            try:
                                response = requests.get(url, timeout=30)
                                response.raise_for_status()
                                lines = [line for line in response.text.split('\n') if line.strip()]
                                targets_count += len(lines)
                            except Exception as e:
                                logger.error(f"Error downloading Filtered Followers file for '{target_username}': {e}")

                    # Count lines in all Already Followed files
                    already_followed_count = 0
                    already_followed_attachments = fields.get('Already Followed', [])
                    for attachment in already_followed_attachments:
                        url = attachment.get('url')
                        if url:
                            try:
                                response = requests.get(url, timeout=30)
                                response.raise_for_status()
                                lines = [line for line in response.text.split('\n') if line.strip()]
                                already_followed_count += len(lines)
                            except Exception as e:
                                logger.error(f"Error downloading Already Followed file for '{target_username}': {e}")

                    # Calculate remaining targets for this Target record
                    remaining_targets = targets_count - already_followed_count

                    # Update this Target record's Remaining Targets field in Targets table
                    self._rate_limit()
                    try:
                        targets_table.update(target_record_id, {'Remaining Targets': remaining_targets})
                        logger.info(f"✅ Target '{target_username}': {remaining_targets} remaining ({targets_count} - {already_followed_count})")
                        success_count += 1
                    except Exception as update_error:
                        logger.warning(f"Could not update Remaining Targets for '{target_username}': {update_error}")
                        error_count += 1

                except Exception as e:
                    logger.error(f"❌ Error calculating Remaining Targets for '{target_username}': {e}")
                    error_count += 1

            logger.info(f"✅ Remaining Targets update complete: {success_count} updated, {skip_count} skipped, {error_count} errors")
            return True

        except Exception as e:
            logger.error(f"❌ Error updating all Remaining Targets: {e}")
            import traceback
            traceback.print_exc()
            return False

    def update_follow_limit_reached(self, record_id) -> bool:
        if not AIRTABLE_AVAILABLE:
            return False
        try:
            from datetime import datetime, timezone, timedelta

            eet = timezone(timedelta(hours=2))
            now_eet = datetime.now(eet)
            formatted_time = now_eet.isoformat()

            self._rate_limit()
            table = self._api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)
            table.update(record_id, {'Reached Follow Limit': formatted_time})
            logger.info(f"✅ Updated 'Reached Follow Limit' for record {record_id}: {formatted_time}")
            return True
        except Exception as e:
            logger.error(f"❌ Error updating 'Reached Follow Limit': {e}")
            import traceback
            traceback.print_exc()
            return False

    def load_profiles(self):
        """Load profile numbers and usernames from Airtable"""
        if not AIRTABLE_AVAILABLE:
            logger.error("pyairtable library not available")
            return []

        try:
            api = self._get_api()
            table = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)
            linked_table = api.table(AIRTABLE_BASE_ID, AIRTABLE_LINKED_TABLE_ID)

            logger.info(f"Fetching profiles from Airtable view {AIRTABLE_VIEW_ID}...")

            # The all() method handles pagination internally with rate limiting
            self._rate_limit()  # Initial rate limit
            records = table.all(view=AIRTABLE_VIEW_ID)

            logger.info(f"Total records fetched: {len(records)}")

            # First pass: collect all AdsPower IDs and Follow Targets attachments
            adspower_ids_to_query = []
            records_with_data = []

            profile_field_names = ['Profile', 'Profile Number', 'AdsPower Profile', 'Profile ID', 'ID A']

            for record in records:
                record_data = {'record': record}

                # Find profile number
                for field_name in profile_field_names:
                    if field_name in record['fields']:
                        record_data['profile_number'] = record['fields'][field_name]
                        break

                # Get AdsPower ID if present
                if 'AdsPower ID' in record['fields']:
                    adspower_id = record['fields']['AdsPower ID']
                    record_data['adspower_id'] = adspower_id
                    if adspower_id and record_data.get('profile_number'):
                        adspower_ids_to_query.append(adspower_id)

                # Get Follow Targets attachments if present
                if 'Follow Targets' in record['fields']:
                    follow_targets_attachments = record['fields']['Follow Targets']
                    if isinstance(follow_targets_attachments, list) and len(follow_targets_attachments) > 0:
                        # Store attachments directly (not linked record IDs)
                        record_data['follow_targets_attachments'] = follow_targets_attachments

                # Get Already Followed (attachment field)
                if 'Already Followed' in record['fields']:
                    already_followed_data = record['fields']['Already Followed']
                    # It should be a list of attachments
                    if isinstance(already_followed_data, list) and len(already_followed_data) > 0:
                        record_data['already_followed_list'] = already_followed_data

                if record_data.get('profile_number'):
                    records_with_data.append(record_data)

            # Query AdsPower names for all profiles
            if adspower_ids_to_query:
                logger.info(f"Querying {len(adspower_ids_to_query)} AdsPower profile names...")
                logger.info(f"AdsPower IDs to query count: {len(adspower_ids_to_query)}")
                adspower_names = self.batch_query_adspower_profiles(adspower_ids_to_query)
                logger.info(f"Got {len(adspower_names)} AdsPower profile names count: {len(adspower_names)}")
            else:
                adspower_names = {}

            # Download Follow Targets attachments directly
            # Create directory for followers files
            followers_dir = os.path.join(os.path.dirname(__file__), 'assigned_followers')
            if not os.path.exists(followers_dir):
                os.makedirs(followers_dir)

            # Download Follow Targets files for each profile
            for record_data in records_with_data:
                follow_targets_attachments = record_data.get('follow_targets_attachments', [])
                if follow_targets_attachments:
                    profile_number = record_data.get('profile_number')
                    # Usually just one attachment
                    attachment = follow_targets_attachments[0]
                    file_url = attachment.get('url')
                    filename = attachment.get('filename', f'profile_{profile_number}_targets.txt')

                    if file_url:
                        filepath = os.path.join(followers_dir, f'{profile_number}_{filename}')

                        # Check if file already exists
                        if os.path.exists(filepath):
                            logger.info(f"Follow Targets file already exists for profile {profile_number}: {filename}")
                            record_data['followers_file'] = filepath
                        else:
                            # Download file
                            try:
                                response = requests.get(file_url, timeout=30)
                                if response.status_code == 200:
                                    with open(filepath, 'w', encoding='utf-8') as f:
                                        f.write(response.text)
                                    logger.info(f"Downloaded Follow Targets file for profile {profile_number}: {filename}")
                                    record_data['followers_file'] = filepath
                                else:
                                    logger.error(f"Failed to download Follow Targets file for profile {profile_number}: HTTP {response.status_code}")
                            except Exception as e:
                                logger.error(f"Error downloading Follow Targets file for profile {profile_number}: {e}")

            # Second pass: build profile data with AdsPower names and Follow Targets data
            profile_data_list = []

            for record_data in records_with_data:
                record = record_data['record']
                profile_number = record_data['profile_number']
                username = None
                adspower_name = None
                airtable_status = None
                vps_status = None
                phase = None
                batch = None

                if 'Username' in record['fields']:
                    username = record['fields']['Username']

                # Get AdsPower name and serial number from batch results
                adspower_id = record_data.get('adspower_id')
                adspower_serial = None
                if adspower_id and str(adspower_id) in adspower_names:
                    profile_info = adspower_names[str(adspower_id)]
                    adspower_name = profile_info.get('name')
                    adspower_serial = profile_info.get('serial_number')

                if 'Status' in record['fields']:
                    airtable_status = record['fields']['Status']

                if 'VPS' in record['fields']:
                    vps_status = record['fields']['VPS']

                if 'Phase' in record['fields']:
                    phase = record['fields']['Phase']

                if 'Batch' in record['fields']:
                    batch = record['fields']['Batch']

                if profile_number and adspower_id:  # Only include profiles with AdsPower IDs
                    # Get Follow Targets file if available (downloaded earlier)
                    assigned_followers_file = record_data.get('followers_file')

                    # Load "Already Followed" from Airtable (attachment field)
                    already_followed_file = None
                    already_followed_data = record_data.get('already_followed_list')

                    if already_followed_data:
                        # It's an attachment - download it
                        if isinstance(already_followed_data, list) and len(already_followed_data) > 0:
                            attachment = already_followed_data[0]
                            file_url = attachment.get('url')

                            if file_url:
                                already_followed_dir = os.path.join(os.path.dirname(__file__), '..', 'already_followed')
                                if not os.path.exists(already_followed_dir):
                                    os.makedirs(already_followed_dir)

                                filepath = os.path.join(already_followed_dir, f'{profile_number}_already_followed.txt')
                                try:
                                    response = requests.get(file_url, timeout=30)
                                    if response.status_code == 200:
                                        with open(filepath, 'w', encoding='utf-8') as f:
                                            f.write(response.text)
                                        logger.info(f"Downloaded 'Already Followed' file from Airtable for profile {profile_number}")
                                        already_followed_file = filepath
                                    else:
                                        logger.error(f"Failed to download 'Already Followed' file for profile {profile_number}: HTTP {response.status_code}")
                                except Exception as e:
                                    logger.error(f"Error downloading 'Already Followed' file for profile {profile_number}: {e}")

                    # Use AdsPower ID as the primary ID
                    profile_data = {
                        'id': str(adspower_id),  # Use AdsPower ID as primary key
                        'profile_number': str(profile_number),
                        'username': username or 'Unknown',
                        'adspower_name': adspower_name,
                        'adspower_id': adspower_id,
                        'adspower_serial': adspower_serial,
                        'airtable_status': airtable_status or 'Alive',
                        'vps_status': vps_status or 'None',
                        'phase': phase or 'None',
                        'batch': batch or 'None',
                        'assigned_followers_file': assigned_followers_file,
                        'already_followed_file': already_followed_file,
                        'airtable_record_id': record['id']  # Store Airtable record ID for updates
                    }
                    profile_data_list.append(profile_data)

            logger.info(f"Loaded {len(profile_data_list)} profiles from Airtable")
            return profile_data_list

        except Exception as e:
            logger.error(f"Error loading profiles from Airtable: {str(e)}")
            import traceback
            traceback.print_exc()
            return []

    def batch_query_adspower_profiles(self, profile_ids):
        """Query AdsPower API for multiple profiles at once"""
        if not profile_ids:
            return {}

        print(f"Querying AdsPower for {len(profile_ids)} profiles...")

        all_profiles = {}
        profile_id_set = set(profile_ids)  # Convert to set for faster lookups

        try:
            headers = {"api_key": ADSPOWER_API_KEY} if ADSPOWER_API_KEY else {}

            # First get all profiles with larger page size
            params = {
                'page_size': 500  # Increase page size
            }

            page = 1
            total_fetched = 0

            while True:
                params['page'] = page

                try:
                    response = requests.get(f"{ADSPOWER_API_URL}/api/v1/user/list",
                                            params=params, headers=headers, timeout=30)

                    if response.status_code == 200:
                        data = response.json()
                        if data.get('code') == 0 and data.get('data', {}).get('list'):
                            profiles = data['data']['list']

                            # Map profiles by user_id
                            for profile in profiles:
                                user_id = profile.get('user_id', '')
                                if user_id in profile_id_set:
                                    name = profile.get('name', '')
                                    serial_number = profile.get('serial_number', '')
                                    all_profiles[str(user_id)] = {
                                        'name': name,
                                        'serial_number': serial_number
                                    }

                            total_fetched += len(profiles)
                            print(
                                f"Fetched page {page}: {len(profiles)} profiles, found {len(all_profiles)} matching so far")

                            # Check if we found all profiles we need
                            if len(all_profiles) >= len(profile_ids):
                                print(f"Found all required profiles!")
                                break

                            # Check if we have more pages
                            total_count = data.get('data', {}).get('count', 0)
                            if total_fetched >= total_count or len(profiles) < 500:
                                break

                            page += 1
                            time.sleep(0.2)  # Small rate limit between pages
                        else:
                            break
                    else:
                        print(f"AdsPower API error: {response.status_code}")
                        break

                except Exception as e:
                    print(f"Error querying AdsPower page {page}: {e}")
                    break

            print(f"Retrieved {len(all_profiles)} AdsPower profiles from {total_fetched} total profiles")

            # For any missing profiles, query individually with concurrent requests
            missing_profiles = [pid for pid in profile_ids if str(pid) not in all_profiles]
            if missing_profiles:
                print(f"Querying {len(missing_profiles)} missing profiles individually...")

                # Use ThreadPoolExecutor for concurrent requests
                from concurrent.futures import ThreadPoolExecutor, as_completed

                def query_single_profile(user_id):
                    try:
                        params = {
                            'user_id': str(user_id),
                            'page_size': 1
                        }

                        response = requests.get(f"{ADSPOWER_API_URL}/api/v1/user/list",
                                                params=params, headers=headers, timeout=5)

                        if response.status_code == 200:
                            data = response.json()
                            if data.get('code') == 0 and data.get('data', {}).get('list'):
                                profiles = data['data']['list']
                                if profiles:
                                    profile = profiles[0]
                                    name = profile.get('name', '')
                                    serial_number = profile.get('serial_number', '')
                                    return user_id, {
                                        'name': name,
                                        'serial_number': serial_number
                                    }
                        return None

                    except Exception as e:
                        print(f"Error querying user_id {user_id}: {e}")
                        return None

                # Query up to 10 profiles concurrently
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {executor.submit(query_single_profile, uid): uid for uid in
                               missing_profiles[:20]}  # Limit to 20

                    for future in as_completed(futures):
                        result = future.result()
                        if result:
                            user_id, profile_data = result
                            all_profiles[str(user_id)] = profile_data

        except Exception as e:
            print(f"Error querying AdsPower: {e}")

        return all_profiles

    def get_vps_options(self):
        """Get all unique VPS options from profiles"""
        vps_options = set()
        with self.profiles_lock:
            for pid, info in self.profiles.items():
                vps = info.get('vps_status', 'None')
                if vps and vps != 'None':
                    vps_options.add(vps)
        return sorted(list(vps_options))

    def get_phase_options(self):
        """Get all unique Phase options from profiles"""
        phase_options = set()
        with self.profiles_lock:
            for pid, info in self.profiles.items():
                phase = info.get('phase', 'None')
                if phase and phase != 'None':
                    phase_options.add(phase)
        return sorted(list(phase_options))

    def get_batch_options(self):
        """Get all unique Batch options from profiles"""
        batch_options = set()
        with self.profiles_lock:
            for pid, info in self.profiles.items():
                batch = info.get('batch', 'None')
                if batch and batch != 'None':
                    batch_options.add(batch)
        return sorted(list(batch_options))
