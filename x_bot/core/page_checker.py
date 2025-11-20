import logging
from typing import List
from selenium.webdriver.common.by import By

from selenium.common.exceptions import NoSuchElementException

logger = logging.getLogger(__name__)


class PageChecker:

    def __init__(self, driver, profile_id: str):
        self.driver = driver
        self.profile_id = profile_id

    def check_page_contains(self, keywords: List[str], check_name: str) -> bool:

        try:
            page_source = self.driver.page_source.lower()

            for keyword in keywords:
                if keyword.lower() in page_source:
                    logger.info(f"Profile {self.profile_id}: {check_name} detected via keyword: '{keyword}'")
                    return True

            return False

        except Exception as e:
            logger.warning(f"Profile {self.profile_id}: Error in {check_name} page check: {e}")
            return False

    def check_elements_exist(self, selectors: List[str], check_name: str) -> bool:

        for selector in selectors:
            try:
                element = self.driver.find_element(By.XPATH, selector)
                if element and element.is_displayed():
                    logger.info(f"Profile {self.profile_id}: {check_name} detected via element")
                    return True
            except NoSuchElementException:
                continue

        # return False

    def check_url_contains(self, paths: List[str], check_name: str) -> bool:

        try:
            current_url = self.driver.current_url

            for path in paths:
                if path in current_url:
                    logger.info(f"Profile {self.profile_id}: {check_name} detected via URL: {path}")
                    return True

            return False

        except Exception as e:
            logger.warning(f"Profile {self.profile_id}: Error checking URL: {e}")
            return False
