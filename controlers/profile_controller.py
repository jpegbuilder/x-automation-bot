import threading
import logging

logger = logging.getLogger(__name__)


class ProfileController:
    """Controls profile operations"""

    def __init__(self, *args, **kwargs):
        self.concurrency_manager = kwargs.get('concurrency_manager') or None
        self.profile_runner = kwargs.get('profile_runner') or None
        self.profiles_lock = kwargs.get('profiles_lock') or None
        self.profiles = kwargs.get('profiles')
        self.airtable_executor = kwargs.get('airtable_executor') or None
        self.airtable_manager = kwargs.get('airtable_manager') or None
        self.status_manager = kwargs.get('status_manager') or None

    def start_profile(self, pid):
        """Start a profile with concurrent limit management"""
        if self.concurrency_manager.can_start_new_profile():
            return self.profile_runner.start_profile_internal(pid)
        else:
            self.concurrency_manager.add_to_pending_queue(pid)
            with self.profiles_lock:
                if str(pid) in self.profiles:
                    self.profiles[str(pid)]['status'] = 'Pending'
            logger.info(f"Profile {pid} queued")
            return True

    def stop_profile(self, pid):
        """Stop a running profile"""
        key = str(pid)

        with self.profiles_lock:
            if key not in self.profiles:
                return False

            self.profiles[key]['stop_requested'] = True
            bot = self.profiles[key].get('bot')

        if bot:
            try:
                bot.stop_profile()
            except:
                pass

        # Wait for thread
        thread = None
        with self.profiles_lock:
            thread = self.profiles[key].get('thread')

        if thread and thread.is_alive():
            thread.join(timeout=2)

        with self.profiles_lock:
            self.profiles[key]['thread'] = None
            self.profiles[key]['status'] = 'Stopped'

        # Update statistics
        self.airtable_executor.submit(
            self.airtable_manager.update_profile_statistics_on_completion,
            pid
        )

        return True

    def test_profile(self, pid):
        """Test a profile by running it with just 1 follow"""
        # Start the profile with max_follows=1 for testing
        return self.test_profile_internal(pid)

    def test_profile_internal(self, pid):
        """Internal function to test a profile with just 1 follow"""
        key = str(pid)

        # Check if already running
        with self.profiles_lock:
            if key in self.profiles:
                if self.profiles[key].get('thread') and self.profiles[key]['thread'].is_alive():
                    logger.info(f"Profile {pid} is already running")
                    return False

        # For test mode, we allow testing of blocked/suspended profiles
        # to check if they're still blocked or have been unblocked
        persistent_status = self.status_manager.get_persistent_status(pid)
        if persistent_status in ['blocked', 'suspended']:
            logger.info(f"Testing {persistent_status} profile {pid}")

        # Update profile info
        with self.profiles_lock:
            if key not in self.profiles:
                self.profiles[key] = {}

            self.profiles[key].update({
                'thread': None,
                'bot': None,
                'status': 'Testing',
                'stop_requested': False
            })

        # Start thread with max_follows=1 for testing
        t = threading.Thread(
            target=self.profile_runner.profile_runner_wrapper,
            args=(pid, 1),  # Only 1 follow for testing
            daemon=True,
            name=f"Profile-{pid}-Test"
        )

        with self.profiles_lock:
            self.profiles[key]['thread'] = t

        t.start()
        logger.info(f"Profile {pid} started in TEST mode (1 follow only)")
        return True
