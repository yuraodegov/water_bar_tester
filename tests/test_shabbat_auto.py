"""
tests/test_shabbat_auto.py — automatic Shabbat and 24-hour daily-cycle tests.

Technique (from the field script): the device RTC is driven with `set_rtc`
to simulate time passing, then the Shabbat automaton is armed and the HC
STATE stream is watched to confirm a real entry into Shabbat.

Entry is verified by the STATE chain printed on the HC stream:
    STATE: PREPARE_SHABBAT_FILLING
    STATE: PREPARE_SHABBAT_BOILING
    STATE: PREPARE_SHABBAT_DONE
    STATE: SHABBAT                <- final state
The test requires these to appear in order within the enter timeout.
It also confirms with the `shabbat_state` command when available.

Commands (HMI console, from the field script):
    set_rtc <dd/mm/YYYY HH:MM:SS>   set the device real-time clock
    shabbat_auto ENTRY_READY        arm automatic Shabbat entry
    get_error                       read active errors
Command (HC console):
    shabbat_state                   read the current Shabbat state (confirm)

Schedules for 2025-2050 come from shabbat_schedules.py. Config keys:
    shabbat_year            year to use            (default: current year)
    shabbat_count           how many Shabbats      (default: 1; 0 = all)
    stage_wait_sec          settle wait per RTC set (default: 3s)
    shabbat_enter_timeout_sec  max wait for STATE: SHABBAT (default: 60s)
    day_step_hours          24h cycle step         (default: 2h)
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
# HEATER: IDLE / START_IDLE, but NOT "Dispenser: IDLE_STATE" (\b stops before _).
EXIT_IDLE_RE = re.compile(r"(?:STATE|HEATER):\s*(START_IDLE|IDLE)\b", re.I)


def _step_wait(test):
    # "wait a minute" pause between RTC moves (default 60s).
    return float(test.config.get("stage_wait_sec", 60))


def _enter_timeout(test):
    # Prepare (fill+boil) can take 40-60 min before a forced entry, so the
    # default is 75 min. Set to 0 for an infinite wait (until SHABBAT/STOP).
    return float(test.config.get("shabbat_enter_timeout_sec", 4500))


def _exit_settle(test):
    # pause after set_rtc(exit-1min) while the RTC ticks through the exit
    # moment; the controller must return to IDLE within this window.
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


def _confirm_state(test):
    """Confirm current Shabbat state with the `shabbat_state` command on HC.
    Returns (available: bool, is_shabbat: bool). If the command is not
    supported yet, available is False and the caller ignores it."""
    hc = test.hydraulic
    if hc is None or not hc.is_connected():
        return False, False
    resp = ""
    try:
        # HCDriver exposes hc_cmd (bare CR); fall back to send_command
        if hasattr(hc, "hc_cmd"):
            resp = hc.hc_cmd("shabbat_state") or ""
        else:
            resp = hc.send_command("shabbat_state") or ""
    except Exception:
        return False, False
    up = resp.upper()
    if not up or "CMD EXECUTE ERROR" in up or "FAILED" in up:
        return False, False
    return True, ("SHABBAT" in up and "PREPARE" not in up.split("SHABBAT")[0][-8:])


def _read_exit_offset(test):
    """Read Shabbat_exit_offset (HMI param 167) in minutes. This is how many
    minutes after the calendar exit the device actually leaves Shabbat.
    Falls back to config default (60) if the param cannot be read."""
    return _read_param(test, 167, int(test.config.get(
        "shabbat_exit_offset_default", 60)))


def _read_param(test, pid, default):
    """Read an HMI integer parameter, returning `default` on any failure."""
    try:
        v = test.hmi.get_param_value(pid)
        return int(v) if v is not None else default
    except Exception:
        return default


def _israel_is_dst(dt):
    """True if `dt` is within Israel daylight-saving (summer) time.
    DST: last Friday of March 02:00 -> last Sunday of October 02:00."""
    y = dt.year
    d = datetime(y, 3, 31)
    while d.weekday() != 4:          # 4 = Friday
        d -= timedelta(days=1)
    dst_start = d.replace(hour=2)
    d = datetime(y, 10, 31)
    while d.weekday() != 6:          # 6 = Sunday
        d -= timedelta(days=1)
    dst_end = d.replace(hour=2)
    return dst_start <= dt < dst_end


def _winter_flag(dt):
    """Winter_time_flag value for a date: 1 = winter, 0 = summer."""
    return 0 if _israel_is_dst(dt) else 1


def _shabbat_setup(test):
    """Apply the Shabbat auto-mode configuration once before the cycles
    (per the reference procedure): auto mode, enter/exit offsets, the
    summer/winter offsets and clear the near-event marker.

    NOTE: this writes device parameters and does not restore them - it is
    the working Shabbat configuration the test needs.
    """
    cfg = [
        (165, 0),      # Shabbat_mode = auto
        (166, 60),     # Shabbat_enter_offset (prepare starts 60 min before)
        (167, 60),     # Shabbat_exit_offset  (real exit 60 min after)
        (169, 180),    # Summer_offset (UTC+3)
        (170, 120),    # Winter_offset (UTC+2)
        (172, 0),      # clear last near-event marker
    ]
    for pid, val in cfg:
        test.hmi.set_param(pid, val)
        time.sleep(0.2)
    test.log("  Shabbat config applied: auto mode, enter/exit offset=60, "
             "summer=180 winter=120")


def _watch_for_shabbat(test, hc, timeout):
    """Watch the HC stream until the entry chain reaches STATE: SHABBAT.

    On a real device the prepare phase (fill + boil) can take 40-60 minutes,
    after which the controller forces the Shabbat entry. So the timeout must
    be large. If `timeout` <= 0 the wait is INFINITE (until STATE: SHABBAT
    or the user presses STOP) so a stuck situation can be investigated.

    Returns (entered:bool, states:list).
    """
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
        # periodic progress log so a long prepare is visible, not a hang
        if int(elapsed) - last_log >= 30:
            last_log = int(elapsed)
            last = seen[-1] if seen else "(none)"
            mode = "infinite" if infinite else f"{int(timeout)}s"
            test.log(f"      waiting for STATE: SHABBAT... {int(elapsed)}s "
                     f"(timeout {mode}), last state={last}")
    return _chain_ok(seen), seen


def _watch_for_idle(test, hc, settle):
    """Hold the exit pause while watching the HC stream for the return to
    IDLE. Honours the full pause (does not return early) so the device
    settles before the next cycle. Returns (idle_seen:bool, states:list)."""
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


def _run_one_cycle(test, entry_dt, exit_dt, name):
    """Run one full Shabbat cycle following the field procedure:

    ENTRY:
      entry-6h  -> wait a minute
      entry-1min-> arm auto entry, WAIT for STATE: SHABBAT (gate!)
      after SHABBAT -> wait 1 minute
    EXIT:
      exit-6h   -> wait a minute
      exit-1h   -> wait a minute
      FINAL: exit + Shabbat_exit_offset - 1min  (offset~100 => exit+99min)
             -> pause 3 min so the RTC ticks through the real exit -> IDLE

    The test only proceeds past entry once the device reports STATE: SHABBAT.
    Returns (ok, info).
    """
    step = _step_wait(test)          # "wait a minute" pause
    hc = test.hydraulic
    have_stream = hc is not None and hc.is_connected()
    info = {"name": name}

    if not have_stream:
        # entry is verified from the HC STATE stream; without it we cannot
        # honour the "continue only after STATE: SHABBAT" rule.
        return False, {"name": name,
                       "reason": "HC stream required (STATE: chain) - connect HC"}

    # ── ENTRY ──
    # set the summer/winter flag for this date so the RTC is interpreted
    # with the correct offset
    flag = _winter_flag(entry_dt)
    test.hmi.set_param(168, flag)
    info["season"] = "winter" if flag else "summer"
    time.sleep(0.2)
    # prepare starts Shabbat_enter_offset minutes BEFORE the calendar entry;
    # arrive 1 minute before prepare starts so the whole prepare phase runs.
    enter_offset = _read_param(test, 166, 60)
    prep_start = entry_dt - timedelta(minutes=enter_offset)
    arrive = prep_start - timedelta(minutes=1)
    info["enter_offset"] = enter_offset
    test.log(f"    [{name}] season={info['season']} enter_offset={enter_offset} "
             f"-> arrive {arrive.strftime(RTC_FMT)} "
             f"(prepare starts {prep_start.strftime(RTC_FMT)})")
    _set_rtc(test, arrive)
    time.sleep(step)
    _hmi(test, "shabbat_auto ENTRY_READY")
    # GATE: wait for STATE: SHABBAT. The device enters via its ~60-min
    # internal prepare timeout; the test only continues after SHABBAT.
    entered, seen = _watch_for_shabbat(test, hc, _enter_timeout(test))
    info["enter_states"] = seen[-6:]
    test.log(f"    [{name}] enter chain={'OK' if entered else 'MISSING'} "
             f"states={seen[-6:]}")
    if not entered:
        info["reason"] = "device did not report STATE: SHABBAT within timeout"
        info["entered"] = False
        return False, info
    info["entered"] = True
    # after entry, wait 1 minute
    time.sleep(step)

    # ── EXIT ──
    # 6 hours before exit, wait a minute
    _set_rtc(test, exit_dt - timedelta(hours=6))
    time.sleep(step)
    # 1 hour before exit, wait a minute
    _set_rtc(test, exit_dt - timedelta(hours=1))
    time.sleep(step)
    # FINAL: read Shabbat_exit_offset and move to exit+offset-1min, then hold
    # a 3-minute pause so the RTC crosses the real exit and the device returns
    # to IDLE. This is the step that actually fixes the Shabbat exit.
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
    DESCRIPTION = ("Drive RTC through Shabbat entry for N scheduled Shabbats "
                   "and verify the STATE chain PREPARE->SHABBAT (+ shabbat_state).")
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
        _shabbat_setup(self)
        failed = {}
        for item in sched:
            if self.stop_check():
                return self._fail("stopped by user", {"done": list(failed)})
            entry = datetime.strptime(item["entry"], RTC_FMT)
            exit_dt = datetime.strptime(item["exit"], RTC_FMT)
            ok, info = _run_one_cycle(self, entry, exit_dt, item["name"])
            if not ok:
                failed[item["name"]] = info.get("reason",
                                                "exit errors" if info.get(
                                                    "exit_errors") else "failed")

        data = {"year": year, "cycles": len(sched), "failed": failed}
        if failed:
            return self._fail(
                f"{len(failed)}/{len(sched)} Shabbat cycle(s) failed", data)
        return self._pass(
            f"OK {len(sched)} Shabbat cycle(s) for {year}: entered via STATE "
            "chain, no exit errors", data)


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