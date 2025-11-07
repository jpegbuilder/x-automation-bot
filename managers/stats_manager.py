import json
import os
from datetime import datetime
import logging


logger = logging.getLogger(__name__)


class StatsManager:
    """Manages profile statistics with async writes"""

    def __init__(self, *args, **kwargs):
        self.profiles = kwargs.get('profiles')
        self.profiles_lock = kwargs.get('profiles_lock') or None
        self.stats_file = kwargs.get('stats_file') or None
        self.status_file = kwargs.get('status_file') or None
        self.file_manager = kwargs.get('file_manager')
        self.dashboard_cache_manager = kwargs.get('dashboard_cache_manager') or None


    @staticmethod
    def get_today_key():
        """Get today's date as key"""
        return datetime.now().strftime('%Y-%m-%d')

    def increment_follow_count(self, profile_id):
        """Increment follow counts for a profile"""
        try:
            pid_str = str(profile_id)
            today = StatsManager.get_today_key()

            # Update in-memory first
            with self.profiles_lock:
                if pid_str in self.profiles:
                    if 'temp_stats' not in self.profiles[pid_str]:
                        self.profiles[pid_str]['temp_stats'] = {'last_run': 0, 'today': 0, 'total': 0}
                    self.profiles[pid_str]['temp_stats']['last_run'] += 1
                    self.profiles[pid_str]['temp_stats']['today'] += 1
                    self.profiles[pid_str]['temp_stats']['total'] += 1

            # Load current stats
            stats = {}
            if os.path.exists(self.stats_file):
                try:
                    with open(self.stats_file, 'r') as f:
                        stats = json.load(f)
                except Exception as e:
                    logger.error(f"Error increment follow counts in increment_follow_count: {e}")

            if pid_str not in stats:
                stats[pid_str] = {
                    'last_run': 0,
                    'today': {},
                    'total_all_time': 0
                }

            stats[pid_str]['last_run'] += 1

            if today not in stats[pid_str]['today']:
                stats[pid_str]['today'][today] = 0
            stats[pid_str]['today'][today] += 1

            stats[pid_str]['total_all_time'] += 1

            # Write asynchronously
            self.file_manager.write_stats_async({pid_str: stats[pid_str]})

        except Exception as e:
            logger.error(f"Error incrementing follow count: {e}")

    def reset_last_run_count(self, profile_id):
        """Reset last run count when profile starts"""
        try:
            pid_str = str(profile_id)

            # Update in-memory
            with self.profiles_lock:
                if pid_str in self.profiles:
                    if 'temp_stats' not in self.profiles[pid_str]:
                        self.profiles[pid_str]['temp_stats'] = {'last_run': 0, 'today': 0, 'total': 0}
                    self.profiles[pid_str]['temp_stats']['last_run'] = 0

            # Load current stats
            stats = {}
            if os.path.exists(self.stats_file):
                try:
                    with open(self.stats_file, 'r') as f:
                        stats = json.load(f)
                except Exception as e:
                    logger.error(f"Error load current stats in reset_last_run_count: {e}")

            if pid_str not in stats:
                stats[pid_str] = {
                    'last_run': 0,
                    'today': {},
                    'total_all_time': 0
                }

            stats[pid_str]['last_run'] = 0

            # Write asynchronously
            self.file_manager.write_stats_async({pid_str: stats[pid_str]})

        except Exception as e:
            logger.error(f"Error resetting last run count: {e}")

    def get_profile_stats(self, profile_id):
        """Get current stats for a profile from cache"""
        pid_str = str(profile_id)

        # Check in-memory stats first
        with self.profiles_lock:
            if pid_str in self.profiles and 'temp_stats' in self.profiles[pid_str]:
                temp_stats = self.profiles[pid_str]['temp_stats']
                return {
                    'last_run': temp_stats.get('last_run', 0),
                    'today': temp_stats.get('today', 0),
                    'total_all_time': temp_stats.get('total', 0)
                }

        # Check dashboard cache
        cached_data = self.dashboard_cache_manager.get_cached_data()
        if pid_str in cached_data['stats']:
            return cached_data['stats'][pid_str]

        # Default
        return {
            'last_run': 0,
            'today': 0,
            'total_all_time': 0
        }
