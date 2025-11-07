import os
import threading
import logging

logger = logging.getLogger(__name__)


class AlreadyFollowedManager:
    """Manages already followed users for each profile"""

    # Dictionary to store already followed usernames for each profile
    already_followed = {}
    already_followed_lock = threading.Lock()
    already_followed_files = {}  # Store file paths for each profile

    def load_already_followed(self, profile_id, already_followed_file):
        """Load already followed usernames from file"""
        try:
            with self.already_followed_lock:
                # Store file path
                self.already_followed_files[profile_id] = already_followed_file

                # Initialize set for this profile
                if profile_id not in self.already_followed:
                    self.already_followed[profile_id] = set()

                if already_followed_file and os.path.exists(already_followed_file):
                    with open(already_followed_file, 'r', encoding='utf-8') as f:
                        usernames = [line.strip() for line in f.readlines() if line.strip()]

                    self.already_followed[profile_id].update(usernames)
                    logger.info(f"Loaded {len(usernames)} already followed usernames for profile {profile_id}")
                    return len(usernames)
                else:
                    # Create empty file if it doesn't exist
                    if already_followed_file:
                        already_followed_dir = os.path.dirname(already_followed_file)
                        if not os.path.exists(already_followed_dir):
                            os.makedirs(already_followed_dir)
                        with open(already_followed_file, 'w', encoding='utf-8') as f:
                            pass  # Create empty file
                        logger.info(f"Created new 'Already Followed' file for profile {profile_id}")
                    return 0

        except Exception as e:
            logger.error(f"Error loading already followed for profile {profile_id}: {e}")
            return 0

    def is_already_followed(self, profile_id, username):
        """Check if username was already followed by this profile"""
        with self.already_followed_lock:
            if profile_id not in self.already_followed:
                return False
            return username in self.already_followed[profile_id]

    def add_followed_user(self, profile_id, username):
        """Add username to already followed list and update file"""
        try:
            with self.already_followed_lock:
                # Add to memory
                if profile_id not in self.already_followed:
                    self.already_followed[profile_id] = set()

                self.already_followed[profile_id].add(username)

                # Append to file immediately
                file_path = self.already_followed_files.get(profile_id)
                if file_path:
                    with open(file_path, 'a', encoding='utf-8') as f:
                        f.write(username + '\n')
                    logger.debug(f"Profile {profile_id}: Added '{username}' to already followed file")
                    return True
                return False

        except Exception as e:
            logger.error(f"Error adding followed user for profile {profile_id}: {e}")
            return False

    def get_already_followed_count(self, profile_id):
        """Get count of already followed users for a profile"""
        with self.already_followed_lock:
            if profile_id not in self.already_followed:
                return 0
            return len(self.already_followed[profile_id])