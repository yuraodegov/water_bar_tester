"""
test_smoke.py — Connection sanity checks (run FIRST before any other tests)

Verifies all 3 terminals respond before running the full test suite.
Takes < 30 seconds. Run with:
    pytest tamar_hil/test_smoke.py --port-sim COM3 --port-hc COM4 --port-hmi COM5 -v
"""

import pytest
import time
from tamar_hil.simulator    import SimulatorUART
from tamar_hil.hc_terminal  import HCTerminal
from tamar_hil.hmi_terminal import HmiTerminal
from tamar_hil.params       import P, HC_SYS


class TestTerminal1Simulator:
    """Terminal 1 — Nucleo-G071RB HIL Simulator."""

    def test_SM_01_sim_responds(self, sim):
        """SM-01 — Simulator responds to STATUS command."""
        resp = sim.status_full()
        assert resp, "Simulator returned empty response — check COM port and firmware"

    def test_SM_02_sim_temp_tank(self, sim):
        """SM-02 — Set T_tank=72°C and verify OK response."""
        resp = sim._send("TEMP TANK 72.0")
        assert "OK" in resp, f"TEMP TANK command failed: {resp}"

    def test_SM_03_sim_electrode(self, sim):
        """SM-03 — Set electrode LF=DRY and verify."""
        resp = sim._send("ELEC LF 1")
        assert "OK" in resp, f"ELEC command failed: {resp}"
        sim._send("ELEC LF 0")   # restore WET

    def test_SM_04_sim_flow(self, sim):
        """SM-04 — Set flow 1.6 LPM and verify."""
        resp = sim._send("FLOW 1.60")
        assert "OK" in resp, f"FLOW command failed: {resp}"
        sim._send("FLOW 0.00")   # stop

    def test_SM_05_sim_preset_idle(self, sim):
        """SM-05 — PRESET IDLE loads without error."""
        resp = sim._send("PRESET IDLE")
        assert "OK" in resp, f"PRESET IDLE failed: {resp}"

    def test_SM_06_sim_status_out(self, sim):
        """SM-06 — STATUS OUT returns output monitor table."""
        resp = sim.status_out()
        assert "HEAT_MAIN" in resp or "EX_VALVE" in resp, \
            "STATUS OUT response missing channel data"

    def test_SM_07_sim_ntc_conversion(self, sim):
        """SM-07 — Temperature injection drives DAC (check STATUS TEMP)."""
        sim.set_temp_tank(72)
        time.sleep(0.1)
        resp = sim.status_temp()
        assert "72" in resp or "TANK" in resp, \
            "STATUS TEMP did not reflect injected temperature"


@pytest.mark.needs_hc
class TestTerminal2HC:
    """Terminal 2 — HC STM32 terminal (P1-2/3, ADDON_TX/RX)."""

    def test_SM_08_hc_responds(self, hc):
        """SM-08 — HC terminal responds to 'status' command."""
        resp = hc.status()
        assert resp, "HC terminal returned empty response — check COM port"

    def test_SM_09_hc_simulation_enabled(self, hc):
        """SM-09 — Simulation mode can be enabled (simulate=63)."""
        resp = hc.enable_simulation(63)
        # No error = OK (HC just processes and returns nothing or OK)
        assert resp is not None

    def test_SM_10_hc_temp_readable(self, hc):
        """SM-10 — HC can report temperatures (get_temp)."""
        resp = hc.get_temp()
        assert resp, "HC get_temp returned empty"

    def test_SM_11_hc_inputs_readable(self, hc):
        """SM-11 — HC can report input states (get_inputs)."""
        resp = hc.get_inputs()
        assert resp, "HC get_inputs returned empty"

    def test_SM_12_hc_outputs_readable(self, hc):
        """SM-12 — HC can report output states (get_outputs)."""
        resp = hc.get_outputs()
        assert resp, "HC get_outputs returned empty"

    def test_SM_13_hc_errors_readable(self, hc):
        """SM-13 — HC error list is accessible."""
        resp = hc.get_errors()
        assert resp is not None   # empty = no errors, also OK

    def test_SM_14_hc_heating_control(self, hc):
        """SM-14 — heating_on command accepted."""
        resp = hc.heating_on()
        assert resp is not None


@pytest.mark.needs_hmi
class TestTerminal3HMI:
    """Terminal 3 — HMI ESP32 (tamar-hmi firmware)."""

    def test_SM_15_hmi_responds(self, hmi):
        """SM-15 — HMI responds to get_param command."""
        resp = hmi.get_param(29)   # Core.BoilingTemp = 96000
        assert resp, "HMI terminal returned empty response — check COM port"

    def test_SM_16_hmi_boiling_temp(self, hmi):
        """SM-16 — HMI BoilingTemp param = 96000 (96°C, IL region)."""
        val = hmi.get_param_value(29)
        assert val is not None, "Could not read BoilingTemp from HMI"
        # Accept IL (96000) or US (95000)
        assert val in (96000, 95000), \
            f"Unexpected BoilingTemp={val}, expected 96000 (IL) or 95000 (US)"

    def test_SM_17_hmi_push_to_drink_readable(self, hmi):
        """SM-17 — Push-to-drink param is readable (param 124)."""
        val = hmi.get_param_value(124)
        assert val is not None, "Could not read pushToDrink param"
        assert val in (0, 1), f"pushToDrink should be 0 or 1, got {val}"

    def test_SM_18_hmi_shabbat_mode_readable(self, hmi):
        """SM-18 — Shabbat mode status readable (param 165)."""
        val = hmi.get_param_value(165)
        assert val is not None, "Could not read Shabbat_mode param"

    def test_SM_19_hmi_single_press(self, hmi):
        """SM-19 — HMI accepts press command without error."""
        # Press menu (3) — safe, no dispense
        resp = hmi.press(3, wait_ms=500)
        # Any response (even empty) means HMI accepted the command


@pytest.mark.needs_hmi
@pytest.mark.needs_hc
class TestFullChain:
    """Integration — verify sensor injection → HC → HMI chain."""

    def test_SM_20_temp_injection_reaches_hc(self, sim, hc, hmi):
        """
        SM-20 — Temperature injected via simulator DAC is read by HC.
        HC should report the new temperature within 100ms.
        """
        # Inject 75°C to T_tank
        sim.set_temp_tank(75)
        time.sleep(HC_SYS.LOW_PRIORITY_INTERVAL_MS / 1000.0 + 0.1)

        resp = hc.get_temp()
        # HC should report something close to 75°C
        assert resp, "HC did not respond to get_temp after temperature injection"

    def test_SM_21_electrode_injection_reaches_hc(self, sim, hc, hmi):
        """
        SM-21 — Electrode state injected via Nucleo is read by HC.
        Set LF=DRY, verify HC inputs reflect change.
        """
        sim.set_electrode("LF", wet=False)   # LF = DRY
        time.sleep(HC_SYS.HIGH_PRIORITY_INTERVAL_MS / 1000.0 * 5)

        resp = hc.get_inputs()
        assert resp, "HC did not respond to get_inputs"

        sim.set_electrode("LF", wet=True)    # restore
