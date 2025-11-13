import json
import os
import threading
import logging
from config import CONFIG_FILE

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages configuration settings"""

    def __init__(self, *args, **kwargs):
        self.config_lock = threading.Lock()

    def load_config(self):
        """Load configuration from file"""
        try:
            with self.config_lock:
                if os.path.exists(CONFIG_FILE):
                    with open(CONFIG_FILE, 'r') as f:
                        return json.load(f)
                else:
                    # Return default configuration
                    default_config = {
                        "delays": {
                            "between_follows": [8, 20],
                            "pre_action_delay": [2, 8],
                            "page_load_wait": [0.5, 2],
                            "follow_check_timeout": 8,
                            "extended_break_interval": [5, 10],
                            "extended_break_duration": [60, 120],
                            "very_long_break_chance": 0.03,
                            "very_long_break_duration": [300, 600],
                            "profile_start_delay": 3,
                            "hourly_reset_break": [600, 1200]
                        },
                        "limits": {
                            "max_follows_per_hour": 35,
                            "max_follows_per_profile": [40, 45]
                        }
                    }
                    ConfigManager.save_config(default_config)
                    return default_config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return None

    def save_config(self, config):
        """Save configuration to file"""
        try:
            with self.config_lock:
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(config, f, indent=2)
                logger.info("Configuration saved successfully")
                return True
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            return False
