import logging

logger = logging.getLogger(__name__)


class StatusManager:
    """Manages profile status persistence with async writes"""

    def __init__(self, *args, **kwargs):
        self.dashboard_cache_lock = kwargs.get('dashboard_cache_lock') or None
        self.profiles_lock = kwargs.get('profiles_lock') or None
        self.dashboard_cache = kwargs.get('dashboard_cache') or {}
        self.profiles = kwargs.get('profiles')
        self.airtable_executor = kwargs.get('airtable_executor') or None
        self.airtable_manager = kwargs.get('airtable_manager') or None
        self.async_file_manager = kwargs.get('async_file_manager') or None

    def get_persistent_status(self, profile_id):
        """Get persistent status for a profile from cache"""
        # Get cached data without holding locks for too long
        try:
            with self.dashboard_cache_lock:
                # Quick copy of just what we need
                status_dict = self.dashboard_cache.get('status', {})

            # Return the status outside of the lock
            return status_dict.get(str(profile_id))
        except Exception as e:
            logger.error(f"Error getting persistent status for {profile_id}: {e}")
            return None

    def mark_profile_blocked(self, profile_id):
        """Mark profile as permanently blocked"""
        try:
            pid_str = str(profile_id)

            # Update in-memory
            with self.profiles_lock:
                if pid_str in self.profiles:
                    self.profiles[pid_str]['status'] = 'Blocked'
                    self.profiles[pid_str]['stop_requested'] = True
                    self.profiles[pid_str]['airtable_status'] = 'Follow Block'

            # Write status asynchronously
            self.async_file_manager.write_status_async({pid_str: 'blocked'})

            logger.info(f"Profile {profile_id} marked as BLOCKED")

            # Update Airtable asynchronously
            self.airtable_executor.submit(
                self.airtable_manager.update_profile_status,
                profile_id,
                'Follow Block'
            )

        except Exception as e:
            logger.error(f"Error marking profile {profile_id} as blocked: {e}")

    def mark_profile_cloudflare_blocked(self, profile_id):
        """Mark profile as permanently blocked"""
        try:
            pid_str = str(profile_id)

            # Update in-memory
            with self.profiles_lock:
                if pid_str in self.profiles:
                    self.profiles[pid_str]['status'] = 'Blocked'
                    self.profiles[pid_str]['stop_requested'] = True
                    self.profiles[pid_str]['airtable_status'] = 'Cloudflare Blocked'

            # Write status asynchronously
            self.async_file_manager.write_status_async({pid_str: 'blocked'})

            logger.info(f"Profile {profile_id} marked as Cloudflare BLOCKED")

            # Update Airtable asynchronously
            self.airtable_executor.submit(
                self.airtable_manager.update_profile_status,
                profile_id,
                'Cloudflare Blocked'
            )

        except Exception as e:
            logger.error(f"Error marking profile {profile_id} as blocked: {e}")

    def mark_profile_suspended(self, profile_id):
        """Mark profile as permanently suspended"""
        try:
            pid_str = str(profile_id)

            # Update in-memory
            with self.profiles_lock:
                if pid_str in self.profiles:
                    self.profiles[pid_str]['status'] = 'Suspended'
                    self.profiles[pid_str]['airtable_status'] = 'Suspended'

            # Write status asynchronously
            self.async_file_manager.write_status_async({pid_str: 'suspended'})

            logger.info(f"Profile {profile_id} marked as SUSPENDED")

            # Update Airtable asynchronously
            self.airtable_executor.submit(
                self.airtable_manager.update_profile_status,
                profile_id,
                'Suspended'
            )

        except Exception as e:
            logger.error(f"Error marking profile {profile_id} as suspended: {e}")

    def revive_profile_status(self, profile_id):
        """Revive a blocked/suspended profile back to alive"""
        try:
            pid_str = str(profile_id)

            # Update in-memory
            with self.profiles_lock:
                if pid_str in self.profiles:
                    self.profiles[pid_str]['status'] = 'Not Running'
                    self.profiles[pid_str]['airtable_status'] = 'Alive'

            # Write status asynchronously (None = delete)
            self.async_file_manager.write_status_async({pid_str: None})

            logger.info(f"Profile {profile_id} REVIVED")

            # Update Airtable asynchronously
            self.airtable_executor.submit(
                self.airtable_manager.update_profile_status,
                profile_id,
                'Alive'
            )

            return True

        except Exception as e:
            logger.error(f"Error reviving profile {profile_id}: {e}")
            return False
