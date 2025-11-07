import os
import queue
import logging
import threading

logger = logging.getLogger(__name__)


class UsernameManager:
    """Manages username allocation"""

    def __init__(self, *args, **kwargs):
        self.username_queue = kwargs.get('username_queue') or queue.Queue()
        self.username_queue_lock = threading.Lock()
        self.io_executor = kwargs.get('io_executor') or None
        self.usernames = kwargs.get('usernames') or []
        self.usernames_lock = kwargs.get('usernames_lock') or None

    def load_usernames_to_queue(self):
        """Load all usernames from file into memory queue"""
        try:
            if os.path.exists('usernames.txt'):
                with open('usernames.txt', 'r', encoding='utf-8') as f:
                    usernames = [line.strip() for line in f.readlines() if line.strip()]

                # Clear existing queue first
                with self.username_queue_lock:
                    while not self.username_queue.empty():
                        try:
                            self.username_queue.get_nowait()
                        except queue.Empty:
                            break

                    # Add new usernames to queue
                    for username in usernames:
                        self.username_queue.put(username)

                logger.info(f"Loaded {len(usernames)} usernames into memory queue")
                return len(usernames)
            return 0
        except Exception as e:
            logger.error(f"Error loading usernames: {e}")
            return 0

    def get_next_username(self):
        """Get next username from memory queue and immediately update file"""
        try:
            with self.username_queue_lock:
                username = self.username_queue.get_nowait()
                logger.debug(f"Username '{username}' allocated from memory queue")

                # Immediately update the file to reflect the removal
                # Submit to IO executor for async processing but don't wait
                self.io_executor.submit(UsernameManager._update_username_file)

                return username
        except queue.Empty:
            logger.info("No more usernames available in memory queue")
            return None

    def _update_username_file(self):
        """Update usernames.txt file with current queue contents"""
        try:
            with self.username_queue_lock:
                # Get all remaining usernames from queue
                remaining_usernames = []
                temp_list = []

                # Empty the queue temporarily to get all items
                while not self.username_queue.empty():
                    try:
                        temp_list.append(self.username_queue.get_nowait())
                    except queue.Empty:
                        break

                # Put them back in the queue
                for username in temp_list:
                    self.username_queue.put(username)
                    remaining_usernames.append(username)

                # Write to file
                with open('usernames.txt', 'w', encoding='utf-8') as f:
                    for username in remaining_usernames:
                        f.write(username + '\n')

                logger.debug(f"Updated usernames.txt with {len(remaining_usernames)} usernames")

        except Exception as e:
            logger.error(f"Error updating username file: {e}")

    def get_remaining_count(self):
        """Get remaining username count from memory queue"""
        with self.username_queue_lock:
            return self.username_queue.qsize()
