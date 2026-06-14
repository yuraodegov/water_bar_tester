"""
tests/test_base.py — base class for all tests.

To add a new test:
  1. Create file tests/test_something.py
  2. Subclass BaseTest
  3. Set NAME, DESCRIPTION, CATEGORY
  4. Implement run() -> TestResult
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TestResult:
    test_name: str
    passed: bool
    message: str = ""
    data: dict = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.test_name}: {self.message}"


class BaseTest:
    NAME = "Base Test"
    DESCRIPTION = "Override in subclass"
    CATEGORY = "general"

    def __init__(self, hmi, hydraulic, config: dict, log_callback=None):
        self.hmi = hmi
        self.hydraulic = hydraulic
        self.config = config
        self.log = log_callback or print
        # replaced by the runner with a real flag check; default never stops
        self.stop_check = lambda: False

    def run(self) -> TestResult:
        raise NotImplementedError(f"{self.__class__.__name__}.run() not implemented")

    def _pass(self, message: str, data: dict = None) -> TestResult:
        return TestResult(self.NAME, True, message, data or {})

    def _fail(self, message: str, data: dict = None) -> TestResult:
        return TestResult(self.NAME, False, message, data or {})

    def _require_hmi(self):
        if self.hmi is None or not self.hmi.is_connected():
            return self._fail("HMI not connected")
        return None

    def _require_hydraulic(self):
        if self.hydraulic is None or not self.hydraulic.is_connected():
            return self._fail("Hydraulic not connected")
        return None