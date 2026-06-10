"""
tests/test_hmi_counters.py — HMI Counters Integrity.
Verifies the volume counters reported by the HMI are self-consistent.
Counters: 0=Total_ml, 1=Filter_ml, 2=Cold_ml, 4=Amb_ml.
"""
import time
from tests.test_base import BaseTest, TestResult

TOLERANCE_ML = 200


class TestCountersMonotonic(BaseTest):
    NAME = "Counters Monotonic Increase"
    DESCRIPTION = "Total_ml must not decrease across two reads with a pour between."
    CATEGORY = "hmi_counters"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        before = self.hmi.get_counter("total")
        if before is None:
            return self._fail("Total counter read None")
        # small cold pour
        self.hmi.press(5, 1000)
        time.sleep(float(self.config.get("pour_wait_sec", 40)))
        after = self.hmi.get_counter("total")
        self.log(f"  total before={before} after={after}")
        data = {"total_before": before, "total_after": after}
        if after is None:
            return self._fail("Total counter read None after pour", data)
        if after >= before:
            return self._pass(f"OK total non-decreasing {before}->{after}", data)
        return self._fail(f"Total decreased {before}->{after}", data)


class TestCountersSum(BaseTest):
    NAME = "Counters Sum (Total = Cold + Amb + Hot)"
    DESCRIPTION = "Total_ml should approx equal Cold_ml + Amb_ml + hot portion."
    CATEGORY = "hmi_counters"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        total = self.hmi.get_counter("total")
        cold = self.hmi.get_counter("cold")
        amb = self.hmi.get_counter("amb")
        self.log(f"  total={total} cold={cold} amb={amb}")
        data = {"total": total, "cold": cold, "amb": amb}
        if None in (total, cold, amb):
            return self._fail("One of the counters read None", data)
        # hot is not a separate counter; cold + amb must not exceed total
        if cold + amb <= total + TOLERANCE_ML:
            return self._pass(f"OK cold+amb={cold + amb} <= total={total}", data)
        return self._fail(f"cold+amb={cold + amb} > total={total}", data)


class TestFilterTracksTotal(BaseTest):
    NAME = "Filter_ml tracks Total_ml"
    DESCRIPTION = "Filter_ml should be within tolerance of Total_ml after a pour."
    CATEGORY = "hmi_counters"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        tol = float(self.config.get("tolerance_ml", TOLERANCE_ML))
        self.hmi.reset_counter("total", 0)
        self.hmi.reset_counter("filter", 0)
        time.sleep(0.5)
        self.hmi.press(5, 1000)
        time.sleep(float(self.config.get("pour_wait_sec", 40)))
        total = self.hmi.get_counter("total")
        filt = self.hmi.get_counter("filter")
        self.log(f"  total={total} filter={filt}")
        data = {"total": total, "filter": filt}
        if None in (total, filt):
            return self._fail("Counter read None", data)
        if abs(total - filt) <= tol:
            return self._pass(f"OK filter tracks total diff={abs(total - filt):.0f}ml", data)
        return self._fail(f"filter vs total diff={abs(total - filt):.0f}ml > {tol}", data)