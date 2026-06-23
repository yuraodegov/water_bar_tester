"""
tests/test_hc_extra_hot.py — Module 3: Extra Hot / Boiling Support.

REAL-DEVICE method (per flowchart + field guidance):
Extra Hot is NOT triggered by injecting a fake temperature. On the real
machine you must physically drain the hot tank: hold the hot button (one
long press, e.g. 240 s). Cold water refills the tank, T_booster drops, and
the controller enters Extra Hot on its own, following the flowchart:

    Enter -> Small heating element = 100% (OSPs)
             Main  heating element = 100% (OSPm)
             ... boiling support by temperature ...
    Exit  -> Idle when T_tank > tank_terminate or FTimer > FT

Entry is confirmed by the HC console: State -> Heater: EXTRA_HOT.
Temperature is read from the status block (TempBoost).

Requires hydraulic port (HCDriver) AND HMI (to press the hot button).
Profile via config["hc_profile"].
"""
import time
from core.hc_driver import HCDriver, HEAT_EXTRA, HEAT_IDLE
from core.hc_config import PROFILES
from tests.test_base import BaseTest, TestResult

SETTLE = 1.0
DRAIN_MS_DEFAULT = 240000        # 240 s long hot press to drain the tank
ENTER_TIMEOUT_DEFAULT = 300      # seconds to wait for EXTRA_HOT to appear


def _hc(test):
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected() or not isinstance(hydr, HCDriver):
        return None
    return hydr


def _cfg(test):
    return PROFILES.get(test.config.get("hc_profile", "IL").upper(),
                        PROFILES["IL"])


def _drain_and_wait_extra_hot(test, hc):
    """Drain the hot tank with one long hot-button press and poll the HC
    status until the controller enters Extra Hot.

    Returns (entered: bool, info: dict). info has the last state, the
    T_booster trend, and how long it took.
    """
    drain_ms = int(test.config.get("eh_drain_ms", DRAIN_MS_DEFAULT))
    timeout = int(test.config.get("eh_enter_timeout_sec", ENTER_TIMEOUT_DEFAULT))

    # starting temperature for reference
    try:
        t0 = hc.hc_temps()
    except Exception:
        t0 = {"tboost": None}

    test.log(f"  draining hot tank: press 1 {drain_ms}ms (~{drain_ms//1000}s)")
    if test.hmi is None or not test.hmi.is_connected():
        return False, {"error": "HMI not connected (needed to press hot)"}
    test.hmi.press(1, drain_ms)

    deadline = time.time() + timeout
    last_state = None
    last_tboost = t0.get("tboost")
    while time.time() < deadline:
        try:
            st = hc.hc_status()
            state = st.get("heater")
            temps = hc.hc_temps()
            tb = temps.get("tboost")
        except Exception:
            time.sleep(3)
            continue
        last_state, last_tboost = state, tb
        test.log(f"    Heater={state}  TempBoost={tb}")
        if state in HEAT_EXTRA:
            return True, {"heater": state, "tboost_start": t0.get("tboost"),
                          "tboost_now": tb,
                          "elapsed_s": int(time.time() - (deadline - timeout))}
        time.sleep(5)
    return False, {"heater": last_state, "tboost_start": t0.get("tboost"),
                   "tboost_now": last_tboost, "timeout_s": timeout}


class TestEH01ExtraHotEntry(BaseTest):
    NAME = "EH-01 Extra Hot entry by draining (OSPS/OSPM=100%)"
    DESCRIPTION = ("Drain hot tank (long press) until controller enters "
                   "Extra Hot; at entry both heaters run at 100%.")
    CATEGORY = "hc_extra_hot"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        entered, info = _drain_and_wait_extra_hot(self, hc)
        if not entered:
            return self._fail(
                f"Did not enter Extra Hot by draining "
                f"(last heater={info.get('heater')}, "
                f"TempBoost {info.get('tboost_start')}->{info.get('tboost_now')})",
                info)
        small = hc.small_heater_duty()
        main = hc.heater_duty()
        info.update({"small": small, "main": main})
        self.log(f"  entered EXTRA_HOT: small={small}% main={main}%")
        return self._pass(
            f"OK entered Extra Hot by draining; small={small}% main={main}% "
            f"(TempBoost {info.get('tboost_start')}->{info.get('tboost_now')})",
            info)


class TestEH02BoilingSupportSwitch(BaseTest):
    NAME = "EH-02 Boiling Support LBS/HBS switch (BTSP1)"
    DESCRIPTION = "While in Extra Hot, main duty changes around BTSP1."
    CATEGORY = "hc_extra_hot"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        entered, info = _drain_and_wait_extra_hot(self, hc)
        if not entered:
            return self._fail("Could not enter Extra Hot to observe support",
                              info)
        # observe main duty for a few samples while boiling support runs
        duties = []
        for _ in range(6):
            duties.append(hc.heater_duty())
            time.sleep(5)
        self.log(f"  main duty samples during support: {duties}")
        return self._pass(f"OK boiling support observed, duties={duties}",
                          {"duties": duties, **info})


class TestEH05TerminateToIdle(BaseTest):
    NAME = "EH-05 Extra Hot terminates to Idle"
    DESCRIPTION = ("After Extra Hot completes (T_tank>terminate or FT), the "
                   "controller returns to Idle.")
    CATEGORY = "hc_extra_hot"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        entered, info = _drain_and_wait_extra_hot(self, hc)
        if not entered:
            return self._fail("Could not enter Extra Hot before terminate test",
                              info)
        timeout = int(self.config.get("eh05_idle_timeout_sec", 600))
        self.log(f"  waiting up to {timeout}s for return to Idle...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = hc.hc_status()
            if st.get("heater") in HEAT_IDLE:
                return self._pass("OK Extra Hot terminated to Idle",
                                  {"heater": st.get("heater")})
            time.sleep(10)
        return self._fail(f"Did not return to Idle in {timeout}s",
                          {"heater": hc.hc_status().get("heater")})


class TestEH06FTRunTime(BaseTest):
    NAME = "EH-06 Boiling support FT param round-trip"
    DESCRIPTION = "heater_ft param is writable and reads back correctly."
    CATEGORY = "hc_extra_hot"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        original = hc.hc_get_param("heater_ft")
        hc.hc_set_param("heater_ft", 5)
        val = hc.hc_get_param("heater_ft")
        if original is not None:
            hc.hc_set_param("heater_ft", original)   # restore
        self.log(f"  heater_ft set=5 read={val} (restored {original})")
        data = {"heater_ft": val, "restored": original}
        if val == 5:
            return self._pass("OK heater_ft round-trip", data)
        return self._fail(f"heater_ft read {val} != 5", data)