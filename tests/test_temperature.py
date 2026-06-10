"""
tests/test_temperature.py
Checks the water temperature through Hydraulic get_temp.
"""
from tests.test_base import BaseTest, TestResult


class TestTemperature(BaseTest):
    NAME        = "Temperature Check"
    DESCRIPTION = "Hydraulic get_temp — проверяет hot/cold/amb температуры."
    CATEGORY    = "temp"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err

        hot_min  = float(self.config.get("hot_min_temp",  85))
        cold_max = float(self.config.get("cold_max_temp",  11))
        amb_min  = float(self.config.get("amb_min_temp",  15))
        amb_max  = float(self.config.get("amb_max_temp",  35))

        self.log(f"[{self.NAME}] Reading temperatures...")
        temps = self.hydraulic.get_temp()
        if not temps:
            return self._fail("get_temp returned nothing")

        self.log(f"  Temps: {temps}")
        errors = []

        # Hot — search for heater_bsp or hot
        hot_val = temps.get("heater_bsp") or temps.get("hot")
        if hot_val is not None:
            if hot_val < hot_min:
                errors.append(f"hot({hot_val}°C) < min({hot_min}°C)")
        else:
            self.log("  [WARN] hot temp not found in response")

        # cold — cooler_setpoint_off or cold
        cold_val = temps.get("cooler_setpoint_off") or temps.get("cold")
        if cold_val is not None:
            if cold_val > cold_max:
                errors.append(f"cold({cold_val}°C) > max({cold_max}°C)")
        else:
            self.log("  [WARN] cold temp not found in response")

        data = {"temps": temps, "hot_min": hot_min, "cold_max": cold_max}

        if errors:
            return self._fail(" | ".join(errors), data)
        return self._pass(f"Temps OK: {temps}", data)