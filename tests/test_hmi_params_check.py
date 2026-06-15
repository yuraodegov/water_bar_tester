"""
tests/test_hmi_params_check.py — per-parameter HMI eeprom check.

Each HMI parameter is its own test: it reads the value by id via
'get_param <id>' and checks it equals the expected baseline (exact match).
Baselines are kept in the dict below so they are easy to edit when a
default changes.

HMI parameters are addressed by numeric id; the device replies
'[<id>] <Name> = <value>  (0x..)'. Only integer params are checked here
(string params like SSID / userProfile are skipped).

NOTE: some of these are user settings that legitimately change at runtime
(language, wake-up times, child lock, region...). Remove any id from
HMI_DEFAULTS that you do not want enforced.
"""
from core.hmi_serial import HmiSerial
from tests.test_base import BaseTest, TestResult

# ── BASELINES (edit these when a default changes) ─────────────────────────────
# Captured from a real HMI 'get_param' dump. Format: id -> (expected, name).
HMI_DEFAULTS = {
    9: (0, "User.Setting.Bit.TraceCommon"),
    10: (0, "User.Setting.Bit.EventTraceExpand"),
    11: (0, "SystemConfig.Core.bit.leakage"),
    14: (183, "Core.FilterLifeTime"),
    15: (364, "Core.UvLifeTime"),
    16: (91, "Core.CleanNetTime"),
    20: (30, "Core.MenuExitTime"),
    23: (1, "SystemConfig.UserSetting.bit.heater_on"),
    29: (96000, "Core.BoilingTemp"),
    31: (376, "Core.CountryCode"),
    35: (0, "Core.TouchSensitivity"),
    36: (0, "Core.Setting.Bit.ShippingMode"),
    37: (1, "SystemConfig.UserSetting.bit.installation_done"),
    38: (0, "SystemConfig.UserSetting.bit.buttons_lock"),
    43: (0, "User.TimeOffset"),
    44: (0, "User.Language"),
    45: (0, "User.Region"),
    46: (0, "User.Units"),
    47: (8, "User.WakeUp[0].Hour"),
    48: (0, "User.WakeUp[0].Min"),
    49: (17, "User.WakeUp[1].Hour"),
    50: (0, "User.WakeUp[1].Min"),
    59: (100, "User.KeypadVibrationDuration"),
    60: (0, "User.Setting.Bit.ChildLock"),
    61: (1, "User.Setting.Bit.KeypadSounds"),
    62: (1, "User.Setting.Bit.ClockDisplayHebrew"),
    63: (0, "User.Setting.Bit.ClockFormat"),
    64: (0, "User.Setting.Bit.WakeUp1"),
    65: (0, "User.Setting.Bit.WakeUp2"),
    67: (0, "User.Setting.Bit.DeepSleep"),
    68: (1, "User.Setting.Bit.ChildLockMenu"),
    69: (1, "User.Setting.Bit.EnergySaving"),
    71: (1, "User.Setting.Bit.DebugReportEnabled"),
    72: (1, "User.Setting.Bit.ShowDayOfWeek"),
    73: (0, "User.Setting.Bit.WifiEnabled"),
    75: (1, "User.Setting.Bit.NightModeEnabled"),
    76: (1080, "SystemConfig.Core.CleanNet_Counter"),
    78: (0, "SystemConfig.TimeMng.UserDisplayOffset"),
    97: (0, "Hwda.Version"),
    98: (0, "Hwda.FirstRtcCounter"),
    99: (1, "Hwda.Setting.Bit.Enabled"),
    100: (0, "Hwda.Setting.Bit.Started"),
    101: (0, "Hwda.Setting.Bit.Duplicate"),
    124: (1, "User.Setting.Bit2.pushToDrink"),
    125: (1, "User.Setting.Bit2.ambientLight"),
    127: (0, "User.Setting.Bit2.isUpdatefFromCloud"),
    129: (1, "Technician.Bit.Debug"),
    130: (1, "Technician.Bit.ChildLock"),
    140: (0, "Core.System.Bit.FactoryReset"),
    141: (0, "Core.System.Bit.FotaInstall"),
    142: (0, "Wifi.certificateIndex"),
    143: (0, "Core.System.Bit.FotaDownloading"),
    144: (0, "washingSavedStage"),
    145: (0, "uvInstallTime"),
    146: (0, "purifierInstallTime"),
    147: (0, "IOTLoggerPage"),
    152: (0, "User.Setting.Bit2.ShabbatMode"),
    160: (0, "HWDA_Info.RTC_Calibrated"),
    163: (0, "SystemConfig.Core.AddonConnected"),
    164: (0, "HWDA_Info.Hwda.Setting.Bit.Enabled"),
    165: (0, "Shabbat_mode"),
    166: (60, "Shabbat_enter_offset"),
    167: (100, "Shabbat_exit_offset"),
    168: (0, "Winter_time_flag"),
    169: (180, "Summer_offset"),
    170: (120, "Winter_offset"),
    171: (0, "Shabbat_mode_override_manual"),
    172: (0, "Shabbat_last_near_event_exit"),
    173: (3600, "Shabbat_wifi_off_before_seconds"),
    174: (600, "Shabbat_wifi_on_after_seconds"),
    175: (0, "Shabbat_mode_manual_or_auto_only"),
}


def _hmi(test):
    h = test.hmi
    if h is None or not h.is_connected() or not isinstance(h, HmiSerial):
        return None
    return h


def _check_param(test, param_id: int) -> TestResult:
    err = test._require_hmi()
    if err:
        return err
    hmi = _hmi(test)
    if not hmi:
        return test._fail("HmiSerial required")

    expected, name = HMI_DEFAULTS[param_id]
    actual = hmi.get_param_value(param_id)
    data = {"param_id": param_id, "name": name,
            "expected": expected, "actual": actual}
    test.log(f"  [{param_id}] {name}: expected={expected} actual={actual}")
    if actual == expected:
        return test._pass(f"OK [{param_id}] {name}={actual}", data)
    return test._fail(
        f"[{param_id}] {name}={actual} != {expected}", data)


def _make_test(param_id: int, name: str):
    """Build one BaseTest subclass that checks a single HMI parameter."""
    class _ParamCheck(BaseTest):
        NAME = f"HMI-PARAM [{param_id}] {name}"
        DESCRIPTION = f"Check HMI param [{param_id}] {name} equals baseline."
        CATEGORY = "hmi_params_check"
        PARAM_ID = param_id

        def run(self) -> TestResult:
            return _check_param(self, self.PARAM_ID)

    safe = name.replace(".", "_").replace("[", "_").replace("]", "_")
    _ParamCheck.__name__ = f"TestHMIParam_{param_id}_{safe}"
    _ParamCheck.__qualname__ = _ParamCheck.__name__
    return _ParamCheck


# generate one test class per parameter and expose them at module level
for _pid, (_val, _name) in HMI_DEFAULTS.items():
    _safe = _name.replace(".", "_").replace("[", "_").replace("]", "_")
    globals()[f"TestHMIParam_{_pid}_{_safe}"] = _make_test(_pid, _name)

# tidy up loop variables so they are not picked up as module globals
del _pid, _val, _name, _safe