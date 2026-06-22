"""
core/base_serial.py — общая база для HMI и Hydraulic соединений.
"""
import re
import time
import serial
from datetime import datetime


class BaseSerial:
    DEVICE_NAME = "Device"

    def __init__(self, port: str, baudrate: int = 115200, log_callback=None):
        self.port = port
        self.baudrate = baudrate
        self.log_callback = log_callback or print
        self.ser = None
        self._log_lines = []

    def connect(self):
        self._log(f"[{self.DEVICE_NAME}] Connecting to {self.port} @ {self.baudrate}...")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=2)
        time.sleep(2)
        self._log(f"[{self.DEVICE_NAME}] Connected.")

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            self._log(f"[{self.DEVICE_NAME}] Disconnected.")

    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def send_command(self, command: str, retries: int = 3, wait: float = 0.2):
        for attempt in range(1, retries + 1):
            try:
                self.ser.reset_input_buffer()
                self.ser.write((command + '\n').encode())
                time.sleep(wait)
                lines = []
                timeout_at = time.time() + 2.0
                while time.time() < timeout_at:
                    line = self.ser.readline().decode(errors='replace').strip()
                    if not line:
                        break
                    clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                    clean = re.sub(r'^I \(\d+\) \w+: ', '', clean)
                    if clean:
                        lines.append(clean)
                resp = '\n'.join(lines)
                self._record(command, resp)
                if resp and "CMD EXECUTE ERROR" not in resp:
                    return resp
                self._log(f"[WARN] Attempt {attempt}: bad resp")
            except Exception as exc:
                self._log(f"[ERROR] attempt {attempt}: {exc}")
            time.sleep(0.5)
        self._record(command, "FAILED")
        return None

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        full = f"[{ts}] {msg}"
        self._log_lines.append(full)
        self.log_callback(full)

    def _record(self, cmd: str, resp: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] >> {cmd!r:35s} | << {resp[:120]!r}"
        self._log_lines.append(line)
        self.log_callback(line)

    def get_full_log(self) -> str:
        return '\n'.join(self._log_lines)

    def listen(self, duration: float, stop_substr=None):
        """Read raw lines from the serial stream for `duration` seconds
        (without sending anything). Returns the list of decoded lines.

        The device prints unsolicited debug lines such as
        'HOT 1015 mil', 'HW fil: 1015', 'Flow meter 531', 'COLD 531 mil',
        and 'Hot filling ... -> FULL'. This captures them.

        If `stop_substr` is given, listening stops early once a line
        containing that substring appears.
        """
        lines = []
        if not self.is_connected():
            return lines
        deadline = time.time() + duration
        buf = ""
        while time.time() < deadline:
            try:
                chunk = self.ser.read(256)
            except Exception:
                break
            if chunk:
                buf += chunk.decode(errors="replace")
                while "\n" in buf:
                    raw, buf = buf.split("\n", 1)
                    clean = re.sub(r'\x1b\[[0-9;]*m', '', raw).strip()
                    if clean:
                        lines.append(clean)
                        if stop_substr and stop_substr in clean:
                            return lines
            else:
                time.sleep(0.05)
        if buf.strip():
            lines.append(buf.strip())
        return lines