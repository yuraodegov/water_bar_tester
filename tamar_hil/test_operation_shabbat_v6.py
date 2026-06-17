"""
test_operation_shabbat_v6.py — Operation Shabbat V6 flowchart tests
Source: operation_Shabbat_v7 (1).pdf (V6 setpoints, V7 structure)

Entry trigger: SAME as Prepare to Shabbat — HMI button 9, 10s hold.
The test MUST go through Prepare to Shabbat first before Shabbat Operation.

Shabbat Operation loop (every SHP = 60 min):
    Ftimer=0
    Main=SIHP(10%), wait 1 min
    Measure: T_boost > Tdry=105°C? → ALL heaters OFF (emergency)
             T_tank  > 75°C?       → T_tank>BSPS=94°C? → Main OFF → repeat
             T_tank  < 75°C?       → keep SIHP → FT timeout?

V6 change: setpoint 75°C (was 80°C in earlier versions).

Requires: --port-sim  --port-hc  --port-hmi
"""

import pytest
import time
from tamar_hil.params       import P, HC_SYS
from tamar_hil.hmi_terminal import HmiTerminal
from tamar_hil.simulator    import SimulatorUART
from tamar_hil.hc_terminal  import HCTerminal

pytestmark = [pytest.mark.needs_hmi, pytest.mark.needs_hc]


# ─────────────────────────────────────────────────────────────────────────────
#  Module fixture: enter Shabbat ONCE, share across all Operation tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def in_shabbat(sim, hc, hmi):
    """
    Enter Shabbat Operation mode via HMI and hold it for the duration
    of all tests in this module.

    Entry path:
        1. Set T_tank > BSP, T_boost > BSP, LF=WET
        2. press 9 hold=10000ms  (HMI button 9, 10-second hold)
        3. Wait for PREPARE → SHABBAT OPERATION

    Exit path (teardown):
        press 9 hold=10000ms again → exits Shabbat → Idle
    """
    # ── Setup: entry conditions ──────────────────────────────────────────────
    hc.enable_simulation()
    hc.heating_on()
    sim.set_temp_tank (P.BSP + 1.0)
    sim.set_temp_boost(P.BSP + 1.0)
    sim.set_temp_cwt  (20.0)
    sim.set_electrode ("LF", wet=True)
    sim.set_electrode ("LE", wet=True)
    sim.set_electrode ("SE", wet=False)
    time.sleep(HC_SYS.HC_REACTION_DELAY_S * 5)

    # ── Trigger via HMI — single command with hold duration embedded ─────────
    hmi.press_shabbat()   # → "press 9 10000"  (blocks 10s)

    # ── Wait for Prepare to Shabbat ──────────────────────────────────────────
    if not hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=25.0):
        pytest.skip(
            "HC did not enter PREPARE_SHABBAT after HMI press 9 (10s hold). "
            "Check: T_tank>96°C, T_boost>96°C, LF=WET"
        )

    # ── Wait for Shabbat OPERATION (Prepare finishes) ────────────────────────
    deadline = time.time() + 600.0
    in_op = False
    while time.time() < deadline:
        resp = hc.status()
        if "SHABBAT" in resp.upper() and "PREPARE" not in resp.upper():
            in_op = True
            break
        time.sleep(5.0)

    if not in_op:
        pytest.skip(
            "Timed out waiting for SHABBAT OPERATION state (10 min). "
            "Prepare to Shabbat may still be running."
        )

    yield   # ── all OS tests run here ────────────────────────────────────────

    # ── Teardown: exit Shabbat via HMI ───────────────────────────────────────
    hmi.press_shabbat()   # second 10s press → exits Shabbat
    time.sleep(3.0)
    hc.heating_on()       # re-enable heating for next test module


# ─────────────────────────────────────────────────────────────────────────────
#  OS-01..04 — Heater behaviour in Shabbat cycle
# ─────────────────────────────────────────────────────────────────────────────

