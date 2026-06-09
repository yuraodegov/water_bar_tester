"""
tests/test_base.py — базовый класс для всех тестов.

Чтобы добавить новый тест:
  1. Создай файл tests/test_my_test.py
  2. Унаследуйся от BaseTest
  3. Задай NAME, DESCRIPTION, CATEGORY
  4. Реализуй метод run() → TestResult
  5. Всё — тест автоматически появится в GUI
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TestResult:
    test_name: str
    passed:    bool
    message:   str = ""
    data:      dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.test_name}: {self.message}"


class BaseTest:
    NAME        = "Base Test"
    DESCRIPTION = "Override in subclass"
    CATEGORY    = "general"   # dispense | button | param | temp | ui

    def __init__(self, hmi, hydraulic, config: dict, log_callback=None):
        """
        hmi        — HmiSerial (может быть None если не подключён)
        hydraulic  — HydraulicSerial (может быть None)
        config     — dict настроек из GUI
        """
        self.hmi        = hmi
        self.hydraulic  = hydraulic
        self.config     = config
        self.log        = log_callback or print

    def run(self) -> TestResult:
        raise NotImplementedError(f"{self.__class__.__name__}.run() not implemented")

    # ── хелперы ──────────────────────────────────────────────────────
    def _pass(self, message: str, data: dict = None) -> TestResult:
        return TestResult(self.NAME, True, message, data or {})

    def _fail(self, message: str, data: dict = None) -> TestResult:
        return TestResult(self.NAME, False, message, data or {})

    def _require_hmi(self) -> TestResult | None:
        if self.hmi is None or not self.hmi.is_connected():
            return self._fail("HMI not connected")
        return None

    def _require_hydraulic(self) -> TestResult | None:
        if self.hydraulic is None or not self.hydraulic.is_connected():
            return self._fail("Hydraulic not connected")
        return None