"""
simulator.py — Nucleo-G071RB HIL Simulator UART interface
Controls sensor injection (NTC, electrodes, flow) and reads output monitor.

For HC state control (dispense, Shabbat, Extra Hot), use HCTerminal (hc_terminal.py).

Full test setup:
    sim = SimulatorUART("COM3")   ← Nucleo (sensors + monitor)
    hc  = HCTerminal("COM4")      ← HC terminal P1-2/3 (commands)
"""

import serial
import time
import re
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_PORT    = "COM3"
DEFAULT_BAUD    = 115200
DEFAULT_TIMEOUT = 2.0


@dataclass
class OutputStatus:
    """Parsed STATUS OUT response from Nucleo simulator."""
    ex_valve_state:    str            # IDLE / OPENING / HOLDING
    ex_valve_freq_hz:  Optional[float]
    ex_valve_duty_pct: Optional[float]
    ex_valve_pass:     Optional[bool]

    relay_comp_active: bool

    heat_main_duty_pct:   Optional[float]
    heat_main_period_ms:  Optional[int]
    heat_main_cycles:     int
    heat_main_freq_pass:  Optional[bool]
    heat_main_duty_pass:  Optional[bool]

    heat_sml_duty_pct:    Optional[float]
    heat_sml_period_ms:   Optional[int]
    heat_sml_cycles:      int

    inlet_valve_state:    str
    inlet_valve_delay_ms: Optional[int]
    inlet_delay_pass:     Optional[bool]

    hot_valve_state:      str         # NEW: HOT_VALVE state
    hot_valve_freq_hz:    Optional[float]
    hot_valve_duty_pct:   Optional[float]

    fan_active:    bool
    raw:           str


class SimulatorError(Exception):
    pass


