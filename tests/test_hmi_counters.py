"""
tests/test_hmi_counters.py — HMI Counters Integrity.
Uses DELTA measurement so lifetime totals do not break the checks.
Counters: 0=Total_ml, 1=Filter_ml, 2=Cold_ml, 4=Amb_ml.
"""
import time
from tests.test_base import BaseTest, TestResult

TOLERANCE_ML = 200


class TestCountersMonotonic(BaseTest):
    NAME = "Counters Monotonic Increase"
    DESCRIPTION = "Total_ml must not decrease across a pour."
    CATEGORY = "hmi_counters"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        before = self.hmi.get_counter("total")
        if before is None:
            return self._fail("Total counter read None")
        self.hmi.press(5, 1000)
        time.sleep(float(self.config.get("pour_wait_sec", 40)))
        after = self.hmi.get_counter("total")
        self.log(f"  total before={before} after={after}")
        data = {"total_before": before, "total_after": after}
        if after is None:
            return self._fail("Total read None after pour", data)
        if after >= before:
            return self._pass(f"OK total non-decreasing {before:.0f}->{after:.0f}", data)
        return self._fail(f"Total decreased {before:.0f}->{after:.0f}", data)


class TestFilterTracksTotalDelta(BaseTest):
    NAME = "Filter_ml tracks Total_ml (delta)"
    DESCRIPTION = "Increment of Filter_ml must match increment of Total_ml during a pour."
    CATEGORY = "hmi_counters"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        tol = float(self.config.get("tolerance_ml", TOLERANCE_ML))
        base_total = self.hmi.get_counter("total")
        base_filter = self.hmi.get_counter("filter")
        if None in (base_total, base_filter):
            return self._fail("Baseline read None")
        self.hmi.press(5, 1000)
        time.sleep(float(self.config.get("pour_wait_sec", 40)))
        after_total = self.hmi.get_counter("total")
        after_filter = self.hmi.get_counter("filter")
        if None in (after_total, after_filter):
            return self._fail("After read None")
        d_total = after_total - base_total
        d_filter = after_filter - base_filter
        self.log(f"  delta total={d_total:.0f} filter={d_filter:.0f}")
        data = {"delta_total": d_total, "delta_filter": d_filter}
        if abs(d_total - d_filter) <= tol:
            return self._pass(f"OK filter delta tracks total diff={abs(d_total - d_filter):.0f}ml", data)
        return self._fail(f"filter vs total delta diff={abs(d_total - d_filter):.0f}ml > {tol}", data)


class TestColdAmbDeltaConsistent(BaseTest):
    NAME = "Cold/Amb delta consistent with Total"
    DESCRIPTION = "A cold pour increments Cold_ml and Total_ml by the same amount."
    CATEGORY = "hmi_counters"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        tol = float(self.config.get("tolerance_ml", TOLERANCE_ML))
        base_total = self.hmi.get_counter("total")
        base_cold = self.hmi.get_counter("cold")
        if None in (base_total, base_cold):
            return self._fail("Baseline read None")
        self.hmi.press(5, 1000)
        time.sleep(float(self.config.get("pour_wait_sec", 40)))
        after_total = self.hmi.get_counter("total")
        after_cold = self.hmi.get_counter("cold")
        if None in (after_total, after_cold):
            return self._fail("After read None")
        d_total = after_total - base_total
        d_cold = after_cold - base_cold
        self.log(f"  delta total={d_total:.0f} cold={d_cold:.0f}")
        data = {"delta_total": d_total, "delta_cold": d_cold}
        if abs(d_total - d_cold) <= tol:
            return self._pass(f"OK cold delta matches total diff={abs(d_total - d_cold):.0f}ml", data)
        return self._fail(f"cold vs total delta diff={abs(d_total - d_cold):.0f}ml > {tol}", data)