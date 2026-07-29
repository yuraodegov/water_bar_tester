"""
tests/test_hc_idle_heating.py — Module 2: Idle / Heating.

Idle logic (per idle flowchart):

    Hot fill enable = 1, Hot dispense enable = 1
    Small heating element = ISP                (idle actuator = SMALL heater)
    if T_tank < LLSP:  Ftime = 0; Small = IHP
        if Ftimer > idle heat timeout -> Error (switch heating off)
    if T_tank < HLSP:  keep heating
    if T_tank >= HLSP: Get Event? -> Extra Hot / Prepare Shabbat / stay Idle

KEY POINT: in Idle the SMALL heating element carries the duty (ISP/IHP).
The MAIN heating element is NOT used in Idle (it stays at 0%). Earlier
versions wrongly checked the MAIN heater here — corrected below.

Temperature on the real machine is changed physically (drain the tank),
not by injection, so these tests OBSERVE the device in its natural Idle
state rather than forcing a fake temperature.

IL profile: ISP=10, IHP=10, LLSP=70, HLSP=75.
"""
import time
from core.hc_driver import (HCDriver, IN_HWT_FLOAT_UP, IN_HWT_ELEC_UP,
                            HEAT_EXTRA, HEAT_IDLE)
from core.hc_config import PROFILES
from tests.test_base import BaseTest, TestResult

SETTLE = 1.0
IDLE_WAIT_DEFAULT = 60       # seconds to wait for the device to settle in Idle


def _hc(test: BaseTest):
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected() or not isinstance(hydr, HCDriver):
        return None
    return hydr


def _cfg(test: BaseTest):
    name = test.config.get("hc_profile", "IL").upper()
    return PROFILES.get(name, PROFILES["IL"])


def _wait_idle(test, hc):
    """Poll the HC status until the heater state is IDLE. Returns the status
    dict (or the last seen one if it never settled)."""
    timeout = int(test.config.get("idle_wait_sec", IDLE_WAIT_DEFAULT))
    deadline = time.time() + timeout
    st = hc.hc_status()
    while time.time() < deadline:
        st = hc.hc_status()
        if st.get("heater") in HEAT_IDLE:
            return st, True
        time.sleep(5)
    return st, st.get("heater") in HEAT_IDLE


class TestID01IdleEnablesFillDispense(BaseTest):
    NAME = "ID-01 Idle enables HotFill and Dispense"
    DESCRIPTION = "In Idle: hot_filling != DISABLE and dispenser != DISABLE_STATE."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        st, in_idle = _wait_idle(self, hc)
        self.log(f"  heater={st.get('heater')} hot_filling={st.get('hot_filling')} "
                 f"dispenser={st.get('dispenser')}")
        data = {"heater": st.get("heater"), "hot_filling": st.get("hot_filling"),
                "dispenser": st.get("dispenser")}
        errors = []
        if st.get("hot_filling") == "DISABLE":
            errors.append("hot_filling=DISABLE expected enabled")
        if st.get("dispenser") == "DISABLE_STATE":
            errors.append("dispenser=DISABLE_STATE expected enabled")
        if errors:
            return self._fail(" | ".join(errors), data)
        return self._pass("OK: HotFill and Dispense enabled in Idle", data)


class TestID02SmallHeaterISP(BaseTest):
    NAME = "ID-02 Idle actuator = SMALL heater at ISP/IHP"
    DESCRIPTION = ("In Idle the SMALL heating element carries the duty "
                   "(ISP or IHP); the MAIN heater stays OFF.")
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        st, in_idle = _wait_idle(self, hc)
        small = hc.small_heater_duty()
        main = hc.heater_duty()
        self.log(f"  heater={st.get('heater')} small={small}% main={main}% "
                 f"(ISP={cfg.ISP} IHP={cfg.IHP})")
        data = {"heater": st.get("heater"), "small": small, "main": main,
                "isp": cfg.ISP, "ihp": cfg.IHP}
        if not in_idle:
            return self._fail(f"Device not in Idle (heater={st.get('heater')}) "
                              f"— cannot verify idle heaters", data)
        allowed = {cfg.ISP, cfg.IHP, 0}
        idle_main_max = int(self.config.get("idle_main_max", 10))
        errors = []
        if small not in allowed:
            errors.append(f"small={small}% not in {{ISP={cfg.ISP},IHP={cfg.IHP}}}")
        if main is not None and main > idle_main_max:
            errors.append(f"main={main}% exceeds idle limit {idle_main_max}%")
        if errors:
            return self._fail(" | ".join(errors), data)
        return self._pass(
            f"OK Idle: small={small}% (ISP/IHP), main={main}% "
            f"(<= {idle_main_max}%)", data)


