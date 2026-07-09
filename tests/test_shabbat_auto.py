"""
tests/test_shabbat_auto.py — automatic Shabbat and 24-hour daily-cycle tests.

The device runs Shabbat in its own automatic mode. This test moves the RTC
to the calendar dates and lets the device do its normal work. The only
parameter it writes is the winter/summer flag (168), set per date so the
device interprets the RTC with the correct offset; it does NOT change the
Shabbat mode (165) or the enter/exit offsets (166/167).

Cycle (exactly as specified in the field procedure):

  ENTRY:
    entry - 6h        -> wait a minute
    entry - 1min      -> arm auto entry, WAIT for STATE: SHABBAT (gate)
    after SHABBAT     -> wait 1 minute
  EXIT:
    exit - 6h         -> wait a minute
    exit - 1h         -> wait a minute
    FINAL: exit + Shabbat_exit_offset - 1min  -> pause 3 min -> IDLE

Entry is proven by the HC STATE chain PREPARE_SHABBAT_FILLING -> BOILING ->
DONE -> SHABBAT. The test continues past entry ONLY after STATE: SHABBAT.
Exit is proven by the return to IDLE on the HC stream.

Commands (HMI): set_rtc, shabbat_auto ENTRY_READY, get_error, get_param 167.
Schedules for 2025-2050 come from shabbat_schedules.py.

Config keys:
    shabbat_year               year to use              (default: current)
    shabbat_count              how many Shabbats        (default: 1; 0 = all)
    stage_wait_sec             "wait a minute" pause    (default: 60s)
    shabbat_enter_timeout_sec  max wait for SHABBAT     (default: 4500s; 0=inf)
    shabbat_exit_settle_sec    exit pause               (default: 180s)
    shabbat_exit_offset_default fallback if 167 unread  (default: 100)
    day_step_hours             24h cycle step           (default: 2h)
"""
import re
import time
from datetime import datetime, timedelta
from tests.test_base import BaseTest, TestResult

try:
    from shabbat_schedules import SCHEDULES
except Exception:
    SCHEDULES = {}

RTC_FMT = "%d/%m/%Y %H:%M:%S"

# ordered STATE chain that proves a real Shabbat entry (from HC stream)
ENTER_CHAIN = [
    "PREPARE_SHABBAT_FILLING",
    "PREPARE_SHABBAT_BOILING",
    "PREPARE_SHABBAT_DONE",
    "SHABBAT",
]
STATE_RE = re.compile(r"STATE:\s*([A-Z_]+)", re.I)
# exit is confirmed when the controller returns to IDLE. Match STATE: IDLE /
# HEATER: IDLE / START_IDLE, but NOT "Dispenser: IDLE_STATE" (\b stops at _).
EXIT_IDLE_RE = re.compile(r"(?:STATE|HEATER):\s*(START_IDLE|IDLE)\b", re.I)


def _step_wait(test):
    # "wait a minute" pause between RTC moves (default 60s).
    return float(test.config.get("stage_wait_sec", 60))


def _enter_timeout(test):
    # Prepare (fill+boil) can take ~60 min before the device forces the
    # entry, so the default is 75 min. Set to 0 for an infinite wait.
    return float(test.config.get("shabbat_enter_timeout_sec", 4500))


def _exit_settle(test):
    # pause after the final set_rtc while the RTC ticks through the real exit.
    return float(test.config.get("shabbat_exit_settle_sec", 180))


def _hmi(test, cmd):
    return test.hmi.send_command(cmd)


def _set_rtc(test, dt):
    return _hmi(test, f"set_rtc {dt.strftime(RTC_FMT)}")


def _errors_present(resp):
    if not resp:
        return False
    up = resp.upper()
    if "ERROR LIST EMPTY" in up or resp.strip() in ("0", ""):
        return False
    return "ERROR ID" in up or "ERROR:" in up


def _states_from(lines):
    """Extract the ordered list of STATE names from raw HC lines."""
    out = []
    for ln in lines:
        m = STATE_RE.search(ln)
        if m:
            out.append(m.group(1).upper())
    return out


def _chain_ok(seen):
    """True if ENTER_CHAIN appears as an ordered subsequence of `seen`."""
    it = iter(seen)
    return all(any(s == step for s in it) for step in ENTER_CHAIN)




