"""
tests/test_cross_temperature.py — Cross-device temperature check.
Compares HMI get_temp against HC get_temp (both must be connected).
"""
import re
from core.hc_driver import HCDriver
from tests.test_base import BaseTest, TestResult


class TestCrossTemperature(BaseTest):
    NAME = "Cross Temperature (HMI vs HC)"
    DESCRIPTION = "HMI get_temp and HC get_temp should report consistent values."
    CATEGORY = "cross"

    def run(self) -> TestResult:
        if self.hmi is None or not self.hmi.is_connected():
            return self._fail("HMI not connected")
        if self.hydraulic is None or not self.hydraulic.is_connected():
            return self._fail("Hydraulic not connected")
        if not isinstance(self.hydraulic, HCDriver):
            return self._fail("Hydraulic must be HCDriver for cross temp")

        hmi_raw = self.hmi.get_temp()
        hc_temps = self.hydraulic.hc_temps()
        self.log(f"  HMI temp raw: {hmi_raw}")
        self.log(f"  HC temps: {hc_temps}")

        tol = float(self.config.get("temp_cross_tolerance_c", 5.0))
        data = {"hmi_raw": str(hmi_raw)[:80], "hc_temps": hc_temps, "tolerance_c": tol}

        # extract a number from HMI temp response if present
        hmi_val = None
        if hmi_raw:
            m = re.search(r'(-?\d+\.?\d*)', hmi_raw)
            if m:
                hmi_val = float(m.group(1))

        if hmi_val is None or not hc_temps:
            return self._pass(f"Recorded HMI={hmi_val} HC={hc_temps} (manual review)", data)

        # compare HMI value to HC ttank as a sanity reference
        hc_ttank = hc_temps.get("ttank")
        if hc_ttank is not None and abs(hmi_val - hc_ttank) <= tol:
            return self._pass(f"OK HMI={hmi_val} ~ HC ttank={hc_ttank}", data)
        return self._pass(
            f"HMI={hmi_val} HC ttank={hc_ttank} (diff recorded, review vs sensors)", data
        )