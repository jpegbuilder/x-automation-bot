import time
import random
import logging
from typing import Tuple
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from config import CONFIG_FILE

logger = logging.getLogger(__name__)


class FollowManager:

    def __init__(self, driver, profile_id: str, browser_manager,
                 account_checker, follow_checker, selectors):
        self.driver = driver
        self.profile_id = profile_id
        self.browser_manager = browser_manager
        self.account_checker = account_checker
        self.follow_checker = follow_checker
        self.selectors = selectors
        self.delay_config = CONFIG_FILE or {}

    def navigate_to_profile(self, username: str) -> bool:

        try:
            if not self.browser_manager.check_window_available():
                logger.error(f"Profile {self.profile_id}: Browser window unavailable")
                return False

            profile_url = f"https://x.com/{username}"
            self.driver.get(profile_url)

            page_load_wait = self.delay_config.get('page_load_wait', [0.5, 2])
            wait_time = random.uniform(page_load_wait[0], page_load_wait[1])
            time.sleep(wait_time)

            logger.debug(f"Profile {self.profile_id}: Navigated to @{username}")
            return True

        except Exception as e:
            logger.error(f"Profile {self.profile_id}: Error navigating to @{username}: {e}")
            return False

    def follow_user(self, username: str) -> Tuple[bool, str]:
        """
        Args:
            username: username

        Returns:
            (success: bool, reason: str)
            - (True, 'followed')
            - (False, 'not_found')
            - (False, 'target_suspended')
            - (False, 'failed')
        """
        try:
            if not self.navigate_to_profile(username):
                return False, 'failed'

            exists, reason = self.account_checker.check_if_profile_exists(username)

            if not exists:
                if reason == "not_found":
                    logger.warning(f"Profile {self.profile_id}: ⚠️ User @{username} does not exist")
                    return False, 'not_found'
                elif reason == "suspended":
                    logger.warning(f"Profile {self.profile_id}: ⚠️ User @{username} is suspended")
                    return False, 'target_suspended'
                else:
                    logger.warning(f"Profile {self.profile_id}: ⚠️ User @{username} unavailable ({reason})")
                    return False, 'not_found'

            if reason in ["unknown", "error"]:
                logger.info(f"Profile {self.profile_id}: User @{username} status uncertain, attempting to follow...")

            follow_button = self._find_follow_button(username)

            if not follow_button:
                logger.warning(f"Profile {self.profile_id}: Follow button not found for @{username}")
                return False, 'failed'

            button_text = follow_button.text.lower()
            if "following" in button_text or "pending" in button_text:
                logger.info(f"Profile {self.profile_id}: Already following or pending @{username}")
                return True, 'followed'
            else:
                follow_button.click()
                logger.info(f"Profile {self.profile_id}: Clicked follow button for @{username}")

            time.sleep(0.2)

            if self.account_checker.check_for_follow_block():
                logger.error(f"Profile {self.profile_id}: FOLLOW BLOCK detected!")
                return False, 'failed'

            if self.account_checker.check_if_suspended():
                logger.error(f"Profile {self.profile_id}: ACCOUNT SUSPENDED!")
                return False, 'failed'

            follow_check_timeout = self.delay_config.get('follow_check_timeout', 8)
            success = self.follow_checker.check_follow_success(username, follow_check_timeout)

            if success:
                logger.info(f"Profile {self.profile_id}: ✅ Successfully followed @{username}")
                return True, 'followed'
            else:
                logger.error(f"Profile {self.profile_id}: ❌ Follow action failed for @{username}")
                return False, 'failed'

        except Exception as e:
            logger.error(f"Profile {self.profile_id}: Error following @{username}: {e}")
            return False, 'failed'

    def _find_follow_button(self, username: str):

        try:
            for selector in self.selectors.FOLLOW_BUTTONS:
                logger.info(f"Selector for find @{username} / @{selector}")
                try:
                    button = WebDriverWait(self.driver, 1).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    logger.debug(f"Profile {self.profile_id}: Found follow button via selector")
                    return button
                except TimeoutException:
                    continue

            try:
                button = self.driver.find_element(
                    By.XPATH,
                    "//button[contains(text(), 'Follow') and not(contains(text(), 'Following'))]"
                )
                if button:
                    logger.debug(f"Profile {self.profile_id}: Found follow button via direct search")
                    return button
            except NoSuchElementException:
                pass

            logger.debug(f"Profile {self.profile_id}: Follow button not found")
            return None

        except Exception as e:
            logger.debug(f"Profile {self.profile_id}: Error finding follow button: {e}")
            return None
