import json
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class Colors:
    """ANSI color codes for pretty console output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"

    # Basic colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    GREY = "\033[90m"

    @classmethod
    def color_for_status(cls, status: str) -> str:
        """Return color code for a given status label."""
        s = status.upper()
        if s in {"OK", "SUCCESS"}:
            return cls.GREEN
        if s in {"WARN", "WARNING"}:
            return cls.YELLOW
        if s in {"ERR", "ERROR", "FAIL"}:
            return cls.RED
        if s in {"INFO"}:
            return cls.BLUE
        return cls.GREY


class TestBotEngine:
    """
    TestableBot is a thin wrapper around a real bot instance (e.g. XFollowBot).

    Responsibilities:
    - Decorate all method calls with:
        - step indexing,
        - console logging with colors,
        - timing and basic metrics,
        - optional screenshot on errors.
    - Accumulate a structured steps log in memory.
    - Provide utilities:
        - start_test()
        - print_summary()
        - save_log_to_file()
        - take_screenshot(reason)

    IMPORTANT:
    - TestableBot does NOT know how to follow, navigate, etc.
      It just forwards everything to the inner bot.
    - ScenarioEngine can use TestableBot exactly like a normal bot.
    """

    def __init__(
        self,
        bot: Any,
        test_name: Optional[str] = None,
    ) -> None:
        """
        :param bot: Inner bot instance (XFollowBot or any bot implementing the required interface).
        :param test_name: Optional logical name for this test run (used in logs & file names).
        """
        self._bot = bot
        self.test_name = test_name or f"test_{int(time.time())}"

        self._steps_log: List[Dict[str, Any]] = []
        self._step_counter: int = 0
        self._started_at: Optional[float] = None
        self._finished_at: Optional[float] = None


    # -------------------------------------------------------------------------
    # Basic helpers
    # -------------------------------------------------------------------------

    @property
    def profile_id(self) -> Optional[str]:
        """Expose profile_id of the inner bot if available."""
        return getattr(self._bot, "profile_id", None)

    # -------------------------------------------------------------------------
    # Test lifecycle
    # -------------------------------------------------------------------------

    def start_test(self, test_name: Optional[str] = None) -> None:
        """
        Reset internal state and mark the beginning of a new test run.
        If test_name is provided, it overrides the previous one.
        """
        if test_name:
            self.test_name = test_name

        self._steps_log.clear()
        self._step_counter = 0
        self._started_at = time.time()
        self._finished_at = None

        header = f"Starting test '{self.test_name}'"
        if self.profile_id:
            header += f" for profile {self.profile_id}"

        self._log_console("INFO", header, bold=True)

    def finish_test(self) -> None:
        """
        Mark test as finished. This does not print summary or save log;
        call print_summary() and/or save_log_to_file() explicitly.
        """
        self._finished_at = time.time()
        self._log_console("INFO", f"Test '{self.test_name}' finished")

    # -------------------------------------------------------------------------
    # Logging helpers
    # -------------------------------------------------------------------------

    def _log_console(
        self,
        status: str,
        message: str,
        bold: bool = False,
        step_index: Optional[int] = None,
    ) -> None:
        """
        Print colored message to console.

        :param status: Status label ('INFO', 'OK', 'ERROR', etc.).
        :param message: Text message.
        :param bold: If True, print in bold.
        :param step_index: Optional step index for prefix.
        """
        color = Colors.color_for_status(status)
        prefix = f"[{status}]"
        if step_index is not None:
            prefix = f"[{status}][step {step_index}]"

        if bold:
            out = f"{Colors.BOLD}{color}{prefix} {message}{Colors.RESET}"
        else:
            out = f"{color}{prefix} {message}{Colors.RESET}"

        print(out)

    # -------------------------------------------------------------------------
    # Structured logging & summary
    # -------------------------------------------------------------------------

    def _register_step(
        self,
        name: str,
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
        status: str,
        duration: float,
        result: Any = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Store structured information about a single step call.
        """
        entry = {
            "index": self._step_counter,
            "name": name,
            "status": status,
            "duration": duration,
            "args": self._safe_serialize(args),
            "kwargs": self._safe_serialize(kwargs),
            "result": self._safe_serialize(result),
            "error": error,
            "timestamp": datetime.now().isoformat(),
        }
        self._steps_log.append(entry)

    @staticmethod
    def _safe_serialize(value: Any) -> Any:
        """
        Try to make value JSON-serializable.
        If impossible, return string representation.
        """
        try:
            json.dumps(value)
            return value
        except Exception:
            return repr(value)

    def print_summary(self) -> None:
        """
        Print summary of the test run: total steps, durations, errors count.
        """
        if self._started_at is None:
            self._log_console("WARN", "print_summary() called but test was not started")
            return

        if self._finished_at is None:
            total_time = time.time() - self._started_at
        else:
            total_time = self._finished_at - self._started_at

        total_steps = len(self._steps_log)
        errors = sum(1 for s in self._steps_log if s["status"].upper() == "ERROR")
        warns = sum(1 for s in self._steps_log if s["status"].upper() == "WARN")

        msg = (
            f"Test '{self.test_name}' summary: "
            f"steps={total_steps}, errors={errors}, warnings={warns}, "
            f"duration={total_time:.2f}s"
        )
        self._log_console("INFO", msg, bold=True)

    # -------------------------------------------------------------------------
    # Dynamic method proxying
    # -------------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """
        Dynamic attribute access.

        If the attribute is not found on TestableBot itself,
        we try to fetch it from the inner bot. If it is callable,
        we wrap it in a step logger. Otherwise, return the attribute as is.
        """
        attr = getattr(self._bot, name)

        # Non-callable attributes are returned as is
        if not callable(attr):
            return attr

        # Wrap callables with logging logic
        def wrapper(*args, **kwargs):
            self._step_counter += 1
            step_index = self._step_counter
            method_full_name = f"{type(self._bot).__name__}.{name}"

            # Prepare a short message for console
            args_repr = ", ".join(repr(a) for a in args[:3])
            if len(args) > 3:
                args_repr += ", ..."
            kwargs_repr = ", ".join(f"{k}={repr(v)}" for k, v in list(kwargs.items())[:3])
            if len(kwargs) > 3:
                kwargs_repr += ", ..."

            call_repr = f"{name}({args_repr}"
            if kwargs_repr:
                if args_repr:
                    call_repr += f", {kwargs_repr}"
                else:
                    call_repr += kwargs_repr
            call_repr += ")"

            self._log_console(
                "INFO",
                f"Calling {method_full_name} -> {call_repr}",
                step_index=step_index,
            )

            start_ts = time.time()
            status = "OK"
            error_msg: Optional[str] = None

            try:
                result = attr(*args, **kwargs)
                duration = time.time() - start_ts

                self._log_console(
                    "OK",
                    f"{method_full_name} completed in {duration:.2f}s",
                    step_index=step_index,
                )

                self._register_step(
                    name=name,
                    args=args,
                    kwargs=kwargs,
                    status=status,
                    duration=duration,
                    result=result,
                )

                return result

            except Exception as e:
                duration = time.time() - start_ts
                status = "ERROR"
                error_msg = f"{type(e).__name__}: {e}"

                self._log_console(
                    "ERROR",
                    f"{method_full_name} failed in {duration:.2f}s: {error_msg}",
                    step_index=step_index,
                )

                self._register_step(
                    name=name,
                    args=args,
                    kwargs=kwargs,
                    status=status,
                    duration=duration,
                    result=None,
                    error=error_msg,
                )

                # Important: re-raise so ScenarioEngine (or caller) can see the error
                raise

        return wrapper
