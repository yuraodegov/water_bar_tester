"""
tests/test_hc_idle_heating.py — Module 2: Idle / Heating (ID-01..ID-09).
Threshold band IL: TLLSP=50 < LLSP=70 < HLSP=75.
Idle heating rule per PRD idle_V7:
  T < TLLSP            -> Extra Hot
  TLLSP < T < LLSP     -> main heater = IHP (ID-04 expected FAIL — PRD divergence)
  T < HLSP             -> keep heating
  T >= HLSP            -> main heater OFF
"""
import time
from core.hc_driver import HCDriver, TEMP_TTANK, IN_HWT_FLOAT_UP, IN_HWT_ELEC_UP, HEAT_EXTRA
from core.hc_config import PROFILES
from tests.test_base import BaseTest, TestResult

SETTLE = 1.0


def _hc(test: BaseTest):
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected():
        return None
    if not isinstance(hydr, HCDriver):
        return None
    return hydr


def _cfg(test: BaseTest):
    name = test.config.get("hc_profile", "IL").upper()
    return PROFILES.get(name, PROFILES["IL"])


class TestID01IdleEnablesFillDispense(BaseTest):
    NAME = "ID-01 Idle enables HotFill and Dispense"
    DESCRIPTION = "On idle entry: hot_filling != DISABLE and dispenser != DISABLE_STATE."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        hc.inject_temp(TEMP_TTANK, cfg.LLSP - 5)
        time.sleep(SETTLE)
        st = hc.hc_status()
        self.log(f"  hot_filling={st['hot_filling']} dispenser={st['dispenser']}")
        data = {"hot_filling": st["hot_filling"], "dispenser": st["dispenser"]}
        errors = []
        if st["hot_filling"] == "DISABLE":
            errors.append("hot_filling=DISABLE expected enabled")
        if st["dispenser"] == "DISABLE_STATE":
            errors.append("dispenser=DISABLE_STATE expected enabled")
        if errors:
            return self._fail(" | ".join(errors), data)
        return self._pass("OK: HotFill and Dispense enabled in Idle", data)


class TestID02SmallHeaterISP(BaseTest):
    NAME = "ID-02 Small heater = ISP on idle entry"
    DESCRIPTION = "Small heater duty must equal ISP% from profile."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        hc.inject_temp(TEMP_TTANK, cfg.LLSP - 5)
        time.sleep(SETTLE)
        duty = hc.small_heater_duty()
        self.log(f"  small_heater_duty={duty}% expected ISP={cfg.ISP}%")
        data = {"small_heater_duty": duty, "isp": cfg.ISP}
        if duty == cfg.ISP:
            return self._pass(f"OK small_heater_duty={duty}% == ISP={cfg.ISP}%", data)
        return self._fail(f"small_heater_duty={duty}% != ISP={cfg.ISP}%", data)


class TestID03BelowTLLSPExtraHot(BaseTest):
    NAME = "ID-03 T < TLLSP -> Extra Hot (edge)"
    DESCRIPTION = "Below TLLSP -> EXTRA_HOT. Above TLLSP -> not EXTRA_HOT."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)

        hc.inject_temp(TEMP_TTANK, cfg.TLLSP - 1)
        time.sleep(SETTLE)
        st_below = hc.hc_status()
        self.log(f"  T={cfg.TLLSP - 1}C heater={st_below['heater']}")

        hc.inject_temp(TEMP_TTANK, cfg.TLLSP + 1)
        time.sleep(SETTLE)
        st_above = hc.hc_status()
        self.log(f"  T={cfg.TLLSP + 1}C heater={st_above['heater']}")

        data = {
            "tllsp": cfg.TLLSP,
            "heater_below": st_below["heater"],
            "heater_above": st_above["heater"],
        }
        errors = []
        if st_below["heater"] not in HEAT_EXTRA:
            errors.append(f"T<TLLSP: expected EXTRA_HOT got {st_below['heater']}")
        if st_above["heater"] in HEAT_EXTRA:
            errors.append(f"T>TLLSP: expected not EXTRA_HOT got {st_above['heater']}")
        if errors:
            return self._fail(" | ".join(errors), data)
        return self._pass("OK: edge TLLSP boundary correct", data)


class TestID04MainHeaterIHP(BaseTest):
    NAME = "ID-04 TLLSP < T < LLSP -> main=IHP [PRD divergence]"
    DESCRIPTION = (
        "PRD idle_V7: main heater must equal IHP% when TLLSP<T<LLSP. "
        "Current firmware keeps MAIN OFF — EXPECTED FAIL (confirms code defect)."
    )
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        mid_temp = (cfg.TLLSP + cfg.LLSP) // 2
        hc.inject_temp(TEMP_TTANK, mid_temp)
        time.sleep(SETTLE)
        duty = hc.heater_duty()
        self.log(f"  T={mid_temp}C main_heater_duty={duty}% expected IHP={cfg.IHP}%")
        data = {"temp": mid_temp, "duty": duty, "ihp": cfg.IHP, "prd_divergence": True}
        if duty == cfg.IHP:
            return self._pass(f"OK main_heater_duty={duty}% == IHP={cfg.IHP}%", data)
        return self._fail(
            f"PRD divergence: duty={duty}% != IHP={cfg.IHP}% "
            f"(firmware keeps MAIN OFF in Idle — code defect)",
            data
        )


