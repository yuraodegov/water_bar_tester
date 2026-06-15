"""
core/hc_driver.py — Hydraulic Controller terminal driver.
Wraps BaseSerial with HC-specific commands and response parsers.
115200 baud, 8N1, line ending CRLF.
"""
import re
import time
from core.base_serial import BaseSerial

TEMP_TTANK = 0
TEMP_TBOOST = 1
TEMP_TCW = 3

IN_HWT_FLOAT_UP = 0
IN_TRAY_ELEC = 1
IN_HWT_OVERFLOW = 2
IN_HWT_ELEC_UP = 3
IN_COLD_ELEC = 4
IN_LEAKAGE = 5
INPUT_REAL = 2

OUT_MAIN_HEATER = "HEATER"
OUT_SMALL_HEATER = "SEC_HEATER"
OUT_COMPRESSOR = "COMPRESSOR"

HEAT_IDLE = {"IDLE", "START_IDLE"}
HEAT_EXTRA = {"EXTRA_HOT", "START_EXTRA_HOT"}
CRITICAL_ERROR_IDS = {18, 22, 55, 56}

_RE_STATUS = re.compile(
    r"Common:\s*(?P<shabbat>\S+)\s+"
    r"Cooler:\s*(?P<cooler>ON|OFF)\s+"
    r"Heater:\s*(?P<heater>\S+)\s+"
    r"Dispenser:\s*(?P<dispenser>\S+)\s+"
    r"Hot Filling:\s*(?P<hot_filling>\S+)"
)
_RE_TEMP = re.compile(
    r"Ttank:\s*(?P<ttank>-?\d+\.\d+)\s*C,\s*"
    r"Tboost:\s*(?P<tboost>-?\d+\.\d+)\s*C,\s*"
    r"TCW:\s*(?P<tcw>-?\d+\.\d+)\s*C"
)
_RE_OUT = re.compile(r"^\s*(?P<name>\S[\S ]*?)\s+-\s+(?P<val>DISABLED|\d+%?)\s*$")
_RE_PARAM = re.compile(r"(?:parameter\s*\[\d+\]:\s*)?(?P<name>\w+)\s*=\s*(?P<val>-?\d+)")