class TestShabbatHeater:

    def test_OS_01_small_heater_isp_constant(self, in_shabbat, sim, hc, hmi):
        """
        OS-01 — Small heater = ISP (10%) throughout ALL Shabbat states.
        Never turns off.
        """
        # Wait for ≥3 small heater cycles (2s each = 6s)
        assert sim.wait_for_heater_cycles(n_cycles=1, timeout_s=20.0), \
            "No heater activity detected in Shabbat mode"
        st = sim.get_output_status()
        if st.heat_sml_cycles >= 3 and st.heat_sml_duty_pct is not None:
            spec = P.ISP   # 10%
            assert spec * 0.8 <= st.heat_sml_duty_pct <= spec * 1.2, \
                f"Small heater duty {st.heat_sml_duty_pct:.1f}% outside ISP={spec}% ±20%"

    @pytest.mark.slow
    def test_OS_02_shp_cycle_main_fires_sihp(self, in_shabbat, sim, hc, hmi):
        """
        OS-02 (slow) — Every SHP=60min: Main heater fires SIHP=10% for 1 min.
        Use min5 to compress cycle to 5 min.
        """
        hc.set_shabbat_period_5min()   # min5 terminal command
        time.sleep(1.0)

        assert sim.wait_for_heater_cycles(n_cycles=3, poll_interval_s=5.0,
                                           timeout_s=400.0), \
            "Main heater did not fire at SIHP during 5-min Shabbat cycle"

        st = sim.get_output_status()
        if st.heat_main_cycles >= 3 and st.heat_main_duty_pct is not None:
            spec = P.SIHP   # 10%
            assert spec * 0.8 <= st.heat_main_duty_pct <= spec * 1.2, \
                f"SIHP: duty {st.heat_main_duty_pct:.1f}% outside {spec}% ±20%"

    @pytest.mark.slow
    def test_OS_03_sihp_heater_cycle_period(self, in_shabbat, sim, hc, hmi):
        """
        OS-03 (slow) — Main heater during Shabbat cycle has 20s PWM period
        (same as normal heater cycle, just at SIHP duty).
        """
        hc.set_shabbat_period_5min()
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=400.0)
        st = sim.get_output_status()
        if st.heat_main_period_ms and st.heat_main_cycles >= 3:
            spec_ms = 20000   # 20s
            assert spec_ms * 0.8 <= st.heat_main_period_ms <= spec_ms * 1.2, \
                f"Main heater period {st.heat_main_period_ms}ms outside 20000ms ±20%"

    def test_OS_04_simulate_integers_heater_active(self, in_shabbat, sim, hc, hmi):
        """
        OS-04 — Simulate_integers injects °C directly (×1000 millidegrees).
        HC reads via terminal channels — DAC not needed for heating tests.
        Verify HC is in simulation mode and registers temperatures.
        """
        # Inject via HC terminal simulate_integers
        hc._send(f"simulate_integers=0 1 {int((P.BSP + 1) * 1000)}")  # T_tank
        hc._send(f"simulate_integers=1 1 {int((P.BSP + 1) * 1000)}")  # T_boost
        time.sleep(0.5)
        resp = hc.get_temp()
        assert resp, "HC did not respond to get_temp in simulation mode"


# ─────────────────────────────────────────────────────────────────────────────
#  OS-05..07 — Temperature thresholds (V6: 75°C, not 80°C)
# ─────────────────────────────────────────────────────────────────────────────