def _read_exit_offset(test):
    """Shabbat_exit_offset in minutes, fixed from config (default 100).
    Not read from the device (unreliable here)."""
    return int(test.config.get("shabbat_exit_offset", 100))


def _watch_for_shabbat(test, hc, timeout):
    """Watch the HC stream until the entry chain reaches STATE: SHABBAT.
    timeout <= 0 means wait forever (until SHABBAT or STOP).
    Returns (entered:bool, states:list)."""
    seen = []
    start = time.time()
    infinite = timeout <= 0
    last_log = 0
    while True:
        if test.stop_check():
            break
        elapsed = time.time() - start
        if not infinite and elapsed >= timeout:
            break
        lines = hc.listen(3.0, stop_substr="STATE: SHABBAT")
        seen.extend(_states_from(lines))
        if "SHABBAT" in seen and _chain_ok(seen):
            return True, seen
        if int(elapsed) - last_log >= 30:
            last_log = int(elapsed)
            last = seen[-1] if seen else "(none)"
            mode = "infinite" if infinite else f"{int(timeout)}s"
            test.log(f"      waiting for STATE: SHABBAT... {int(elapsed)}s "
                     f"(timeout {mode}), last state={last}")
    return _chain_ok(seen), seen


def _watch_for_idle(test, hc, settle):
    """Hold the exit pause while watching the HC stream for the return to
    IDLE. Honours the full pause so the device settles before the next
    cycle. Returns (idle_seen:bool, states:list)."""
    seen = []
    idle = False
    deadline = time.time() + settle
    while time.time() < deadline:
        if test.stop_check():
            break
        lines = hc.listen(3.0)
        seen.extend(_states_from(lines))
        if any(EXIT_IDLE_RE.search(ln) for ln in lines):
            idle = True
    return idle, seen


def _season_offset(dt):
    """Time offset (minutes) for param 169, by month, matching the device:
      winter (Nov..Mar): 120  (UTC+2)
      summer (Apr..Oct): 180  (UTC+3)
    Setting param 169 directly is what actually shifts the device clock
    (the Winter_time_flag 168 does not)."""
    return 120 if (dt.month >= 11 or dt.month <= 3) else 180


def _run_one_cycle(test, entry_dt, exit_dt, name):
    """Run one full Shabbat cycle by moving the RTC only. Returns (ok, info)."""
    step = _step_wait(test)
    hc = test.hydraulic
    have_stream = hc is not None and hc.is_connected()
    info = {"name": name}
    if not have_stream:
        return False, {"name": name,
                       "reason": "HC stream required (STATE: chain) - connect HC"}

    # ── ENTRY ──
    # Set the active time offset (param 169) for this date's season. Writing
    # 169 directly (120 winter / 180 summer) is what actually shifts the
    # device clock; the Winter_time_flag (168) does not, so it is not used.
    # Mode (165) and enter/exit offsets (166/167) are left untouched.
    offset = _season_offset(entry_dt)
    _hmi(test, f"set_param 169 {offset}")
    time.sleep(0.3)
    # read it back to confirm the offset actually changed
    try:
        applied = test.hmi.get_param_value(169)
    except Exception:
        applied = None
    info["season"] = "winter" if offset == 120 else "summer"
    info["offset169_set"] = offset
    info["offset169_read"] = applied
    if applied is not None and applied != offset:
        test.log(f"    [{name}] WARNING set_param 169 {offset} but reads "
                 f"{applied} (time offset did not apply)")
    else:
        test.log(f"    [{name}] season={info['season']} set_param 169 {offset} "
                 f"(read={applied})")
    # prepare starts Shabbat_enter_offset minutes before the calendar entry
    # (fixed value from config, not read from the device).
    enter_offset = int(test.config.get("shabbat_enter_offset", 60))
    prep_start = entry_dt - timedelta(minutes=enter_offset)
    info["enter_offset"] = enter_offset
    # 1) arrive 6 hours before the calendar entry, wait a minute
    _set_rtc(test, entry_dt - timedelta(hours=6))
    time.sleep(step)
    # 2) move to 1 minute before prepare STARTS (= entry - enter_offset - 1min),
    #    then arm the auto entry
    arrive = prep_start - timedelta(minutes=1)
    test.log(f"    [{name}] enter_offset={enter_offset}, "
             f"prepare starts {prep_start.strftime(RTC_FMT)} -> arrive "
             f"{arrive.strftime(RTC_FMT)}")
    _set_rtc(test, arrive)
    _hmi(test, "shabbat_auto ENTRY_READY")
    # GATE: wait for STATE: SHABBAT. The device runs prepare (~60 min) then
    # enters; the test only continues after SHABBAT.
    entered, seen = _watch_for_shabbat(test, hc, _enter_timeout(test))
    info["enter_states"] = seen[-6:]
    test.log(f"    [{name}] enter chain={'OK' if entered else 'MISSING'} "
             f"states={seen[-6:]}")
    if not entered:
        info["entered"] = False
        info["reason"] = "device did not report STATE: SHABBAT within timeout"
        return False, info
    info["entered"] = True
    # 3) after entry, wait 1 minute
    time.sleep(step)

    # ── EXIT ──
    # 4) 6 hours before exit, wait a minute
    _set_rtc(test, exit_dt - timedelta(hours=6))
    time.sleep(step)
    # 5) 1 hour before exit, wait a minute
    _set_rtc(test, exit_dt - timedelta(hours=1))
    time.sleep(step)
    # 6) FINAL: check Shabbat_exit_offset (read-only) and move to
    #    exit + offset - 1min, then hold a 3-minute pause so the RTC crosses
    #    the real exit and the device returns to IDLE.
    offset = _read_exit_offset(test)
    final_dt = exit_dt + timedelta(minutes=offset - 1)
    info["exit_offset"] = offset
    test.log(f"    [{name}] exit_offset={offset} -> final RTC "
             f"{final_dt.strftime(RTC_FMT)} (exit+{offset - 1}min)")
    _set_rtc(test, final_dt)
    exited, exit_states = _watch_for_idle(test, hc, _exit_settle(test))
    info["exit_states"] = exit_states[-6:]
    err_resp = _hmi(test, "get_error")
    info["exit_errors"] = _errors_present(err_resp)
    info["exited"] = exited
    test.log(f"    [{name}] exit -> IDLE: {'OK' if exited else 'NOT seen'} "
             f"states={exit_states[-4:]}")

    ok = entered and exited and not info["exit_errors"]
    if not exited:
        info["reason"] = "device did not return to IDLE after exit"
    elif info["exit_errors"]:
        info["reason"] = "errors present after exit"
    return ok, info


