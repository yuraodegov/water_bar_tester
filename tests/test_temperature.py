"""
tests/test_temperature.py
Temperature check via the hydraulic connection.
Works with both HCDriver (hc_temps) and HydraulicSerial (get_temp dict).
"""
from tests.test_base import BaseTest, TestResult


class TestTemperature(BaseTest):
    NAME = "Temperature Check"
    DESCRIPTION = "Reads hydraulic temperatures and checks hot/cold thresholds."
    CATEGORY = "temp"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err

        hot_min = float(self.config.get("hot_min_temp", 85))
        cold_max = float(self.config.get("cold_max_temp", 11))

        self.log(f"[{self.NAME}] Reading temperatures...")

        temps = None
        # HCDriver exposes hc_temps() -> {ttank, tboost, tcw}
        if hasattr(self.hydraulic, "hc_temps"):
            try:
                temps = self.hydraulic.hc_temps()
            except Exception as exc:
                self.log(f"  hc_temps failed: {exc}")
        # HydraulicSerial exposes get_temp() -> dict of param=value
        if not temps and hasattr(self.hydraulic, "get_temp"):
            temps = self.hydraulic.get_temp()

        if not temps:
            return self._fail("Temperature read returned nothing")

        self.log(f"  temps: {temps}")
        data = {"temps": temps, "hot_min": hot_min, "cold_max": cold_max}

        # accept any of the common keys
        hot = temps.get("ttank") or temps.get("heater_bsp") or temps.get("hot")
        cold = temps.get("tcw") or temps.get("cooler_setpoint_off") or temps.get("cold")

        errors = []
        if hot is not None and hot < hot_min:
            errors.append(f"hot({hot}C) < min({hot_min}C)")
        if cold is not None and cold > cold_max:
            errors.append(f"cold({cold}C) > max({cold_max}C)")

        if errors:
            return self._fail(" | ".join(errors), data)
        return self._pass(f"OK temps={temps}", data)
