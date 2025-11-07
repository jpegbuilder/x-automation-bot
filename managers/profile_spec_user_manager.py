import os
import queue
import threading
import logging

logger = logging.getLogger(__name__)


class ProfileSpecificUsernameManager:
    """Manages profile-specific username allocation from assigned followers files"""

    def __init__(self):
        # Dictionary to store queues for each profile
        self.profile_queues = {}
        self.profile_queues_lock = threading.Lock()

    def load_profile_usernames(self, profile_id, followers_file):
        """Load usernames from a profile's assigned followers file"""
        try:
            if not followers_file or not os.path.exists(followers_file):
                logger.warning(f"No followers file for profile {profile_id}")
                return 0

            with open(followers_file, 'r', encoding='utf-8') as f:
                usernames = [line.strip() for line in f.readlines() if line.strip()]

            # Create a queue for this profile
            with self.profile_queues_lock:
                if profile_id not in self.profile_queues:
                    self.profile_queues[profile_id] = queue.Queue()

                profile_queue = self.profile_queues[profile_id]

                # Clear existing queue first
                while not profile_queue.empty():
                    try:
                        profile_queue.get_nowait()
                    except queue.Empty:
                        break

                # Add new usernames to queue
                for username in usernames:
                    profile_queue.put(username)

            logger.info(f"Loaded {len(usernames)} usernames for profile {profile_id} from {followers_file}")
            return len(usernames)

        except Exception as e:
            logger.error(f"Error loading usernames for profile {profile_id}: {e}")
            return 0

    def get_next_username_for_profile(self, profile_id):
        """Get next username for a specific profile"""
        try:
            with self.profile_queues_lock:
                if profile_id not in self.profile_queues:
                    logger.warning(f"No username queue for profile {profile_id}")
                    return None

                profile_queue = self.profile_queues[profile_id]
                username = profile_queue.get_nowait()
                logger.debug(f"Profile {profile_id}: Allocated username '{username}'")
                return username

        except queue.Empty:
            logger.info(f"Profile {profile_id}: No more usernames available")
            return None

    def get_remaining_count_for_profile(self, profile_id):
        """Get remaining username count for a specific profile"""
        with self.profile_queues_lock:
            if profile_id not in self.profile_queues:
                return 0
            return self.profile_queues[profile_id].qsize()