class HCDriver(BaseSerial):
    DEVICE_NAME = "HC"

    def hc_cmd(self, line: str, settle: float = 0.2, read_for: float = 1.2) -> str:
        """
        Send a command to the HC and read the full response.

        The device answers on the first try; 'Bad command' is a real error
        (wrong syntax for this firmware), not a warm-up, so we do NOT retry
        it. Long replies like 'status' stream in several chunks over ~1 s, so
        we keep reading while data is still arriving.
        """
        if not self.is_connected():
            raise RuntimeError("HC not connected")

        # single buffer flush immediately before writing; a second flush with
        # a gap lets async log lines slip in and corrupt the command
        self.ser.reset_input_buffer()
        self.ser.write((line + "\r\n").encode("ascii"))
        time.sleep(settle)
        deadline = time.time() + read_for
        chunks = []
        while time.time() < deadline:
            data = self.ser.read(4096)
            if data:
                chunks.append(data)
                # extend the window while data keeps arriving
                deadline = time.time() + 0.25
        return b"".join(chunks).decode("ascii", errors="ignore")

    def hc_set_param(self, name: str, value: int) -> None:
        # verified syntax: 'set_param=name=value' (no spaces) ->
        # 'New value name=value'. Retry on async-log collision.
        r = self.hc_cmd_clean(f"set_param={name}={value}", read_for=0.8)
        low = r.lower()
        if "must be between" in low or "not in range" in low:
            raise ValueError(f"set_param range error '{name}': {r.strip()!r}")
        if "not found" in low or "not fount" in low:
            raise RuntimeError(f"set_param param not found '{name}'")
        # the full-dump cache is now stale
        self._param_dump = None
        if "new value" in low:
            return
        # fall back to read-back verification
        if self.hc_get_param(name) == value:
            return
        raise RuntimeError(f"set_param failed '{name}': {r.strip()!r}")

    def hc_cmd_clean(self, line: str, settle: float = 0.2,
                     read_for: float = 1.2, tries: int = 4) -> str:
        """
        Send a command and retry while the reply is only 'Bad command'.

        On a busy line the device occasionally sees an async log byte glued
        to the start of the command and rejects it. The same command on a
        clean line succeeds (verified manually), so retrying recovers it.
        A short pause before each retry lets the async burst drain.
        """
        last = ""
        for _ in range(tries):
            last = self.hc_cmd(line, settle=settle, read_for=read_for)
            stripped = last.strip()
            if stripped and "Bad command" not in stripped:
                return last
            time.sleep(0.4)
        return last

    def hc_get_param_dump(self, force: bool = False) -> str:
        """
        Return the full 'get_param' dump, reading until it looks complete.

        The HC streams ~46 parameter lines over ~2 s, so a short read can cut
        off the tail (the cooler_* params come last). We read with a long
        window and retry until the last expected parameter is present. The
        result is cached for the rest of the run (pass force=True to refresh).
        """
        if not force and getattr(self, "_param_dump", None):
            return self._param_dump
        dump = ""
        for _ in range(4):
            dump = self.hc_cmd("get_param", settle=0.2, read_for=3.0)
            # the dump is complete once the final parameter has arrived
            if "shabbat_bypass" in dump and "Bad command" not in dump:
                self._param_dump = dump
                return dump
            time.sleep(0.4)
        # keep whatever we got (parsing will raise if the param is missing)
        self._param_dump = dump
        return dump

    def hc_get_param(self, name: str) -> int:
        # fast path: 'get_param=name' returns 'parameter [NN]: name = val unit'
        # (retry on async-log collision). Fall back to the full dump if needed.
        r = self.hc_cmd_clean(f"get_param={name}", read_for=0.8)
        for m in _RE_PARAM.finditer(r):
            if m.group("name") == name:
                return int(m.group("val"))
        # fallback: parse from the full bare 'get_param' dump
        dump = self.hc_get_param_dump()
        for m in _RE_PARAM.finditer(dump):
            if m.group("name") == name:
                return int(m.group("val"))
        dump = self.hc_get_param_dump(force=True)
        for m in _RE_PARAM.finditer(dump):
            if m.group("name") == name:
                return int(m.group("val"))
        raise RuntimeError(f"param '{name}' not found in get_param dump")

    def heater_calibration_flag(self) -> int:
        # 'heater_calibration' is a dedicated command (not an eeprom param);
        # it replies 'Heater calibration flag = N'.
        r = self.hc_cmd_clean("heater_calibration", read_for=0.8)
        m = re.search(r"flag\s*=\s*(-?\d+)", r)
        if m:
            return int(m.group(1))
        raise RuntimeError(f"could not read calibration flag from: {r.strip()!r}")

    def sim_all_on(self) -> None:
        self.hc_cmd("simulate=63")

    def inject_temp(self, channel: int, deg_c: int) -> None:
        self.hc_cmd(f"simulate_integers={channel} 1 {deg_c}")

    def release_temp(self, channel: int) -> None:
        self.hc_cmd(f"simulate_integers={channel} 0 0")

    def inject_inputs(self, values: dict) -> None:
        vec = [values.get(i, INPUT_REAL) for i in range(6)]
        self.hc_cmd("simulate_inputs=" + " ".join(str(v) for v in vec))

    def hc_reset(self) -> None:
        self.hc_cmd("reset", settle=2.0, read_for=2.5)

    def heating(self, on: bool) -> None:
        self.hc_cmd("heating_on" if on else "heating_off")

    def extra_hot(self) -> None:
        self.hc_cmd("ex_on")

    def pour_hot(self, seconds: int) -> None:
        self.hc_cmd(f"pour_hot={seconds}")

    def hc_stop_dispense(self) -> None:
        self.hc_cmd("stop_dispense")

    def min5(self) -> None:
        self.hc_cmd("min5")

    def inject_error(self, error_id: int, active: bool = True) -> None:
        self.hc_cmd(f"error={error_id} {1 if active else 0}")

    def read_errors(self) -> str:
        return self.hc_cmd("error")

    def hc_status(self) -> dict:
        r = self.hc_cmd_clean("status", read_for=1.5)
        m = _RE_STATUS.search(r)
        if not m:
            raise RuntimeError(f"could not parse status: {r.strip()!r}")
        d = m.groupdict()
        d["outputs"] = self._parse_outputs(r)
        return d

    def hc_temps(self) -> dict:
        # 'get_temp' is not valid on this firmware (returns 'Bad command'),
        # so read the temperatures straight from the status block, which
        # lists 'TempTank / TempBoost / CWTtemp'.
        r2 = self.hc_cmd_clean("status", read_for=1.5)
        m2 = re.search(
            r"TempTank:\s*(\d+)\s+TempBoost:\s*(\d+)\s+CWTtemp:\s*(\d+)", r2)
        if m2:
            return {"ttank": float(m2.group(1)),
                    "tboost": float(m2.group(2)),
                    "tcw": float(m2.group(3))}
        raise RuntimeError(f"could not read temps from status: {r2.strip()!r}")

    def hc_outputs(self) -> dict:
        return self._parse_outputs(self.hc_cmd("get_io", read_for=1.0))

    def heater_duty(self):
        return self.hc_outputs().get(OUT_MAIN_HEATER)

    def small_heater_duty(self):
        return self.hc_outputs().get(OUT_SMALL_HEATER)

    def compressor_on(self) -> bool:
        return str(self.hc_outputs().get(OUT_COMPRESSOR)) in ("1", "True")

    @classmethod
    def _parse_outputs(cls, text: str) -> dict:
        out = {}
        in_block = False
        for raw in text.splitlines():
            if raw.strip().startswith("Outputs:"):
                in_block = True
                continue
            if not in_block:
                continue
            m = _RE_OUT.match(raw)
            if not m:
                continue
            name = m.group("name").strip()
            val = m.group("val")
            if val == "DISABLED":
                out[name] = None
            elif val.endswith("%"):
                out[name] = int(val[:-1])
            else:
                out[name] = int(val)
        return out