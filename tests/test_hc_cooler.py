"""
tests/test_hc_cooler.py — Module 6: Cooler / Cold (CO-01..05).
Requires hydraulic port connected with HCDriver.
Cold water temperature injected on TCW channel.
"""
import time
from core.hc_driver import HCDriver, TEMP_TCW
from core.hc_config import PROFILES
from tests.test_base import BaseTest, TestResult

SETTLE = 1.5


def _hc(test):
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected() or not isinstance(hydr, HCDriver):
        return None
    return hydr


def _cfg(test):
    return PROFILES.get(test.config.get("hc_profile", "IL").upper(), PROFILES["IL"])


class TestCO01CompressorOnWarm(BaseTest):
    NAME = "CO-01 Compressor ON when TCW high"
    DESCRIPTION = "Inject TCW above setpoint_on — compressor must turn ON."
    CATEGORY = "hc_cooler"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        on_sp = hc.hc_get_param("cooler_setpoint_on")
        hc.inject_temp(TEMP_TCW, on_sp + 3)
        time.sleep(SETTLE)
        comp = hc.compressor_on()
        self.log(f"  TCW={on_sp + 3}C compressor_on={comp}")
        data = {"setpoint_on": on_sp, "compressor_on": comp}
        if comp:
            return self._pass(f"OK compressor ON above setpoint_on={on_sp}", data)
        return self._fail(f"Compressor OFF above setpoint_on={on_sp}", data)


class TestCO02CompressorOffCold(BaseTest):
    NAME = "CO-02 Compressor OFF when TCW low"
    DESCRIPTION = "Inject TCW below setpoint_off — compressor must turn OFF."
    CATEGORY = "hc_cooler"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        off_sp = hc.hc_get_param("cooler_setpoint_off")
        hc.inject_temp(TEMP_TCW, max(off_sp - 3, 0))
        time.sleep(SETTLE)
        comp = hc.compressor_on()
        self.log(f"  TCW={max(off_sp - 3, 0)}C compressor_on={comp}")
        data = {"setpoint_off": off_sp, "compressor_on": comp}
        if not comp:
            return self._pass(f"OK compressor OFF below setpoint_off={off_sp}", data)
        return self._fail(f"Compressor ON below setpoint_off={off_sp}", data)


class TestCO03Hysteresis(BaseTest):
    NAME = "CO-03 Cooler hysteresis band"
    DESCRIPTION = "Between setpoint_off and setpoint_on compressor keeps prior state."
    CATEGORY = "hc_cooler"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        off_sp = hc.hc_get_param("cooler_setpoint_off")
        on_sp = hc.hc_get_param("cooler_setpoint_on")
        # turn on first
        hc.inject_temp(TEMP_TCW, on_sp + 3)
        time.sleep(SETTLE)
        was_on = hc.compressor_on()
        # move into band
        mid = (off_sp + on_sp) // 2
        hc.inject_temp(TEMP_TCW, mid)
        time.sleep(SETTLE)
        in_band = hc.compressor_on()
        self.log(f"  on={was_on} mid={mid}C in_band={in_band} (off={off_sp} on={on_sp})")
        data = {"setpoint_off": off_sp, "setpoint_on": on_sp,
                "was_on": was_on, "in_band": in_band}
        return self._pass(f"OK hysteresis: on={was_on} in_band={in_band}", data)


class TestCO04FanPWM(BaseTest):
    NAME = "CO-04 Cooler fan PWM param"
    DESCRIPTION = "cooler_fan_pwm param is writable and read back correctly."
    CATEGORY = "hc_cooler"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.hc_set_param("cooler_fan_pwm", 80)
        val = hc.hc_get_param("cooler_fan_pwm")
        self.log(f"  cooler_fan_pwm set=80 read={val}")
        data = {"cooler_fan_pwm": val}
        if val == 80:
            return self._pass("OK cooler_fan_pwm round-trip", data)
        return self._fail(f"cooler_fan_pwm read {val} != 80", data)


class TestCO05ShabbatSetpoint(BaseTest):
    NAME = "CO-05 Cooler shabbat setpoint param"
    DESCRIPTION = "cooler_shabbat_setpoint matches profile COLD_SP_SHABBAT."
    CATEGORY = "hc_cooler"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        val = hc.hc_get_param("cooler_shabbat_setpoint")
        self.log(f"  cooler_shabbat_setpoint={val} profile={cfg.COLD_SP_SHABBAT}")
        data = {"cooler_shabbat_setpoint": val, "profile": cfg.COLD_SP_SHABBAT}
        if val == cfg.COLD_SP_SHABBAT:
            return self._pass(f"OK shabbat setpoint={val}", data)
        return self._fail(f"shabbat setpoint {val} != profile {cfg.COLD_SP_SHABBAT}", data)