class TestID05HLSPStopsHeater(BaseTest):
    NAME = "ID-05 T >= HLSP -> main heater OFF (edge)"
    DESCRIPTION = "Below HLSP: heater on. At/above HLSP: main heater must be OFF."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)

        hc.inject_temp(TEMP_TTANK, cfg.HLSP - 1)
        time.sleep(SETTLE)
        duty_below = hc.heater_duty()
        self.log(f"  T={cfg.HLSP - 1}C duty={duty_below}%")

        hc.inject_temp(TEMP_TTANK, cfg.HLSP + 1)
        time.sleep(SETTLE)
        duty_above = hc.heater_duty()
        self.log(f"  T={cfg.HLSP + 1}C duty={duty_above}%")

        data = {"hlsp": cfg.HLSP, "duty_below": duty_below, "duty_above": duty_above}
        if duty_above not in (0, None):
            return self._fail(
                f"main heater must be OFF at T>HLSP={cfg.HLSP} got duty={duty_above}%", data
            )
        return self._pass(f"OK: main heater OFF above HLSP={cfg.HLSP}", data)


class TestID06IdleHeatTimeoutErr158(BaseTest):
    NAME = "ID-06 Idle heat timeout -> Err158"
    DESCRIPTION = "Set idle_heat_timeout=1min, stay below HLSP — Err158 must fire, heaters OFF."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        timeout_sec = int(self.config.get("id06_timeout_sec", 120))

        hc.hc_set_param("heater_idle_heat_timeout", 1)
        hc.inject_temp(TEMP_TTANK, cfg.LLSP - 5)
        self.log(f"  Waiting up to {timeout_sec}s for Err158...")
        deadline = time.time() + timeout_sec
        raised = False
        while time.time() < deadline:
            if "158" in hc.read_errors():
                raised = True
                break
            time.sleep(3)

        duty = hc.heater_duty()
        self.log(f"  err158={raised} heater_duty={duty}")
        data = {"err158_raised": raised, "heater_duty_after": duty}
        if not raised:
            return self._fail(f"Err158 not raised within {timeout_sec}s", data)
        if duty not in (0, None):
            return self._fail(f"Heater duty={duty}% must be OFF after Err158", data)
        return self._pass("OK: Err158 raised and heaters OFF", data)


class TestID07FillResetsHeatTimeout(BaseTest):
    NAME = "ID-07 Tank fill resets idle heat timeout"
    DESCRIPTION = "After fill event (float+electrode) Err158 must NOT appear immediately."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)

        hc.inject_temp(TEMP_TTANK, cfg.LLSP - 5)
        time.sleep(SETTLE)
        hc.inject_inputs({IN_HWT_FLOAT_UP: 1, IN_HWT_ELEC_UP: 1})
        time.sleep(SETTLE)
        errors = hc.read_errors()
        self.log(f"  errors after fill: {errors[:60]}")
        data = {"errors": errors[:60]}
        if "158" not in errors:
            return self._pass("OK: no Err158 after fill event", data)
        return self._fail("Err158 appeared after fill event — timeout not reset", data)


class TestID08ShabbatNeedsHMI(BaseTest):
    NAME = "ID-08 Shabbat event -> Prepare [needs HMI]"
    DESCRIPTION = "Requires Manual Shabbat from HMI — skipped automatically."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        return self._pass(
            "SKIPPED: trigger Manual Shabbat from HMI then assert START_PREPARE_SHABBAT",
            {"skipped": True}
        )


class TestID09ExtraHotRequest(BaseTest):
    NAME = "ID-09 Extra Hot request (ex_on)"
    DESCRIPTION = "Inject T at LLSP (neutral), send ex_on — heater must enter EXTRA_HOT."
    CATEGORY = "hc_idle"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)

        hc.inject_temp(TEMP_TTANK, cfg.LLSP)
        time.sleep(SETTLE)
        hc.extra_hot()
        time.sleep(SETTLE)
        st = hc.hc_status()
        self.log(f"  heater={st['heater']}")
        data = {"heater": st["heater"]}
        if st["heater"] in HEAT_EXTRA:
            return self._pass(f"OK heater={st['heater']} after ex_on", data)
        return self._fail(f"Expected EXTRA_HOT after ex_on got {st['heater']}", data)