import os
import time
import logging
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from config import ADSPOWER_API_URL, ADSPOWER_API_KEY

logger = logging.getLogger(__name__)

# Try to import webdriver_manager
try:
    from webdriver_manager.chrome import ChromeDriverManager

    USE_WEBDRIVER_MANAGER = True
except ImportError:
    USE_WEBDRIVER_MANAGER = False
    logger.info("webdriver-manager not available, will use alternative methods")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMEDRIVER_PATH = os.path.join(SCRIPT_DIR, "..", "chromedrivers", "chromedriver.exe")


class BrowserManager:

    def __init__(self, profile_id: str):
        self.profile_id = profile_id
        self.adspower_api_url = ADSPOWER_API_URL
        self.adspower_api_key = ADSPOWER_API_KEY
        self.driver = None
        self.debug_port = None
        self.adspower_response = None

    def _get_profile_param_name(self) -> str:
        return "serial_number" if str(self.profile_id).isdigit() else "user_id"

    def _get_headers(self) -> dict:
        return {"api_key": self.adspower_api_key} if self.adspower_api_key else {}

    def check_adspower_connection(self) -> bool:
        try:
            test_url = f"{self.adspower_api_url}/api/v1/user/list"
            response = requests.get(test_url, headers=self._get_headers(), timeout=5)

            if response.status_code == 200:
                logger.info(f"AdsPower API is accessible at {self.adspower_api_url}")
                return True
            else:
                logger.error(f"AdsPower API returned status code: {response.status_code}")
                return False

        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to AdsPower API at {self.adspower_api_url} - Make sure AdsPower is running!")
            return False
        except Exception as e:
            logger.error(f"Error checking AdsPower connection: {e}")
            return False

    def start_profile(self) -> bool:
        if not self.check_adspower_connection():
            return False

        try:
            url = f"{self.adspower_api_url}/api/v1/browser/start"
            param_name = self._get_profile_param_name()

            params = {
                param_name: self.profile_id,
                "launch_args": "",
                "headless": 0,
                "disable_password_filling": 0,
                "clear_cache_after_closing": 0,
                "enable_password_saving": 0,
            }

            response = requests.get(url, params=params, headers=self._get_headers(), timeout=5)
            data = response.json()

            if data.get('code') == 0:
                self.adspower_response = data
                debug_info = data['data']['ws']['selenium']
                self.debug_port = str(debug_info).split(':')[-1] if ':' in str(debug_info) else str(debug_info)
                logger.info(f"Profile {self.profile_id}: Started successfully. Debug port: {self.debug_port}")
                return True
            else:
                error_msg = data.get('msg', 'Unknown error')
                if any(kw in error_msg.lower() for kw in ['already', 'running', 'opened', 'started', 'being used']):
                    logger.warning(f"Profile {self.profile_id}: Already running, attempting restart...")
                    return self._restart_profile()
                else:
                    logger.error(f"Profile {self.profile_id}: Failed to start - {error_msg}")
                    return False

        except Exception as e:
            logger.error(f"Profile {self.profile_id}: Error starting profile: {e}")
            return False

    def _restart_profile(self) -> bool:
        try:
            logger.info(f"Profile {self.profile_id}: Restarting profile...")

            try:
                url = f"{self.adspower_api_url}/api/v1/browser/stop"
                param_name = self._get_profile_param_name()
                params = {param_name: self.profile_id}

                response = requests.get(url, params=params, headers=self._get_headers())
                data = response.json()

                if data.get('code') == 0:
                    logger.info(f"Profile {self.profile_id}: Stopped successfully")
                else:
                    logger.warning(f"Profile {self.profile_id}: Stop returned: {data.get('msg', 'Unknown')}")
            except Exception as e:
                logger.warning(f"Profile {self.profile_id}: Stop error (ignoring): {e}")

            time.sleep(3)

            url = f"{self.adspower_api_url}/api/v1/browser/start"
            param_name = self._get_profile_param_name()

            params = {
                param_name: self.profile_id,
                "launch_args": "",
                "headless": 0,
                "disable_password_filling": 0,
                "clear_cache_after_closing": 0,
                "enable_password_saving": 0
            }

            response = requests.get(url, params=params, headers=self._get_headers())
            data = response.json()

            if data.get('code') == 0:
                self.adspower_response = data
                debug_info = data['data']['ws']['selenium']
                self.debug_port = str(debug_info).split(':')[-1] if ':' in str(debug_info) else str(debug_info)
                logger.info(f"Profile {self.profile_id}: Successfully restarted! Port: {self.debug_port}")
                return True
            else:
                logger.error(f"Profile {self.profile_id}: Restart failed - {data.get('msg', 'Unknown')}")
                return False

        except Exception as e:
            logger.error(f"Profile {self.profile_id}: Error during restart: {e}")
            return False

    def _get_running_profile_info(self) -> bool:
        try:
            url = f"{self.adspower_api_url}/api/v1/browser/active"
            param_name = self._get_profile_param_name()
            params = {param_name: self.profile_id}

            response = requests.get(url, params=params, headers=self._get_headers())
            data = response.json()

            if data.get('code') == 0 and data.get('data'):
                self.adspower_response = data
                debug_info = data['data'].get('ws', {}).get('selenium')
                if debug_info:
                    self.debug_port = str(debug_info).split(':')[-1] if ':' in str(debug_info) else str(debug_info)
                    logger.info(f"Profile {self.profile_id}: Connected to existing session. Port: {self.debug_port}")
                    return True

            logger.warning(f"Profile {self.profile_id}: Could not get running profile info")
            return False

        except Exception as e:
            logger.error(f"Profile {self.profile_id}: Error getting running profile info: {e}")
            return False

    def connect_to_browser(self) -> bool:
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                chrome_options = Options()
                chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{self.debug_port}")

                if self._try_adspower_driver(chrome_options):
                    return True

                if USE_WEBDRIVER_MANAGER and self._try_webdriver_manager(chrome_options):
                    return True

                if self._try_local_driver(chrome_options):
                    return True

                if self._try_system_driver(chrome_options):
                    return True

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Profile {self.profile_id}: Connection attempt {attempt + 1}/{max_retries} failed")
                    logger.info(f"Profile {self.profile_id}: Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Profile {self.profile_id}: All connection attempts failed: {e}")
                    return False

        logger.error(f"Profile {self.profile_id}: All ChromeDriver methods failed!")
        return False

    def _try_adspower_driver(self, options) -> bool:
        try:
            if self.adspower_response and 'data' in self.adspower_response:
                driver_path = self.adspower_response['data'].get('webdriver')
                if driver_path:
                    service = Service(driver_path)
                    self.driver = webdriver.Chrome(service=service, options=options)
                    logger.info(f"Profile {self.profile_id}: Connected using AdsPower ChromeDriver")
                    return True
        except Exception as e:
            logger.debug(f"Profile {self.profile_id}: AdsPower driver failed: {e}")
        return False

    def _try_webdriver_manager(self, options) -> bool:
        try:
            service = Service(ChromeDriverManager(version="137.0.7106.61").install())
            self.driver = webdriver.Chrome(service=service, options=options)
            logger.info(f"Profile {self.profile_id}: Connected using webdriver-manager (Chrome 137)")
            return True
        except Exception:
            try:
                service = Service(ChromeDriverManager(version="138.0.7106.61").install())
                self.driver = webdriver.Chrome(service=service, options=options)
                logger.info(f"Profile {self.profile_id}: Connected using webdriver-manager (Chrome 138)")
                return True
            except Exception:
                try:
                    service = Service(ChromeDriverManager().install())
                    self.driver = webdriver.Chrome(service=service, options=options)
                    logger.info(f"Profile {self.profile_id}: Connected using webdriver-manager (latest)")
                    return True
                except Exception as e:
                    logger.debug(f"Profile {self.profile_id}: webdriver-manager failed: {e}")
        return False

    def _try_local_driver(self, options) -> bool:
        try:
            if os.path.exists(CHROMEDRIVER_PATH):
                service = Service(CHROMEDRIVER_PATH)
                self.driver = webdriver.Chrome(service=service, options=options)
                logger.info(f"Profile {self.profile_id}: Connected using local ChromeDriver")
                return True
        except Exception as e:
            logger.debug(f"Profile {self.profile_id}: Local driver failed: {e}")
        return False

    def _try_system_driver(self, options) -> bool:
        try:
            self.driver = webdriver.Chrome(options=options)
            logger.info(f"Profile {self.profile_id}: Connected using system PATH ChromeDriver")
            return True
        except Exception as e:
            logger.debug(f"Profile {self.profile_id}: System driver failed: {e}")
        return False

    def close_extra_tabs(self) -> bool:
        try:
            if not self.driver:
                return False

            all_windows = self.driver.window_handles
            logger.info(f"Profile {self.profile_id}: Found {len(all_windows)} open tabs")

            if len(all_windows) <= 1:
                return True

            x_window = None
            windows_to_close = []

            for window in all_windows:
                try:
                    self.driver.switch_to.window(window)
                    current_url = self.driver.current_url

                    if ("x.com" in current_url or "twitter.com" in current_url) and not x_window:
                        x_window = window
                        logger.info(f"Profile {self.profile_id}: Found X.com tab: {current_url}")
                    else:
                        windows_to_close.append(window)
                except Exception:
                    windows_to_close.append(window)

            for window in windows_to_close:
                try:
                    self.driver.switch_to.window(window)
                    self.driver.close()
                    logger.info(f"Profile {self.profile_id}: Closed extra tab")
                except Exception:
                    pass

            remaining_windows = self.driver.window_handles
            if x_window and x_window in remaining_windows:
                self.driver.switch_to.window(x_window)
            elif remaining_windows:
                self.driver.switch_to.window(remaining_windows[0])
            else:
                logger.warning(f"Profile {self.profile_id}: All windows closed, opening new tab")
                self.driver.execute_script("window.open('about:blank', '_blank');")
                self.driver.switch_to.window(self.driver.window_handles[-1])

            logger.info(
                f"Profile {self.profile_id}: Tab cleanup complete. {len(self.driver.window_handles)} tab(s) remaining")
            return True

        except Exception as e:
            logger.error(f"Profile {self.profile_id}: Error during tab cleanup: {e}")
            return False

    def check_window_available(self) -> bool:
        try:
            if self.driver and self.driver.current_window_handle:
                return True
        except Exception:
            pass
        return False

    def stop_profile(self) -> bool:
        try:
            if self.driver:
                try:
                    logger.info(f"Profile {self.profile_id}: Quitting driver...")
                    self.driver.quit()
                    logger.info(f"Profile {self.profile_id}: Driver quit successfully")
                except Exception as e:
                    logger.warning(f"Profile {self.profile_id}: Error quitting driver: {e}")

            url = f"{self.adspower_api_url}/api/v1/browser/stop"
            param_name = self._get_profile_param_name()
            params = {param_name: self.profile_id}

            logger.info(f"Profile {self.profile_id}: Sending stop request to AdsPower API...")
            response = requests.get(url, params=params, headers=self._get_headers(), timeout=10)
            data = response.json()

            logger.info(f"Profile {self.profile_id}: Stop API response: {data}")

            if data.get('code') == 0:
                logger.info(f"Profile {self.profile_id}: Stopped successfully")
                return True
            else:
                error_msg = data.get('msg', 'Unknown error')
                if any(kw in error_msg.lower() for kw in
                       ['not running', 'not started', 'already stopped', 'not found', 'not open']):
                    logger.info(f"Profile {self.profile_id}: Was already stopped")
                    return True
                else:
                    logger.error(f"Profile {self.profile_id}: Failed to stop - {error_msg}")
                    return False

        except Exception as e:
            logger.error(f"Profile {self.profile_id}: Error stopping profile: {e}")
            return False