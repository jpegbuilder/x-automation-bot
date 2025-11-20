"""
ScenarioEngine - generic scenario runner for X bots.
"""
import os
import time
import logging
from typing import Any, Dict, List, Optional, Union, Tuple
import yaml

logger = logging.getLogger(__name__)


StepType = Union[str, Dict[str, Any]]


class ScenarioEngine:
    """
    ScenarioEngine executes high-level scenarios on top of a given bot.

    The expected YAML structure:

    scenarios:
      simple_follow:
        description: "..."
        target_required: true
        steps:
          - wait: 2
          - navigate_to_profile
          - follow_user
          - go_home
          - wait: 2

    The engine does not implement the low-level actions itself.
    It just calls methods on `self.bot`.
    """

    # Steps that normally require a target username if no explicit argument is given
    TARGET_AWARE_STEPS = {
        "navigate_to_profile",
        "follow_user",
        "find_and_goto_repost_author",
    }

    def __init__(
        self,
        bot: Any,
        scenarios_path: Optional[str] = None,
        scenarios_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        :param bot: Bot instance that will actually perform the actions.
                    It must implement the methods used in scenarios (e.g. navigate_to_profile, follow_user, ...).
        :param scenarios_path: Optional path to YAML file with scenarios.
                              Can be absolute or relative to this file's directory.
                              If not provided, defaults to 'scenarios.yaml' in the same directory.
        :param scenarios_data: Optional dict with already loaded scenarios.
                               If both are provided, scenarios_data takes precedence.
        """
        self.bot = bot
        self._scenarios: Dict[str, Any] = {}
        self._scenario_index: int = 0
        self.context: Dict[str, Any] = {}

        if scenarios_data is not None:
            self._load_from_dict(scenarios_data)
        elif scenarios_path is not None:
            self.load_from_file(scenarios_path)
        else:
            # Default: look for scenarios.yaml in the same directory as this file
            default_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'scenarios.yaml'
            )
            if os.path.isfile(default_path):
                logger.info(f"Using default scenarios file: {default_path}")
                self.load_from_file(default_path)
            else:
                logger.warning(
                    "ScenarioEngine initialized without scenarios. "
                    f"Expected default file at: {default_path}. "
                    "Use load_from_file() or provide scenarios_data."
                )

    def __getattr__(self, name: str):
        """
        Proxy attribute access to the underlying bot.
        This allows the engine to be used as if it were the bot itself.
        """
        return getattr(self.bot, name)

    # -------------------------------------------------------------------------
    # Loading scenarios
    # -------------------------------------------------------------------------

    def load_from_file(self, path: str) -> None:
        """
        Load scenarios from a YAML file.

        :param path: Path to the scenarios YAML file.
                    If not absolute, will be resolved relative to this script's directory.
        """
        # Если передан относительный путь, ищем относительно текущего файла
        if not os.path.isabs(path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            scenarios_path = os.path.join(script_dir, path)
        else:
            scenarios_path = path

        if not os.path.isfile(scenarios_path):
            raise FileNotFoundError(
                f"❌ Scenarios file not found at: {scenarios_path}\n"
                f"   Script directory: {os.path.dirname(os.path.abspath(__file__))}"
            )

        logger.info(f"Loading scenarios from file: {scenarios_path}")
        with open(scenarios_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self._load_from_dict(data)

    def _load_from_dict(self, data: Dict[str, Any]) -> None:
        """
        Internal helper to load scenarios from a dict.
        Expects a top-level key 'scenarios'.
        """
        scenarios = data.get("scenarios") or {}
        if not isinstance(scenarios, dict):
            raise ValueError("Invalid scenarios format: top-level 'scenarios' key must be a dict")

        self._scenarios = scenarios
        logger.info(f"Loaded {len(self._scenarios)} scenarios: {list(self._scenarios.keys())}")

    # -------------------------------------------------------------------------
    # Introspection helpers
    # -------------------------------------------------------------------------

    @property
    def scenarios(self) -> Dict[str, Any]:
        """Get all loaded scenarios"""
        return self._scenarios

    def get_scenario_names(self) -> List[str]:
        """Get list of available scenario names"""
        return list(self._scenarios.keys())

    def get_scenario_config(self, name: str) -> Dict[str, Any]:
        """Get configuration for a specific scenario"""
        if name not in self._scenarios:
            raise KeyError(f"Scenario '{name}' not found. Available: {self.get_scenario_names()}")
        return self._scenarios[name]

    # -------------------------------------------------------------------------
    # Execution
    # -------------------------------------------------------------------------

    def execute_scenario(
        self,
        name: str,
        target_username: Optional[str] = None,
        initial_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a scenario by name.

        :param name: Scenario name (key in self._scenarios)
        :param target_username: Target username for steps that operate on a profile
        :param initial_context: Optional context data to start with
        :return: Result dict with details about execution
        """
        scenario = self.get_scenario_config(name)

        description = scenario.get("description", "")
        target_required = bool(scenario.get("target_required", False))
        steps: List[StepType] = scenario.get("steps") or []

        if target_required and not target_username:
            raise ValueError(f"Scenario '{name}' requires target_username, but none was provided.")

        # Reset context
        self.context = dict(initial_context or {})

        logger.info(
            f"Starting scenario '{name}' "
            f"(target_required={target_required}, target={target_username!r}, steps={len(steps)})"
        )

        results: List[Dict[str, Any]] = []
        overall_success = True
        first_error: Optional[str] = None

        for idx, step in enumerate(steps, start=1):
            start_ts = time.time()
            try:
                step_name, param = self._parse_step(step)

                logger.debug(f"Scenario '{name}': executing step #{idx}: {step}")

                result = self._execute_single_step(
                    step_name=step_name,
                    param=param,
                    target_username=target_username,
                )

                duration = time.time() - start_ts
                results.append(
                    {
                        "index": idx,
                        "step": step,
                        "status": "ok",
                        "duration": duration,
                        "result": result,
                    }
                )

            except Exception as e:
                duration = time.time() - start_ts
                err_msg = f"{type(e).__name__}: {e}"
                logger.error(
                    f"Scenario '{name}': step #{idx} failed ({step}). Error: {err_msg}"
                )

                results.append(
                    {
                        "index": idx,
                        "step": step,
                        "status": "error",
                        "duration": duration,
                        "error": err_msg,
                    }
                )

                overall_success = False
                if first_error is None:
                    first_error = err_msg

                # You can choose whether to stop on first error or continue.
                # For now we stop to avoid cascading failures.
                break

        logger.info(
            f"Finished scenario '{name}' with success={overall_success}. "
            f"Steps executed: {len(results)}/{len(steps)}"
        )

        return {
            "scenario": name,
            "description": description,
            "target_username": target_username,
            "success": overall_success,
            "error": first_error,
            "steps": results,
            "context": self.context,
        }

    # -------------------------------------------------------------------------
    # Step parsing & execution
    # -------------------------------------------------------------------------

    @staticmethod
    def _parse_step(step: StepType) -> Tuple[str, Any]:
        """
        Parse a step definition into (method_name, param).

        Supported forms:
        - "navigate_to_profile"
        - {"wait": 2}
        - {"scroll_posts": 5}
        - {"like_random_post": null}
        """
        if isinstance(step, str):
            return step, None

        if isinstance(step, dict):
            if len(step) != 1:
                raise ValueError(f"Invalid step dict, expected exactly 1 key: {step}")
            method_name, param = next(iter(step.items()))
            return method_name, param

        raise TypeError(f"Unsupported step type: {type(step)} ({step!r})")

    def _execute_single_step(
        self,
        step_name: str,
        param: Any,
        target_username: Optional[str],
    ) -> Any:
        """
        Execute a single step by calling the corresponding method on the bot.

        :param step_name: Name of the step (mapped to bot method)
        :param param: Optional parameter from YAML
        :param target_username: Target username if scenario is profile-related
        :return: Whatever the bot method returns
        """
        if not hasattr(self.bot, step_name):
            raise AttributeError(
                f"Bot of type {type(self.bot).__name__} does not implement method '{step_name}'"
            )

        method = getattr(self.bot, step_name)

        # Build args/kwargs for the method call
        args: List[Any] = []
        kwargs: Dict[str, Any] = {}

        # Special handling for steps that usually operate on a target username
        if step_name in self.TARGET_AWARE_STEPS:
            if param is None:
                # No parameter in YAML: assume we should pass the target username as the first argument
                if not target_username:
                    raise ValueError(
                        f"Step '{step_name}' requires target_username but none was provided."
                    )
                args.append(target_username)
            else:
                # Parameter is given, decide how to pass it
                if isinstance(param, dict):
                    # Use dict as kwargs, but also provide username if not specified
                    kwargs.update(param)
                    if target_username and "username" not in kwargs:
                        kwargs["username"] = target_username
                else:
                    # Non-dict param: let it override username
                    args.append(param)

        else:
            # Regular step without implicit username
            if param is not None:
                if isinstance(param, dict):
                    kwargs.update(param)
                else:
                    args.append(param)

        # Call the method on the bot
        logger.debug(
            f"Calling bot.{step_name}(*{args}, **{kwargs}) "
            f"on {type(self.bot).__name__}"
        )
        return method(*args, **kwargs)

    def choose_scenario_for_user(
        self,
        profile_id: Optional[str] = None,
        username: Optional[str] = None
    ) -> str:
        """
        Choose a scenario for a given user/profile using round-robin selection.

        :param profile_id: Optional profile ID for logging
        :param username: Optional username for logging
        :return: Selected scenario name
        """
        if not self._scenarios:
            raise RuntimeError("ScenarioEngine: no scenarios available")

        scenarios_names = list(self._scenarios.keys())

        scenario_name = scenarios_names[self._scenario_index % len(scenarios_names)]
        self._scenario_index += 1

        logger.info(
            f"ScenarioEngine: selected scenario '{scenario_name}' "
            f"for profile={profile_id!r}, username={username!r}"
        )
        return scenario_name