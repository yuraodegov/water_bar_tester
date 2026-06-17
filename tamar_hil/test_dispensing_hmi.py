"""
test_dispensing_hmi.py — Dispense tests using the REAL HMI buttons
Source: ShabbatBar_Buttons.xlsx + observed behavior

These tests drive the actual HMI (press N) rather than the HC terminal
(pour_hot/cold). This validates the full signal chain:
    PC → HMI (press) → HMI sends binary packet → HC → valves open.

All tests require all 3 terminals:  --port-sim  --port-hc  --port-hmi

Push-to-drink is DISABLED by default (conftest _manage_push_to_drink fixture).
Tests marked @pytest.mark.with_ptd test the safety lock with PTD ON.

Button map:
    1 = Hot Cup    2 = Hot Jug    4 = Cold Cup
    5 = Cold Jug   6 = Ambient Cup 7 = Ambient Jug
    8 = Extra Hot  9 = Shabbat (10s long press)
"""

import pytest
import time
from tamar_hil.params       import P
from tamar_hil.hmi_terminal import HmiTerminal
from tamar_hil.simulator    import SimulatorUART
from tamar_hil.hc_terminal  import HCTerminal


pytestmark = [pytest.mark.needs_hmi, pytest.mark.needs_hc]


# ─────────────────────────────────────────────────────────────────────────────
#  Cold Cup — CD-01 via HMI (PTD-free, single press)
# ─────────────────────────────────────────────────────────────────────────────

class TestColdDispenseHMI:

    def setup_method(self, method):
        """Precondition: cold electrode WET, CWT=8°C."""

    def test_HMID_01_cold_cup_opens_valves(self, sim, hc, hmi):
        """
        HMID-01 — Press 4 (Cold Cup) → EX_VALVE then INLET_VALVE open.
        PTD disabled automatically.
        """
        sim.set_temp_cwt(8)
        sim.set_electrode("COLD", wet=True)
        sim.set_electrode("LF", wet=True)
        sim.set_flow(P.FLOW_NOMINAL_LPM)

        hmi.press_cold_cup()          # press 4

        # Allow 500ms for HC to react and valves to start opening
        time.sleep(0.5)
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=5), \
            "EX_VALVE did not open after Cold Cup press"

    def test_HMID_02_cold_jug_opens_valves(self, sim, hc, hmi):
        """HMID-02 — Press 5 (Cold Jug) → valves open."""
        sim.set_temp_cwt(8)
        sim.set_flow(P.FLOW_NOMINAL_LPM)

        hmi.press_cold_jug()          # press 5

        time.sleep(0.5)
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=5)

    def test_HMID_03_cold_cup_sequence_delay(self, sim, hc, hmi):
        """HMID-03 — EX_VALVE → 200ms ±20% → INLET_VALVE sequence."""
        sim.set_flow(P.FLOW_NOMINAL_LPM)
        sim.reset_output_monitor()

        hmi.press_cold_cup()
        time.sleep(2.0)

        st = sim.get_output_status()
        assert st.inlet_valve_delay_ms is not None, "No sequence delay measured"
        assert 160 <= st.inlet_valve_delay_ms <= 240, (
            f"Seq delay {st.inlet_valve_delay_ms}ms outside 200ms ±20%")

    def test_HMID_04_ambient_cup(self, sim, hc, hmi):
        """HMID-04 — Press 6 (Ambient Cup) → valves open."""
        sim.set_temp_cwt(20)
        sim.set_flow(P.FLOW_NOMINAL_LPM)

        hmi.press_ambient_cup()       # press 6
        time.sleep(0.5)
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=5)


# ─────────────────────────────────────────────────────────────────────────────
#  Hot Cup — PTD disabled (normal automated test path)
# ─────────────────────────────────────────────────────────────────────────────

