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
        return self._parse_counter_value(resp, cid)

    @staticmethod
    def _parse_counter_value(resp, cid=None):
        """
        Parse a counter value from a response like:
          'get_counter 0\n[00] Total_ml = 1701861037\nCMD EXECUTE OK\n> '
        The HC/HMI also emits async lines such as
          'SET [06] FilterMinutes = 6520'
        which must NOT be mistaken for the requested counter. When cid is
        given we only accept the line whose index '[NN]' equals cid, and we
        prefer the direct reply line '[NN] Name = value' over 'SET [NN] ...'.
        """
        if resp is None:
            return None

        want_idx = None
        if cid is not None:
            try:
                want_idx = int(cid)
            except (TypeError, ValueError):
                want_idx = None

        direct = None   # '[NN] Name = value'  (the reply we asked for)
        any_set = None  # 'SET [NN] Name = value' (async update, fallback)
        fallback = None  # any '= value' line, last resort

        for line in resp.splitlines():
            m = re.search(r'\[(\d+)\]\s*\w+\s*=\s*(-?\d+)', line)
            if m:
                idx = int(m.group(1))
                val = float(m.group(2))
                if want_idx is None or idx == want_idx:
                    if line.strip().startswith("SET"):
                        any_set = val
                    else:
                        direct = val
                continue
            m2 = re.search(r'=\s*(-?\d+)', line)
            if m2:
                fallback = float(m2.group(1))

        if direct is not None:
            return direct
        if any_set is not None:
            return any_set
        return fallback

    def reset_counter(self, counter, value: int = 0):
        cid = COUNTERS.get(str(counter).lower(), counter)
        return self.send_command(f"set_counter {cid} {value}")

    def get_all_counters(self) -> dict:
        return {name: self.get_counter(cid) for name, cid in COUNTERS.items()}

    def get_temp(self):
        return self.send_command("get_temp")

    def get_param(self, param_id=""):
        return self.send_command(f"get_param {param_id}".strip())

    def get_param_value(self, param_id: int) -> int:
        """
        Read one HMI parameter by id and return its integer value.

        The device answers '[<id>] <Name> = <value>  (0x..)'; we parse the
        value for the requested id. Raises if the id is not found or the
        value is not an integer (e.g. string params like SSID).
        """
        resp = self.send_command(f"get_param {param_id}")
        # match '[29] Core.BoilingTemp = 96000' (ignore trailing hex/units)
        pat = re.compile(
            r"\[0*%d\]\s+[\w.\[\]]+\s*=\s*(-?\d+)" % int(param_id))
        m = pat.search(resp)
        if not m:
            raise RuntimeError(
                f"param [{param_id}] not found / not integer in: {resp!r}")
        return int(m.group(1))

    def set_param(self, param_id: int, value):
        return self.send_command(f"set_param {param_id} {value}")

    def get_error(self):
        return self.send_command("get_error")

    def set_error(self, error_id):
        """Raise error <error_id> on the device (HMI 'set_error <N>')."""
        return self.send_command(f"set_error {error_id}")

    def clear_error(self, error_id):
        """Clear error <error_id> on the device (HMI 'clear_error <N>')."""
        return self.send_command(f"clear_error {error_id}")

    def get_rtc(self):
        return self.send_command("get_rtc")

    def get_info(self):
        return self.send_command("info")