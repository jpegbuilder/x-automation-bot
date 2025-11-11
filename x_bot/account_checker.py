import logging
from typing import Tuple, Optional
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from .page_checker import PageChecker

logger = logging.getLogger(__name__)


class AccountChecker(PageChecker):

    def __init__(self, driver, profile_id: str, selectors):
        super().__init__(driver, profile_id)
        self.selectors = selectors

    def check_if_suspended(self) -> bool:

        logger.debug(f"Profile {self.profile_id}: Checking for suspension")

        if self.check_url_contains(['/account/suspended', '/account_suspended'], 'suspension'):
            return True

        if self.check_page_contains(self.selectors.SUSPENSION_KEYWORDS, 'suspension'):
            return True

        if self.check_elements_exist(self.selectors.SUSPENSION_SELECTORS, 'suspension'):
            return True

        return False

    def check_if_public_account(self) -> Optional[bool]:

        logger.debug(f"Profile {self.profile_id}: Checking if account is public")

        if self.check_page_contains(self.selectors.PROTECTED_KEYWORDS, 'protected account'):
            logger.debug(f"Profile {self.profile_id}: Account is PROTECTED")
            return False

        if self.check_elements_exist(self.selectors.PROTECTED_SELECTORS, 'protected account'):
            logger.debug(f"Profile {self.profile_id}: Account is PROTECTED")
            return False

        logger.debug(f"Profile {self.profile_id}: Account appears to be PUBLIC")
        return True

    def check_if_profile_exists(self, username: str) -> Tuple[bool, str]:

        try:
            if self.check_url_contains(['/account/suspended', '/account_suspended'], 'target suspension'):
                logger.warning(f"Profile {self.profile_id}: User @{username} is suspended")
                return False, "suspended"

            if self.check_page_contains(self.selectors.DOESNT_EXIST_KEYWORDS, 'profile not found'):
                logger.warning(f"Profile {self.profile_id}: User @{username} doesn't exist")
                return False, "not_found"

            suspension_keywords = ["account suspended", "this account has been suspended"]
            if self.check_page_contains(suspension_keywords, 'target suspension'):
                logger.warning(f"Profile {self.profile_id}: User @{username} is suspended")
                return False, "suspended"

            for selector in self.selectors.PROFILE_ERROR_SELECTORS:
                try:
                    element = self.driver.find_element(By.XPATH, selector)
                    if element and element.is_displayed():
                        text = element.text.lower()
                        if "doesn't exist" in text or "not exist" in text:
                            logger.warning(f"Profile {self.profile_id}: User @{username} doesn't exist (element)")
                            return False, "not_found"
                        elif "suspended" in text:
                            logger.warning(f"Profile {self.profile_id}: User @{username} is suspended (element)")
                            return False, "suspended"
                except NoSuchElementException:
                    continue

            if self.check_elements_exist(self.selectors.PROFILE_INDICATORS, 'valid profile'):
                logger.debug(f"Profile {self.profile_id}: User @{username} exists")
                return True, "exists"

            logger.debug(f"Profile {self.profile_id}: User @{username} - status unknown, assuming exists")
            return True, "unknown"

        except Exception as e:
            logger.warning(f"Profile {self.profile_id}: Error checking profile @{username}: {e}")
            return True, "error"

    def check_for_follow_block(self) -> bool:

        logger.debug(f"Profile {self.profile_id}: Checking for follow block")

        if self.check_page_contains(self.selectors.FOLLOW_BLOCK_KEYWORDS, 'follow block'):
            logger.error(f"Profile {self.profile_id}: Follow block detected via keywords")
            return True

        if self.check_elements_exist(self.selectors.FOLLOW_BLOCK_SELECTORS, 'follow block'):
            logger.error(f"Profile {self.profile_id}: Follow block detected via elements")
            return True

        return False
