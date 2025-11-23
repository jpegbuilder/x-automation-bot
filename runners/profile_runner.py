import random
import threading
import logging
import time

logger = logging.getLogger(__name__)


class ProfileRunner:
    """Handles profile execution - scenarios only"""

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
        from x_bot.core import XFollowBot
        from x_bot.scenario.scenario_engine import ScenarioEngine

        key = str(pid)

        # Check if this profile was blocked before starting
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

        # ========================================
        # STEP 1: Create bot and load scenarios
        # ========================================
        inner_bot = XFollowBot(
            profile_id=bot_profile_id,
            airtable_manager=self.airtable_manager
        )
        logger.info(f'Profile {pid}: XFollowBot created successfully (ID: {inner_bot.profile_id})')

        # Load ScenarioEngine - REQUIRED, no fallback
        try:
            engine = ScenarioEngine(bot=inner_bot)  # Auto-search scenarios.yaml
            scenario_names = list(engine.scenarios.keys())
            logger.info(
                f"Profile {pid}: ScenarioEngine loaded with {len(scenario_names)} scenarios: {scenario_names}"
            )
        except FileNotFoundError as e:
            logger.error(f"Profile {pid}: scenarios.yaml not found - {e}")
            logger.error(f"Profile {pid}: Cannot start without scenarios.yaml")
            with self.profiles_lock:
                self.profiles[key]['status'] = 'Error'
            return
        except Exception as e:
            logger.error(f"Profile {pid}: Failed to load ScenarioEngine - {e}", exc_info=True)
            with self.profiles_lock:
                self.profiles[key]['status'] = 'Error'
            return

        # Store references
        with self.profiles_lock:
            self.profiles[key]['inner_bot'] = inner_bot
            self.profiles[key]['scenario_engine'] = engine

        try:
            # ========================================
            # STEP 2: Start browser
            # ========================================
            if not inner_bot.start_profile():
                logger.error(f"Profile {pid}: Failed to start profile")
                with self.profiles_lock:
                    self.profiles[key]['status'] = 'Error'
                return

            if not inner_bot.connect_to_browser():
                logger.error(f"Profile {pid}: Failed to connect to browser")
                with self.profiles_lock:
                    self.profiles[key]['status'] = 'Error'
                inner_bot.stop_profile()
                return

            # Close extra tabs immediately after connecting to reduce RAM usage
            inner_bot.close_extra_tabs()

            if not inner_bot.check_cloudflare():
                with self.profiles_lock:
                    self.profiles[key]['status'] = 'Cloudflare Blocked'
                self.status_manager.mark_profile_cloudflare_blocked(pid)
                inner_bot.stop_profile()

            if not inner_bot.navigate_to_x():
                if hasattr(inner_bot, 'is_suspended') and inner_bot.is_suspended:
                    logger.error(f"Profile {pid}: Account SUSPENDED")
                    with self.profiles_lock:
                        self.profiles[key]['status'] = 'Suspended'
                    self.status_manager.mark_profile_suspended(pid)
                else:
                    logger.error(f"Profile {pid}: Failed to navigate to X")
                    with self.profiles_lock:
                        self.profiles[key]['status'] = 'Error'
                inner_bot.stop_profile()
                return

            # Check suspension
            if inner_bot.check_if_suspended():
                logger.error(f"Profile {pid}: Account SUSPENDED")
                with self.profiles_lock:
                    self.profiles[key]['status'] = 'Suspended'
                self.status_manager.mark_profile_suspended(pid)
                inner_bot.stop_profile()
                return

            # Update status to Running
            with self.profiles_lock:
                self.profiles[key]['status'] = 'Running'

            # ========================================
            # STEP 3: Follow loop with scenarios
            # ========================================
            follows_this_hour = 0
            hour_start_time = time.time()

            for i in range(max_follows):
                # Check stop request
                stop_requested = False
                with self.profiles_lock:
                    stop_requested = self.profiles[key].get('stop_requested', False)

                if stop_requested:
                    logger.info(f"Profile {pid}: Stop requested")
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
                    logger.info(f"Profile {pid}: Hourly limit reached, taking {break_duration:.0f}s break")
                    time.sleep(break_duration)
                    follows_this_hour = 0
                    hour_start_time = time.time()

                # Get username - prefer profile-specific, fallback to shared
                username = self.profile_spec_user_manager.get_next_username_for_profile(key)
                if not username:
                    # Fallback to shared username pool
                    username = self.username_manager.get_next_username()
                    if not username:
                        logger.info(f"Profile {pid}: No more usernames available")
                        with self.profiles_lock:
                            self.profiles[key]['status'] = 'Finished'
                        break

                # Check if already followed
                if self.already_follow_manager.is_already_followed(key, username):
                    logger.info(f"Profile {pid}: Skipping @{username} - already followed")
                    continue

                # Pre-action pause
                pause = random.uniform(pre_action_delay[0], pre_action_delay[1])
                time.sleep(pause)

                # ========================================
                # Execute scenario (round-robin automatic)
                # ========================================
                try:
                    # Choose scenario - automatic round-robin
                    scenario_name = engine.choose_scenario_for_user(
                        profile_id=pid,
                        username=username
                    )

                    logger.info(
                        f"Profile {pid}: Executing scenario '{scenario_name}' for @{username} ({i + 1}/{max_follows})"
                    )

                    # Execute scenario
                    result = engine.execute_scenario(
                        name=scenario_name,
                        target_username=username
                    )

                    success = result.get('success', False)

                    if not success:
                        error = result.get('error', 'Unknown error')
                        logger.warning(
                            f"Profile {pid}: Scenario '{scenario_name}' failed for @{username}: {error}"
                        )

                except Exception as e:
                    logger.error(
                        f"Profile {pid}: Exception during scenario execution for @{username}: {e}",
                        exc_info=True
                    )
                    success = False

                # Update stats if successful
                if success:
                    self.stats_manager.increment_follow_count(pid)
                    follows_this_hour += 1

                    # Add to already followed list
                    self.already_follow_manager.add_followed_user(key, username)
                    logger.info(
                        f"Profile {pid}: Successfully completed scenario '{scenario_name}' for @{username}"
                    )

                # Check for blocks - ALWAYS through inner_bot
                if inner_bot.is_follow_blocked:
                    logger.error(f"Profile {pid}: FOLLOW BLOCK detected")
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

                if inner_bot.is_suspended:
                    logger.error(f"Profile {pid}: SUSPENDED detected")
                    with self.profiles_lock:
                        self.profiles[key]['status'] = 'Suspended'
                    self.status_manager.mark_profile_suspended(pid)
                    break

                # Delays between follows
                delay = random.uniform(between_follows[0], between_follows[1])
                logger.debug(f"Profile {pid}: Waiting {delay:.1f}s before next action")
                time.sleep(delay)

                # Extended breaks
                if i > 0 and i % random.randint(extended_break_interval[0], extended_break_interval[1]) == 0:
                    long_break = random.uniform(extended_break_duration[0], extended_break_duration[1])
                    logger.info(f"Profile {pid}: Taking extended break ({long_break:.0f}s)")
                    time.sleep(long_break)

                # Very long breaks
                if random.random() < very_long_break_chance:
                    very_long = random.uniform(very_long_break_duration[0], very_long_break_duration[1])
                    logger.info(f"Profile {pid}: Taking very long break ({very_long:.0f}s)")
                    time.sleep(very_long)

        except Exception as e:
            logger.error(f"Profile {pid}: Unexpected error in main loop: {e}", exc_info=True)
            with self.profiles_lock:
                self.profiles[key]['status'] = 'Error'

        finally:
            # ========================================
            # STEP 4: Cleanup
            # ========================================
            inner_bot.stop_profile()

            # Check if this was a successful test of a previously blocked profile
            final_status = None
            bot_was_blocked = inner_bot.is_follow_blocked if inner_bot else False

            with self.profiles_lock:
                final_status = self.profiles[key]['status']
                if self.profiles[key]['status'] == 'Running':
                    self.profiles[key]['status'] = 'Finished'

                # Clear references
                self.profiles[key]['inner_bot'] = None
                self.profiles[key]['scenario_engine'] = None

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

            # If this was a test mode and the profile was previously blocked but completed successfully
            if is_test_mode and was_blocked:
                if not bot_was_blocked and final_status in ['Running', 'Finished', 'Testing']:
                    logger.info(f"Profile {pid}: Test successful for previously blocked profile - reviving")
                    self.status_manager.revive_profile_status(pid)
                else:
                    logger.info(f"Profile {pid}: Test confirmed profile is still blocked - keeping blocked status")

            # Update Airtable
            if final_status in ['Finished', 'Stopped', 'Blocked', 'Suspended']:
                self.airtable_executor.submit(
                    self.airtable_manager.update_profile_statistics_on_completion,
                    pid
                )

            logger.info(f"Profile {pid}: Completed with status '{final_status}'")

    def profile_runner_wrapper(self, pid, max_follows):
        """Wrapper that handles cleanup"""
        try:
            self.profile_runner(pid, max_follows)
        except Exception as e:
            logger.error(f"Profile {pid}: Wrapper caught error: {e}", exc_info=True)
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
                'inner_bot': None,
                'scenario_engine': None,
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