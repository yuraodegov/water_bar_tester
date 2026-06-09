"""
core/hmi_serial.py — соединение с HMI UI.

Команды (из help лога):
  press <key>                   — нажать кнопку
  get_counter <id>              — прочитать счётчик
  set_counter <id> <value>      — сбросить счётчик
  get_param / set_param <id> <v>
  get_temp
  get_error
  get_rtc / set_rtc
  info / ver

Кнопки:
  1 = HOT GLASS     2 = HOT JUG
  4 = COLD GLASS    5 = COLD JUG
  6 = AMB GLASS     7 = AMB JUG
  3 = MENU          8 = FILTERED

Счётчики:
  0 = Total_ml   1 = Filter_ml
  2 = Cold_ml    4 = Amb_ml
"""
import re
import time
from core.base_serial import BaseSerial

DEVICE_NAME = "HMI"

# Кнопки
BUTTONS = {
    "HOT_GLASS":  1,
    "HOT_JUG":    2,
    "MENU":       3,
    "COLD_GLASS": 4,
    "COLD_JUG":   5,
    "AMB_GLASS":  6,
    "AMB_JUG":    7,
    "FILTERED":   8,
}

# Счётчики
COUNTERS = {
    "total":  0,
    "filter": 1,
    "cold":   2,
    "amb":    4,
}


class HmiSerial(BaseSerial):
    DEVICE_NAME = "HMI"

    # ── кнопки ──────────────────────────────────────────────────────
    def press(self, button_id: int, duration_ms: int = 1000) -> str | None:
        """press <id> <duration_ms>"""
        return self.send_command(f"press {button_id} {duration_ms}")

    def press_named(self, name: str, duration_ms: int = 1000) -> str | None:
        """press по имени кнопки: HOT_JUG, COLD_GLASS и т.д."""
        bid = BUTTONS.get(name.upper())
        if bid is None:
            self._log(f"[ERROR] Unknown button name: {name}")
            return None
        return self.press(bid, duration_ms)

    # ── счётчики ─────────────────────────────────────────────────────
    def get_counter(self, counter: str | int) -> float | None:
        """
        get_counter <id>
        Ответ: "COUNTERS: SET [00] Total_ml = 1234567" или просто число.
        Возвращает миллилитры как float.
        """
        cid = COUNTERS.get(str(counter).lower(), counter)
        resp = self.send_command(f"get_counter {cid}")
        if resp is None:
            return None
        # ищем число после "=" или просто первое число
        m = re.search(r'=\s*([\d]+)', resp)
        if m:
            return float(m.group(1))
        for part in resp.split():
            try:
                return float(part)
            except ValueError:
                continue
        self._log(f"[WARN] Cannot parse counter from: {resp!r}")
        return None

    def reset_counter(self, counter: str | int, value: int = 0) -> str | None:
        """set_counter <id> <value>"""
        cid = COUNTERS.get(str(counter).lower(), counter)
        return self.send_command(f"set_counter {cid} {value}")

    def get_all_counters(self) -> dict:
        """Читает все 4 счётчика, возвращает dict в мл."""
        result = {}
        for name, cid in COUNTERS.items():
            result[name] = self.get_counter(cid)
        return result

    # ── температура ──────────────────────────────────────────────────
    def get_temp(self) -> str | None:
        return self.send_command("get_temp")

    # ── параметры ────────────────────────────────────────────────────
    def get_param(self, param_id: int | str = "") -> str | None:
        return self.send_command(f"get_param {param_id}".strip())

    def set_param(self, param_id: int, value) -> str | None:
        return self.send_command(f"set_param {param_id} {value}")

    # ── прочее ───────────────────────────────────────────────────────
    def get_error(self) -> str | None:
        return self.send_command("get_error")

    def get_rtc(self) -> str | None:
        return self.send_command("get_rtc")

    def get_info(self) -> str | None:
        return self.send_command("info")