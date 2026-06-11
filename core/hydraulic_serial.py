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

    # ────────────────────────────────────────────────────────────────
    # Налив воды
    # ────────────────────────────────────────────────────────────────

    def pour_cold(self, seconds: float) -> str | None:
        return self.send_command(f"pour_cold {seconds}", wait=0.3)

    def pour_hot(self, seconds: float) -> str | None:
        return self.send_command(f"pour_hot {seconds}", wait=0.3)

    def pour_ambient(self, seconds: float) -> str | None:
        return self.send_command(f"pour_ambient {seconds}", wait=0.3)

    def stop_dispense(self) -> str | None:
        return self.send_command("stop_dispense")

    # ────────────────────────────────────────────────────────────────
    # Флоуметр
    # ────────────────────────────────────────────────────────────────

    def get_pulse(self) -> float | None:
        resp = self.send_command("get_pulse")

        if resp is None:
            return None

        m = re.search(r"(\d+)", resp)

        if m:
            return float(m.group(1))

        return None

    # ────────────────────────────────────────────────────────────────
    # Температуры
    # ────────────────────────────────────────────────────────────────

    def get_temp(self) -> dict | None:

        resp = self.send_command("get_temp", wait=0.5)

        if resp is None:
            return None

        result = {}

        for m in re.finditer(
            r"(\w+)\s*[=:]\s*([\d.]+)\s*(?:C deg|C|°C)?",
            resp,
            re.IGNORECASE,
        ):
            key = m.group(1).lower()
            val = float(m.group(2))
            result[key] = val

        return result if result else None

    # ────────────────────────────────────────────────────────────────
    # Статус
    # ────────────────────────────────────────────────────────────────

    def get_status(self) -> str | None:
        return self.send_command("status", wait=0.5)

    def get_io(self) -> str | None:
        return self.send_command("get_io", wait=0.5)

    def get_inputs(self) -> str | None:
        return self.send_command("get_inputs")

    def get_outputs(self) -> str | None:
        return self.send_command("get_outputs")

    # ────────────────────────────────────────────────────────────────
    # Параметры
    # ────────────────────────────────────────────────────────────────

    def get_param(self, name: str = "") -> str | None:
        return self.send_command(f"get_param {name}".strip(), wait=1.0)

    def set_param(self, name: str, value) -> str | None:
        return self.send_command(f"set_param {name} {value}")

    # ────────────────────────────────────────────────────────────────
    # Прочее
    # ────────────────────────────────────────────────────────────────

    def get_error(self) -> str | None:
        return self.send_command("error")

    def get_info(self) -> str | None:
        return self.send_command("info")

    def get_volt(self) -> str | None:
        return self.send_command("volt")

    # ────────────────────────────────────────────────────────────────
    # Tamar HC helpers
    # ────────────────────────────────────────────────────────────────

    def reset(self):
        return self.send_command("reset", wait=2)

    def heating(self, enable=True):
        return self.send_command(f"heating {1 if enable else 0}")

    def sim_all_on(self):
        return self.send_command("sim_all_on")

    def inject_temp(self, sensor: int, value: int):
        return self.send_command(f"simulate_integers {sensor} {value}")

    def cmd(self, command: str):
        return self.send_command(command)

    # ────────────────────────────────────────────────────────────────
    # Разбор status
    # ────────────────────────────────────────────────────────────────

    def status_dict(self) -> dict:

        resp = self.get_status()

        if not resp:
            return {}

        result = {}

        temp_match = re.search(
            r"TempTank:(\d+)\s+TempBoost:(\d+)\s+CWTtemp:(\d+)",
            resp,
            re.MULTILINE,
        )

        if temp_match:
            result["temp_tank"] = int(temp_match.group(1))
            result["temp_boost"] = int(temp_match.group(2))
            result["temp_cold"] = int(temp_match.group(3))

        state_match = re.search(
            r"Common:\s*(\S+)\s+Cooler:\s*(\S+)\s+Heater:\s*(\S+)\s+Dispenser:\s*(\S+)\s+Hot Filling:\s*(\S+)",
            resp,
            re.MULTILINE,
        )

        if state_match:
            result["common"] = state_match.group(1)
            result["cooler"] = state_match.group(2)
            result["heater"] = state_match.group(3)
            result["dispenser"] = state_match.group(4)
            result["hot_filling"] = state_match.group(5)

        return result

    # ────────────────────────────────────────────────────────────────
    # Разбор Outputs
    # ────────────────────────────────────────────────────────────────

    def outputs_dict(self) -> dict:

        resp = self.get_status()

        if not resp:
            return {}

        outputs = {}

        for name, value in re.findall(
            r"([A-Z_]+)\s*-\s*(\d+%?)",
            resp,
        ):
            outputs[name] = value

        return outputs

    # ────────────────────────────────────────────────────────────────
    # Filter / Purifier
    # ────────────────────────────────────────────────────────────────

    def get_purifier_info(self) -> dict:

        resp = self.send_command("purifier", wait=1)

        if not resp:
            return {}

        result = {}

        ml = re.search(r"Milliliters:\s*(\d+)", resp)
        minutes = re.search(r"Minutes:\s*(\d+)", resp)
        inserted = re.search(r"Inserted:\s*(\d+)", resp)

        if ml:
            result["milliliters"] = int(ml.group(1))

        if minutes:
            result["minutes"] = int(minutes.group(1))

        if inserted:
            result["inserted"] = int(inserted.group(1))

        return result

    # ────────────────────────────────────────────────────────────────
    # Errors
    # ────────────────────────────────────────────────────────────────

    def get_errors(self) -> list:

        resp = self.send_command("error")

        if not resp:
            return []

        return re.findall(r"\b\d+\b", resp)
