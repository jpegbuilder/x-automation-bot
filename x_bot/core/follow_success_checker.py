import time
import logging
from typing import Optional, List
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)


class FollowSuccessChecker:

    def __init__(self, driver, profile_id: str, account_checker):
        self.driver = driver
        self.profile_id = profile_id
        self.account_checker = account_checker

    def check_follow_success(self, username: str, timeout: int = 8) -> bool:

        start_time = time.time()
        logger.info(f"Profile {self.profile_id}: Checking follow success for @{username}")

        while time.time() - start_time < timeout:
            result = self._check_current_state(username)

            if result is not None:
                return result

            time.sleep(0.5)

        logger.info(f"Profile {self.profile_id}: Timeout reached, final verification for @{username}")
        return self._final_verification(username)

    def _check_current_state(self, username: str) -> Optional[bool]:

        try:
            button_state = self._find_button_state()

            if button_state == "following":
                logger.info(f"Profile {self.profile_id}: ✅ Follow confirmed for @{username}")
                return True

            elif button_state == "pending":
                return self._handle_pending_state(username)

            elif button_state == "follow":
                return None  # Продолжаем ждать

            return self._check_if_button_disappeared(username)

        except Exception as e:
            logger.debug(f"Profile {self.profile_id}: Error during state check: {e}")
            return None

    def _find_button_state(self) -> Optional[str]:

        try:
            all_buttons = self.driver.find_elements(By.TAG_NAME, "button")

            for btn in all_buttons:
                if not btn.is_displayed():
                    continue

                text = btn.text.strip().lower()
                aria_label = (btn.get_attribute('aria-label') or '').lower()

                if text == "following" or "following" in aria_label:
                    return "following"
                elif text in ["pending", "requested"]:
                    return "pending"
                elif text == "follow":
                    return "follow"

            return None

        except Exception:
            return None

    def _handle_pending_state(self, username: str) -> bool:

        logger.info(f"Profile {self.profile_id}: Found 'Pending' for @{username} - checking account type")

        is_public = self.account_checker.check_if_public_account()

        if is_public is True:
            logger.error(f"Profile {self.profile_id}: ❌ FOLLOW BLOCK - public account with 'Pending'")
            return False
        elif is_public is False:
            logger.info(f"Profile {self.profile_id}: ✅ Follow success - protected account with 'Pending'")
            return True
        else:
            logger.warning(f"Profile {self.profile_id}: ⚠️ Follow uncertain - cannot determine account type")
            return True

    def _check_if_button_disappeared(self, username: str) -> Optional[bool]:

        try:
            message_buttons = self.driver.find_elements(By.XPATH, "//button[contains(text(), 'Message')]")
            if message_buttons and any(btn.is_displayed() for btn in message_buttons):
                logger.info(f"Profile {self.profile_id}: ✅ Follow success for @{username} - Follow button disappeared")
                return True

            return None

        except Exception:
            return None

    def _final_verification(self, username: str) -> bool:

        try:
            time.sleep(1)

            button_texts = self._scan_all_buttons()
            logger.info(f"Profile {self.profile_id}: Final scan - buttons found: {button_texts}")

            if 'Following' in button_texts:
                logger.info(f"Profile {self.profile_id}: ✅ Follow success for @{username}")
                return True

            elif 'Pending' in button_texts:
                return self._handle_pending_state(username)

            elif 'Follow' in button_texts:
                logger.error(f"Profile {self.profile_id}: ❌ Follow failed for @{username} - button still present")
                return False

            else:
                if 'Message' in button_texts:
                    logger.info(f"Profile {self.profile_id}: ✅ Follow success for @{username} - profile loaded")
                    return True
                else:
                    logger.warning(f"Profile {self.profile_id}: ❓ Follow uncertain for @{username}")
                    return False

        except Exception as e:
            logger.warning(f"Profile {self.profile_id}: Error in final verification: {e}")
            return False

    def _scan_all_buttons(self) -> List[str]:

        try:
            all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
            button_texts = []

            for btn in all_buttons:
                try:
                    if btn.is_displayed():
                        text = btn.text.strip()
                        if text in ['Following', 'Pending', 'Follow', 'Message', 'Post']:
                            button_texts.append(text)
                except:
                    continue

            return button_texts

        except Exception:
            return []