class TestShabbatAuto(BaseTest):
    NAME = "SHB-AUTO Automatic Shabbat cycle(s)"
    DESCRIPTION = ("Move the RTC through Shabbat entry/exit for N scheduled "
                   "Shabbats; verify STATE chain PREPARE->SHABBAT and exit->IDLE.")
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

        to = _enter_timeout(self)
        to_str = "infinite" if to <= 0 else f"{int(to)}s ({int(to // 60)}min)"
        self.log(f"  running {len(sched)} Shabbat cycle(s) for {year} "
                 f"(enter timeout {to_str})")
        failed = {}
        for item in sched:
            if self.stop_check():
                return self._fail("stopped by user", {"done": list(failed)})
            entry = datetime.strptime(item["entry"], RTC_FMT)
            exit_dt = datetime.strptime(item["exit"], RTC_FMT)
            ok, info = _run_one_cycle(self, entry, exit_dt, item["name"])
            if not ok:
                failed[item["name"]] = info.get("reason", "failed")

        data = {"year": year, "cycles": len(sched), "failed": failed}
        if failed:
            return self._fail(
                f"{len(failed)}/{len(sched)} Shabbat cycle(s) failed", data)
        return self._pass(
            f"OK {len(sched)} Shabbat cycle(s) for {year}: entered via STATE "
            "chain and returned to IDLE", data)


class TestDailyAutoCycle(BaseTest):
    NAME = "DAY-24H Daily auto-cycle (24h via RTC)"
    DESCRIPTION = ("Advance the RTC across a full 24-hour day in steps and "
                   "verify the device runs the daily auto-cycle without errors.")
    CATEGORY = "shabbat_auto"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err

        base_str = self.config.get("day_start")  # optional "dd/mm/YYYY"
        if base_str:
            try:
                base = datetime.strptime(base_str, "%d/%m/%Y")
            except ValueError:
                return self._fail(f"bad day_start '{base_str}', use dd/mm/YYYY")
        else:
            now = datetime.now()
            base = datetime(now.year, now.month, now.day)

        step_hours = int(self.config.get("day_step_hours", 2))
        wait = _step_wait(self)
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
            resp = _hmi(self, "get_error")
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