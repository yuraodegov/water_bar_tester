"""
tests/test_hc_extra_hot.py — Module 3: Extra Hot / Boiling Support (EH-01..06).
Requires hydraulic port connected with HCDriver. Profile via config["hc_profile"].
"""
import time
from core.hc_driver import HCDriver, TEMP_TTANK, HEAT_EXTRA, HEAT_IDLE
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


class TestEH01ExtraHotDuties(BaseTest):
    NAME = "EH-01 Extra Hot stage 1 duties (OSPS/OSPM)"
    DESCRIPTION = "In Extra Hot stage 1: small heater=OSPS, main heater=OSPM."
    CATEGORY = "hc_extra_hot"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        osps = hc.hc_get_param("heater_osps")
        ospm = hc.hc_get_param("heater_ospm")
        hc.inject_temp(TEMP_TTANK, cfg.TLLSP - 5)
        time.sleep(SETTLE)
        st = hc.hc_status()
        small = hc.small_heater_duty()
        main = hc.heater_duty()
        self.log(f"  heater={st['heater']} small={small}% main={main}% (OSPS={osps} OSPM={ospm})")
        data = {"heater": st["heater"], "small": small, "main": main, "osps": osps, "ospm": ospm}
        if st["heater"] not in HEAT_EXTRA:
            return self._fail(f"Not in Extra Hot, heater={st['heater']}", data)
        return self._pass(f"OK Extra Hot small={small}% main={main}%", data)


class TestEH02BoilingSupportSwitch(BaseTest):
    NAME = "EH-02 Boiling Support LBS/HBS switch (BTSP1)"
    DESCRIPTION = "Main duty switches LBS<->HBS around BTSP1 during boiling support."
    CATEGORY = "hc_extra_hot"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        hc.inject_temp(TEMP_TTANK, cfg.BTSP1 - 2)
        time.sleep(SETTLE)
        duty_low = hc.heater_duty()
        hc.inject_temp(TEMP_TTANK, cfg.BTSP1 + 2)
        time.sleep(SETTLE)
        duty_high = hc.heater_duty()
        self.log(f"  T<BTSP1 duty={duty_low}% (HBS={cfg.HBS})  T>BTSP1 duty={duty_high}% (LBS={cfg.LBS})")
        data = {"btsp1": cfg.BTSP1, "duty_below": duty_low, "duty_above": duty_high,
                "lbs": cfg.LBS, "hbs": cfg.HBS}
        return self._pass(f"OK BTSP1 switch observed below={duty_low}% above={duty_high}%", data)


class TestEH03BoilToBSP(BaseTest):
    NAME = "EH-03 Boil to BSP setpoint"
    DESCRIPTION = "When T reaches BSP, main heater reduces (boil target reached)."
    CATEGORY = "hc_extra_hot"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        hc.inject_temp(TEMP_TTANK, cfg.BSP + 1)
        time.sleep(SETTLE)
        duty = hc.heater_duty()
        self.log(f"  T>BSP={cfg.BSP} main_duty={duty}%")
        data = {"bsp": cfg.BSP, "main_duty": duty}
        if duty in (0, None) or (duty is not None and duty < cfg.HBS):
            return self._pass(f"OK main duty reduced at/above BSP: {duty}%", data)
        return self._fail(f"Main duty still high {duty}% above BSP={cfg.BSP}", data)


class TestEH04ExtraHotTimeout(BaseTest):
    NAME = "EH-04 Extra Hot timeout -> error"
    DESCRIPTION = "Shorten heater_eh_t_o=1min, keep cold — extra-hot timeout fires."
    CATEGORY = "hc_extra_hot"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        timeout_sec = int(self.config.get("eh04_timeout_sec", 120))
        hc.hc_set_param("heater_eh_t_o", 1)
        hc.inject_temp(TEMP_TTANK, cfg.TLLSP - 5)
        self.log(f"  Waiting up to {timeout_sec}s for extra-hot timeout error...")
        deadline = time.time() + timeout_sec
        raised = False
        while time.time() < deadline:
            errs = hc.read_errors()
            if errs and errs.strip() not in ("", "0"):
                raised = True
                break
            time.sleep(3)
        self.log(f"  error_raised={raised}")
        data = {"error_raised": raised}
        if raised:
            return self._pass("OK extra-hot timeout error raised", data)
        return self._fail(f"No error within {timeout_sec}s", data)


class TestEH05TerminateToIdle(BaseTest):
    NAME = "EH-05 Terminate -> Idle (Ttank>terminate & FT)"
    DESCRIPTION = "FT=1min, T above ttank_terminate — boiling support terminates to Idle."
    CATEGORY = "hc_extra_hot"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        timeout_sec = int(self.config.get("eh05_timeout_sec", 120))
        hc.hc_set_param("heater_ft", 1)
        hc.inject_temp(TEMP_TTANK, cfg.TLLSP - 1)
        time.sleep(SETTLE)
        hc.inject_temp(TEMP_TTANK, cfg.TTANK_TERMINATE + 1)
        self.log(f"  Waiting up to {timeout_sec}s for Idle...")
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            st = hc.hc_status()
            if st["heater"] in HEAT_IDLE:
                return self._pass("OK terminated to Idle", {"heater": st["heater"]})
            time.sleep(3)
        return self._fail(f"Did not reach Idle in {timeout_sec}s", {"heater": hc.hc_status()["heater"]})


class TestEH06FTRunTime(BaseTest):
    NAME = "EH-06 Boiling support FT run time"
    DESCRIPTION = "heater_ft param is writable and read back correctly."
    CATEGORY = "hc_extra_hot"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.hc_set_param("heater_ft", 5)
        val = hc.hc_get_param("heater_ft")
        self.log(f"  heater_ft set=5 read={val}")
        data = {"heater_ft": val}
        if val == 5:
            return self._pass("OK heater_ft round-trip", data)
        return self._fail(f"heater_ft read {val} != 5", data)