import time
import logging
from dataclasses import dataclass
from typing import Tuple, Optional

from .selectors import XSelectors
from .browser_manager import BrowserManager
from .account_checker import AccountChecker
from .follow_success_checker import FollowSuccessChecker
from .follow_manager import FollowManager

logger = logging.getLogger(__name__)


@dataclass
class BotState:
    is_suspended: bool = False
    is_follow_blocked: bool = False
    consecutive_follow_errors: int = 0
    consecutive_follow_blocks: int = 0


class XFollowBot:

    def __init__(self, profile_id: str, adspower_api_url: str = None,
                 adspower_api_key: str = None, airtable_manager = None):
        try:
            from config import ADSPOWER_API_URL, ADSPOWER_API_KEY
        except ImportError:
            logger.warning("Could not import config, using default values")
            ADSPOWER_API_URL = "http://local.adspower.net:50325"
            ADSPOWER_API_KEY = ""

        self.profile_id = profile_id
        self.state = BotState()

        # API
        self.adspower_api_url = adspower_api_url or ADSPOWER_API_URL
        self.adspower_api_key = adspower_api_key or ADSPOWER_API_KEY

        self.airtable_manager = airtable_manager

        self.selectors = XSelectors()

        self.browser_manager = BrowserManager(
            profile_id,
            self.adspower_api_url,
            self.adspower_api_key
        )

        self.account_checker = None
        self.follow_checker = None
        self.follow_manager = None

        logger.info(f"XFollowBot initialized for profile {profile_id}")

    def _init_components(self):
        driver = self.browser_manager.driver

        self.account_checker = AccountChecker(driver, self.profile_id, self.selectors)
        self.follow_checker = FollowSuccessChecker(driver, self.profile_id, self.account_checker)
        self.follow_manager = FollowManager(
            driver, self.profile_id, self.browser_manager,
            self.account_checker, self.follow_checker, self.selectors
        )

        logger.debug(f"Profile {self.profile_id}: All components initialized")

    def _update_airtable_status(self, status: str):

        if not self.airtable_manager:
            logger.debug(f"Profile {self.profile_id}: AirtableManager not available")
            return

        try:
            self.airtable_manager.update_profile_status(self.profile_id, status)
            logger.info(f"Profile {self.profile_id}: Updated Airtable status to '{status}'")
        except Exception as e:
            logger.error(f"Profile {self.profile_id}: Error updating Airtable status: {e}")

    @property
    def driver(self):
        return self.browser_manager.driver

    @property
    def is_suspended(self) -> bool:
        return self.state.is_suspended

    @property
    def is_follow_blocked(self) -> bool:
        return self.state.is_follow_blocked

    def start_profile(self) -> bool:
        logger.info(f"Profile {self.profile_id}: Starting profile...")
        return self.browser_manager.start_profile()

    def connect_to_browser(self) -> bool:
        logger.info(f"Profile {self.profile_id}: Connecting to browser...")
        success = self.browser_manager.connect_to_browser()

        if success:
            self._init_components()
            logger.info(f"Profile {self.profile_id}: Successfully connected to browser")
        else:
            logger.error(f"Profile {self.profile_id}: Failed to connect to browser")

        return success

    def stop_profile(self) -> bool:
        logger.info(f"Profile {self.profile_id}: Stopping profile...")
        return self.browser_manager.stop_profile()

    def close_extra_tabs(self) -> bool:
        return self.browser_manager.close_extra_tabs()

    def navigate_to_x(self) -> bool:
        try:
            logger.info(f"Profile {self.profile_id}: Navigating to X.com...")

            self.close_extra_tabs()

            self.driver.get("https://x.com")
            time.sleep(2)

            if self.check_if_suspended():
                self.state.is_suspended = True
                logger.error(f"Profile {self.profile_id}: Account SUSPENDED")

                self._update_airtable_status('Suspended')

                return False

            logger.info(f"Profile {self.profile_id}: Successfully navigated to X.com")
            return True

        except Exception as e:
            logger.error(f"Profile {self.profile_id}: Error navigating to X.com: {e}")
            return False

    def check_if_suspended(self) -> bool:
        if not self.account_checker:
            logger.warning(f"Profile {self.profile_id}: Account checker not initialized")
            return False

        return self.account_checker.check_if_suspended()

    def check_for_follow_block(self) -> bool:
        if not self.account_checker:
            logger.warning(f"Profile {self.profile_id}: Account checker not initialized")
            return False

        is_blocked = self.account_checker.check_for_follow_block()

        if is_blocked:
            self.state.is_follow_blocked = True
            logger.error(f"Profile {self.profile_id}: Follow block detected!")

            self._update_airtable_status('Follow Block')

        return is_blocked

    def follow_user(self, username: str, fast_mode: bool = True,
                    delay_config: dict = None) -> Tuple[bool, str]:

        if not self.follow_manager:
            logger.error(f"Profile {self.profile_id}: Follow manager not initialized")
            return False, 'failed'

        success, reason = self.follow_manager.follow_user(username, delay_config)

        if success:
            self.state.consecutive_follow_errors = 0
            self.state.consecutive_follow_blocks = 0
        else:
            if reason == 'failed':
                self.state.consecutive_follow_blocks += 1

        if self.check_for_follow_block():
            self.state.is_follow_blocked = True
            return False, 'failed'

        if self.check_if_suspended():
            self.state.is_suspended = True
            return False, 'failed'

        return success, reason
