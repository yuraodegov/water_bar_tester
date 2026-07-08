"""
tests/test_hc_params_check.py — per-parameter HC eeprom check.

Each HC parameter is its own test: it reads the value from the device
'get_param' dump and checks it equals the expected baseline (exact match).
Baselines are kept in the dicts below so they are easy to edit when a
default changes.

Profile is taken from config['hc_profile'] ('IL' or 'US').
The test classes are generated automatically from the IL_DEFAULTS keys,
so to add/remove a parameter just edit the baseline dicts.
"""
from core.hc_driver import HCDriver
from tests.test_base import BaseTest, TestResult

# ── BASELINES (edit these when a default changes) ─────────────────────────────
# IL-220 defaults, captured from a real 'get_param' dump.
IL_DEFAULTS = {
    "heater_osps": 100,
    "heater_ospm": 100,
    "heater_lbs": 50,
    "heater_hbs": 70,
    "heater_hdisp": 70,
    "heater_lbsp": 93,
    "heater_isp": 10,
    "heater_hsp": 50,
    "heater_sihp": 10,
    "heater_bsp": 96,
    "heater_hlsp": 75,
    "heater_llsp": 65,
    "heater_btsp0": 80,
    "heater_ttank_terminate": 90,
    "heater_ft": 10,
    "heater_btsp1": 80,
    "heater_eh_t_o": 60,
    "heater_btsp2": 85,
    "heater_btsp3": 93,
    "heater_c_delay": 20,
    "heater_cmt": 5,
    "heater_sdev_max": 500,
    "heater_hot_fill_timeout": 200,
    "heater_time_level": 5,
    "heater_time_overfill": 5,
    "heater_idle_heat_timeout": 200,
    "heater_shp": 60,
    "heater_t_dry": 105,
    "heater_bsps": 94,
    "heater_spmh1": 50,
    "heater_spmh2": 20,
    "heater_spmh3": 10,
    "heater_b_offset": 3,
    "heater_fts": 140,
    "heater_shabbat_timeout": 50,
    "heater_calibration": 0,
    "valves_pwm_freq": 500,
    "valves_pwm_pcnt": 50,
    "cooler_setpoint_off": 6,
    "cooler_setpoint_on": 11,
    "cooler_shabbat_setpoint": 6,
    "cooler_shabbat_period": 36000,
    "cooler_shabbat_timeout": 80,
    "cooler_fan_pwm": 80,
    "printParam": 0,
    "shabbat_bypass": 0,
}

# US-115 defaults, captured from a real 'get_param' dump.
# Differs from IL on the heater duty/setpoint params and shabbat timeout.
US_DEFAULTS = {
    "heater_osps": 100,
    "heater_ospm": 100,
    "heater_lbs": 90,
    "heater_hbs": 100,
    "heater_hdisp": 100,
    "heater_lbsp": 93,
    "heater_isp": 50,
    "heater_hsp": 50,
    "heater_sihp": 20,
    "heater_bsp": 96,
    "heater_hlsp": 80,
    "heater_llsp": 75,
    "heater_btsp0": 80,
    "heater_ttank_terminate": 90,
    "heater_ft": 10,
    "heater_btsp1": 80,
    "heater_eh_t_o": 120,
    "heater_btsp2": 85,
    "heater_btsp3": 93,
    "heater_c_delay": 20,
    "heater_cmt": 5,
    "heater_sdev_max": 500,
    "heater_hot_fill_timeout": 200,
    "heater_time_level": 5,
    "heater_time_overfill": 5,
    "heater_idle_heat_timeout": 200,
    "heater_shp": 60,
    "heater_t_dry": 105,
    "heater_bsps": 94,
    "heater_spmh1": 100,
    "heater_spmh2": 100,
    "heater_spmh3": 100,
    "heater_b_offset": 3,
    "heater_fts": 140,
    "heater_shabbat_timeout": 50,
    "heater_calibration": 0,
    "valves_pwm_freq": 500,
    "valves_pwm_pcnt": 50,
    "cooler_setpoint_off": 6,
    "cooler_setpoint_on": 11,
    "cooler_shabbat_setpoint": 6,
    "cooler_shabbat_period": 36000,
    "cooler_shabbat_timeout": 300,
    "cooler_fan_pwm": 80,
    "printParam": 0,
    "shabbat_bypass": 0,
}

BASELINES = {"IL": IL_DEFAULTS, "US": US_DEFAULTS}


def _hc(test):
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected() or not isinstance(hydr, HCDriver):
        return None
    return hydr


def _profile(test) -> str:
    name = str(test.config.get("hc_profile", "IL")).upper()
    return name if name in BASELINES else "IL"


def _check_param(test, param_name: str) -> TestResult:
    err = test._require_hydraulic()
    if err:
        return err
    hc = _hc(test)
    if not hc:
        return test._fail("HCDriver required")

    profile = _profile(test)
    expected = BASELINES[profile][param_name]
    actual = hc.hc_get_param(param_name)
    data = {"param": param_name, "profile": profile,
            "expected": expected, "actual": actual}
    test.log(f"  [{profile}] {param_name}: expected={expected} actual={actual}")
    if actual == expected:
        return test._pass(f"OK {param_name}={actual} ({profile})", data)
    return test._fail(
        f"{param_name}={actual} != {expected} ({profile})", data)


def _make_test(param_name: str):
    """Build one BaseTest subclass that checks a single HC parameter."""
    class _ParamCheck(BaseTest):
        NAME = f"HC-PARAM {param_name}"
        DESCRIPTION = f"Check HC parameter {param_name} equals baseline."
        CATEGORY = "hc_params_check"
        PARAM = param_name

        def run(self) -> TestResult:
            return _check_param(self, self.PARAM)

    # give each generated class a unique, readable name
    _ParamCheck.__name__ = f"TestHCParam_{param_name}"
    _ParamCheck.__qualname__ = _ParamCheck.__name__
    return _ParamCheck


# generate one test class per parameter and expose them at module level
for _name in IL_DEFAULTS:
    globals()[f"TestHCParam_{_name}"] = _make_test(_name)

# tidy up loop variable so it is not picked up as a module global
del _name