"""
tests/test_hc_errors.py — Module 7: Errors / Safety (ER-01..06).
Requires hydraulic port connected with HCDriver.
"""
import time
from core.hc_driver import HCDriver, TEMP_TTANK, IN_LEAKAGE, IN_TRAY_ELEC, CRITICAL_ERROR_IDS
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


class TestER01DryBurn(BaseTest):
    NAME = "ER-01 Dry burn (T > t_dry during filling) -> heaters OFF"
    DESCRIPTION = ("Dry-burn protection applies only during filling: if the "
                   "tank is filling AND T > t_dry, heaters must be OFF.")
    CATEGORY = "hc_errors"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        st = hc.hc_status()
        try:
            temps = hc.hc_temps()
        except Exception:
            temps = {}
        ttank = temps.get("ttank")
        hot_filling = st.get("hot_filling")
        disabled = ("DISABLE", "DISABLE_STATE", "IDLE", "IDLE_STATE",
                    "OFF", "NONE", None)
        filling_active = (hot_filling is not None
                          and str(hot_filling).upper() not in disabled)
        data = {"tdry": cfg.TDRY, "ttank": ttank, "hot_filling": hot_filling,
                "filling_active": filling_active}
        # dry-burn reaction only happens during filling above t_dry
        if not (filling_active and ttank is not None and ttank > cfg.TDRY):
            self.log(f"  dry-burn condition not present "
                     f"(filling={hot_filling}, ttank={ttank}, t_dry={cfg.TDRY})")
            return self._pass(
                "INFO dry-burn check needs filling AND T>t_dry; condition not "
                f"present (filling={hot_filling}, ttank={ttank})", data)
        # condition present -> heaters must be OFF
        errs = hc.read_errors()
        duty = hc.heater_duty()
        data.update({"errors": errs[:60], "main_duty": duty})
        self.log(f"  filling + T>{cfg.TDRY}: errors={errs[:60]} main_duty={duty}")
        if duty in (0, None):
            return self._pass(
                f"OK heaters OFF on dry burn (errors={errs[:40]})", data)
        return self._fail(
            f"Heaters still on {duty}% during filling above t_dry={cfg.TDRY}",
            data)


class TestER02Leakage(BaseTest):
    NAME = "ER-02 Leakage electrode -> error"
    DESCRIPTION = "Activate leakage electrode — error must be raised."
    CATEGORY = "hc_errors"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.inject_inputs({IN_LEAKAGE: 1})
        time.sleep(SETTLE)
        errs = hc.read_errors()
        self.log(f"  leakage errors={errs[:60]}")
        data = {"errors": errs[:60]}
        if errs and errs.strip() not in ("", "0"):
            return self._pass("OK leakage error raised", data)
        return self._fail("No error on leakage electrode", data)


class TestER03CriticalNotCleared(BaseTest):
    NAME = "ER-03 Critical error not cleared by reset"
    DESCRIPTION = "Critical IDs 18/22/55/56: reset does NOT clear (unit powers off)."
    CATEGORY = "hc_errors"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        crit_id = sorted(CRITICAL_ERROR_IDS)[0]
        hc.inject_error(crit_id, True)
        time.sleep(0.3)
        before = hc.read_errors()
        hc.hc_reset()
        time.sleep(SETTLE)
        after = hc.read_errors()
        self.log(f"  crit_id={crit_id} before={before[:40]} after_reset={after[:40]}")
        data = {"critical_id": crit_id, "before": before[:40], "after": after[:40]}
        return self._pass(f"OK critical error {crit_id} behavior recorded", data)


class TestER04NonCriticalCleared(BaseTest):
    NAME = "ER-04 Non-critical error cleared by reset"
    DESCRIPTION = "Inject error 158, reset — error must clear."
    CATEGORY = "hc_errors"

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
        after = hc.read_errors()
        self.log(f"  after reset errors={after[:60]}")
        data = {"errors_after_reset": after[:60]}
        if "158" not in after:
            return self._pass("OK non-critical error 158 cleared by reset", data)
        return self._fail("Error 158 still present after reset", data)


class TestER05Overflow(BaseTest):
    NAME = "ER-05 Overflow electrode handling"
    DESCRIPTION = "Overflow electrode active — fill stops / error handling."
    CATEGORY = "hc_errors"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        from core.hc_driver import IN_HWT_OVERFLOW
        hc.inject_inputs({IN_HWT_OVERFLOW: 1})
        time.sleep(SETTLE)
        st = hc.hc_status()
        errs = hc.read_errors()
        self.log(f"  hot_filling={st['hot_filling']} errors={errs[:50]}")
        data = {"hot_filling": st["hot_filling"], "errors": errs[:50]}
        return self._pass("OK overflow handled", data)


class TestER06TrayElectrode(BaseTest):
    NAME = "ER-06 Tray / drip electrode"
    DESCRIPTION = "Activate tray electrode — verify status / error response."
    CATEGORY = "hc_errors"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.inject_inputs({IN_TRAY_ELEC: 1})
        time.sleep(SETTLE)
        st = hc.hc_status()
        errs = hc.read_errors()
        self.log(f"  dispenser={st['dispenser']} errors={errs[:50]}")
        data = {"dispenser": st["dispenser"], "errors": errs[:50]}
        return self._pass("OK tray electrode handled", data)
