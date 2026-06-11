"""
core/hmi_serial.py — соединение с HMI UI.

Команды:
  press <key> <duration_ms>
  get_counter <id>  /  set_counter <id> <value>
  get_param [id]   /  set_param <id> <value>
  get_temp, get_error, get_rtc, info

Кнопки:
  1=HOT_GLASS  2=HOT_JUG
  3=MENU       4=COLD_GLASS
  5=COLD_JUG   6=AMB_GLASS
  7=AMB_JUG    8=FILTERED

Счётчики:
  0=Total_ml  1=Filter_ml  2=Cold_ml  4=Amb_ml
"""
import re
from core.base_serial import BaseSerial

BUTTONS = {
    "HOT_GLASS": 1,
    "HOT_JUG": 2,
    "MENU": 3,
    "COLD_GLASS": 4,
    "COLD_JUG": 5,
    "AMB_GLASS": 6,
    "AMB_JUG": 7,
    "FILTERED": 8,
}

COUNTERS = {
    "total": 0,
    "filter": 1,
    "cold": 2,
    "amb": 4,
}


class HmiSerial(BaseSerial):
    DEVICE_NAME = "HMI"

    def press(self, button_id: int, duration_ms: int = 1000):
        return self.send_command(f"press {button_id} {duration_ms}")

    def press_named(self, name: str, duration_ms: int = 1000):
        bid = BUTTONS.get(name.upper())
        if bid is None:
            self._log(f"[ERROR] Unknown button name: {name}")
            return None
        return self.press(bid, duration_ms)

    def get_counter(self, counter):
        cid = COUNTERS.get(str(counter).lower(), counter)
        resp = self.send_command(f"get_counter {cid}")
        return self._parse_counter_value(resp)

    @staticmethod
    def _parse_counter_value(resp):
        """
        Parse counter value from a response like:
          'get_counter 9\n[09] FilterStatus = 1\nCMD EXECUTE OK\n> '
        Only the number AFTER '=' is the real value. The command echo
        ('get_counter 9') and the index ('[09]') must be ignored.
        """
        if resp is None:
            return None
        # take the value after '=' on the last line that has one
        last = None
        for line in resp.splitlines():
            m = re.search(r'=\s*(-?\d+)', line)
            if m:
                last = float(m.group(1))
        return last

    def reset_counter(self, counter, value: int = 0):
        cid = COUNTERS.get(str(counter).lower(), counter)
        return self.send_command(f"set_counter {cid} {value}")

    def get_all_counters(self) -> dict:
        return {name: self.get_counter(cid) for name, cid in COUNTERS.items()}

    def get_temp(self):
        return self.send_command("get_temp")

    def get_param(self, param_id=""):
        return self.send_command(f"get_param {param_id}".strip())

    def set_param(self, param_id: int, value):
        return self.send_command(f"set_param {param_id} {value}")

    def get_error(self):
        return self.send_command("get_error")

    def get_rtc(self):
        return self.send_command("get_rtc")

    def get_info(self):
        return self.send_command("info")