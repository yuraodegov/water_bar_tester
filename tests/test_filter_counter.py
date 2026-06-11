"""
tests/test_filter_counter.py
Проверяет счётчик фильтра Filter_ml [01].
"""
from tests.test_base import BaseTest, TestResult


class TestFilterCounter(BaseTest):
    NAME = "Filter Counter"
    DESCRIPTION = "Проверяет счётчик Filter_ml — должен соответствовать цели."
    CATEGORY = "param"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err

        target_ml = int(float(self.config.get("target_liters", 1)) * 1000)
        filter_max_l = float(self.config.get("filter_max_liters", 5000))
        filter_max_ml = filter_max_l * 1000

        self.log(f"[{self.NAME}] Reading Filter_ml counter...")
        val = self.hmi.get_counter("filter")
        if val is None:
            return self._fail("get_counter filter returned None")

        self.log(f"  Filter_ml = {val:.0f} ml ({val / 1000:.2f} L)")
        data = {"filter_ml": val, "filter_l": val / 1000, "target_ml": target_ml}

        if val < target_ml:
            return self._fail(f"Filter {val:.0f}ml < target {target_ml}ml", data)
        if val >= filter_max_ml:
            return self._fail(
                f"Filter {val / 1000:.1f}L >= max {filter_max_l}L — замените фильтр!", data
            )

        return self._pass(f"Filter OK: {val / 1000:.2f} L", data)
