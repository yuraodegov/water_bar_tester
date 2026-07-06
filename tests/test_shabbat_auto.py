"""
tests/test_shabbat_auto.py — automatic Shabbat and 24-hour daily-cycle tests.

Technique (from the field script): the device RTC is driven with `set_rtc`
to simulate time passing, then the Shabbat automaton is triggered and the
device is polled for errors at each stage. No physical waiting for real
Shabbat times is needed.

Commands (HMI console, confirmed in the field script):
    set_rtc <dd/mm/YYYY HH:MM:SS>   set the device real-time clock
    shabbat_auto ENTRY_READY        arm the automatic Shabbat entry
    get_error                       read active errors

Schedules for 2025-2050 come from shabbat_schedules.py (real entry/exit
times). Configurable via config:
    shabbat_year   : which year to use          (default: current year)
    shabbat_count  : how many Shabbats to run    (default: 1; 0 = all)
    stage_wait_sec : observation wait per stage  (default: 3s; raise for
                     real runs so the device has time to react)

Each Shabbat cycle reproduces the field flow:
    wake 4h before prep -> prep 1min before entry -> arm entry ->
    4h before exit -> exit +99min -> check errors.
"""
import time
from datetime import datetime, timedelta
from tests.test_base import BaseTest, TestResult

try:
    from shabbat_schedules import SCHEDULES
except Exception:
    SCHEDULES = {}

RTC_FMT = "%d/%m/%Y %H:%M:%S"


def _stage_wait(test):
    return float(test.config.get("stage_wait_sec", 3))


def _hmi_cmd(test, cmd):
    """Send a command on the HMI console and return the response text."""
    return test.hmi.send_command(cmd)


def _errors_present(resp):
    """True if get_error reports at least one active error."""
    if not resp:
        return False
    up = resp.upper()
    if "ERROR LIST EMPTY" in up or resp.strip() in ("0", ""):
        return False
    return "ERROR ID" in up or "ERROR:" in up


def _set_rtc(test, dt):
    return _hmi_cmd(test, f"set_rtc {dt.strftime(RTC_FMT)}")


def _run_one_cycle(test, entry_dt, exit_dt, name):
    """Run a single Shabbat cycle. Returns (ok, stage_errors:list)."""
    wait = _stage_wait(test)
    stage_errors = []

    def check(stage):
        resp = _hmi_cmd(test, "get_error")
        if _errors_present(resp):
            stage_errors.append(f"{stage}: {resp.strip()[:80]}")
            test.log(f"    [{name}] {stage}: ERROR {resp.strip()[:60]}")
        else:
            test.log(f"    [{name}] {stage}: no errors")

    # 1) wake up 4 hours before preparation
    _set_rtc(test, entry_dt - timedelta(hours=4))
    time.sleep(wait)
    # 2) preparation, 1 minute before entry
    _set_rtc(test, entry_dt - timedelta(minutes=1))
    time.sleep(wait)
    # 3) arm automatic Shabbat entry
    _hmi_cmd(test, "shabbat_auto ENTRY_READY")
    time.sleep(wait)
    check("entry")
    # 4) 4 hours before exit
    _set_rtc(test, exit_dt - timedelta(hours=4))
    time.sleep(wait)
    # 5) exit + 99 minutes
    _set_rtc(test, exit_dt + timedelta(minutes=99))
    time.sleep(wait)
    check("exit")

    return (len(stage_errors) == 0), stage_errors


class TestShabbatAuto(BaseTest):
    NAME = "SHB-AUTO Automatic Shabbat cycle(s)"
    DESCRIPTION = ("Drive RTC through Shabbat entry/exit for N scheduled "
                   "Shabbats and verify no errors are raised.")
    CATEGORY = "shabbat_auto"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        if not SCHEDULES:
            return self._fail("shabbat_schedules.py not found or empty")

        year = int(self.config.get("shabbat_year", datetime.now().year))
        if year not in SCHEDULES:
            return self._fail(f"no schedule for year {year} "
                              f"(have {min(SCHEDULES)}-{max(SCHEDULES)})")
        count = int(self.config.get("shabbat_count", 1))
        sched = SCHEDULES[year]
        if count > 0:
            sched = sched[:count]

        self.log(f"  running {len(sched)} Shabbat cycle(s) for {year}")
        all_errors = {}
        for item in sched:
            if self.stop_check():
                return self._fail("stopped by user", {"done": list(all_errors)})
            entry = datetime.strptime(item["entry"], RTC_FMT)
            exit_dt = datetime.strptime(item["exit"], RTC_FMT)
            ok, errs = _run_one_cycle(self, entry, exit_dt, item["name"])
            if not ok:
                all_errors[item["name"]] = errs

        data = {"year": year, "cycles": len(sched),
                "failed_cycles": all_errors}
        if all_errors:
            return self._fail(
                f"{len(all_errors)}/{len(sched)} Shabbat cycles had errors",
                data)
        return self._pass(
            f"OK {len(sched)} Shabbat cycle(s) for {year}, no errors", data)


class TestDailyAutoCycle(BaseTest):
    NAME = "DAY-24H Daily auto-cycle (24h via RTC)"
    DESCRIPTION = ("Advance the RTC across a full 24-hour day in steps and "
                   "verify the device runs the daily auto-cycle without errors.")
    CATEGORY = "shabbat_auto"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err

        # start at midnight of a chosen date (default: today)
        base_str = self.config.get("day_start")  # "dd/mm/YYYY" optional
        if base_str:
            try:
                base = datetime.strptime(base_str, "%d/%m/%Y")
            except ValueError:
                return self._fail(f"bad day_start '{base_str}', use dd/mm/YYYY")
        else:
            now = datetime.now()
            base = datetime(now.year, now.month, now.day)

        step_hours = int(self.config.get("day_step_hours", 2))
        wait = _stage_wait(self)
        steps = list(range(0, 24, max(1, step_hours))) + [24]

        self.log(f"  simulating a full day from {base.strftime('%d/%m/%Y')} "
                 f"in {step_hours}h steps")
        stage_errors = []
        for h in steps:
            if self.stop_check():
                return self._fail("stopped by user")
            t = base + timedelta(hours=h)
            _set_rtc(self, t)
            time.sleep(wait)
            resp = _hmi_cmd(self, "get_error")
            mark = "ERR" if _errors_present(resp) else "ok"
            self.log(f"    {t.strftime('%H:%M')} -> {mark}")
            if _errors_present(resp):
                stage_errors.append(f"{t.strftime('%H:%M')}: {resp.strip()[:60]}")

        data = {"date": base.strftime("%d/%m/%Y"), "step_hours": step_hours,
                "errors": stage_errors}
        if stage_errors:
            return self._fail(
                f"daily auto-cycle raised errors at {len(stage_errors)} step(s)",
                data)
        return self._pass("OK full 24h auto-cycle, no errors", data)