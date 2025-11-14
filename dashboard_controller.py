import threading
import queue
import logging
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from dotenv import load_dotenv

from managers import *
from runners import ProfileRunner
from controlers import ProfileController
from handlers import DashboardHandler
from config import STATS_FILE, STATUS_FILE, MAX_CONCURRENT_PROFILES, PORT

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s | %(filename)s:%(lineno)d')
logger = logging.getLogger(__name__)


@dataclass
class AppState:
    profiles: dict = field(default_factory=dict)
    profiles_lock: threading.RLock = field(default_factory=threading.RLock)
    username_queue: queue.Queue = field(default_factory=queue.Queue)
    pending_profiles: list = field(default_factory=list)
    concurrent_lock: threading.Lock = field(default_factory=threading.Lock)
    username_queue_lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class Executors:
    profile: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=20, thread_name_prefix="profile"))
    airtable: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=5, thread_name_prefix="airtable"))
    io: ThreadPoolExecutor = field(default_factory=lambda: ThreadPoolExecutor(max_workers=10, thread_name_prefix="io"))
    dashboard: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(max_workers=5, thread_name_prefix="dashboard"))

    @property
    def profile_executor(self):
        return self.profile

    @property
    def airtable_executor(self):
        return self.airtable

    @property
    def io_executor(self):
        return self.io

    @property
    def dashboard_executor(self):
        return self.dashboard


class ManagerFactory:

    def __init__(self, state: AppState, executors: Executors):
        self.state = state
        self.executors = executors
        self.managers = {}

    def create_all(self):

        self.managers['config'] = ConfigManager()
        self.managers['async_file'] = AsyncFileManager(stats_file=STATS_FILE, status_file=STATUS_FILE)
        self.managers['already_followed'] = AlreadyFollowedManager()
        self.managers['profile_specific_username'] = ProfileSpecificUsernameManager()

        self.managers['airtable'] = AirtableManager(
            profiles_lock=self.state.profiles_lock,
            profiles=self.state.profiles
        )

        self.managers['username'] = UsernameManager(
            username_queue=self.state.username_queue,
            username_queue_lock=self.state.username_queue_lock,
            io_executor=self.executors.io
        )

        self.managers['dashboard_cache'] = DashboardCacheManager(
            profiles_lock=self.state.profiles_lock,
            io_executor=self.executors.io,
            profiles=self.state.profiles,
            stats_file=STATS_FILE,
            status_file=STATUS_FILE,
            profile_spec_user_manager=self.managers['profile_specific_username']
        )

        self.managers['profile_runner'] = ProfileRunner(
            profiles_lock=self.state.profiles_lock,
            profiles=self.state.profiles,
            config_manager=self.managers['config'],
            username_manager=self.managers['username'],
            already_follow_manager=self.managers['already_followed'],
            airtable_manager=self.managers['airtable'],
            airtable_executor=self.executors.airtable,
            concurrent_lock=self.state.concurrent_lock,
            profile_spec_user_manager=self.managers['profile_specific_username']
        )

        self.managers['concurrency'] = ConcurrencyManager(
            profiles_lock=self.state.profiles_lock,
            io_executor=self.executors.io,
            profile_executor=self.executors.profile,
            profiles=self.state.profiles,
            concurrent_lock=self.state.concurrent_lock,
            airtable_manager=self.managers['airtable'],
            dashboard_cache_manager=self.managers['dashboard_cache'],
            airtable_executor=self.executors.airtable,
            profile_runner=self.managers['profile_runner'],
            pending_profiles_queue=self.state.pending_profiles
        )

        self.managers['profile_runner'].concurrency_manager = self.managers['concurrency']

        self.managers['stats'] = StatsManager(
            profiles=self.state.profiles,
            profiles_lock=self.state.profiles_lock,
            stats_file=STATS_FILE,
            status_file=STATUS_FILE,
            file_manager=self.managers['async_file'],
            dashboard_cache_manager=self.managers['dashboard_cache']
        )

        self.managers['status'] = StatusManager(
            dashboard_cache_lock=self.managers['dashboard_cache'].dashboard_cache_lock,
            profiles_lock=self.state.profiles_lock,
            dashboard_cache=self.managers['dashboard_cache'],
            profiles=self.state.profiles,
            airtable_executor=self.executors.airtable,
            airtable_manager=self.managers['airtable'],
            async_file_manager=self.managers['async_file']
        )

        self.managers['profile_runner'].stats_manager = self.managers['stats']
        self.managers['profile_runner'].status_manager = self.managers['status']
        self.managers['airtable'].stats_manager = self.managers['stats']

        self.managers['profile_controller'] = ProfileController(
            concurrency_manager=self.managers['concurrency'],
            profile_runner=self.managers['profile_runner'],
            profiles_lock=self.state.profiles_lock,
            profiles=self.state.profiles,
            airtable_executor=self.executors.airtable,
            airtable_manager=self.managers['airtable'],
            status_manager=self.managers['status']
        )

        return self.managers