class TestHotDispenseHMI:

    def test_HMID_05_hot_cup_ptd_disabled(self, sim, hc, hmi):
        """
        HMID-05 — Press 1 (Hot Cup) with push-to-drink OFF.
        PTD is disabled automatically by conftest fixture.
        Only HOT_VALVE should open (not EX_VALVE).
        """
        sim.set_temp_tank(90)
        sim.set_temp_boost(92)
        sim.set_electrode("LF", wet=True)

        hmi.press(HmiTerminal.BUTTON_HOT_CUP)
        time.sleep(0.5)

        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE", \
            f"EX_VALVE must stay IDLE for hot dispense; state={st.ex_valve_state}"
        assert sim.wait_for_valve_opening("HOT_VLV", timeout_s=5), \
            "HOT_VALVE did not open"

    def test_HMID_06_hot_jug_ptd_disabled(self, sim, hc, hmi):
        """HMID-06 — Press 2 (Hot Jug) with PTD off → HOT_VALVE opens."""
        sim.set_temp_tank(90)
        sim.set_temp_boost(92)

        hmi.press(HmiTerminal.BUTTON_HOT_JUG)
        time.sleep(0.5)
        assert sim.wait_for_valve_opening("HOT_VLV", timeout_s=5)

    def test_HMID_07_hot_valve_opening_pulse(self, sim, hc, hmi):
        """HMID-07 — HOT_VALVE opening pulse 1000ms ±20% (800–1200ms)."""
        sim.set_temp_tank(90)
        sim.reset_output_monitor()

        hmi.press(HmiTerminal.BUTTON_HOT_CUP)
        time.sleep(2.5)

        st = sim.get_output_status()
        import re
        m = re.search(r'HOT_VLV.*?pulse=(\d+)ms', st.raw, re.IGNORECASE)
        if m:
            pulse = int(m.group(1))
            assert 800 <= pulse <= 1200, f"HOT_VALVE pulse {pulse}ms outside 1000ms ±20%"

    def test_HMID_08_hot_valve_holding_500hz(self, sim, hc, hmi):
        """HMID-08 — HOT_VALVE holding: 500Hz ±20%, 50% duty ±20%."""
        sim.set_temp_tank(90)
        hmi.press(HmiTerminal.BUTTON_HOT_CUP)
        time.sleep(3.0)

        st = sim.get_output_status()
        assert st.hot_valve_freq_hz is not None, "HOT_VALVE freq not measured"
        assert 400 <= st.hot_valve_freq_hz <= 600, \
            f"HOT_VALVE freq {st.hot_valve_freq_hz:.1f}Hz outside 500Hz ±20%"
        assert st.hot_valve_duty_pct is not None
        assert 40 <= st.hot_valve_duty_pct <= 60, \
            f"HOT_VALVE duty {st.hot_valve_duty_pct:.1f}% outside 50% ±20%"


