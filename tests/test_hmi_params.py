"""
tests/test_hmi_params.py — HMI Parameter Validation.
"""
from tests.test_base import BaseTest, TestResult


class TestParamReadAll(BaseTest):
    NAME = "Param Dump Readable"
    DESCRIPTION = "get_param returns a non-empty parameter dump."
    CATEGORY = "hmi_params"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        resp = self.hmi.get_param()
        length = len(resp) if resp else 0
        self.log(f"  get_param length={length}")
        data = {"length": length}
        if resp and (length > 50 or "CMD EXECUTE OK" in resp):
            return self._pass("OK param dump received", data)
        return self._fail("Empty or invalid param dump", data)


class TestParamRoundTrip(BaseTest):
    NAME = "Param Set/Get Round-Trip"
    DESCRIPTION = "Read a param, write the same value back, read again — must match."
    CATEGORY = "hmi_params"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        param_id = int(self.config.get("hmi_test_param_id", 29))
        # read current value first
        resp = self.hmi.get_param(param_id)
        if resp is None:
            return self._fail(f"get_param {param_id} read None")
        import re
        m = re.search(r'=\s*(-?\d+)', resp)
        if not m:
            return self._fail(f"Could not parse param[{param_id}] from response")
        current = int(m.group(1))
        self.log(f"  param[{param_id}] current={current}")
        # write it back (same value, always in-range)
        self.hmi.set_param(param_id, current)
        # read again
        resp2 = self.hmi.get_param(param_id)
        m2 = re.search(r'=\s*(-?\d+)', resp2 or "")
        readback = int(m2.group(1)) if m2 else None
        self.log(f"  param[{param_id}] readback={readback}")
        data = {"param_id": param_id, "current": current, "readback": readback}
        if readback == current:
            return self._pass(f"OK param[{param_id}] round-trip = {current}", data)
        return self._fail(f"param[{param_id}] readback {readback} != {current}", data)


class TestParamRangeRejection(BaseTest):
    NAME = "Param Range Rejection"
    DESCRIPTION = "An out-of-range param value must be rejected by firmware."
    CATEGORY = "hmi_params"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        param_id = int(self.config.get("hmi_range_param_id", 29))
        bad_value = int(self.config.get("hmi_range_bad_value", 999999999))
        # send raw so we can inspect the rejection message even on retries
        resp = self.hmi.send_command(f"set_param {param_id} {bad_value}", retries=1)
        self.log(f"  set param[{param_id}]={bad_value} -> {str(resp)[:60]}")
        data = {"param_id": param_id, "bad_value": bad_value, "response": str(resp)[:60]}
        text = (resp or "").lower()
        if resp is None or "not in range" in text or "error" in text or "between" in text:
            return self._pass("OK out-of-range value rejected", data)
        return self._fail(f"value not rejected: {resp}", data)
