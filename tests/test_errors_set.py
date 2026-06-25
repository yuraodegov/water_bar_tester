"""
tests/test_errors_set.py — error injection / set-get-clear tests (via HMI).

Commands (HMI terminal, confirmed from device log):
    set_error <N>     raise error N      -> "SET ERROR N TO ACTUAL", CMD EXECUTE OK
    get_error         list active errors -> "ERROR ID: N DisplayStatus: ..."
    clear_error <N>   clear error N       (primary way to clear)

Each test:
    1. set_error N
    2. get_error  -> N must be listed (raised)
    3. clear_error N
    4. get_error  -> N must NOT be listed (cleared)
Always clears in a finally block so the device is left clean.

The error list below comes from the Error-Table spec (code: name).
Add a new error by adding one line to ERROR_TABLE.

Also includes NEGATIVE checks: invalid error ids must be rejected
(the device answered "CMD EXECUTE ERROR" to set_error 0 / clear_error
without an id in the log).
"""
import re
import time
from tests.test_base import BaseTest, TestResult

SETTLE = 0.6

# code : (name, region)   region: "ALL" | "IL" | "US"
ERROR_TABLE = {
    2: ("Cold water sensor shorting", "ALL"),
    3: ("Cold water sensor disconnected", "ALL"),
    4: ("Cooling system did not reach setpoint", "ALL"),
    5: ("Booster hot water sensor shorting", "ALL"),
    6: ("Booster hot water sensor disconnected", "ALL"),
    8: ("Heating system - heater on 60min, temp not rising", "ALL"),
    9: ("Mqtt error", "ALL"),
    10: ("Wifi error", "ALL"),
    12: ("Tank hot water sensor shorting", "ALL"),
    13: ("Tank hot water sensor disconnected", "ALL"),
    14: ("Cold water temp below 1C", "ALL"),
    16: ("Malfunction in power supply -12V", "ALL"),
    20: ("Dry protection triggered", "ALL"),
    22: ("Current limit", "ALL"),
    27: ("Temperature in CWT above 45C", "ALL"),
    38: ("Common-PCB temp sensor shorted", "ALL"),
    47: ("HMI memory reading error", "ALL"),
    48: ("HMI memory writing error", "ALL"),
    49: ("Hot water tank fill flow too low", "ALL"),
    50: ("Hot water tank fill flow too high", "ALL"),
    51: ("No hot water flow", "ALL"),
    52: ("HMI-PCB temp sensor shorted", "ALL"),
    53: ("HMI-PCB temp sensor disconnected", "ALL"),
    55: ("HMI-PCB over heating", "ALL"),
    56: ("Common PCB over heating", "ALL"),
    57: ("Cold water flow too low", "ALL"),
    58: ("Cold water flow too high", "ALL"),
    59: ("Wrong purifier (UK/IL mismatch)", "ALL"),
    60: ("No cold water flow", "ALL"),
    63: ("Addon internal error", "ALL"),
    74: ("HMI fail to communicate with Common", "ALL"),
    75: ("HMI fail to update Common SW version", "ALL"),
    76: ("HMI communication failed (>3 in 12h)", "ALL"),
    78: ("HMI PCB RTC fail", "ALL"),
    79: ("FOTA error", "ALL"),
    150: ("Ambient water flow too low", "ALL"),
    151: ("Ambient water flow too high", "ALL"),
    153: ("HWT over flow", "ALL"),
    154: ("HOT water tank level sensor doesnt work", "ALL"),
    155: ("Machine not ready for shabbat at auto mode", "ALL"),
    156: ("Common memory reading error", "ALL"),
    157: ("Common memory writing error", "ALL"),
}

# invalid ids for negative testing (device rejected these in the log)
INVALID_IDS = [0, 9999]


def _err_active(get_resp, code):
    """True if get_error response lists this error code as active."""
    if not get_resp:
        return False
    # device prints e.g. "ERROR ID: 5 DisplayStatus: Display"
    for m in re.finditer(r'ERROR\s+ID:\s*(\d+)', get_resp, re.I):
        if int(m.group(1)) == code:
            return True
    return False


