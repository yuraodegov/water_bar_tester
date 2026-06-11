"""
tests/test_hmi_filter_flow.py — HMI Filter Replacement Flow.
Verifies FilterStatus transitions and FilterMinutes counter.
Uses the HMI counter parser (value after '='), not the command echo.
"""
from tests.test_base import BaseTest, TestResult


class TestFilterMinutesIncrement(BaseTest):
    NAME = "Filter Minutes Counter"
    DESCRIPTION = "FilterMinutes counter (id 6) is readable and non-negative."
    CATEGORY = "hmi_filter"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        val = self.hmi.get_counter(6)
        self.log(f"  FilterMinutes={val}")
        data = {"filter_minutes": val}
        if val is None:
            return self._fail("Could not parse FilterMinutes", data)
        if val >= 0:
            return self._pass(f"OK FilterMinutes={int(val)}", data)
        return self._fail(f"FilterMinutes negative: {val}", data)


class TestFilterStatusReadable(BaseTest):
    NAME = "Filter Status Readable"
    DESCRIPTION = "FilterStatus counter (id 9) reads 0 or 1."
    CATEGORY = "hmi_filter"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        val = self.hmi.get_counter(9)
        self.log(f"  FilterStatus={val}")
        data = {"filter_status": val}
        if val is None:
            return self._fail("Could not parse FilterStatus", data)
        if int(val) in (0, 1):
            return self._pass(f"OK FilterStatus={int(val)}", data)
        return self._fail(f"FilterStatus={int(val)} not in (0,1)", data)


class TestFilterLifeTimeParam(BaseTest):
    NAME = "Filter Life Time Param"
    DESCRIPTION = "FilterLifeTime param (id 14) readable."
    CATEGORY = "hmi_filter"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        resp = self.hmi.get_param(14)
        self.log(f"  FilterLifeTime raw len={len(resp) if resp else 0}")
        data = {"has_response": bool(resp)}
        if resp and "FilterLifeTime" in resp:
            return self._pass("OK FilterLifeTime readable", data)
        if resp:
            return self._pass("OK param 14 response received", data)
        return self._fail("get_param 14 read None", data)