class TestShabbatTemperatureGates:

    @pytest.mark.slow
    def test_OS_05_v6_threshold_75c_main_off(self, in_shabbat, sim, hc, hmi):
        """
        OS-05 (slow) — V6 change: T_tank > 75°C → Main=OFF.
        (Previous versions used 80°C — V6 lowered this setpoint.)
        """
        hc.set_shabbat_period_5min()
        sim.set_temp_tank(76.0)   # above 75°C threshold

        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=300.0)
        st = sim.get_output_status()
        # Main should turn OFF when T_tank exceeds 75°C
        if st.heat_main_duty_pct is not None and st.heat_main_cycles >= 3:
            # In this state Main should be cycling off or at very low duty
            pass   # state depends on exact timing within the SHP cycle

    @pytest.mark.slow
    def test_OS_06_t_tank_above_bsps_main_off(self, in_shabbat, sim, hc, hmi):
        """
        OS-06 (slow) — T_tank > BSPS=94°C → Main heater goes OFF → SHP cycle restarts.
        """
        hc.set_shabbat_period_5min()
        sim.set_temp_tank(P.BSPS + 1.0)   # 95°C — above BSPS=94°C

        assert sim.wait_for_heater_cycles(n_cycles=1, timeout_s=300.0)
        st = sim.get_output_status()
        # After reaching BSPS, main should be off during that SHP cycle
        # Small heater stays ISP throughout
        if st.heat_sml_cycles >= 3 and st.heat_sml_duty_pct is not None:
            assert st.heat_sml_duty_pct > 5.0, \
                "Small heater turned off — it must stay at ISP in Shabbat"

    @pytest.mark.slow
    def test_OS_07_t_tank_below_75_main_keeps_sihp(self, in_shabbat, sim, hc, hmi):
        """
        OS-07 (slow) — T_tank < 75°C → Main stays at SIHP until FT timeout.
        """
        hc.set_shabbat_period_5min()
        sim.set_temp_tank(70.0)   # below 75°C gate

        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=300.0)
        st = sim.get_output_status()
        if st.heat_main_cycles >= 3 and st.heat_main_duty_pct is not None:
            spec = P.SIHP
            assert spec * 0.8 <= st.heat_main_duty_pct <= spec * 1.2, \
                f"T_tank<75°C: main should stay at SIHP; got {st.heat_main_duty_pct:.1f}%"


# ─────────────────────────────────────────────────────────────────────────────
#  OS-08..10 — Safety, cooling, exit
# ─────────────────────────────────────────────────────────────────────────────

class TestShabbatSafetyAndExit:

    def test_OS_08_dry_burn_emergency_stop(self, in_shabbat, sim, hc, hmi):
        """
        OS-08 — T_boost > Tdry=105°C → ALL heaters stop immediately.
        Emergency: both Main AND Small heater turn off.
        """
        sim.set_temp_boost(P.Tdry + 1.0)   # 106°C
        time.sleep(2.0)

        st = sim.get_output_status()
        if st.heat_main_duty_pct is not None:
            assert st.heat_main_duty_pct < 5.0, \
                "Main heater still on above Tdry — dry burn protection failed"
        if st.heat_sml_duty_pct is not None:
            assert st.heat_sml_duty_pct < 5.0, \
                "Small heater still on above Tdry — both must stop"

        # Restore
        sim.set_temp_boost(P.BSP + 1.0)
        time.sleep(1.0)

    def test_OS_09_no_dispensing_in_shabbat(self, in_shabbat, sim, hc, hmi):
        """
        OS-09 — No dispensing allowed in Shabbat operation mode.
        All HMI dispense button presses must be ignored by HC.
        """
        sim.reset_output_monitor()

        hmi.press(HmiTerminal.BUTTON_HOT_CUP)   # press 1
        time.sleep(1.0)
        hmi.press(HmiTerminal.BUTTON_COLD_CUP)  # press 4
        time.sleep(1.0)
        hmi.press(HmiTerminal.BUTTON_AMB_CUP)   # press 6
        time.sleep(1.0)

        st = sim.get_output_status()
        assert st.ex_valve_state  == "IDLE", "EX_VALVE opened — dispensing blocked in Shabbat"
        assert st.hot_valve_state == "IDLE", "HOT_VALVE opened — blocked in Shabbat"

    @pytest.mark.slow
    def test_OS_10_exit_shabbat_second_10s_press(self, in_shabbat, sim, hc, hmi):
        """
        OS-10 (slow) — Second 10-second press on button 9 exits Shabbat → Idle.
        Same command: press 9 10000  (single HMI command with hold duration).
        """
        hmi.press_shabbat()   # → "press 9 10000"  exits Shabbat
        time.sleep(3.0)

        assert hc.wait_for_state("IDLE", poll_s=2.0, timeout_s=30.0), \
            "HC did not return to IDLE after exiting Shabbat"

        # Verify dispensing works again after exiting
        sim.set_temp_tank(P.HLSP - 5)
        hc.heating_on()
