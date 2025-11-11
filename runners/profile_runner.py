import random
import threading
import logging
import time

logger = logging.getLogger(__name__)


class ProfileRunner:
    """Handles profile execution"""

    def __init__(self, *args, **kwargs):
        self.io_executor = kwargs.get('io_executor') or None
        self.profiles_lock = kwargs.get('profiles_lock') or threading.RLock()
        self.profiles = kwargs.get('profiles')
        self.airtable_executor = kwargs.get('airtable_executor') or None
        self.active_profiles_count = 0
        self.concurrent_lock = kwargs.get('concurrent_lock')
        self.dashboard_cache_manager = kwargs.get('dashboard_cache_manager') or None
        self.status_manager = kwargs.get('status_manager') or None
        self.stats_manager = kwargs.get('stats_manager') or None
        self.config_manager = kwargs.get('config_manager') or None
        self.profile_spec_user_manager = kwargs.get('profile_spec_user_manager') or None
        self.username_manager = kwargs.get('username_manager') or None
        self.already_follow_manager = kwargs.get('already_follow_manager') or None
        self.airtable_manager = kwargs.get('airtable_manager') or None
        self.concurrency_manager = kwargs.get('concurrency_manager')

    def profile_runner(self, pid, max_follows):
        """Main profile runner logic"""
        from x_bot import XFollowBot

        key = str(pid)

        # Check if this profile was blocked before starting
        # Check both persistent status and Airtable status
        persistent_status = self.status_manager.get_persistent_status(pid)
        airtable_status = None
        with self.profiles_lock:
            if key in self.profiles:
                airtable_status = self.profiles[key].get('airtable_status', 'Alive')

        was_blocked = persistent_status == 'blocked' or airtable_status == 'Follow Block'
        is_test_mode = max_follows == 1

        # Update status
        with self.profiles_lock:
            if key not in self.profiles:
                return
            self.profiles[key]['status'] = 'Running'
            self.profiles[key]['stop_requested'] = False

        self.stats_manager.reset_last_run_count(pid)

        # Get configuration
        config = self.config_manager.load_config() or {}
        delay_config = config.get('delays', {})
        limits_config = config.get('limits', {})

        # Extract settings
        between_follows = delay_config.get('between_follows', [8, 20])
        pre_action_delay = delay_config.get('pre_action_delay', [2, 8])
        extended_break_interval = delay_config.get('extended_break_interval', [5, 10])
        extended_break_duration = delay_config.get('extended_break_duration', [60, 120])
        very_long_break_chance = delay_config.get('very_long_break_chance', 0.03)
        very_long_break_duration = delay_config.get('very_long_break_duration', [300, 600])
        hourly_reset_break = delay_config.get('hourly_reset_break', [600, 1200])
        max_follows_per_hour = limits_config.get('max_follows_per_hour', 35)

        # Get the AdsPower serial number for this profile
        adspower_serial = None
        with self.profiles_lock:
            if key in self.profiles:
                adspower_serial = self.profiles[key].get('adspower_serial')

        # Use AdsPower serial number if available, otherwise fall back to pid
        bot_profile_id = adspower_serial if adspower_serial else pid
        bot = XFollowBot(
            profile_id=bot_profile_id,
            airtable_manager=self.airtable_manager
        )

        with self.profiles_lock:
            self.profiles[key]['bot'] = bot

        try:
            # Initialize bot
            if not bot.start_profile():
                with self.profiles_lock:
                    self.profiles[key]['status'] = 'Error'
                return

            if not bot.connect_to_browser():
                with self.profiles_lock:
                    self.profiles[key]['status'] = 'Error'
                bot.stop_profile()
                return

            # Close extra tabs immediately after connecting to reduce RAM usage
            bot.close_extra_tabs()

            if not bot.navigate_to_x():
                if hasattr(bot, 'is_suspended') and bot.is_suspended:
                    logger.error(f"Profile {pid}: SUSPENDED")
                    with self.profiles_lock:
                        self.profiles[key]['status'] = 'Suspended'
                    self.status_manager.mark_profile_suspended(pid)
                else:
                    with self.profiles_lock:
                        self.profiles[key]['status'] = 'Error'
                bot.stop_profile()
                return

            # Check suspension
            if bot.check_if_suspended():
                logger.error(f"Profile {pid}: SUSPENDED")
                with self.profiles_lock:
                    self.profiles[key]['status'] = 'Suspended'
                self.status_manager.mark_profile_suspended(pid)
                bot.stop_profile()
                return

            # Follow loop
            follows_this_hour = 0
            hour_start_time = time.time()

            for i in range(max_follows):
                # Check stop request
                stop_requested = False
                with self.profiles_lock:
                    stop_requested = self.profiles[key].get('stop_requested', False)

                if stop_requested:
                    with self.profiles_lock:
                        self.profiles[key]['status'] = 'Stopped'
                    break

                # Check hourly limits
                current_time = time.time()
                if current_time - hour_start_time >= 3600:
                    follows_this_hour = 0
                    hour_start_time = current_time

                if follows_this_hour >= max_follows_per_hour:
                    break_duration = random.uniform(hourly_reset_break[0], hourly_reset_break[1])
                    time.sleep(break_duration)
                    follows_this_hour = 0
                    hour_start_time = time.time()

                # Get username - prefer profile-specific, fallback to shared
                username = self.profile_spec_user_manager.get_next_username_for_profile(key)
                if not username:
                    # Fallback to shared username pool
                    username = self.username_manager.get_next_username()
                    if not username:
                        with self.profiles_lock:
                            self.profiles[key]['status'] = 'Finished'
                        break

                # Check if already followed
                if self.already_follow_manager.is_already_followed(key, username):
                    logger.info(f"Profile {pid}: Skipping {username} - already followed")
                    continue

                # Pre-action pause
                pause = random.uniform(pre_action_delay[0], pre_action_delay[1])
                time.sleep(pause)

                # Follow user
                logger.info(f"Profile {pid}: Following {username} ({i + 1}/{max_follows})")
                success = bot.follow_user(username, fast_mode=False, delay_config=delay_config)

                if success:
                    self.stats_manager.increment_follow_count(pid)
                    follows_this_hour += 1

                    # Add to already followed list
                    self.already_follow_manager.add_followed_user(key, username)
                    logger.info(f"Profile {pid}: Added {username} to already followed list")

                # Check blocks
                if bot.is_follow_blocked:
                    with self.profiles_lock:
                        self.profiles[key]['status'] = 'Blocked'
                    self.status_manager.mark_profile_blocked(pid)

                    # Update Airtable with follow limit timestamp
                    airtable_record_id = None
                    with self.profiles_lock:
                        if key in self.profiles:
                            airtable_record_id = self.profiles[key].get('airtable_record_id')

                    if airtable_record_id:
                        logger.info(f"Profile {pid}: Updating 'Reached Follow Limit' in Airtable...")
                        self.airtable_executor.submit(
                            self.airtable_manager.update_follow_limit_reached,
                            airtable_record_id
                        )

                    break

                if bot.is_suspended:
                    with self.profiles_lock:
                        self.profiles[key]['status'] = 'Suspended'
                    self.status_manager.mark_profile_suspended(pid)
                    break

                # Delays
                delay = random.uniform(between_follows[0], between_follows[1])
                time.sleep(delay)

                # Extended breaks
                if i > 0 and i % random.randint(extended_break_interval[0], extended_break_interval[1]) == 0:
                    long_break = random.uniform(extended_break_duration[0], extended_break_duration[1])
                    time.sleep(long_break)

                # Very long breaks
                if random.random() < very_long_break_chance:
                    very_long = random.uniform(very_long_break_duration[0], very_long_break_duration[1])
                    time.sleep(very_long)

        except Exception as e:
            logger.error(f"Profile {pid} error: {e}")
            with self.profiles_lock:
                self.profiles[key]['status'] = 'Error'
        finally:
            # Cleanup
            bot.stop_profile()

            # Check if this was a successful test of a previously blocked profile
            final_status = None
            bot_was_blocked = bot.is_follow_blocked if bot else False

            with self.profiles_lock:
                final_status = self.profiles[key]['status']
                if self.profiles[key]['status'] == 'Running':
                    self.profiles[key]['status'] = 'Finished'
                self.profiles[key]['bot'] = None

            # Upload Already Followed file to Airtable
            already_followed_file = None
            airtable_record_id = None
            with self.profiles_lock:
                if key in self.profiles:
                    already_followed_file = self.profiles[key].get('already_followed_file')
                    airtable_record_id = self.profiles[key].get('airtable_record_id')

            if already_followed_file and airtable_record_id:
                logger.info(f"Profile {pid}: Uploading 'Already Followed' file to Airtable...")
                self.airtable_executor.submit(
                    self.airtable_manager.upload_already_followed_file,
                    airtable_record_id,
                    already_followed_file
                )
                # Note: Remaining Targets are updated once at dashboard startup, not per profile

            # If this was a test mode and the profile was previously blocked but completed successfully
            # Check both the final status AND the bot's internal follow block flag
            if is_test_mode and was_blocked:
                if not bot_was_blocked and final_status in ['Running', 'Finished', 'Testing']:
                    logger.info(f"Test successful for previously blocked profile {pid} - reviving profile")
                    self.status_manager.revive_profile_status(pid)
                else:
                    logger.info(f"Test confirmed profile {pid} is still blocked - keeping blocked status")

            # Update Airtable
            if self.profiles[key]['status'] in ['Finished', 'Stopped', 'Blocked', 'Suspended']:
                self.airtable_executor.submit(
                    self.airtable_manager.update_profile_statistics_on_completion,
                    pid
                )

    def profile_runner_wrapper(self, pid, max_follows):
        """Wrapper that handles cleanup"""
        try:
            self.profile_runner(pid, max_follows)
        finally:
            key = str(pid)
            with self.profiles_lock:
                if key in self.profiles:
                    if self.profiles[key]['status'] == 'Running':
                        self.profiles[key]['status'] = 'Finished'
                    self.profiles[key]['thread'] = None
                    self.profiles[key]['stop_requested'] = False

            # Decrement active count
            with self.concurrent_lock:
                self.active_profiles_count = max(0, self.active_profiles_count - 1)

            # Try to start next pending
            time.sleep(0.5)  # Small delay
            self.concurrency_manager.start_next_pending_profile()

    def start_profile_internal(self, pid):
        """Internal function to start a profile"""
        key = str(pid)

        # Check if already running
        with self.profiles_lock:
            if key in self.profiles:
                if self.profiles[key].get('thread') and self.profiles[key]['thread'].is_alive():
                    logger.info(f"Profile {pid} is already running")
                    return False

        # Check Airtable status has priority
        key = str(pid)
        with self.profiles_lock:
            if key in self.profiles:
                airtable_status = self.profiles[key].get('airtable_status', 'Alive')
                if airtable_status == 'Follow Block' or airtable_status == 'Suspended':
                    logger.info(f"Profile {pid} is {airtable_status} in Airtable")
                    return False

        # Get follow limits
        config = self.config_manager.load_config() or {}
        limits_config = config.get('limits', {})
        follow_range = limits_config.get('max_follows_per_profile', [40, 45])
        max_follows = random.randint(follow_range[0], follow_range[1])

        # Update profile info
        with self.profiles_lock:
            if key not in self.profiles:
                self.profiles[key] = {}

            self.profiles[key].update({
                'thread': None,
                'bot': None,
                'status': 'Queueing',
                'stop_requested': False
            })

        # Start thread
        t = threading.Thread(
            target=self.profile_runner_wrapper,
            args=(pid, max_follows),
            daemon=True,
            name=f"Profile-{pid}"
        )

        with self.profiles_lock:
            self.profiles[key]['thread'] = t

        t.start()
        logger.info(f"Profile {pid} started (max {max_follows} follows)")
        return True
