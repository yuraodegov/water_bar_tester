"""
tests/test_param_dependencies.py — parameter relationship tests.

Three kinds of test, generated from data tables so new entries are one line:

  TYPE 1  Dependency : change a "driver" param (BSP) and verify every
                       dependent param recomputes by its formula, then restore.
                       Per spec:  BSPS = BSP-2
                                  BTSP3 = LBSP = TTANK_TERMINATE = BSP-3
  TYPE 2  Cross-check: write a param on one side (HMI or HC) and read it back
                       on the other side; values must agree (with unit scaling,
                       e.g. HMI Core.BoilingTemp is milli-degC = HC bsp * 1000).
  TYPE 3  Round-trip : remember original, write a new value, read it back,
                       confirm, then ALWAYS restore the original (try/finally).

Writing changes EEPROM, so every test restores the original value in a
finally block. Test values are small offsets, never extremes.
"""
import time
from core.hc_driver import HCDriver
from tests.test_base import BaseTest, TestResult

SETTLE = 1.5

# ── TYPE 1: dependency formulas (driver -> {dependent: f(driver)}) ──
# All dependents of BSP, per the parameter spec.
BSP_DEPENDENTS = {
    "heater_bsps": lambda bsp: bsp - 2,
    "heater_btsp3": lambda bsp: bsp - 3,
    "heater_lbsp": lambda bsp: bsp - 3,
    "heater_ttank_terminate": lambda bsp: bsp - 3,
}

# ── TYPE 2: HMI <-> HC cross map ──
# hc_name : (hmi_id, hmi_name, scale)  where  HMI_value = HC_value * scale
CROSS_MAP = {
    "heater_bsp": (29, "Core.BoilingTemp", 1000),
}

# ── TYPE 3: round-trip set (hc params safe to nudge by a small delta) ──
ROUNDTRIP_PARAMS = {
    "heater_btsp2": 2,        # delta to add then restore
    "heater_cmt": 1,
    "heater_c_delay": 5,
    "cooler_fan_pwm": 5,
}


def _hc(test):
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected() or not isinstance(hydr, HCDriver):
        return None
    return hydr


# ══════════════════════════════════════════════════════════════════════
#  TYPE 1 — DEPENDENCY
# ══════════════════════════════════════════════════════════════════════
class TestDepBSPChain(BaseTest):
    NAME = "DEP-BSP dependent params recompute from BSP"
    DESCRIPTION = ("Set heater_bsp to a test value and verify BSPS=BSP-2, "
                   "BTSP3=LBSP=TTANK_TERMINATE=BSP-3, then restore BSP.")
    CATEGORY = "param_deps"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")

        original = hc.hc_get_param("heater_bsp")
        if original is None:
            return self._fail("cannot read heater_bsp")
        test_bsp = int(self.config.get("dep_test_bsp", original + 2))
        self.log(f"  original BSP={original}; setting BSP={test_bsp}")

        results = {}
        errors = []
        try:
            hc.hc_set_param("heater_bsp", test_bsp)
            time.sleep(SETTLE)
            got_bsp = hc.hc_get_param("heater_bsp")
            results["heater_bsp"] = got_bsp
            if got_bsp != test_bsp:
                errors.append(f"BSP not applied: set {test_bsp}, read {got_bsp}")

            for dep, formula in BSP_DEPENDENTS.items():
                expected = formula(test_bsp)
                actual = hc.hc_get_param(dep)
                results[dep] = {"expected": expected, "actual": actual}
                mark = "OK" if actual == expected else "MISMATCH"
                self.log(f"    {dep}: expected={expected} actual={actual} [{mark}]")
                if actual != expected:
                    errors.append(f"{dep}={actual} != BSP-formula={expected}")
        finally:
            hc.hc_set_param("heater_bsp", original)
            time.sleep(SETTLE)
            restored = hc.hc_get_param("heater_bsp")
            self.log(f"  restored BSP -> {restored} (was {original})")
            results["restored_bsp"] = restored

        if errors:
            return self._fail(" | ".join(errors), results)
        return self._pass(
            f"OK all BSP dependents recompute correctly (BSP test={test_bsp})",
            results)


