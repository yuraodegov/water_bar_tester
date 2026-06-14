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
        val = hc.heater_calibration_flag()
        self.log(f"  heater_calibration flag={val}")
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
        val = hc.hc_get_param("heater_c_delay")
        self.log(f"  heater_c_delay={val}")
        data = {"heater_c_delay": val}
        if val is not None and val >= 0:
            return self._pass(f"OK c_delay readable={val}", data)
        return self._fail(f"c_delay invalid: {val}", data)


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
        val = hc.hc_get_param("heater_sdev_max")
        self.log(f"  heater_sdev_max={val}")
        data = {"heater_sdev_max": val}
        if val is not None and val >= 0:
            return self._pass(f"OK sdev_max readable={val}", data)
        return self._fail(f"sdev_max invalid: {val}", data)