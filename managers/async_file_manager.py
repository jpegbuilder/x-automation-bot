import json
import os
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


io_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="io")


class AsyncFileManager:
    """Handles all file I/O operations asynchronously"""

    def __init__(self, *args, **kwargs):
        self.stats_write_lock = threading.Lock()
        self.status_write_lock = threading.Lock()
        self.stats_file = kwargs.get('stats_file') or None
        self.status_file = kwargs.get('status_file') or None


    def write_stats_async(self, stats_update):
        """Write stats update asynchronously"""
        io_executor.submit(self._write_stats, stats_update)

    def _write_stats(self, stats_update):
        """Internal stats writer"""
        try:
            with self.stats_write_lock:
                # Load existing
                existing = {}
                if os.path.exists(self.stats_file):
                    try:
                        with open(self.stats_file, 'r') as f:
                            existing = json.load(f)
                    except:
                        pass

                # Update
                existing.update(stats_update)

                # Write to temp file
                temp_file = self.stats_file + '.tmp'
                with open(temp_file, 'w') as f:
                    json.dump(existing, f, indent=2)

                # Atomic rename
                os.replace(temp_file, self.stats_file)

        except Exception as e:
            logger.error(f"Error writing stats: {e}")

    def write_status_async(self, status_update):
        """Write status update asynchronously"""
        io_executor.submit(self._write_status, status_update)

    def _write_status(self, status_update):
        """Internal status writer"""
        try:
            with self.status_write_lock:
                # Load existing
                existing = {}
                if os.path.exists(self.status_file):
                    try:
                        with open(self.status_file, 'r') as f:
                            existing = json.load(f)
                    except:
                        pass

                # Update
                for key, value in status_update.items():
                    if value is None and key in existing:
                        del existing[key]
                    else:
                        existing[key] = value

                # Write to temp file
                temp_file = self.status_file + '.tmp'
                with open(temp_file, 'w') as f:
                    json.dump(existing, f, indent=2)

                # Atomic rename
                os.replace(temp_file, self.status_file)

        except Exception as e:
            logger.error(f"Error writing status: {e}")
