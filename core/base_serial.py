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

    # ── connect / disconnect ─────────────────────────────────────────
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

    # ── low-level ────────────────────────────────────────────────────
    def send_command(self, command: str, retries: int = 3, wait: float = 0.2) -> str | None:
        for attempt in range(1, retries + 1):
            try:
                self.ser.reset_input_buffer()
                self.ser.write((command + '\n').encode())
                time.sleep(wait)
                # читаем все доступные строки
                lines = []
                timeout_at = time.time() + 2.0
                while time.time() < timeout_at:
                    line = self.ser.readline().decode(errors='replace').strip()
                    if not line:
                        break
                    # убираем ANSI escape-коды
                    clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                    # убираем префикс ESP-IDF "I (xxxxx) TERMINAL: "
                    clean = re.sub(r'^I \(\d+\) \w+: ', '', clean)
                    if clean:
                        lines.append(clean)
                resp = '\n'.join(lines)
                self._record(command, resp)
                if resp and "CMD EXECUTE ERROR" not in resp:
                    return resp
                self._log(f"[WARN] Attempt {attempt}: bad resp")
            except Exception as e:
                self._log(f"[ERROR] attempt {attempt}: {e}")
            time.sleep(0.5)
        self._record(command, "FAILED")
        return None

    # ── logging ──────────────────────────────────────────────────────
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