"""
hmi_terminal.py — Tamar HMI (ESP32, tamar-hmi v0.02.123) terminal interface
115200-8N1, ASCII protocol.

Button map (ShabbatBar_Buttons.xlsx):
    1 = Hot Cup       5 = Cold Jug
    2 = Hot Jug       6 = Ambient Cup
    3 = Menu          7 = Ambient Jug
    4 = Cold Cup      8 = Extra Hot
                      9 = Shabbat

IMPORTANT — interaction rules:
    Shabbat entry:  LONG PRESS button 9 for 10 seconds.
    Hot dispense:   Push-to-drink safety sequence:
                      1. Hold hot button (1 or 2) → 2s
                      2. At T+0.5s: also press Menu (3) → hold 1s
                      3. Release Menu at T+1.5s, release hot at T+2s
                      → dispensing starts
    Cold/Ambient:   Single press (no push-to-drink).
    Extra Hot:      Single press 8.

For automated testing with push-to-drink enabled, use:
    hmi.press_hot_push_to_drink()   — sequences both buttons precisely
OR disable the safety lock for the test session:
    hmi.set_push_to_drink(False)    — set_param 124 0
    ... run tests ...
    hmi.set_push_to_drink(True)     — restore
"""

import serial
import time
import re
import threading
import logging
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_BAUD    = 115200
DEFAULT_TIMEOUT = 3.0

# Push-to-drink param ID on HMI
_PARAM_PUSH_TO_DRINK   = 124   # User.Setting.Bit2.pushToDrink
_PARAM_SHABBAT_MODE    = 165   # Shabbat_mode (active state)
_PARAM_SHABBAT_MANUAL  = 171   # Shabbat_mode_override_manual
_PARAM_BOILING_TEMP    = 29    # Core.BoilingTemp (millidegrees)
_PARAM_REGION          = 45    # User.Region (0=IL, 1=US)
_PARAM_HEATER_ON       = 23    # SystemConfig.UserSetting.bit.heater_on
_PARAM_SHABBAT_FLAG    = 152   # User.Setting.Bit2.ShabbatMode


class HmiTerminalError(Exception):
    pass