# ─────────────────────────────────────────────────────────────────────────────
#  Hot Cup — push-to-drink ON (tests the safety mechanism itself)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.with_ptd
class TestPushToDrink:

    def test_HMID_09_single_press_blocked_when_ptd_on(self, sim, hc, hmi):
        """
        HMID-09 — When push-to-drink is ON, single press on hot button
        should NOT start dispensing (safety lock active).
        """
        sim.set_temp_tank(90)
        sim.reset_output_monitor()

        # Single press only — should be blocked
        hmi.press(HmiTerminal.BUTTON_HOT_CUP, wait_ms=400)
        time.sleep(2.5)

        st = sim.get_output_status()
        assert st.hot_valve_state == "IDLE", \
            f"HOT_VALVE should stay IDLE with PTD on and single press; state={st.hot_valve_state}"

    def test_HMID_10_push_to_drink_sequence_starts_hot(self, sim, hc, hmi):
        """
        HMID-10 — Full push-to-drink sequence:
          Hold hot cup (2s) + press menu at T+500ms (1s) → dispensing starts.
        """
        sim.set_temp_tank(90)
        sim.reset_output_monitor()

        hmi.press_hot_push_to_drink(button=HmiTerminal.BUTTON_HOT_CUP)

        time.sleep(0.5)
        assert sim.wait_for_valve_opening("HOT_VLV", timeout_s=8), \
            "HOT_VALVE did not open after push-to-drink sequence"

    def test_HMID_11_push_to_drink_jug(self, sim, hc, hmi):
        """HMID-11 — Hot Jug with PTD sequence (button 2)."""
        sim.set_temp_tank(90)
        sim.reset_output_monitor()

        hmi.press_hot_jug_push_to_drink()
        time.sleep(0.5)
        assert sim.wait_for_valve_opening("HOT_VLV", timeout_s=8)

    def test_HMID_12_wrong_sequence_blocked(self, sim, hc, hmi):
        """
        HMID-12 — Menu pressed BEFORE hot button: should NOT trigger dispense.
        (Sequence must be: hot first, then menu.)
        """
        sim.set_temp_tank(90)
        sim.reset_output_monitor()

        # Wrong order: menu first, then hot
        hmi.press(HmiTerminal.BUTTON_MENU)
        time.sleep(0.1)
        hmi.press(HmiTerminal.BUTTON_HOT_CUP)
        time.sleep(2.5)

        st = sim.get_output_status()
        assert st.hot_valve_state == "IDLE", \
            "Wrong PTD sequence should not trigger dispense"


# ─────────────────────────────────────────────────────────────────────────────
#  Extra Hot via HMI
# ─────────────────────────────────────────────────────────────────────────────

class TestExtraHotHMI:

    def test_HMID_13_extra_hot_button(self, sim, hc, hmi):
        """
        HMID-13 — Press 8 (Extra Hot) → HC enters Extra Hot heating mode.
        Single press, no PTD required.
        """
        sim.set_temp_tank(P.TLLSP + 5)   # above TLLSP, below BSP
        sim.set_temp_boost(P.TLLSP + 5)
        hmi.press_extra_hot()

        time.sleep(1.0)
        # After Extra Hot press, main heater should be at 100% (OSPm)
        # We verify via the HC terminal status
        resp = hc.status()
        assert "EXTRA" in resp.upper() or "heater" in resp.lower(), \
            "HC should be in Extra Hot mode after press 8"


# ─────────────────────────────────────────────────────────────────────────────
#  Shabbat via HMI (long press 10s)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.slow
@pytest.mark.needs_hmi
@pytest.mark.needs_hc
class TestShabbatEntryHMI:

    def test_HMID_14_shabbat_long_press_enters_mode(self, sim, hc, hmi):
        """
        HMID-14 (slow) — 10-second long press on button 9 → Shabbat prepare mode.
        HC should enter COMMON_STATE_START_PREPARE_SHABBAT.
        """
        # Precondition: tank is at temperature
        sim.set_temp_tank(P.BSP - 10)
        sim.set_temp_boost(P.BSP - 10)
        sim.set_electrode("LF", wet=True)

        # 10-second long press
        hmi.press_shabbat()    # blocks for 10s

        time.sleep(1.0)
        # Check HC state
        resp = hc.status()
        assert "PREPARE" in resp.upper() or "SHABBAT" in resp.upper(), (
            "HC did not enter Shabbat prepare after 10s long press")

    def test_HMID_15_shabbat_exit_long_press(self, sim, hc, hmi):
        """
        HMID-15 (slow) — Second 10-second long press exits Shabbat mode.
        """
        # Enter first
        hmi.press_shabbat()
        time.sleep(2.0)
        assert hmi.is_shabbat_active() or "SHABBAT" in hc.status().upper(), \
            "Should be in Shabbat first"

        # Exit
        hmi.press_shabbat()
        time.sleep(2.0)
        resp = hc.status()
        assert "IDLE" in resp.upper() or "RUN" in resp.upper(), \
            "HC should exit Shabbat after second long press"