def _make_error_test(code, name, region):
    class _ErrTest(BaseTest):
        NAME = f"ERR-{code:03d} {name}"
        DESCRIPTION = (f"set_error {code} -> get_error sees it -> "
                       f"clear_error {code} -> gone.")
        CATEGORY = "errors_set"
        CODE, ENAME, REGION = code, name, region

        def run(self) -> TestResult:
            err = self._require_hmi()
            if err:
                return err
            hmi = self.hmi
            data = {"code": self.CODE, "name": self.ENAME, "region": self.REGION}
            errors = []
            try:
                hmi.set_error(self.CODE)
                time.sleep(SETTLE)
                after_set = hmi.get_error()
                raised = _err_active(after_set, self.CODE)
                data["raised"] = raised
                self.log(f"  set_error {self.CODE} -> active={raised}")
                if not raised:
                    errors.append(f"error {self.CODE} not active after set_error")

                hmi.clear_error(self.CODE)
                time.sleep(SETTLE)
                after_clear = hmi.get_error()
                still = _err_active(after_clear, self.CODE)
                data["cleared"] = not still
                self.log(f"  clear_error {self.CODE} -> active={still}")
                if still:
                    errors.append(f"error {self.CODE} still active after clear_error")
            finally:
                # make sure we leave the device clean
                try:
                    hmi.clear_error(self.CODE)
                except Exception:
                    pass

            if errors:
                return self._fail(" | ".join(errors), data)
            return self._pass(f"OK error {self.CODE} set/get/clear works", data)

    _ErrTest.__name__ = f"TestErr_{code}"
    _ErrTest.__qualname__ = _ErrTest.__name__
    return _ErrTest


class TestErrorsNegativeInvalid(BaseTest):
    NAME = "ERR-NEG invalid error id rejected"
    DESCRIPTION = ("set_error with an invalid id (0 / out of range) must be "
                   "rejected (CMD EXECUTE ERROR), not accepted.")
    CATEGORY = "errors_set"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        hmi = self.hmi
        data = {"checked": INVALID_IDS}
        errors = []
        for bad in INVALID_IDS:
            resp = hmi.set_error(bad) or ""
            rejected = "CMD EXECUTE ERROR" in resp or not _err_active(
                hmi.get_error(), bad)
            self.log(f"  set_error {bad} -> rejected={rejected}")
            if not rejected:
                errors.append(f"invalid id {bad} was NOT rejected")
                try:
                    hmi.clear_error(bad)
                except Exception:
                    pass
        if errors:
            return self._fail(" | ".join(errors), data)
        return self._pass("OK invalid error ids are rejected", data)


class TestErrorsClearAllSweep(BaseTest):
    NAME = "ERR-SWEEP set then clear two errors (no leftovers)"
    DESCRIPTION = ("Raise two errors, confirm both listed, clear both, "
                   "confirm get_error reports none of them.")
    CATEGORY = "errors_set"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        hmi = self.hmi
        pair = [5, 12]
        data = {"pair": pair}
        errors = []
        try:
            for c in pair:
                hmi.set_error(c)
                time.sleep(SETTLE)
            listed = hmi.get_error()
            for c in pair:
                if not _err_active(listed, c):
                    errors.append(f"{c} not active after set")
            for c in pair:
                hmi.clear_error(c)
                time.sleep(SETTLE)
            after = hmi.get_error()
            for c in pair:
                if _err_active(after, c):
                    errors.append(f"{c} still active after clear")
        finally:
            for c in pair:
                try:
                    hmi.clear_error(c)
                except Exception:
                    pass
        if errors:
            return self._fail(" | ".join(errors), data)
        return self._pass("OK both errors set and cleared cleanly", data)


# ── generate one test per error code ──
for _code, (_name, _region) in ERROR_TABLE.items():
    globals()[f"TestErr_{_code}"] = _make_error_test(_code, _name, _region)
del _code, _name, _region