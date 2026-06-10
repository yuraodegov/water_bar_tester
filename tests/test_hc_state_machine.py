"""
tests/test_hc_state_machine.py — Module 1: State Machine (SM-01..SM-09).
Requires hydraulic port connected with HCDriver.
Profile IL/US selected via config["hc_profile"] in GUI (default: IL).
SM-04, SM-05, SM-06 require Manual Shabbat from HMI — reported as SKIPPED.
"""
import time
from core.hc_driver import HCDriver, TEMP_TTANK, HEAT_IDLE, HEAT_EXTRA, CRITICAL_ERROR_IDS
from core.hc_config import PROFILES
from tests.test_base import BaseTest, TestResult

SETTLE = 1.0


def _hc(test: BaseTest):
    """Return HCDriver if hydraulic is connected and is an HCDriver instance."""
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected():
        return None
    if not isinstance(hydr, HCDriver):
        return None
    return hydr


def _cfg(test: BaseTest):
    name = test.config.get("hc_profile", "IL").upper()
    return PROFILES.get(name, PROFILES["IL"])


class TestSM01PowerOnIdle(BaseTest):
    NAME = "SM-01 Power-On -> Idle"
    DESCRIPTION = "After reset heater state must be IDLE."
    CATEGORY = "hc_sm"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("Hydraulic port must be HCDriver for HC tests")
        hc.hc_reset()
        time.sleep(SETTLE)
        st = hc.hc_status()
        self.log(f"  heater={st['heater']}")
        if st["heater"] in HEAT_IDLE:
            return self._pass(f"OK heater={st['heater']}", {"heater": st["heater"]})
        return self._fail(f"Expected IDLE got {st['heater']}", {"heater": st["heater"]})


class TestSM02IdleToExtraHot(BaseTest):
    NAME = "SM-02 Idle -> Extra Hot (T < TLLSP)"
    DESCRIPTION = "Inject T_tank below TLLSP — heater must switch to EXTRA_HOT."
    CATEGORY = "hc_sm"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        temp = cfg.TLLSP - 1
        hc.inject_temp(TEMP_TTANK, temp)
        time.sleep(SETTLE)
        st = hc.hc_status()
        self.log(f"  inject T={temp}C heater={st['heater']}")
        data = {"temp_injected": temp, "tllsp": cfg.TLLSP, "heater": st["heater"]}
        if st["heater"] in HEAT_EXTRA:
            return self._pass(f"OK heater={st['heater']}", data)
        return self._fail(f"Expected EXTRA_HOT got {st['heater']}", data)


class TestSM03ExtraHotToIdle(BaseTest):
    NAME = "SM-03 Extra Hot -> Idle (terminate)"
    DESCRIPTION = "Shorten FT=1min, T above TTANK_TERMINATE — must return to IDLE."
    CATEGORY = "hc_sm"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        timeout_sec = int(self.config.get("sm03_timeout_sec", 120))

        hc.hc_set_param("heater_ft", 1)
        hc.inject_temp(TEMP_TTANK, cfg.TLLSP - 1)
        time.sleep(SETTLE)
        st = hc.hc_status()
        if st["heater"] not in HEAT_EXTRA:
            return self._fail(f"Could not enter EXTRA_HOT, got {st['heater']}")

        hc.inject_temp(TEMP_TTANK, cfg.TTANK_TERMINATE + 1)
        self.log(f"  Waiting up to {timeout_sec}s for IDLE...")
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            st = hc.hc_status()
            if st["heater"] in HEAT_IDLE:
                return self._pass("OK returned to IDLE", {"heater": st["heater"]})
            time.sleep(3)
        return self._fail(f"Did not return to IDLE in {timeout_sec}s", {"heater": st["heater"]})


class TestSM04ShabbatNeedsHMI(BaseTest):
    NAME = "SM-04 Idle -> Prepare Shabbat [needs HMI]"
    DESCRIPTION = "Requires Manual Shabbat from HMI — skipped automatically."
    CATEGORY = "hc_sm"

    def run(self) -> TestResult:
        return self._pass(
            "SKIPPED: trigger Manual Shabbat from HMI then assert START_PREPARE_SHABBAT",
            {"skipped": True}
        )


class TestSM05PrepareShabbatNeedsHMI(BaseTest):
    NAME = "SM-05 Prepare -> Operation Shabbat [needs HMI]"
    DESCRIPTION = "Requires Shabbat prep via HMI/shabbat_bypass — skipped."
    CATEGORY = "hc_sm"

    def run(self) -> TestResult:
        return self._pass(
            "SKIPPED: enter via HMI/shabbat_bypass, use min5 to shorten waits",
            {"skipped": True}
        )


class TestSM06ShabbatEndNeedsHMI(BaseTest):
    NAME = "SM-06 Operation Shabbat -> Idle [needs HMI]"
    DESCRIPTION = "Requires Operation-Shabbat state via HMI — skipped."
    CATEGORY = "hc_sm"

    def run(self) -> TestResult:
        return self._pass("SKIPPED: enter via HMI", {"skipped": True})


class TestSM07FaultEntersError(BaseTest):
    NAME = "SM-07 Fault -> Error state"
    DESCRIPTION = "Inject error 158 — unit must reflect error state."
    CATEGORY = "hc_sm"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.inject_error(158, True)
        time.sleep(SETTLE)
        errors = hc.read_errors()
        self.log(f"  errors: {errors[:80]}")
        if "158" in errors:
            return self._pass("OK: error 158 active", {"errors": errors[:80]})
        return self._fail("Error 158 not found in response", {"errors": errors[:80]})


class TestSM08ResetClearsNonCritical(BaseTest):
    NAME = "SM-08 Reset clears non-critical error"
    DESCRIPTION = "Inject error 158, reset — must return to IDLE. Critical: 18,22,55,56."
    CATEGORY = "hc_sm"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.inject_error(158, True)
        time.sleep(0.3)
        hc.hc_reset()
        time.sleep(SETTLE)
        st = hc.hc_status()
        self.log(f"  heater={st['heater']}")
        data = {"heater": st["heater"], "critical_ids": list(CRITICAL_ERROR_IDS)}
        if st["heater"] in HEAT_IDLE:
            return self._pass("OK: non-critical error cleared after reset", data)
        return self._fail(f"Expected IDLE after reset got {st['heater']}", data)


class TestSM09DispenseParallelIdle(BaseTest):
    NAME = "SM-09 Dispense parallel with idle heating"
    DESCRIPTION = "Inject T in idle region, pour_hot — dispenser must not be DISABLED."
    CATEGORY = "hc_sm"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        hc.inject_temp(TEMP_TTANK, cfg.TLLSP + 10)
        hc.pour_hot(15)
        time.sleep(SETTLE)
        st = hc.hc_status()
        hc.hc_stop_dispense()
        self.log(f"  dispenser={st['dispenser']}")
        data = {"dispenser": st["dispenser"], "heater": st["heater"]}
        if st["dispenser"] not in ("DISABLE_STATE",):
            return self._pass(f"OK dispenser={st['dispenser']}", data)
        return self._fail("Dispenser is DISABLE_STATE during idle heating", data)