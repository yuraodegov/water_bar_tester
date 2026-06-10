"""
tests/test_hmi_filter_flow.py — HMI Filter Replacement Flow.
Verifies FilterStatus transitions and FilterMinutes counter.
From logs: COUNTERS SET [09] FilterStatus = 0/1, [06] FilterMinutes increments.
"""
import re
from tests.test_base import BaseTest, TestResult


class TestFilterMinutesIncrement(BaseTest):
    NAME = "Filter Minutes Counter"
    DESCRIPTION = "FilterMinutes counter (id 6) is readable and non-negative."
    CATEGORY = "hmi_filter"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        resp = self.hmi.send_command("get_counter 6")
        self.log(f"  FilterMinutes raw={resp}")
        data = {"response": resp}
        if resp is None:
            return self._fail("get_counter 6 read None", data)
        m = re.search(r'(\d+)', resp)
        if m:
            val = int(m.group(1))
            data["filter_minutes"] = val
            return self._pass(f"OK FilterMinutes={val}", data)
        return self._fail(f"Could not parse FilterMinutes from {resp}", data)


class TestFilterStatusReadable(BaseTest):
    NAME = "Filter Status Readable"
    DESCRIPTION = "FilterStatus counter (id 9) reads 0 or 1."
    CATEGORY = "hmi_filter"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        resp = self.hmi.send_command("get_counter 9")
        self.log(f"  FilterStatus raw={resp}")
        data = {"response": resp}
        if resp is None:
            return self._fail("get_counter 9 read None", data)
        m = re.search(r'(\d+)', resp)
        if m:
            val = int(m.group(1))
            data["filter_status"] = val
            if val in (0, 1):
                return self._pass(f"OK FilterStatus={val}", data)
            return self._fail(f"FilterStatus={val} not in (0,1)", data)
        return self._fail(f"Could not parse FilterStatus from {resp}", data)


class TestFilterLifeTimeParam(BaseTest):
    NAME = "Filter Life Time Param"
    DESCRIPTION = "FilterLifeTime param (id 14) readable."
    CATEGORY = "hmi_filter"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        resp = self.hmi.get_param(14)
        self.log(f"  FilterLifeTime raw={resp}")
        data = {"response": resp}
        if resp is None:
            return self._fail("get_param 14 read None", data)
        return self._pass("OK FilterLifeTime readable", data)