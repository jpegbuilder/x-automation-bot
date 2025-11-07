import threading
import logging
import time

logger = logging.getLogger(__name__)

MAX_CONCURRENT_PROFILES = 50



class ConcurrencyManager:
    """Manages concurrent profile execution"""

    def __init__(self, *args, **kwargs):
        self.profiles_lock = kwargs.get('profiles_lock') or None
        self.io_executor = kwargs.get('io_executor') or None
        self.profiles = kwargs.get('profiles')
        self.dashboard_cache_manager = kwargs.get('dashboard_cache_manager') or None
        self.async_file_manager = kwargs.get('async_file_manager') or None
        self.pending_profiles_queue = []
        self.monitor_thread = None
        self.concurrent_lock = kwargs.get('concurrent_lock') or None
        self.dashboard_cache_manager = kwargs.get('dashboard_cache_manager') or None
        self.profile_executor = kwargs.get('profile_executor') or None
        self.airtable_manager = kwargs.get('airtable_manager') or None
        self.airtable_executor = kwargs.get('airtable_executor') or None
        self.active_profiles_count = 0
        self.pofile_runner = kwargs.get('pofile_runner') or None

    def get_active_profiles_count(self):
        """Get number of currently active profiles"""
        with self.concurrent_lock:
            count = 0
            with self.profiles_lock:
                for pid, info in self.profiles.items():
                    if info['status'] in ['Running', 'Queueing']:
                        count += 1
            self.active_profiles_count = count
            return count

    def can_start_new_profile(self):
        """Check if we can start a new profile"""
        return self.get_active_profiles_count() < MAX_CONCURRENT_PROFILES

    def add_to_pending_queue(self, profile_id):
        """Add a profile to the pending queue"""
        with self.concurrent_lock:
            if profile_id not in self.pending_profiles_queue:
                self.pending_profiles_queue.append(profile_id)
                logger.info(f"Profile {profile_id} added to pending queue. Queue length: {len(self.pending_profiles_queue)}")

    def start_next_pending_profile(self):
        """Start the next profile from the pending queue if possible"""
        with self.concurrent_lock:
            if not self.pending_profiles_queue:
                return False

            active_count = self.get_active_profiles_count()
            logger.info(
                f"Checking pending queue. Active: {active_count}/{MAX_CONCURRENT_PROFILES}, Pending: {len(self.pending_profiles_queue)}")

            if self.can_start_new_profile():
                next_profile = self.pending_profiles_queue.pop(0)
                logger.info(f"Starting pending profile: {next_profile}")

                # Submit to executor instead of direct call
                self.profile_executor.submit(ProfileRunner.start_profile_internal, next_profile)
                return True
            else:
                logger.info(f"Cannot start pending profile - max concurrent limit reached")
                return False

    def cleanup_finished_profiles(self):
        """Clean up stuck profiles"""
        try:
            cleanup_count = 0
            with self.concurrent_lock:
                with self.profiles_lock:
                    for pid, info in list(self.profiles.items()):
                        if info['status'] in ['Running', 'Queueing']:
                            thread = info.get('thread')
                            if thread is None or not thread.is_alive():
                                info['status'] = 'Finished'
                                info['thread'] = None
                                info['stop_requested'] = False
                                cleanup_count += 1

                                # Update stats
                                self.airtable_executor.submit(
                                    self.airtable_manager.update_profile_statistics_on_completion,
                                    pid
                                )

                # Recalculate active count
                self.active_profiles_count = 0
                with self.profiles_lock:
                    for pid, info in self.profiles.items():
                        if info['status'] in ['Running', 'Queueing']:
                            self.active_profiles_count += 1

            if cleanup_count > 0:
                logger.info(f"Cleaned up {cleanup_count} stuck profiles")
                # Try to start pending
                self.start_next_pending_profile()

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def monitor_and_start_pending(self):
        """Background thread to monitor and start pending profiles"""
        while True:
            try:
                # Check every second
                time.sleep(1)

                # Update dashboard cache
                self.dashboard_cache_manager.update_cache()

                # Check for pending profiles
                if self.pending_profiles_queue:
                    self.start_next_pending_profile()

                # Clean up stuck profiles
                self.cleanup_finished_profiles()

            except Exception as e:
                logger.error(f"Error in monitor thread: {e}")
                time.sleep(2)
