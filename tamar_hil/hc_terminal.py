"""
hc_terminal.py — Direct HC terminal UART interface (P1-2/3, ADDON_TX/RX)
ASCII protocol, 115200-8N1.

This is the HC firmware's built-in debug/control terminal.
Commands documented in terminal.c (Tamar HC firmware).

Usage:
    with HCTerminal("/dev/ttyACM1") as hc:
        hc.heating_on()
        hc.pour_hot(5)          # pour hot for 5 seconds
        hc.shabbat_on()         # enter Shabbat prepare mode
        status = hc.status()    # get full system status

IMPORTANT:
    After applying terminal_patch.diff to terminal.c, shabbat_on / shabbat_off
    are available. Without the patch, use the HMI binary protocol instead.
"""

import serial
import time
import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_BAUD    = 115200
DEFAULT_TIMEOUT = 3.0


class HCTerminalError(Exception):
    pass


class HCTerminal:
    """
    ASCII command interface to the HC firmware terminal UART (ADDON_TX/RX, P1-2/3).
    All commands are sent as plain ASCII terminated with \\r\\n.
    """

    def __init__(self, port: str, baud: int = DEFAULT_BAUD,
                 timeout: float = DEFAULT_TIMEOUT):
        self.port    = port
        self.baud    = baud
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None

    # ── Context manager ──────────────────────────────────────────────────────
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

    def open(self):
        self._ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        time.sleep(0.3)
        self._ser.reset_input_buffer()
        log.info("HC terminal port %s opened", self.port)

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()
            log.info("HC terminal port closed")

    # ── Low-level ────────────────────────────────────────────────────────────
    def _send(self, cmd: str, wait_ms: int = 200) -> str:
        line = (cmd.strip() + "\r\n").encode()
        self._ser.write(line)
        log.debug("HC TX: %s", cmd)
        time.sleep(wait_ms / 1000.0)
        lines = []
        while self._ser.in_waiting:
            raw = self._ser.readline().decode(errors="replace").rstrip()
            if raw:
                log.debug("HC RX: %s", raw)
                lines.append(raw)
        return "\n".join(lines)

    # ── Simulation mode ───────────────────────────────────────────────────────
    def enable_simulation(self, mask: int = 63) -> str:
        """Enable all HC simulation channels. mask=63 enables all."""
        return self._send(f"simulate={mask}")

    def set_temp(self, channel: int, enable: int, value_mdeg: int) -> str:
        """
        Inject temperature via simulate_integers command.
        channel: 0=T_tank, 1=T_boost, 3=CWT
        value_mdeg: temperature in millidegrees (72°C = 72000)
        """
        return self._send(f"simulate_integers={channel} {enable} {value_mdeg}")

    def set_temp_deg(self, channel: int, temp_c: float) -> str:
        """Inject temperature in degrees Celsius (convenience)."""
        return self.set_temp(channel, 1, int(temp_c * 1000))

    def set_inputs(self, lf: int, tray: int, se: int, le: int, cold: int) -> str:
        """
        Inject electrode states: simulate_inputs=lf tray se le cold
        0=WET (conducting), 1=DRY (open)
        gpio_inputs order: [0]=LF [1]=TRAY [2]=SE [3]=LE [4]=COLD_ELS
        """
        return self._send(f"simulate_inputs={lf} {tray} {se} {le} {cold}")

    def set_flow_simulate(self, enable: int) -> str:
        """Enable (1) or disable (0) software flow simulation."""
        return self._send(f"simulate_flow={enable}")

    # ── Dispense commands ─────────────────────────────────────────────────────
    def pour_hot(self, seconds: int) -> str:
        """
        Start hot water dispense for N seconds.
        Calls DispenserStart(DISPENSER_HOT) directly in HC.
        """
        resp = self._send(f"pour_hot {seconds}", wait_ms=300)
        log.info("pour_hot %ds → %s", seconds, resp)
        return resp

    def pour_cold(self, seconds: int) -> str:
        """Start cold water dispense for N seconds."""
        resp = self._send(f"pour_cold {seconds}", wait_ms=300)
        log.info("pour_cold %ds → %s", seconds, resp)
        return resp

    def pour_ambient(self, seconds: int) -> str:
        """Start ambient water dispense for N seconds."""
        resp = self._send(f"pour_ambient {seconds}", wait_ms=300)
        log.info("pour_ambient %ds → %s", seconds, resp)
        return resp

    def stop_dispense(self) -> str:
        """Stop any active dispense."""
        resp = self._send("stop_dispense", wait_ms=200)
        log.info("stop_dispense → %s", resp)
        return resp

    # ── State transitions ─────────────────────────────────────────────────────
    def extra_hot_on(self) -> str:
        """
        Trigger Extra Hot mode (heater_extra_hot_set()).
        Terminal command: ex_on
        """
        resp = self._send("ex_on", wait_ms=200)
        log.info("ex_on → %s", resp)
        return resp

    def shabbat_on(self) -> str:
        """
        Enter Shabbat prepare mode.
        Requires terminal_patch.diff applied to terminal.c.
        Triggers: heater_start() + shabbat_state_set(COMMON_STATE_START_PREPARE_SHABBAT)
        """
        resp = self._send("shabbat_on", wait_ms=300)
        log.info("shabbat_on → %s", resp)
        return resp

    def shabbat_off(self) -> str:
        """
        Exit Shabbat mode → returns to Idle.
        Requires terminal_patch.diff applied to terminal.c.
        """
        resp = self._send("shabbat_off", wait_ms=300)
        log.info("shabbat_off → %s", resp)
        return resp

    def set_shabbat_period_5min(self) -> str:
        """Accelerate Shabbat 60-min cycle to 5 min (for testing). min5 command."""
        return self._send("min5", wait_ms=200)

    def heating_on(self) -> str:
        """Enable heater after HC reset."""
        return self._send("heating_on", wait_ms=200)

    def heating_off(self) -> str:
        """Disable heater."""
        return self._send("heating_off", wait_ms=200)

    def reset(self) -> str:
        """Reset HC MCU."""
        resp = self._send("reset", wait_ms=500)
        time.sleep(2.0)   # wait for boot
        return resp

    # ── Status & monitoring ───────────────────────────────────────────────────
    def status(self) -> str:
        """Get full system status (state machine states, temperatures, I/O)."""
        return self._send("status", wait_ms=500)

    def get_temp(self) -> str:
        """Get all temperatures."""
        return self._send("get_temp", wait_ms=300)

    def get_inputs(self) -> str:
        """Get electrode / flow input states."""
        return self._send("get_inputs", wait_ms=300)

    def get_outputs(self) -> str:
        """Get valve / heater output states."""
        return self._send("get_outputs", wait_ms=300)

    def get_errors(self) -> str:
        """List all active HC errors."""
        return self._send("error", wait_ms=300)

    def clear_error(self, error_id: int) -> str:
        """Clear a specific error by ID."""
        return self._send(f"error={error_id} 0", wait_ms=200)

    # ── Parsed helpers ────────────────────────────────────────────────────────
    def get_common_state(self) -> str:
        """Return the 'Common state' keyword from STATUS output."""
        resp = self.status()
        m = re.search(r'Common state:\s*(\w+)', resp)
        return m.group(1) if m else "UNKNOWN"

    def get_heater_state(self) -> str:
        """Return the 'Heater' state keyword from STATUS output."""
        resp = self.status()
        m = re.search(r'Heater:\s*(\w+)', resp)
        return m.group(1) if m else "UNKNOWN"

    def get_dispenser_state(self) -> str:
        """Return the 'Dispenser' state keyword from STATUS output."""
        resp = self.status()
        m = re.search(r'Dispenser:\s*(\w+)', resp)
        return m.group(1) if m else "UNKNOWN"

    def wait_for_state(self, keyword: str, poll_s: float = 2.0,
                        timeout_s: float = 300.0) -> bool:
        """
        Poll STATUS until keyword appears in the output.
        Example: hc.wait_for_state("SHABBAT")
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if keyword.upper() in self.status().upper():
                return True
            time.sleep(poll_s)
        return False

    def wait_for_dispense_active(self, timeout_s: float = 30.0) -> bool:
        """Wait until dispenser is active (valves open)."""
        return self.wait_for_state("DISPENSE", timeout_s=timeout_s)

    def wait_for_dispense_done(self, timeout_s: float = 60.0) -> bool:
        """Wait until dispensing has stopped."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            state = self.get_dispenser_state()
            if state in ("IDLE", "IDLE_STATE", "DISABLE_STATE"):
                return True
            time.sleep(1.0)
        return False