class XBotApplication:

    def __init__(self):
        self.state = AppState()
        self.executors = Executors()
        self.managers = ManagerFactory(self.state, self.executors).create_all()

    def initialize_profiles(self):
        profiles_list = self.managers['airtable'].load_profiles()

        if not profiles_list:
            logger.error("No profiles loaded!")
            return False

        self._register_profiles(profiles_list)
        self._load_profile_data(profiles_list)

        logger.info(f"Loaded {len(profiles_list)} profiles")
        return True

    def _register_profiles(self, profiles_list):
        with self.state.profiles_lock:
            for profile_data in profiles_list:
                pid = str(profile_data['id'])
                self.state.profiles[pid] = {
                    'thread': None,
                    'bot': None,
                    'status': 'Not Running',
                    'stop_requested': False,
                    'username': profile_data['username'],
                    'adspower_name': profile_data.get('adspower_name'),
                    'adspower_id': profile_data.get('adspower_id'),
                    'adspower_serial': profile_data.get('adspower_serial'),
                    'profile_number': profile_data.get('profile_number'),
                    'airtable_status': profile_data['airtable_status'],
                    'vps_status': profile_data.get('vps_status', 'None'),
                    'phase': profile_data.get('phase', 'None'),
                    'batch': profile_data.get('batch', 'None'),
                    'assigned_followers_file': profile_data.get('assigned_followers_file'),
                    'already_followed_file': profile_data.get('already_followed_file'),
                    'airtable_record_id': profile_data.get('airtable_record_id')
                }

    def _load_profile_data(self, profiles_list):
        for profile_data in profiles_list:
            pid = profile_data['id']
            self._load_assigned_followers(pid, profile_data)
            self._load_already_followed(pid, profile_data)

    def _load_assigned_followers(self, pid, profile_data):
        followers_file = profile_data.get('assigned_followers_file')
        if followers_file:
            count = self.managers['profile_specific_username'].load_profile_usernames(pid, followers_file)
            logger.info(f"Profile {pid}: Loaded {count} assigned followers")

    def _load_already_followed(self, pid, profile_data):
        already_followed_file = profile_data.get('already_followed_file')
        if not already_followed_file:
            already_followed_file = self._create_already_followed_file(profile_data)

        count = self.managers['already_followed'].load_already_followed(pid, already_followed_file)
        logger.info(f"Profile {pid}: Loaded {count} already followed users")

        with self.state.profiles_lock:
            if str(pid) in self.state.profiles:
                self.state.profiles[str(pid)]['already_followed_file'] = already_followed_file

    def _create_already_followed_file(self, profile_data):
        import os
        profile_number = profile_data.get('profile_number')
        if not profile_number:
            return None

        already_followed_dir = os.path.join(os.path.dirname(__file__), 'already_followed')
        os.makedirs(already_followed_dir, exist_ok=True)
        return os.path.join(already_followed_dir, f'{profile_number}_already_followed.txt')

    def start_background_monitor(self):
        monitor_thread = threading.Thread(
            target=self.managers['concurrency'].monitor_and_start_pending,
            daemon=True,
            name="Monitor"
        )
        monitor_thread.start()
        logger.info("Background monitor started")

    def create_server(self, port: int):
        httpd = ThreadingHTTPServer(('', port), DashboardHandler)

        httpd.app = self

        httpd.profiles = self.state.profiles
        httpd.profiles_lock = self.state.profiles_lock
        httpd.io_executor = self.executors.io
        httpd.stats_file = STATS_FILE
        httpd.status_file = STATUS_FILE
        httpd.profile_executor = self.executors.profile
        httpd.pending_profiles_queue = self.state.pending_profiles
        httpd.MAX_CONCURRENT_PROFILES = int(MAX_CONCURRENT_PROFILES)

        httpd.request_lock = threading.Lock()
        httpd.request_counter = 0

        httpd.config_manager = self.managers['config']
        httpd.dashboard_cache_manager = self.managers['dashboard_cache']
        httpd.airtable_manager = self.managers['airtable']
        httpd.concurrency_manager = self.managers['concurrency']
        httpd.username_manager = self.managers['username']
        httpd.profile_controller = self.managers['profile_controller']

        return httpd

    def run(self):
        if not self.initialize_profiles():
            return

        username_count = self.managers['username'].load_usernames_to_queue()
        logger.info(f"Loaded {username_count} usernames")

        self.managers['dashboard_cache'].update_cache()

        logger.info("Updating Remaining Targets for all Target records...")
        self.executors.airtable.submit(
            self.managers['airtable'].update_all_remaining_targets
        )

        self.start_background_monitor()

        self._log_startup_info()

        try:
            httpd = self.create_server(PORT)
            logger.info(f"Server started successfully on port {PORT}")
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        except OSError as e:
            self._handle_server_error(e)
        except Exception as e:
            logger.error(f"Server error: {e}", exc_info=True)

    def _log_startup_info(self):
        logger.info(f"Dashboard at http://localhost:{PORT}")
        logger.info("✨ ULTIMATE FIX APPLIED:")
        logger.info("  - Separate dashboard cache from profile operations")
        logger.info("  - Multiple thread pools for different tasks")
        logger.info("  - Async file I/O - no blocking")
        logger.info("  - Ultra-fast request handling")
        logger.info("  - Smart batching for Start All")
        logger.info("  - Profiles start in order from lowest to highest ID")
        logger.info("🚀 Dashboard will NEVER freeze again!")

    def _handle_server_error(self, error: OSError):
        if error.errno == 48:  # Address already in use
            logger.error(f"Port {PORT} is already in use.")
            logger.info("To kill the existing server, run: lsof -ti:8080 | xargs kill -9")
        else:
            logger.error(f"Server error: {error}")


def main():
    app = XBotApplication()
    app.run()


if __name__ == '__main__':
    main()