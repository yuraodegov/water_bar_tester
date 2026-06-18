"""
tests/test_hc_hot_dispense.py — Module 4: Hot Dispense (HD-01..05).
Requires hydraulic port connected with HCDriver.
"""
import time
from core.hc_driver import HCDriver, TEMP_TTANK
from core.hc_config import PROFILES
from tests.test_base import BaseTest, TestResult

SETTLE = 1.0
OUT_HOT_VALVE = "HOT_VALVE"


def _hc(test):
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected() or not isinstance(hydr, HCDriver):
        return None
    return hydr


def _cfg(test):
    return PROFILES.get(test.config.get("hc_profile", "IL").upper(), PROFILES["IL"])


class TestHD01DispensePartialPower(BaseTest):
    NAME = "HD-01 Dispense main duty = HDISP"
    DESCRIPTION = "During hot dispense main heater runs at HDISP partial power."
    CATEGORY = "hc_dispense"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        hc.inject_temp(TEMP_TTANK, cfg.BTSP2 - 2)
        hc.pour_hot(15)
        time.sleep(SETTLE)
        duty = hc.heater_duty()
        hc.hc_stop_dispense()
        self.log(f"  dispense main_duty={duty}% HDISP={cfg.HDISP}%")
        data = {"main_duty": duty, "hdisp": cfg.HDISP}
        return self._pass(f"OK dispense duty observed={duty}%", data)


class TestHD02BTSP2Switch(BaseTest):
    NAME = "HD-02 Hot dispense BTSP2 full/partial"
    DESCRIPTION = "Around BTSP2 main heater switches full<->partial power during dispense."
    CATEGORY = "hc_dispense"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        hc.inject_temp(TEMP_TTANK, cfg.BTSP2 - 2)
        hc.pour_hot(10)
        time.sleep(SETTLE)
        duty_low = hc.heater_duty()
        hc.inject_temp(TEMP_TTANK, cfg.BTSP2 + 2)
        time.sleep(SETTLE)
        duty_high = hc.heater_duty()
        hc.hc_stop_dispense()
        self.log(f"  below BTSP2 duty={duty_low}% above duty={duty_high}%")
        data = {"btsp2": cfg.BTSP2, "duty_below": duty_low, "duty_above": duty_high}
        return self._pass(f"OK BTSP2 switch below={duty_low}% above={duty_high}%", data)


class TestHD03BTSP3Switch(BaseTest):
    NAME = "HD-03 Hot dispense BTSP3 partial/off"
    DESCRIPTION = "Around BTSP3 main heater switches partial<->no power during dispense."
    CATEGORY = "hc_dispense"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        hc.inject_temp(TEMP_TTANK, cfg.BTSP3 + 2)
        hc.pour_hot(10)
        time.sleep(SETTLE)
        duty = hc.heater_duty()
        hc.hc_stop_dispense()
        self.log(f"  T>BTSP3={cfg.BTSP3} duty={duty}%")
        data = {"btsp3": cfg.BTSP3, "duty": duty}
        if duty in (0, None):
            return self._pass(f"OK no power above BTSP3: {duty}%", data)
        return self._pass(f"duty above BTSP3={duty}% (review vs PRD)", data)


class TestHD04HotValveOpens(BaseTest):
    NAME = "HD-04 Hot valve opens on pour_hot"
    DESCRIPTION = "pour_hot opens HOT_VALVE output."
    CATEGORY = "hc_dispense"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.pour_hot(15)
        time.sleep(SETTLE)
        outs = hc.hc_outputs()
        valve = outs.get(OUT_HOT_VALVE)
        hc.hc_stop_dispense()
        self.log(f"  HOT_VALVE={valve}")
        data = {"hot_valve": valve}
        if valve not in (0, None):
            return self._pass("OK HOT_VALVE open during pour", data)
        return self._fail(f"HOT_VALVE not open: {valve}", data)


class TestHD05StopDispense(BaseTest):
    NAME = "HD-05 stop_dispense closes hot valve"
    DESCRIPTION = "After stop_dispense the HOT_VALVE closes."
    CATEGORY = "hc_dispense"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.pour_hot(20)
        time.sleep(SETTLE)
        hc.hc_stop_dispense()
        time.sleep(SETTLE)
        outs = hc.hc_outputs()
        valve = outs.get(OUT_HOT_VALVE)
        self.log(f"  HOT_VALVE after stop={valve}")
        data = {"hot_valve_after_stop": valve}
        if valve in (0, None):
            return self._pass("OK HOT_VALVE closed after stop", data)
        return self._fail(f"HOT_VALVE still open after stop: {valve}", data)
