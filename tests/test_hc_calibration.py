"""
tests/test_hc_calibration.py — Module 10: Calibration (CAL-01..03).
Requires hydraulic port connected with HCDriver.
Calibration is DISABLED in shipping firmware; these tests verify params.
"""
from core.hc_driver import HCDriver
from tests.test_base import BaseTest, TestResult

SETTLE = 1.0


def _hc(test):
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected() or not isinstance(hydr, HCDriver):
        return None
    return hydr


class TestCAL01CalibrationFlag(BaseTest):
    NAME = "CAL-01 Calibration flag readable"
    DESCRIPTION = "heater_calibration param readable (disabled in shipping fw)."
    CATEGORY = "hc_calibration"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        val = hc.hc_get_param("heater_calibration")
        self.log(f"  heater_calibration={val}")
        data = {"heater_calibration": val}
        return self._pass(f"OK calibration flag={val}", data)


class TestCAL02CalibDelay(BaseTest):
    NAME = "CAL-02 Calibration delay param"
    DESCRIPTION = "heater_c_delay param writable and read back."
    CATEGORY = "hc_calibration"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.hc_set_param("heater_c_delay", 20)
        val = hc.hc_get_param("heater_c_delay")
        self.log(f"  heater_c_delay set=20 read={val}")
        data = {"heater_c_delay": val}
        if val == 20:
            return self._pass("OK c_delay round-trip", data)
        return self._fail(f"c_delay read {val} != 20", data)


class TestCAL03SdevMax(BaseTest):
    NAME = "CAL-03 Calibration sdev_max param"
    DESCRIPTION = "heater_sdev_max param writable and read back."
    CATEGORY = "hc_calibration"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.hc_set_param("heater_sdev_max", 500)
        val = hc.hc_get_param("heater_sdev_max")
        self.log(f"  heater_sdev_max set=500 read={val}")
        data = {"heater_sdev_max": val}
        if val == 500:
            return self._pass("OK sdev_max round-trip", data)
        return self._fail(f"sdev_max read {val} != 500", data)
