import json
import os
import threading
import time
import logging
from datetime import datetime
from .profile_spec_user_manager import ProfileSpecificUsernameManager

logger = logging.getLogger(__name__)


class DashboardCacheManager:
    def __init__(self, *args, **kwargs):
        self.profiles_lock = kwargs.get('profiles_lock')
        self.io_executor = kwargs.get('io_executor')
        self.profiles = kwargs.get('profiles')
        self.stats_file = kwargs.get('stats_file')
        self.status_file = kwargs.get('status_file')
        self.profile_spec_user_manager = kwargs.get('profile_spec_user_manager')  # может быть None

        self.dashboard_cache_lock = threading.RLock()
        self.dashboard_cache = self.get_cache_dict()

    @staticmethod
    def get_cache_dict():
        return {
            'profiles': {},
            'stats': {},
            'status': {},
            'last_update': 0,
            'update_interval': 1.0,
        }

    def update_cache(self):
        try:
            current_time = time.time()
            with self.dashboard_cache_lock:
                if current_time - self.dashboard_cache['last_update'] < self.dashboard_cache['update_interval']:
                    return

            # снимок профилей
            profiles_snapshot = {}
            if self.profiles_lock:
                with self.profiles_lock:
                    src = dict(self.profiles)
            else:
                src = dict(self.profiles)

            for pid, info in src.items():
                assigned_count = 0
                if self.profile_spec_user_manager:
                    try:
                        assigned_count = self.profile_spec_user_manager.get_remaining_count_for_profile(pid)
                    except Exception as e:
                        logger.warning(f"assigned_followers_count error for {pid}: {e}")

                profiles_snapshot[pid] = {
                    'status': info.get('status', 'Not Running'),
                    'stop_requested': info.get('stop_requested', False),
                    'username': info.get('username', 'Unknown'),
                    'adspower_name': info.get('adspower_name'),
                    'airtable_status': info.get('airtable_status', 'Alive'),
                    'vps_status': info.get('vps_status', 'None'),
                    'phase': info.get('phase', 'None'),
                    'batch': info.get('batch', 'None'),
                    'profile_number': info.get('profile_number', pid),
                    'has_assigned_followers': info.get('assigned_followers_file') is not None,
                    'assigned_followers_count': assigned_count,
                    'temp_stats': info.get('temp_stats', {'last_run': 0, 'today': 0, 'total': 0}),
                }

            with self.dashboard_cache_lock:
                self.dashboard_cache['profiles'] = profiles_snapshot
                self.dashboard_cache['last_update'] = current_time

            # файлы — синхронно, если нет executor’а
            if self.io_executor and not self.io_executor._shutdown:
                try:
                    self.io_executor.submit(self._update_file_caches)
                except RuntimeError:
                    self._update_file_caches()
            else:
                self._update_file_caches()

        except Exception as e:
            logger.error(f"Error updating dashboard cache: {e}")

    def _update_file_caches(self):
        try:
            # STATS
            if self.stats_file and os.path.exists(self.stats_file):
                try:
                    with open(self.stats_file, 'r') as f:
                        stats_data = json.load(f)
                    today = datetime.now().strftime('%Y-%m-%d')
                    processed_stats = {
                        pid: {
                            'last_run': s.get('last_run', 0),
                            'today': s.get('today', {}).get(today, 0),
                            'total_all_time': s.get('total_all_time', 0),
                        }
                        for pid, s in stats_data.items()
                    }
                    with self.dashboard_cache_lock:
                        self.dashboard_cache['stats'] = processed_stats
                except Exception as e:
                    logger.error(f"Error updating stats cache: {e}")

            # STATUS
            if self.status_file and os.path.exists(self.status_file):
                try:
                    with open(self.status_file, 'r') as f:
                        status_data = json.load(f)
                    with self.dashboard_cache_lock:
                        self.dashboard_cache['status'] = status_data
                except Exception as e:
                    logger.error(f"Error updating status cache: {e}")

        except Exception as e:
            logger.error(f"Error updating file caches: {e}")

    def get_cached_data(self):
        with self.dashboard_cache_lock:
            return {
                'profiles': dict(self.dashboard_cache['profiles']),
                'stats': dict(self.dashboard_cache['stats']),
                'status': dict(self.dashboard_cache['status']),
            }
