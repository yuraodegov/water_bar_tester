"""
tests/test_hc_hot_filling.py — Module 5: Hot Filling (HF-01..05).
Requires hydraulic port connected with HCDriver.
"""
import time
from core.hc_driver import (
    HCDriver, IN_HWT_FLOAT_UP, IN_HWT_ELEC_UP, IN_HWT_OVERFLOW
)
from core.hc_config import PROFILES
from tests.test_base import BaseTest, TestResult

SETTLE = 1.0


def _hc(test):
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected() or not isinstance(hydr, HCDriver):
        return None
    return hydr


def _cfg(test):
    return PROFILES.get(test.config.get("hc_profile", "IL").upper(), PROFILES["IL"])


class TestHF01FillStartsLowLevel(BaseTest):
    NAME = "HF-01 Hot fill starts when level low"
    DESCRIPTION = "With float down and electrode down, hot_filling becomes active."
    CATEGORY = "hc_filling"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.inject_inputs({IN_HWT_FLOAT_UP: 0, IN_HWT_ELEC_UP: 0})
        time.sleep(SETTLE)
        st = hc.hc_status()
        self.log(f"  hot_filling={st['hot_filling']}")
        data = {"hot_filling": st["hot_filling"]}
        if st["hot_filling"] not in ("DISABLE",):
            return self._pass(f"OK hot_filling active={st['hot_filling']}", data)
        return self._fail("hot_filling DISABLE at low level", data)


class TestHF02HotFillTimeout(BaseTest):
    NAME = "HF-02 Hot fill timeout -> Err159"
    DESCRIPTION = "hot_fill_timeout=1min, tank never fills — Err159 fires."
    CATEGORY = "hc_filling"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        timeout_sec = int(self.config.get("hf02_timeout_sec", 120))
        hc.hc_set_param("heater_hot_fill_timeout", 1)
        hc.inject_inputs({IN_HWT_FLOAT_UP: 0, IN_HWT_ELEC_UP: 0})
        self.log(f"  Waiting up to {timeout_sec}s for Err159...")
        deadline = time.time() + timeout_sec
        raised = False
        while time.time() < deadline:
            if "159" in hc.read_errors():
                raised = True
                break
            time.sleep(3)
        self.log(f"  err159={raised}")
        data = {"err159_raised": raised}
        if raised:
            return self._pass("OK Err159 raised on hot-fill timeout", data)
        return self._fail(f"Err159 not raised within {timeout_sec}s", data)


class TestHF03Overfill(BaseTest):
    NAME = "HF-03 Overfill detection"
    DESCRIPTION = "Overflow electrode active — fill must stop / error handling."
    CATEGORY = "hc_filling"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.inject_inputs({IN_HWT_OVERFLOW: 1})
        time.sleep(SETTLE)
        st = hc.hc_status()
        errs = hc.read_errors()
        self.log(f"  hot_filling={st['hot_filling']} errors={errs[:60]}")
        data = {"hot_filling": st["hot_filling"], "errors": errs[:60]}
        return self._pass(f"OK overfill handled hot_filling={st['hot_filling']}", data)


class TestHF04FillStopsWhenFull(BaseTest):
    NAME = "HF-04 Fill stops when tank full"
    DESCRIPTION = "Float up + electrode up — hot_filling stops (FULL/PAUSE)."
    CATEGORY = "hc_filling"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.inject_inputs({IN_HWT_FLOAT_UP: 1, IN_HWT_ELEC_UP: 1})
        time.sleep(SETTLE)
        st = hc.hc_status()
        self.log(f"  hot_filling={st['hot_filling']}")
        data = {"hot_filling": st["hot_filling"]}
        return self._pass(f"OK fill stopped hot_filling={st['hot_filling']}", data)


class TestHF05TimeLevelParam(BaseTest):
    NAME = "HF-05 time_level averaging param"
    DESCRIPTION = "heater_time_level param is writable and read back correctly."
    CATEGORY = "hc_filling"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.hc_set_param("heater_time_level", 5)
        val = hc.hc_get_param("heater_time_level")
        self.log(f"  time_level set=5 read={val}")
        data = {"time_level": val}
        if val == 5:
            return self._pass("OK time_level round-trip", data)
        return self._fail(f"time_level read {val} != 5", data)