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

    def hc_cmd(self, line: str, settle: float = 0.15, read_for: float = 0.5) -> str:
        if not self.is_connected():
            raise RuntimeError("HC not connected")
        self.ser.reset_input_buffer()
        self.ser.write((line + "\r\n").encode("ascii"))
        time.sleep(settle)
        deadline = time.time() + read_for
        chunks = []
        while time.time() < deadline:
            data = self.ser.read(4096)
            if data:
                chunks.append(data)
                deadline = time.time() + 0.08
        return b"".join(chunks).decode("ascii", errors="ignore")

    def hc_set_param(self, name: str, value: int) -> None:
        for cmd in (f"set_param={name}={value}", f"set_param {name} {value}"):
            r = self.hc_cmd(cmd, read_for=0.8)
            if "New value" in r or "CMD EXECUTE OK" in r:
                return
            if "must be between" in r or "Not in range" in r:
                raise ValueError(f"set_param range error '{name}': {r.strip()!r}")
        raise RuntimeError(f"set_param failed '{name}': {r.strip()!r}")

    def hc_get_param(self, name: str) -> int:
        # device may use 'get_param=name' or 'get_param name'; try both,
        # and read for longer because the HC spams async log lines.
        for cmd in (f"get_param={name}", f"get_param {name}"):
            r = self.hc_cmd(cmd, read_for=0.8)
            for m in _RE_PARAM.finditer(r):
                if m.group("name") == name:
                    return int(m.group("val"))
        raise RuntimeError(f"could not read param '{name}' from: {r.strip()!r}")

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
        r = self.hc_cmd("status", read_for=0.6)
        m = _RE_STATUS.search(r)
        if not m:
            raise RuntimeError(f"could not parse status: {r.strip()!r}")
        d = m.groupdict()
        d["outputs"] = self._parse_outputs(r)
        return d

    def hc_temps(self) -> dict:
        # retry: HC sometimes returns 'Bad command' when busy with async logs
        for _ in range(3):
            r = self.hc_cmd("get_temp", read_for=0.8)
            m = _RE_TEMP.search(r)
            if m:
                return {k: float(v) for k, v in m.groupdict().items()}
            time.sleep(0.3)
        raise RuntimeError(f"could not parse get_temp: {r.strip()!r}")

    def hc_outputs(self) -> dict:
        return self._parse_outputs(self.hc_cmd("get_io", read_for=0.6))

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