# ══════════════════════════════════════════════════════════════════════
#  TYPE 2 — CROSS-CHECK HMI <-> HC
# ══════════════════════════════════════════════════════════════════════
def _make_cross(hc_name, hmi_id, hmi_name, scale):
    class _Cross(BaseTest):
        NAME = f"XCHK {hc_name} <-> HMI[{hmi_id}] {hmi_name}"
        DESCRIPTION = (f"Write {hc_name} on HC, read HMI[{hmi_id}] "
                       f"(scale x{scale}); values must agree both ways.")
        CATEGORY = "param_cross"
        HC_NAME, HMI_ID, HMI_NAME, SCALE = hc_name, hmi_id, hmi_name, scale

        def run(self) -> TestResult:
            err = self._require_hydraulic()
            if err:
                return err
            hc = _hc(self)
            if not hc:
                return self._fail("HCDriver required")
            if self.hmi is None or not self.hmi.is_connected():
                return self._fail("HMI required for cross-check")

            hc_orig = hc.hc_get_param(self.HC_NAME)
            hmi_orig = self.hmi.get_param_value(self.HMI_ID)
            data = {"hc_name": self.HC_NAME, "hmi_id": self.HMI_ID,
                    "hc_orig": hc_orig, "hmi_orig": hmi_orig, "scale": self.SCALE}
            errors = []
            try:
                # 1) consistency as-is
                if hc_orig is not None and hmi_orig is not None:
                    if hmi_orig != hc_orig * self.SCALE:
                        errors.append(
                            f"initial mismatch: HC={hc_orig} HMI={hmi_orig} "
                            f"(expected HMI={hc_orig * self.SCALE})")
                # 2) write on HC, read on HMI
                test_hc = hc_orig + 1
                hc.hc_set_param(self.HC_NAME, test_hc)
                time.sleep(SETTLE)
                hmi_after = self.hmi.get_param_value(self.HMI_ID)
                self.log(f"  HC set {self.HC_NAME}={test_hc} -> "
                         f"HMI[{self.HMI_ID}]={hmi_after} "
                         f"(expected {test_hc * self.SCALE})")
                data["hmi_after_hc_write"] = hmi_after
                if hmi_after != test_hc * self.SCALE:
                    errors.append(
                        f"after HC write: HMI={hmi_after} != "
                        f"{test_hc * self.SCALE}")
            finally:
                if hc_orig is not None:
                    hc.hc_set_param(self.HC_NAME, hc_orig)
                    time.sleep(SETTLE)
                    data["hc_restored"] = hc.hc_get_param(self.HC_NAME)

            if errors:
                return self._fail(" | ".join(errors), data)
            return self._pass(f"OK HC<->HMI consistent for {self.HC_NAME}", data)

    _Cross.__name__ = f"TestCross_{hc_name}"
    _Cross.__qualname__ = _Cross.__name__
    return _Cross


# ══════════════════════════════════════════════════════════════════════
#  TYPE 3 — ROUND-TRIP
# ══════════════════════════════════════════════════════════════════════
def _make_roundtrip(param_name, delta):
    class _RT(BaseTest):
        NAME = f"RT {param_name} write/read/restore"
        DESCRIPTION = (f"Write {param_name}=orig+{delta}, read back, "
                       "then restore original.")
        CATEGORY = "param_roundtrip"
        PARAM, DELTA = param_name, delta

        def run(self) -> TestResult:
            err = self._require_hydraulic()
            if err:
                return err
            hc = _hc(self)
            if not hc:
                return self._fail("HCDriver required")

            original = hc.hc_get_param(self.PARAM)
            if original is None:
                return self._fail(f"cannot read {self.PARAM}")
            test_val = original + self.DELTA
            data = {"param": self.PARAM, "original": original,
                    "test_val": test_val}
            errors = []
            try:
                hc.hc_set_param(self.PARAM, test_val)
                time.sleep(SETTLE)
                readback = hc.hc_get_param(self.PARAM)
                data["readback"] = readback
                self.log(f"  {self.PARAM}: set {test_val} read {readback}")
                if readback != test_val:
                    errors.append(f"readback {readback} != set {test_val}")
            finally:
                hc.hc_set_param(self.PARAM, original)
                time.sleep(SETTLE)
                restored = hc.hc_get_param(self.PARAM)
                data["restored"] = restored
                self.log(f"  restored {self.PARAM} -> {restored} (was {original})")
                if restored != original:
                    errors.append(f"NOT restored: {restored} != {original}")

            if errors:
                return self._fail(" | ".join(errors), data)
            return self._pass(f"OK {self.PARAM} round-trip + restored", data)

    _RT.__name__ = f"TestRT_{param_name}"
    _RT.__qualname__ = _RT.__name__
    return _RT


# ── generate cross-check and round-trip classes ──
for _hcn, (_id, _hn, _sc) in CROSS_MAP.items():
    globals()[f"TestCross_{_hcn}"] = _make_cross(_hcn, _id, _hn, _sc)
del _hcn, _id, _hn, _sc

for _p, _d in ROUNDTRIP_PARAMS.items():
    globals()[f"TestRT_{_p}"] = _make_roundtrip(_p, _d)
del _p, _d