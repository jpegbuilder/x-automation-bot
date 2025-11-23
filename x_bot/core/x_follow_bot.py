import random
import time
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from selenium.webdriver.support import expected_conditions as EC
from typing import Tuple, List, Any, Optional
from selenium.common import NoSuchElementException, InvalidSessionIdException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait

from x_bot.core.selectors import XSelectors
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

    def __init__(self, profile_id: str, airtable_manager = None):

        self.profile_id = profile_id
        self.state = BotState()

        self.airtable_manager = airtable_manager

        self.selectors = XSelectors()

        self.browser_manager = BrowserManager(
            profile_id,
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

    def check_cloudflare(self) -> bool:
        """Return True if Cloudflare / X access protection page is detected."""
        if not self.driver:
            return False

        try:
            current_url = (self.driver.current_url or "").lower()
            page_source = (self.driver.page_source or "").lower()
        except Exception as e:
            logger.debug(f"Profile {self.profile_id}: check_cloudflare(): failed to read page: {e}")
            return False

        blocked_url_patterns = [
            "x.com/account/access",
        ]

        cf_markers = [
            "verify you are human by completing the action below",
            "performance & security by cloudflare",
            "x.com needs to review the security of your connection before proceeding",
            "cf-browser-verification",
            "cf-challenge",
            "/cdn-cgi/challenge-platform/",
            "cloudflare ray id",
        ]

        is_access_block = any(p in current_url for p in blocked_url_patterns)
        matched_markers = [m for m in cf_markers if m in page_source]
        is_cf_challenge = bool(matched_markers)

        if is_access_block or is_cf_challenge:
            logger.error(
                f"Profile {self.profile_id}: protection page detected "
                f"(url={current_url}, markers={matched_markers}) – entering silent mode"
            )
            return True

        return False

    def navigate_to_x(self) -> bool:

        try:
            logger.info(f"Profile {self.profile_id}: Navigating to X.com...")

            self.driver.get("https://x.com")
            self.close_extra_tabs()
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

    def navigate_to_profile(self, username: str) -> bool:
        self.close_extra_tabs()
        return self.follow_manager.navigate_to_profile(username)

    def go_home(self) -> bool:
        """
        Navigate to X home timeline.
        Used by scenarios as a generic starting point.
        """
        if not self.driver:
            logger.error("go_home() called but driver is not initialized")
            return False

        try:
            logger.info(f"Profile {self.profile_id}: Navigating to home timeline...")
            self.close_extra_tabs()
            self.driver.get("https://x.com/home")
            return True
        except Exception as e:
            logger.exception(f"Profile {self.profile_id}: Failed to navigate to home: {e}")
            return False

    def go_back(self) -> bool:
        """
        Go one step back in browser history.
        """
        if not self.driver:
            logger.error("go_back() called but driver is not initialized")
            return False

        try:
            logger.info(f"Profile {self.profile_id}: Going back in browser history...")
            self.driver.back()
            return True
        except Exception as e:
            logger.exception(f"Profile {self.profile_id}: Failed to go back: {e}")
            return False

    def wait(self, seconds: float) -> None:
        """
        Simple blocking wait. Used by scenarios for pacing.
        """
        try:
            seconds = max(0.0, float(seconds))
        except (TypeError, ValueError):
            logger.warning(f"wait() called with invalid seconds={seconds!r}, using 0")
            seconds = 0.0

        logger.debug(f"Profile {self.profile_id}: Waiting for {seconds} seconds")
        time.sleep(seconds)

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

    def follow_user(self, username: str, fast_mode: bool = True,) -> Tuple[bool, str]:

        if not self.follow_manager:
            logger.error(f"Profile {self.profile_id}: Follow manager not initialized")
            return False, 'failed'

        success, reason = self.follow_manager.follow_user(username)

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

    def _find_post_elements(self) -> List[Any]:
        """
        Internal helper to find visible post elements on a profile or timeline.

        X layout changes frequently, so this method is intentionally generic.
        You can tune XPATH to better match your environment.
        """
        if not self.driver:
            logger.error("_find_post_elements() called but driver is not initialized")
            return []

        xpaths = [
            "//article[@data-testid='tweet']",
            "//article[@data-testid='tweetDetail']",
        ]

        posts: List[Any] = []
        for xp in xpaths:
            try:
                found = self.driver.find_elements(By.XPATH, xp)
                if found:
                    posts.extend(found)
            except Exception as e:
                logger.debug(f"_find_post_elements(): error while searching with xpath={xp}: {e}")

        return posts

    def check_has_posts(self) -> bool:
        """
        Check whether current view contains at least one post.
        """
        posts = self._find_post_elements()
        has_posts = len(posts) > 0
        logger.info(
            f"Profile {self.profile_id}: check_has_posts() -> {has_posts} "
            f"(found={len(posts)} posts)"
        )
        return has_posts

    def count_posts(self, limit: Optional[int] = None) -> int:
        """
        Count posts on current page (optionally up to a given limit).

        :param limit: Optional upper bound for the count.
        :return: Number of posts found (possibly capped by limit).
        """
        posts = self._find_post_elements()
        count = len(posts)

        if limit is not None:
            try:
                limit = int(limit)
                if limit >= 0:
                    count = min(count, limit)
            except (TypeError, ValueError):
                logger.warning(f"count_posts(): invalid limit={limit!r}, ignoring")

        logger.info(
            f"Profile {self.profile_id}: count_posts() -> {count} (raw={len(posts)})"
        )
        return count

    def scroll_top(self):
        """
        Scroll to the top of the current page.
        """
        if not self.driver:
            logger.error("scroll_top() called but driver is not initialized")

        try:
            self.driver.execute_script("window.scrollTo(0, 0)")
            time.sleep(random.uniform(1, 2))
        except Exception as e:
            logger.error(f"scroll_top(): failed to scroll to top: {e}")

    def scroll_posts(self, pages: int = 1, pause: float = 5.0) -> None:
        """
        Scroll down the page to load more posts.

        :param pages: Number of scroll iterations.
        :param pause: Delay in seconds between scrolls.
        """
        if not self.driver:
            logger.error("scroll_posts() called but driver is not initialized")
            return

        try:
            _ = self.driver.current_window_handle
        except Exception as e:
            logger.error(f"Browser session not available: {e}")
            return

        if not self.check_has_posts():
            return

        try:
            pages = max(1, int(pages))
        except (TypeError, ValueError):
            logger.warning(f"scroll_posts(): invalid pages={pages!r}, using 3")
            pages = 3.0

        try:
            pause = float(pause)
        except (TypeError, ValueError):
            logger.warning(f"scroll_posts(): invalid pause={pause!r}, using 5.0")
            pause = 5.0

        logger.info(
            f"Profile {self.profile_id}: Scrolling posts (pages={pages}, pause={pause})"
        )

        for i in range(pages):
            if not self.browser_manager.check_window_available():
                logger.warning(
                    f"Profile {self.profile_id}: Window not available, stopping scroll at iteration {i + 1}"
                )
                break

            try:
                self.driver.execute_script(
                    "window.scrollBy(0, Math.round(window.innerHeight * 0.8));"
                )
                logger.debug(
                    f"Profile {self.profile_id}: scroll_posts iteration {i + 1}/{pages}"
                )
                time.sleep(pause)
            except InvalidSessionIdException:
                logger.error(
                    f"Profile {self.profile_id}: Browser session lost during scroll at iteration {i + 1}"
                )
                break
            except WebDriverException as e:
                logger.error(
                    f"Profile {self.profile_id}: WebDriver error during scroll at iteration {i + 1}: {e}"
                )
                break
            except Exception as e:
                logger.exception(
                    f"Profile {self.profile_id}: scroll_posts error on iteration {i + 1}: {e}"
                )
                break

        self.scroll_top()

    def _find_like_button_in_post(self, post_element: Any) -> Optional[Any]:
        """
        Try to find a 'Like' button inside a given post element.

        Returns WebElement or None.
        """
        like_xpaths = [
            ".//button[@data-testid='like']",
        ]

        for xp in like_xpaths:
            try:
                btns = post_element.find_elements(By.XPATH, xp)
                if btns:
                    return btns[0]
            except Exception as e:
                logger.debug(
                    f"_find_like_button_in_post(): error with xpath={xp}: {e}"
                )

        return None

    def like_first_post(self) -> bool:
        """
        Like the first available post on the page.
        """
        if not self.driver:
            logger.error("like_first_post() called but driver is not initialized")
            return False

        posts = self._find_post_elements()
        if not posts:
            logger.warning(
                f"Profile {self.profile_id}: like_first_post(): no posts found"
            )
            return False

        first = posts[0]
        like_btn = self._find_like_button_in_post(first)
        if not like_btn:
            logger.warning(
                f"Profile {self.profile_id}: like_first_post(): like button not found in first post"
            )
            return False

        try:
            wait = WebDriverWait(self.driver, 5)

            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                like_btn,
            )
            wait.until(EC.element_to_be_clickable(like_btn))
            like_btn.click()
            logger.info(
                f"Profile {self.profile_id}: like_first_post(): like clicked on first post"
            )
            return True
        except Exception as e:
            logger.exception(
                f"Profile {self.profile_id}: like_first_post(): failed to click like: {e}"
            )
            return False

    def like_random_post(self, max_attempts: int = 5) -> bool:
        """
        Like a random post from the currently visible ones.

        :param max_attempts: Maximum number of random picks to try
                             before giving up (in case some posts do not have like buttons).
        :return: True if a like was successfully clicked, False otherwise.
        """
        import random

        if not self.driver:
            logger.error("like_random_post() called but driver is not initialized")
            return False

        posts = self._find_post_elements()
        if not posts:
            logger.warning(
                f"Profile {self.profile_id}: like_random_post(): no posts found"
            )
            return False

        indices = list(range(len(posts)))
        random.shuffle(indices)

        attempts = 0
        for idx in indices:
            if attempts >= max_attempts:
                break
            attempts += 1

            post = posts[idx]
            like_btn = self._find_like_button_in_post(post)
            if not like_btn:
                logger.debug(
                    f"Profile {self.profile_id}: like_random_post(): "
                    f"no like button in post index={idx}"
                )
                continue

            try:
                wait = WebDriverWait(self.driver, 5)

                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                    like_btn,
                )
                wait.until(EC.element_to_be_clickable(like_btn))
                like_btn.click()
                logger.info(
                    f"Profile {self.profile_id}: like_random_post(): liked post index={idx}"
                )
                return True
            except Exception as e:
                logger.exception(
                    f"Profile {self.profile_id}: like_random_post(): "
                    f"failed to click like in post index={idx}: {e}"
                )

        logger.warning(
            f"Profile {self.profile_id}: like_random_post(): failed to like any post"
        )
        return False

    def find_and_goto_repost_author(self, *args):
        """
        Find a repost ("X reposted") on the page and navigate to the ORIGINAL tweet author's profile.

        Logic:
        - Locate <span data-testid="socialContext"> that contains the word "reposted"
          (this is the "X reposted" label – X is the reposting user).
        - Go up to its closest ancestor <article> (the repost tweet container).
        - Inside that <article>, find the original author block: <div data-testid="User-Name">…</div>.
        - Click the first <a> inside that block (this is the original tweet author's profile link).
        """
        try:
            wait = WebDriverWait(self.driver, 10)

            # 1. Find all social context spans that indicate a repost ("X reposted")
            repost_badges = self.driver.find_elements(
                By.XPATH,
                "//span[@data-testid='socialContext' and "
                "contains(translate(normalize-space(.),'REPOSTED','reposted'),'reposted')]"
            )

            if not repost_badges:
                logger.info("No repost socialContext spans found on page.")
                return "No repost socialContext spans found on page."

            for badge in repost_badges:
                article = None
                try:
                    # 2. Go up to the closest <article> that contains this repost context
                    article = badge.find_element(By.XPATH, "./ancestor::article[1]")

                    # 3. Inside this article, find the original author block:
                    #    <div data-testid="User-Name"><a href="/original_author">...</a></div>
                    author_link = article.find_element(
                        By.XPATH,
                        ".//div[@data-testid='User-Name']//a[1]"
                    )

                    # Debug: log which original author we are about to click
                    try:
                        href = author_link.get_attribute("href")
                        logger.debug(f"Original tweet author link detected: {href}")
                    except Exception:
                        pass

                    # 4. Scroll into view to avoid overlay / visibility issues
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                        author_link,
                    )

                    # 5. Wait until the link is clickable
                    wait.until(EC.element_to_be_clickable(author_link))

                    # 6. Try normal Selenium click first
                    try:
                        author_link.click()
                    except Exception as click_exc:
                        logger.debug(f"Normal click failed, trying JS click: {click_exc}")
                        # Fallback to JS click
                        self.driver.execute_script("arguments[0].click();", author_link)

                    time.sleep(random.uniform(2, 3))
                    logger.info("Found repost and navigated to ORIGINAL tweet author's profile")
                    return "Found repost and navigated to original author"

                except Exception as inner_exc:
                    logger.debug(f"Failed to navigate from repost badge to original author: {inner_exc}")

                    # Optional: dump article HTML once for debugging if needed
                    if article is not None:
                        try:
                            html = article.get_attribute("outerHTML")
                            logger.debug("Repost article HTML (truncated): %s",
                                         (html[:1000] + "...") if html and len(html) > 1000 else html)
                        except Exception as html_exc:
                            logger.debug(f"Failed to get article outerHTML: {html_exc}")

                    # Try next badge if available
                    continue

            # If we had repost badges but none led to a successful navigation
            raise Exception("Repost badges found, but failed to navigate to original author")

        except Exception as e:
            logger.error(f"Failed to find repost and navigate to original author: {e}")
            raise