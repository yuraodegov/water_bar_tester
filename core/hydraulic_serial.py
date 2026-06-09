"""
core/hydraulic_serial.py — соединение с Hydraulic Controller.

Команды (из help лога):
  pour_cold <sec>       — налить холодную N секунд
  pour_hot <sec>        — налить горячую N секунд
  pour_ambient <sec>    — налить комнатную N секунд
  stop_dispense         — стоп
  get_temp              — температуры (hot/cold/amb/pcb)
  get_pulse             — пульсы флоуметра
  status / Status       — статус входов/выходов
  get_param / set_param
  get_inputs / get_outputs / get_io
  info / volt / temp / error
  simulate_flow <val>   — симуляция потока (для тестов без воды)
"""
import re
from core.base_serial import BaseSerial


class HydraulicSerial(BaseSerial):
    DEVICE_NAME = "HYDRAULIC"

    # ── налив воды ───────────────────────────────────────────────────
    def pour_cold(self, seconds: float) -> str | None:
        return self.send_command(f"pour_cold {seconds}", wait=0.3)

    def pour_hot(self, seconds: float) -> str | None:
        return self.send_command(f"pour_hot {seconds}", wait=0.3)

    def pour_ambient(self, seconds: float) -> str | None:
        return self.send_command(f"pour_ambient {seconds}", wait=0.3)

    def stop_dispense(self) -> str | None:
        return self.send_command("stop_dispense")

    # ── флоуметр ─────────────────────────────────────────────────────
    def get_pulse(self) -> float | None:
        """
        get_pulse → возвращает число импульсов (мл).
        Из лога: "Flow meter 1000" → 1000 мл
        """
        resp = self.send_command("get_pulse")
        if resp is None:
            return None
        m = re.search(r'(\d+)', resp)
        if m:
            return float(m.group(1))
        return None

    # ── температура ──────────────────────────────────────────────────
    def get_temp(self) -> dict | None:
        """
        get_temp → парсим все температуры.
        Возвращает dict: {'hot': 96.0, 'cold': 6.0, 'amb': 22.0, ...}
        """
        resp = self.send_command("get_temp", wait=0.5)
        if resp is None:
            return None
        result = {}
        # ищем паттерны "heater_bsp = 96 C deg" или "cold: 6.0"
        for m in re.finditer(r'(\w+)\s*[=:]\s*([\d.]+)\s*(?:C deg|C|°C)?', resp, re.IGNORECASE):
            key = m.group(1).lower()
            val = float(m.group(2))
            result[key] = val
        return result if result else None

    # ── статус ───────────────────────────────────────────────────────
    def get_status(self) -> str | None:
        return self.send_command("status", wait=0.5)

    def get_io(self) -> str | None:
        return self.send_command("get_io", wait=0.5)

    def get_inputs(self) -> str | None:
        return self.send_command("get_inputs")

    def get_outputs(self) -> str | None:
        return self.send_command("get_outputs")

    # ── параметры ────────────────────────────────────────────────────
    def get_param(self, name: str = "") -> str | None:
        return self.send_command(f"get_param {name}".strip(), wait=1.0)

    def set_param(self, name: str, value) -> str | None:
        return self.send_command(f"set_param {name} {value}")

    # ── прочее ───────────────────────────────────────────────────────
    def get_error(self) -> str | None:
        return self.send_command("error")

    def get_info(self) -> str | None:
        return self.send_command("info")

    def get_volt(self) -> str | None:
        return self.send_command("volt")