class HmiTerminal:
    """
    ASCII command interface to the Tamar HMI (ESP32).

    Dispensing rule summary:
        Cold / Ambient      → single press, no hold required
        Hot (pushToDrink)   → 2-button sequence (see press_hot_push_to_drink)
        Shabbat entry/exit  → 10-second long press on button 9
        Extra Hot           → single press 8

    Context manager:
        with HmiTerminal("COM5") as hmi:
            hmi.press_cold_cup()
            hmi.press_hot_push_to_drink()
    """

    BUTTON_HOT_CUP      = 1
    BUTTON_HOT_JUG      = 2
    BUTTON_MENU         = 3
    BUTTON_COLD_CUP     = 4
    BUTTON_COLD_JUG     = 5
    BUTTON_AMB_CUP      = 6
    BUTTON_AMB_JUG      = 7
    BUTTON_EXTRA_HOT    = 8
    BUTTON_SHABBAT      = 9

    # Shabbat long-press duration (ms)
    SHABBAT_LONG_PRESS_MS = 10_000

    # Push-to-drink timing (ms)
    PTD_HOT_HOLD_MS     = 2_000   # total hold duration on hot button
    PTD_MENU_DELAY_MS   = 500     # wait before pressing menu
    PTD_MENU_HOLD_MS    = 1_000   # how long to hold menu

    def __init__(self, port: str, baud: int = DEFAULT_BAUD,
                 timeout: float = DEFAULT_TIMEOUT):
        self.port    = port
        self.baud    = baud
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._lock   = threading.Lock()

    # ── Context manager ──────────────────────────────────────────────────────
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

    def open(self):
        self._ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        time.sleep(0.5)
        self._ser.reset_input_buffer()
        log.info("HMI terminal port %s opened", self.port)

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()

    # ── Low-level ────────────────────────────────────────────────────────────
    def _send(self, cmd: str, wait_ms: int = 400) -> str:
        with self._lock:
            line = (cmd.strip() + "\r\n").encode()
            self._ser.write(line)
            log.debug("HMI TX: %s", cmd)
            time.sleep(wait_ms / 1000.0)
            lines = []
            while self._ser.in_waiting:
                raw = self._ser.readline().decode(errors="replace").rstrip()
                if raw:
                    clean = re.sub(r'\x1b\[[0-9;]*[mA-Z]', '', raw).strip()
                    if clean:
                        log.debug("HMI RX: %s", clean)
                        lines.append(clean)
        return "\n".join(lines)

    # ── Single press (tap) ────────────────────────────────────────────────────
    def press(self, button: int, hold_ms: int = 0, wait_ms: int = 400) -> str:
        """
        Press button N.

        hold_ms=0 (default) → single tap: sends  "press <N>\r\n"
        hold_ms>0           → held press:  sends  "press <N> <hold_ms>\r\n"
                              The HMI firmware holds the key for hold_ms ms
                              and the call blocks until the HMI responds.

        Example — Shabbat long press (10s):
            hmi.press(9, hold_ms=10_000)   # single command, blocks 10s

        For cold/ambient dispensing (no hold needed):
            hmi.press(4)

        For hot dispensing with push-to-drink disabled:
            hmi.press(1)
        """
        if hold_ms > 0:
            cmd = f"press {button} {hold_ms}"
            # Block for the hold duration — the HMI processes the long press
            resp = self._send(cmd, wait_ms=hold_ms + 500)
        else:
            cmd = f"press {button}"
            resp = self._send(cmd, wait_ms=wait_ms)
        log.info("HMI %s → %s", cmd, resp[:80] if resp else "")
        return resp

    # ── Long press — Shabbat entry / exit ────────────────────────────────────
    def press_shabbat(self) -> str:
        """
        Enter or exit Shabbat mode.

        Sends: press 9 10000
        The hold duration (10,000 ms) is embedded IN the press command —
        the HMI firmware holds the key for 10s before returning.

        Preconditions for "Prepare to Shabbat" to trigger:
            T_tank  > BSP (96°C)
            T_boost > BSP (96°C)
            LF (hot float) = WET  ← tank is FULL

        Call this ONLY after confirming the above conditions via sim/hc.
        """
        log.info("Shabbat: sending press 9 hold=10000ms...")
        return self.press(self.BUTTON_SHABBAT, hold_ms=self.SHABBAT_LONG_PRESS_MS)

    # ── Push-to-drink — hot water ─────────────────────────────────────────────
    def press_hot_push_to_drink(self, button: int = BUTTON_HOT_CUP) -> None:
        """
        Hot water dispense with push-to-drink safety lock enabled.

        Sequence:
            T=0ms:    press hot button (1 or 2) — hold start
            T=500ms:  also press menu (3) — hold start
            T=1500ms: release menu (stop pressing 3)
            T=2000ms: release hot button
            → dispensing starts

        Implementation: simulates hold by sending the hot button repeatedly
        during the hold window, then adds the menu press at T+500ms.
        """
        assert button in (self.BUTTON_HOT_CUP, self.BUTTON_HOT_JUG), \
            "button must be 1 (Hot Cup) or 2 (Hot Jug)"

        log.info("Hot push-to-drink: button %d + menu (3), sequence start", button)
        t0 = time.time()

        # Phase 1: hold hot button (T=0 → T=500ms) — 100ms intervals
        while (time.time() - t0) * 1000 < self.PTD_MENU_DELAY_MS:
            self._send(f"press {button}", wait_ms=0)
            time.sleep(0.1)

        # Phase 2: hold hot + menu (T=500ms → T=1500ms)
        menu_deadline = t0 + (self.PTD_MENU_DELAY_MS + self.PTD_MENU_HOLD_MS) / 1000.0
        log.info("  + pressing menu (3) at T=%.0fms",
                 (time.time() - t0) * 1000)
        while time.time() < menu_deadline:
            self._send(f"press {button}", wait_ms=0)
            self._send(f"press {self.BUTTON_MENU}", wait_ms=0)
            time.sleep(0.1)

        # Phase 3: release menu, keep hot until T=2000ms
        hot_deadline = t0 + self.PTD_HOT_HOLD_MS / 1000.0
        log.info("  - menu released at T=%.0fms", (time.time() - t0) * 1000)
        while time.time() < hot_deadline:
            self._send(f"press {button}", wait_ms=0)
            time.sleep(0.1)

        log.info("Hot push-to-drink complete at T=%.0fms",
                 (time.time() - t0) * 1000)

    def press_hot_jug_push_to_drink(self) -> None:
        """Hot Jug with push-to-drink (button 2)."""
        self.press_hot_push_to_drink(button=self.BUTTON_HOT_JUG)

    # ── Cold / Ambient (no push-to-drink) ────────────────────────────────────
    def press_cold_cup(self) -> str:
        """Cold Cup — single press 4."""
        return self.press(self.BUTTON_COLD_CUP)

    def press_cold_jug(self) -> str:
        """Cold Jug — single press 5."""
        return self.press(self.BUTTON_COLD_JUG)

    def press_ambient_cup(self) -> str:
        """Ambient Cup — single press 6."""
        return self.press(self.BUTTON_AMB_CUP)

    def press_ambient_jug(self) -> str:
        """Ambient Jug — single press 7."""
        return self.press(self.BUTTON_AMB_JUG)

    def press_extra_hot(self) -> str:
        """Extra Hot — single press 8."""
        return self.press(self.BUTTON_EXTRA_HOT)

    def press_menu(self) -> str:
        """Menu — single press 3."""
        return self.press(self.BUTTON_MENU)

    # ── Push-to-drink control ─────────────────────────────────────────────────
    def set_push_to_drink(self, enable: bool) -> str:
        """
        Enable or disable the push-to-drink safety lock.
        Param 124: User.Setting.Bit2.pushToDrink

        RECOMMENDED for automated tests:
            hmi.set_push_to_drink(False)   # disable before tests
            ...
            hmi.set_push_to_drink(True)    # restore after tests
        """
        val = 1 if enable else 0
        resp = self.set_param(_PARAM_PUSH_TO_DRINK, val)
        log.info("pushToDrink = %d", val)
        return resp

    def is_push_to_drink_enabled(self) -> bool:
        """Check if push-to-drink is currently active."""
        v = self.get_param_value(_PARAM_PUSH_TO_DRINK)
        return bool(v)

    # ── Context manager: disable push-to-drink for test scope ────────────────
    class _NoPushToDrink:
        def __init__(self, hmi):
            self._hmi = hmi
            self._was_enabled = False
        def __enter__(self):
            self._was_enabled = self._hmi.is_push_to_drink_enabled()
            if self._was_enabled:
                self._hmi.set_push_to_drink(False)
        def __exit__(self, *_):
            if self._was_enabled:
                self._hmi.set_push_to_drink(True)

    def no_push_to_drink(self):
        """
        Context manager: disable push-to-drink for the duration of a block.
            with hmi.no_push_to_drink():
                hmi.press(HmiTerminal.BUTTON_HOT_CUP)
        """
        return self._NoPushToDrink(self)

    # ── Script runner ─────────────────────────────────────────────────────────
    def run_script(self, script: str) -> None:
        """
        Execute a button script (Excel Dispense Script format):
            press 1; sleep(1000); press 4; sleep(30000);

        NOTE: Hot button presses in scripts bypass push-to-drink
              (assumes PTD is disabled or they use the terminal directly).
        """
        tokens = [t.strip() for t in script.replace('\n', ' ').split(';') if t.strip()]
        for token in tokens:
            if token.startswith('press '):
                parts = token.split()
                n = int(parts[1])
                self.press(n)
                log.info("Script: press %d", n)
            elif token.startswith('sleep('):
                m = re.match(r'sleep\((\d+)\)', token)
                if m:
                    ms = int(m.group(1))
                    log.info("Script: sleep %dms", ms)
                    time.sleep(ms / 1000.0)
            else:
                log.warning("Script: unknown token '%s'", token)

    # ── Parameters ───────────────────────────────────────────────────────────
    def get_param(self, param_id: Optional[int] = None) -> str:
        """Get all parameters or a specific one by ID."""
        if param_id is not None:
            return self._send(f"get_param {param_id}", wait_ms=500)
        return self._send("get_param", wait_ms=2000)

    def set_param(self, param_id: int, value) -> str:
        resp = self._send(f"set_param {param_id} {value}", wait_ms=600)
        log.info("set_param %d = %s → %s", param_id, value, resp[:60])
        return resp

    def get_param_value(self, param_id: int) -> Optional[int]:
        resp = self.get_param(param_id)
        m = re.search(rf'\[{param_id}\].*?=\s*(\d+)', resp)
        return int(m.group(1)) if m else None

    # ── Shabbat parameters ────────────────────────────────────────────────────
    def is_shabbat_active(self) -> bool:
        """Param 165: Shabbat_mode current state."""
        return bool(self.get_param_value(_PARAM_SHABBAT_MODE))

    def set_shabbat_override_manual(self, enable: bool) -> str:
        """Param 171: Shabbat_mode_override_manual."""
        return self.set_param(_PARAM_SHABBAT_MANUAL, 1 if enable else 0)

    # ── Diagnostics ───────────────────────────────────────────────────────────
    def reset(self) -> None:
        self._send("reset", wait_ms=200)
        time.sleep(5.0)
        log.info("HMI reset complete")

    def get_rtc(self) -> str:
        return self._send("get_rtc", wait_ms=400)

    def set_rtc(self, day: int, month: int, year: int,
                hour: int = 0, minute: int = 0, second: int = 0) -> str:
        return self._send(
            f"set_rtc {day:02d}/{month:02d}/{year} {hour:02d}:{minute:02d}:{second:02d}",
            wait_ms=500)

    def get_temp(self) -> str:
        return self._send("get_temp", wait_ms=300)

    def get_inputs(self, board: int = 1) -> str:
        return self._send(f"get_inputs_{board}", wait_ms=300)

    def get_outputs(self, board: int = 1) -> str:
        return self._send(f"get_outputs_{board}", wait_ms=300)

    def get_errors(self) -> str:
        return self._send("get_error", wait_ms=300)

    def clear_error(self, error_num: int) -> str:
        return self._send(f"clear_error {error_num}", wait_ms=300)

    def fast_wash(self) -> str:
        return self._send("fast_wash", wait_ms=500)

    def skip_process(self) -> str:
        return self._send("skip_process", wait_ms=500)

    def help(self) -> str:
        return self._send("help", wait_ms=1000)
