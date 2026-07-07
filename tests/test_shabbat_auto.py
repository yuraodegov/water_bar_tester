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


def _wait(test):
    return float(test.config.get("stage_wait_sec", 3))


def _enter_timeout(test):
    return float(test.config.get("shabbat_enter_timeout_sec", 60))


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


def _run_one_cycle(test, entry_dt, exit_dt, name):
    """Run one Shabbat cycle. Returns (ok, info)."""
    wait = _wait(test)
    hc = test.hydraulic
    have_stream = hc is not None and hc.is_connected()
    info = {"name": name}

    # 1) wake up 4 hours before preparation
    _set_rtc(test, entry_dt - timedelta(hours=4))
    time.sleep(wait)
    # 2) preparation, 1 minute before entry
    _set_rtc(test, entry_dt - timedelta(minutes=1))
    time.sleep(wait)
    # 3) arm automatic Shabbat entry, then watch the HC STATE stream
    _hmi(test, "shabbat_auto ENTRY_READY")

    seen = []
    if have_stream:
        deadline = time.time() + _enter_timeout(test)
        while time.time() < deadline:
            lines = hc.listen(3.0, stop_substr="STATE: SHABBAT")
            seen.extend(_states_from(lines))
            if "SHABBAT" in seen and _chain_ok(seen):
                break
    info["states"] = seen

    entered_by_chain = _chain_ok(seen)
    available, is_shabbat = _confirm_state(test)
    info["shabbat_state_available"] = available
    info["shabbat_state_is_shabbat"] = is_shabbat

    test.log(f"    [{name}] chain={'OK' if entered_by_chain else 'MISSING'} "
             f"states={seen[-6:]}")
    if available:
        test.log(f"    [{name}] shabbat_state confirms: "
                 f"{'SHABBAT' if is_shabbat else 'NOT shabbat'}")

    # entry is OK if the STATE chain was seen; if the stream is not available
    # fall back to the shabbat_state command; if neither, we cannot verify
    if have_stream:
        entered = entered_by_chain or (available and is_shabbat)
    else:
        entered = available and is_shabbat
    info["entered"] = entered
    if not entered:
        if not have_stream and not available:
            info["reason"] = ("cannot verify entry: HC stream not connected "
                              "and shabbat_state unavailable")
        else:
            info["reason"] = "STATE chain to SHABBAT not observed in timeout"

    # ── EXIT ──
    # 4) 4 hours before exit (approach)
    _set_rtc(test, exit_dt - timedelta(hours=4))
    time.sleep(wait)
    # 5) exit - 1 minute, then hold a pause so the RTC ticks THROUGH the exit
    #    moment. This is what actually drives the controller out of Shabbat
    #    and back to IDLE (symmetric to the entry step). Watch the HC stream
    #    for the return to IDLE during the pause.
    _set_rtc(test, exit_dt - timedelta(minutes=1))
    exited = False
    exit_states = []
    if have_stream:
        deadline = time.time() + _exit_settle(test)
        while time.time() < deadline:
            if test.stop_check():
                break
            lines = hc.listen(3.0)  # hold the full pause, collect the stream
            exit_states.extend(_states_from(lines))
            if any(EXIT_IDLE_RE.search(ln) for ln in lines):
                exited = True
                # keep listening a little so the pause is honoured, but we
                # have our confirmation
        info["exit_states"] = exit_states[-6:]
    else:
        # no HC stream: just hold the pause so the device processes the exit
        time.sleep(_exit_settle(test))

    # confirm exit with shabbat_state when available
    avail2, is_shabbat2 = _confirm_state(test)
    if avail2:
        info["exit_state_is_idle"] = not is_shabbat2
        if not is_shabbat2:
            exited = True

    err_resp = _hmi(test, "get_error")
    info["exit_errors"] = _errors_present(err_resp)
    info["exited"] = exited

    if have_stream or avail2:
        test.log(f"    [{name}] exit -> IDLE: {'OK' if exited else 'NOT seen'} "
                 f"states={exit_states[-4:]}")

    # overall: entered AND (exit verified if we could verify) AND no errors
    can_verify_exit = have_stream or avail2
    exit_ok = exited if can_verify_exit else True
    ok = entered and exit_ok and not info["exit_errors"]
    if not exit_ok:
        info["reason"] = "did not return to IDLE after exit"
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

        self.log(f"  running {len(sched)} Shabbat cycle(s) for {year} "
                 f"(enter timeout {int(_enter_timeout(self))}s)")
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
        wait = _wait(self)
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