class SimulatorUART:
    """
    ASCII command interface to the Nucleo-G071RB HIL Simulator.
    Controls: NTC temperature injection (DAC), electrodes (BC547),
              flow sensor (PWM), output monitor (valves, heaters via PC817).

    Context manager:
        with SimulatorUART("COM3") as sim:
            sim.set_temp_tank(72)
            sim.set_electrode("LF", wet=False)
            sim.set_flow(1.6)
            status = sim.get_output_status()
    """

    def __init__(self, port: str = DEFAULT_PORT,
                 baud: int = DEFAULT_BAUD,
                 timeout: float = DEFAULT_TIMEOUT):
        self.port    = port
        self.baud    = baud
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

    def open(self):
        self._ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        time.sleep(0.5)
        self._ser.reset_input_buffer()
        log.info("Simulator port %s opened", self.port)

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()

    # ── Low-level ────────────────────────────────────────────────────────────
    def _send(self, cmd: str) -> str:
        line = (cmd.strip() + "\r\n").encode()
        self._ser.write(line)
        log.debug("SIM TX: %s", cmd)
        lines = []
        deadline = time.time() + self.timeout * 3
        while time.time() < deadline:
            raw = self._ser.readline().decode(errors="replace").rstrip()
            if raw:
                log.debug("SIM RX: %s", raw)
                lines.append(raw)
                if raw.startswith("OK") or raw.startswith("ERR"):
                    break
            else:
                if lines:
                    break
        resp = "\n".join(lines)
        if "ERR" in resp:
            raise SimulatorError(f"Command '{cmd}' failed: {resp}")
        return resp

    def _send_ok(self, cmd: str) -> str:
        resp = self._send(cmd)
        if "OK" not in resp:
            raise SimulatorError(f"No OK for '{cmd}': {resp}")
        return resp

    # ── Temperature injection (MCP4728 DAC) ───────────────────────────────────
    def set_temp_tank(self, temp_c: float) -> None:
        self._send_ok(f"TEMP TANK {temp_c:.1f}")

    def set_temp_boost(self, temp_c: float) -> None:
        self._send_ok(f"TEMP BOOST {temp_c:.1f}")

    def set_temp_cwt(self, temp_c: float) -> None:
        self._send_ok(f"TEMP CWT {temp_c:.1f}")

    # ── Electrode injection (BC547) ───────────────────────────────────────────
    def set_electrode(self, name: str, wet: bool) -> None:
        """name: LF | LE | SE | TRAY | COLD | ALL. wet=True → WET (0)."""
        self._send_ok(f"ELEC {name} {0 if wet else 1}")

    def set_all_electrodes(self, wet: bool) -> None:
        self._send_ok(f"ELEC ALL {0 if wet else 1}")

    # ── Flow injection (TIM2 PWM) ─────────────────────────────────────────────
    def set_flow(self, lpm: float) -> None:
        self._send_ok(f"FLOW {lpm:.2f}")

    def set_flow_cal(self, pulses_per_liter: int) -> None:
        self._send_ok(f"FLOW_CAL {pulses_per_liter}")

    # ── Presets ───────────────────────────────────────────────────────────────
    def preset(self, name: str) -> None:
        self._send_ok(f"PRESET {name}")

    def reset(self) -> None:
        """Reset Nucleo simulator state (does NOT reset HC)."""
        self._send_ok("RESET")

    def reset_output_monitor(self) -> None:
        """Clear output monitor cycle counters."""
        self._send_ok("RESET")

    # ── Status queries ────────────────────────────────────────────────────────
    def status_full(self) -> str:
        return self._send("STATUS")

    def status_out(self) -> str:
        return self._send("STATUS OUT")

    def status_temp(self) -> str:
        return self._send("STATUS TEMP")

    def status_elec(self) -> str:
        return self._send("STATUS ELEC")

    # ── Parsed output monitor ─────────────────────────────────────────────────
    def get_output_status(self) -> OutputStatus:
        return _parse_output_status(self.status_out())

    def get_main_heater_duty(self) -> Optional[float]:
        s = self.get_output_status()
        return s.heat_main_duty_pct if s.heat_main_cycles >= 3 else None

    def get_small_heater_duty(self) -> Optional[float]:
        s = self.get_output_status()
        return s.heat_sml_duty_pct if s.heat_sml_cycles >= 3 else None

    # ── Wait helpers ──────────────────────────────────────────────────────────
    def wait_for_heater_cycles(self, n_cycles: int = 3,
                                poll_interval_s: float = 5.0,
                                timeout_s: float = 120.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.get_output_status().heat_main_cycles >= n_cycles:
                return True
            time.sleep(poll_interval_s)
        return False

    def wait_for_valve_opening(self, channel: str = "EX_VALVE",
                                timeout_s: float = 30.0) -> bool:
        """Wait until a valve channel enters OPENING or HOLDING state."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            st = self.status_out()
            if channel in st and ("OPENING" in st or "HOLDING" in st):
                return True
            time.sleep(0.5)
        return False

    def wait_for_valve_idle(self, channel: str = "EX_VALVE",
                             timeout_s: float = 60.0) -> bool:
        """Wait until a valve channel returns to IDLE."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            st = self.status_out()
            # Find the channel line and check for IDLE
            for line in st.split("\n"):
                if channel in line and "IDLE" in line:
                    return True
            time.sleep(0.5)
        return False

    # ── HC terminal passthrough (convenience when Nucleo bridges to HC) ───────
    def hc_terminal(self, cmd: str) -> str:
        """
        Send a raw command to HC terminal UART.
        This works if the Nucleo firmware bridges to HC terminal (future feature).
        For now, use HCTerminal class directly for HC commands.
        """
        raise NotImplementedError(
            "Use HCTerminal(port_hc) directly. "
            "See hc_terminal.py and conftest.py --port-hc option."
        )

    # ── Legacy HC control (for backward compatibility with old tests) ─────────
    def hc_reset(self) -> None:
        """Legacy: not available via simulator. Use HCTerminal.reset()."""
        raise NotImplementedError("Use hc.reset() via HCTerminal")

    def hc_clear_all_errors(self) -> None:
        """Legacy: not available via simulator. Use HCTerminal.clear_error()."""
        raise NotImplementedError("Use hc.clear_error() via HCTerminal")

    def hc_safe_state(self) -> None:
        """Legacy: not available via simulator. Use conftest._hc_safe_state()."""
        raise NotImplementedError("Use conftest._hc_safe_state(sim, hc)")

    def ramp_temp_boost(self, start_c: float, end_c: float,
                         step_c: float = 1.0, step_delay_s: float = 2.0) -> None:
        t = start_c
        direction = 1.0 if end_c >= start_c else -1.0
        while (direction > 0 and t <= end_c) or (direction < 0 and t >= end_c):
            self.set_temp_boost(round(t, 1))
            time.sleep(step_delay_s)
            t += direction * step_c


# ── Response parser ────────────────────────────────────────────────────────

def _pf(pat: str, text: str) -> Optional[float]:
    m = re.search(pat, text)
    return float(m.group(1)) if m else None

def _pi(pat: str, text: str) -> Optional[int]:
    m = re.search(pat, text)
    return int(m.group(1)) if m else None

def _pb(pat: str, text: str) -> Optional[bool]:
    m = re.search(pat, text, re.IGNORECASE)
    return ("PASS" in m.group(0).upper()) if m else None


def _parse_output_status(raw: str) -> OutputStatus:
    hm_duty   = _pf(r'HEAT_MAIN.*?Duty=([\d.]+)%', raw)
    hm_period = _pi(r'HEAT_MAIN.*?Period=(\d+)ms', raw)
    hm_cycles = _pi(r'HEAT_MAIN.*?Cycles=(\d+)', raw) or 0
    hm_fpass  = _pb(r'HEAT_MAIN.*?\[SPEC.*?\]', raw)
    hm_dpass  = _pb(r'HEAT_MAIN.*?Duty=.*?\[SPEC.*?\]', raw)

    hs_duty   = _pf(r'HEAT_SML.*?Duty=([\d.]+)%', raw)
    hs_period = _pi(r'HEAT_SML.*?Period=(\d+)ms', raw)
    hs_cycles = _pi(r'HEAT_SML.*?Cycles=(\d+)', raw) or 0

    exv_state = "IDLE"
    if "EX_VALVE" in raw:
        if "OPENING" in raw[raw.find("EX_VALVE"):raw.find("EX_VALVE")+60]: exv_state = "OPENING"
        if "HOLDING" in raw[raw.find("EX_VALVE"):raw.find("EX_VALVE")+60]: exv_state = "HOLDING"
    exv_freq = _pf(r'EX_VALVE.*?Freq=([\d.]+)Hz', raw)
    exv_duty = _pf(r'EX_VALVE.*?Duty=([\d.]+)%',  raw)
    exv_pass = _pb(r'EX_VALVE.*?\[SPEC.*?\]', raw)

    hvlv_state = "IDLE"
    if "HOT_VLV" in raw:
        if "OPENING" in raw[raw.find("HOT_VLV"):raw.find("HOT_VLV")+60]: hvlv_state = "OPENING"
        if "HOLDING" in raw[raw.find("HOT_VLV"):raw.find("HOT_VLV")+60]: hvlv_state = "HOLDING"
    hvlv_freq = _pf(r'HOT_VLV.*?Freq=([\d.]+)Hz', raw)
    hvlv_duty = _pf(r'HOT_VLV.*?Duty=([\d.]+)%',  raw)

    comp_active = ("RELAY_COMP" in raw and
                   "ON" in raw[raw.find("RELAY_COMP"):raw.find("RELAY_COMP")+60]
                   if "RELAY_COMP" in raw else False)

    inv_state = "IDLE"
    if "INLET_VLV" in raw:
        if "HOLDING" in raw[raw.find("INLET_VLV"):raw.find("INLET_VLV")+60]: inv_state = "HOLDING"
        if "OPENING" in raw[raw.find("INLET_VLV"):raw.find("INLET_VLV")+60]: inv_state = "OPENING"
    inv_delay = _pi(r'SeqDelay=(\d+)ms', raw)
    inv_dpass = _pb(r'SeqDelay.*?\[SPEC.*?\]', raw)

    fan_active = "FAN" in raw and "ON" in raw[raw.find("FAN"):raw.find("FAN")+40] if "FAN" in raw else False

    return OutputStatus(
        ex_valve_state   = exv_state,
        ex_valve_freq_hz = exv_freq,
        ex_valve_duty_pct= exv_duty,
        ex_valve_pass    = exv_pass,
        relay_comp_active= comp_active,
        heat_main_duty_pct  = hm_duty,
        heat_main_period_ms = hm_period,
        heat_main_cycles    = hm_cycles,
        heat_main_freq_pass = hm_fpass,
        heat_main_duty_pass = hm_dpass,
        heat_sml_duty_pct   = hs_duty,
        heat_sml_period_ms  = hs_period,
        heat_sml_cycles     = hs_cycles,
        inlet_valve_state   = inv_state,
        inlet_valve_delay_ms= inv_delay,
        inlet_delay_pass    = inv_dpass,
        hot_valve_state     = hvlv_state,
        hot_valve_freq_hz   = hvlv_freq,
        hot_valve_duty_pct  = hvlv_duty,
        fan_active          = fan_active,
        raw                 = raw,
    )