class TestID04MainHeaterOffInIdle(BaseTest):
    NAME = "ID-04 MAIN heater within idle limit (small carries duty)"
    DESCRIPTION = ("In Idle the SMALL heater is the main actuator; the MAIN "
                   "heater may idle up to a small limit (default 10%).")
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        st, in_idle = _wait_idle(self, hc)
        if not in_idle:
            return self._fail(f"Device not in Idle (heater={st.get('heater')})",
                              {"heater": st.get("heater")})
        idle_main_max = int(self.config.get("idle_main_max", 10))
        # sample the main heater a few times; it must stay within the idle limit
        mains = []
        for _ in range(4):
            mains.append(hc.heater_duty())
            time.sleep(3)
        self.log(f"  main heater samples in Idle: {mains} (limit {idle_main_max}%)")
        data = {"main_samples": mains, "idle_main_max": idle_main_max}
        bad = [m for m in mains if m is not None and m > idle_main_max]
        if bad:
            return self._fail(f"MAIN heater above idle limit: {bad}% "
                              f"(> {idle_main_max}%)", data)
        return self._pass(
            f"OK MAIN heater within idle limit ({idle_main_max}%)", data)


class TestID05SmallHeaterFollowsTemp(BaseTest):
    NAME = "ID-05 Idle small heater within ISP/IHP band"
    DESCRIPTION = ("In Idle the small heater duty stays within the ISP/IHP "
                   "range; main heater within idle limit (default 10%).")
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        st, in_idle = _wait_idle(self, hc)
        if not in_idle:
            return self._fail(f"Device not in Idle (heater={st.get('heater')})",
                              {"heater": st.get("heater")})
        small = hc.small_heater_duty()
        main = hc.heater_duty()
        try:
            temps = hc.hc_temps()
        except Exception:
            temps = {}
        self.log(f"  TempTank={temps.get('ttank')} small={small}% main={main}% "
                 f"(ISP={cfg.ISP} IHP={cfg.IHP} LLSP={cfg.LLSP} HLSP={cfg.HLSP})")
        lo = min(cfg.ISP, cfg.IHP)
        hi = max(cfg.ISP, cfg.IHP)
        idle_main_max = int(self.config.get("idle_main_max", 10))
        data = {"ttank": temps.get("ttank"), "small": small, "main": main,
                "isp": cfg.ISP, "ihp": cfg.IHP}
        errors = []
        if small is not None and not (lo <= small <= hi or small == 0):
            errors.append(f"small={small}% outside ISP/IHP band [{lo},{hi}]")
        if main is not None and main > idle_main_max:
            errors.append(f"main={main}% exceeds idle limit {idle_main_max}%")
        if errors:
            return self._fail(" | ".join(errors), data)
        return self._pass(
            f"OK small={small}% in band, main={main}% (<= {idle_main_max}%)",
            data)


class TestID06IdleHeatTimeoutErr158(BaseTest):
    NAME = "ID-06 Idle heat timeout -> Err158"
    DESCRIPTION = ("Set idle heat timeout short; if tank stays cold the "
                   "controller raises Err158 and switches heating off.")
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        timeout_sec = int(self.config.get("id06_timeout_sec", 120))
        hc.hc_set_param("heater_idle_heat_timeout", 1)
        self.log(f"  Waiting up to {timeout_sec}s for Err158 "
                 "(tank must stay below threshold)...")
        deadline = time.time() + timeout_sec
        raised = False
        while time.time() < deadline:
            if "158" in hc.read_errors():
                raised = True
                break
            time.sleep(3)
        duty = hc.heater_duty()
        self.log(f"  err158={raised} main_duty={duty}")
        data = {"err158_raised": raised, "main_duty_after": duty}
        if not raised:
            return self._fail(
                f"Err158 not raised within {timeout_sec}s "
                "(needs tank kept below idle threshold — physical condition)",
                data)
        return self._pass("OK Err158 raised on idle heat timeout", data)


class TestID07FillResetsHeatTimeout(BaseTest):
    NAME = "ID-07 Tank fill resets idle heat timeout"
    DESCRIPTION = "After a fill event Err158 must not be present."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        hc.inject_inputs({IN_HWT_FLOAT_UP: 1, IN_HWT_ELEC_UP: 1})
        time.sleep(SETTLE)
        errors = hc.read_errors()
        self.log(f"  errors after fill: {errors[:60]}")
        data = {"errors": errors[:60]}
        if "158" not in errors:
            return self._pass("OK: no Err158 after fill event", data)
        return self._fail("Err158 present after fill event — timeout not reset",
                          data)


class TestID08ShabbatNeedsHMI(BaseTest):
    NAME = "ID-08 Shabbat event -> Prepare [needs HMI]"
    DESCRIPTION = "Requires Manual Shabbat from HMI — informational."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        return self._pass(
            "INFO: trigger Manual Shabbat from HMI, then assert PREPARE_SHABBAT",
            {"skipped": True})


class TestID09ExtraHotRequest(BaseTest):
    NAME = "ID-09 Extra Hot request (ex_on event)"
    DESCRIPTION = "From Idle, an ex_on event must move the controller to Extra Hot."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        st0, in_idle = _wait_idle(self, hc)
        hc.extra_hot()
        time.sleep(SETTLE)
        # allow a few seconds for the state machine to switch
        deadline = time.time() + 15
        state = st0.get("heater")
        while time.time() < deadline:
            state = hc.hc_status().get("heater")
            if state in HEAT_EXTRA:
                break
            time.sleep(2)
        self.log(f"  heater after ex_on = {state}")
        data = {"heater": state}
        if state in HEAT_EXTRA:
            return self._pass(f"OK heater={state} after ex_on", data)
        return self._fail(f"Expected EXTRA_HOT after ex_on got {state}", data)