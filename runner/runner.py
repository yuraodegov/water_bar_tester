"""
runner/runner.py — авто-discovery и запуск тестов.
"""
import importlib
import pkgutil
import sys
import os
from datetime import datetime
from tests.test_base import BaseTest, TestResult

TESTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tests")


def discover_tests() -> dict:
    if TESTS_DIR not in sys.path:
        sys.path.insert(0, TESTS_DIR)
    found = {}
    for _, module_name, _ in pkgutil.iter_modules([TESTS_DIR]):
        if module_name == "test_base":
            continue
        try:
            mod = importlib.import_module(f"tests.{module_name}")
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if isinstance(obj, type) and issubclass(obj, BaseTest) and obj is not BaseTest:
                    found[obj.NAME] = obj
        except Exception as e:
            print(f"[WARN] Cannot load {module_name}: {e}")
    return dict(sorted(found.items()))


class TestRunner:
    def __init__(self, hmi, hydraulic, config: dict, log_callback=None):
        self.hmi = hmi
        self.hydraulic = hydraulic
        self.config = config
        self.log = log_callback or print
        self.results = []
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self, test_names=None):
        all_tests = discover_tests()
        self.results = []
        self._stop = False
        to_run = test_names if test_names else list(all_tests.keys())
        for name in to_run:
            if self._stop:
                self.log("[RUNNER] Stopped by user.")
                break
            cls = all_tests.get(name)
            if cls is None:
                self.log(f"[RUNNER] Test '{name}' not found.")
                continue
            self.log(f"\n{'=' * 55}")
            self.log(f"  > {name}")
            self.log(f"{'=' * 55}")
            try:
                inst = cls(self.hmi, self.hydraulic, self.config, self.log)
                result = inst.run()
            except Exception as e:
                result = TestResult(name, False, f"Exception: {e}")
            self.results.append(result)
            self.log(str(result))
        return self.results

    def generate_report(self) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        lines = []
        lines.append("=" * 55)
        lines.append("       WATER BAR TESTER — REPORT")
        lines.append(f"       {now}")
        lines.append("=" * 55)
        lines.append(f"  HMI port       : {self.config.get('hmi_port', '?')}")
        lines.append(f"  Hydraulic port : {self.config.get('hydraulic_port', '?')}")
        lines.append(f"  Target         : {self.config.get('target_liters', '?')} L")
        lines.append(f"  Tolerance      : {self.config.get('tolerance_ml', 150)} ml")
        lines.append(f"  Tests run      : {len(self.results)}")
        lines.append(f"  Passed         : {passed}   Failed: {failed}")
        lines.append("-" * 55)
        for r in self.results:
            icon = "✓" if r.passed else "✗"
            lines.append(f"  {icon}  {r.test_name}")
            lines.append(f"       {r.message}")
            for k, v in r.data.items():
                if v is not None:
                    lines.append(f"       {k}: {v}")

        # ── ordered summary: failed first, then passed ──────────────
        failed_list = [r for r in self.results if not r.passed]
        passed_list = [r for r in self.results if r.passed]

        lines.append("=" * 55)
        lines.append("                    SUMMARY")
        lines.append("=" * 55)
        lines.append(f"  TOTAL : {len(self.results)}")
        lines.append(f"  PASSED: {passed}")
        lines.append(f"  FAILED: {failed}")
        if self.results:
            pct = passed * 100 // len(self.results)
            lines.append(f"  RATE  : {pct}% passed")
        lines.append("-" * 55)

        if failed_list:
            lines.append(f"  FAILED TESTS ({len(failed_list)}):")
            for r in failed_list:
                lines.append(f"    ✗ {r.test_name}")
                lines.append(f"        {r.message}")
            lines.append("-" * 55)

        if passed_list:
            lines.append(f"  PASSED TESTS ({len(passed_list)}):")
            for r in passed_list:
                lines.append(f"    ✓ {r.test_name}")

        lines.append("=" * 55)
        return "\n".join(lines)