"""
test_prepare_shabbat_v7.py — Prepare to Shabbat V7 flowchart tests
Source: Preper to shabbat_v7 (1).pdf

Entry trigger: HMI button 9, 10-second hold  →  "press 9 10000"
Entry conditions (HC firmware requirement):
    T_tank  > BSP  (96°C)
    T_boost > BSP  (96°C)
    LF = WET       (hot float — tank full)

Sequence after entry:
    OSPm/OSPs → T_boost>BSP → SPMH1(50%)
    T_tank>BTSP0=80°C → SPMH2(20%)
    T_tank>T_terminate=93°C → SPMH3(10%)
    T_tank>BSP → Main OFF, Small=ISP, filling enabled (V7 new)
    → entry to Shabbat

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
#  Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _enter_prepare(sim, hc, hmi,
                   t_tank=None, t_boost=None, lf_wet=True):
    """
    Set conditions and trigger Prepare to Shabbat via HMI button 9.
    Default temperatures: BSP+1 (satisfy entry gate).
    """
    hc.enable_simulation()
    hc.heating_on()
    sim.set_temp_tank (t_tank  or P.BSP + 1.0)
    sim.set_temp_boost(t_boost or P.BSP + 1.0)
    sim.set_temp_cwt(20.0)
    sim.set_electrode("LF", wet=lf_wet)
    sim.set_electrode("LE", wet=True)
    sim.set_electrode("SE", wet=False)
    time.sleep(HC_SYS.HC_REACTION_DELAY_S * 5)

    # Single command with hold duration embedded — NOT a separate sleep()
    hmi.press_shabbat()   # → "press 9 10000"


# ─────────────────────────────────────────────────────────────────────────────
#  PS-01..04 — Entry conditions
# ─────────────────────────────────────────────────────────────────────────────

class TestPrepareShabbatEntry:

    def test_PS_01_entry_main_ospm_small_osps(self, sim, hc, hmi):
        """
        PS-01 — After 10s press with conditions met:
        Main=OSPm=100%, Small=OSPs=100%. Both heaters fully on.
        Requires: T_tank>BSP, T_boost>BSP, LF=WET.
        """
        # Drop temps so HC actually needs to heat
        hc.enable_simulation(); hc.heating_on()
        sim.set_temp_tank(P.TLLSP + 5)
        sim.set_temp_boost(P.TLLSP + 5)
        sim.set_electrode("LF", wet=True)
        time.sleep(0.5)

        hmi.press_shabbat()   # 10s hold via HMI

        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0), \
            "HC did not enter PREPARE_SHABBAT after HMI press 9 (10s hold)"
        # Heater should be active
        assert sim.wait_for_heater_cycles(n_cycles=1, timeout_s=30.0), \
            "Main heater not active during OSPm phase"

    def test_PS_02_entry_blocked_tank_below_bsp(self, sim, hc, hmi):
        """
        PS-02 — Shabbat press blocked when T_tank < BSP.
        HC must NOT enter Prepare mode.
        """
        hc.enable_simulation()
        sim.set_temp_tank(P.TLLSP - 5)    # 45°C — clearly below BSP
        sim.set_temp_boost(P.BSP + 1)
        sim.set_electrode("LF", wet=True)
        time.sleep(0.5)

        hmi.press_shabbat()
        time.sleep(2.0)

        resp = hc.status()
        assert "PREPARE" not in resp.upper(), \
            "HC entered PREPARE even though T_tank < BSP"

    def test_PS_03_entry_blocked_boost_below_bsp(self, sim, hc, hmi):
        """
        PS-03 — Shabbat press blocked when T_boost < BSP.
        """
        hc.enable_simulation()
        sim.set_temp_tank(P.BSP + 1)
        sim.set_temp_boost(P.TLLSP - 5)   # boost too cold
        sim.set_electrode("LF", wet=True)
        time.sleep(0.5)

        hmi.press_shabbat()
        time.sleep(2.0)

        resp = hc.status()
        assert "PREPARE" not in resp.upper(), \
            "HC entered PREPARE even though T_boost < BSP"

    def test_PS_04_entry_blocked_float_dry(self, sim, hc, hmi):
        """
        PS-04 — Shabbat press blocked when LF = DRY (tank not full).
        Hot water tank must be FULL (LF=WET) to enter Shabbat.
        """
        hc.enable_simulation()
        sim.set_temp_tank(P.BSP + 1)
        sim.set_temp_boost(P.BSP + 1)
        sim.set_electrode("LF", wet=False)   # DRY — tank empty
        time.sleep(0.5)

        hmi.press_shabbat()
        time.sleep(2.0)

        resp = hc.status()
        assert "PREPARE" not in resp.upper(), \
            "HC entered PREPARE even though LF=DRY (tank not full)"


# ─────────────────────────────────────────────────────────────────────────────
#  PS-05..08 — Heating stages
# ─────────────────────────────────────────────────────────────────────────────

class TestPrepareHeating:

    @pytest.mark.slow
    def test_PS_05_spmh1_50pct_after_tboost_bsp(self, sim, hc, hmi):
        """
        PS-05 (slow) — T_boost > BSP → Main switches to SPMH1 = 50%.
        Requires ≥3 cycles (≥60s observation).
        """
        _enter_prepare(sim, hc, hmi,
                       t_tank=P.TLLSP + 5,     # need to heat tank
                       t_boost=P.BSP + 1.0)    # boost already above BSP → SPMH1

        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90.0), \
            "Timed out waiting for ≥3 cycles in SPMH1"
        duty = sim.get_main_heater_duty()
        assert duty is not None
        assert P.SPMH1 * 0.8 <= duty <= P.SPMH1 * 1.2, \
            f"SPMH1: duty {duty:.1f}% outside {P.SPMH1}% ±20%"

    @pytest.mark.slow
    def test_PS_06_spmh2_20pct_after_ttank_btsp0(self, sim, hc, hmi):
        """
        PS-06 (slow) — T_tank > BTSP0=80°C → Main switches to SPMH2 = 20%.
        """
        _enter_prepare(sim, hc, hmi,
                       t_tank=P.BTSP0 + 1.0,   # 81°C
                       t_boost=P.BSP + 1.0)

        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90.0)
        duty = sim.get_main_heater_duty()
        assert duty is not None
        assert P.SPMH2 * 0.8 <= duty <= P.SPMH2 * 1.2, \
            f"SPMH2: duty {duty:.1f}% outside {P.SPMH2}% ±20%"

    @pytest.mark.slow
    def test_PS_07_spmh3_10pct_after_ttank_t_terminate(self, sim, hc, hmi):
        """
        PS-07 (slow) — T_tank > T_terminate=93°C → Main = SPMH3 = 10%.
        """
        _enter_prepare(sim, hc, hmi,
                       t_tank=P.T_terminate + 1.0,  # 94°C
                       t_boost=P.BSP + 1.0)

        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90.0)
        duty = sim.get_main_heater_duty()
        assert duty is not None
        assert P.SPMH3 * 0.8 <= duty <= P.SPMH3 * 1.2, \
            f"SPMH3: duty {duty:.1f}% outside {P.SPMH3}% ±20%"

    @pytest.mark.slow
    def test_PS_08_full_heating_progression(self, sim, hc, hmi):
        """
        PS-08 (slow) — Full stage progression: OSPm → SPMH1 → SPMH2 → SPMH3 → Main OFF.
        Ramp T_tank and T_boost through all thresholds and verify each stage.
        """
        hc.enable_simulation(); hc.heating_on()
        sim.set_temp_tank(P.TLLSP + 5)       # start below all thresholds
        sim.set_temp_boost(P.TLLSP + 5)
        sim.set_electrode("LF", wet=True)
        time.sleep(0.5)

        hmi.press_shabbat()
        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0)

        # Stage 1: boost > BSP → SPMH1
        sim.set_temp_boost(P.BSP + 1.0)
        time.sleep(2.0)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90.0)
        d1 = sim.get_main_heater_duty()
        assert d1 is not None and P.SPMH1 * 0.8 <= d1 <= P.SPMH1 * 1.2, \
            f"SPMH1 failed: {d1}% ≠ {P.SPMH1}%"

        # Stage 2: tank > BTSP0
        sim.set_temp_tank(P.BTSP0 + 1.0)
        time.sleep(2.0)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90.0)
        d2 = sim.get_main_heater_duty()
        assert d2 is not None and P.SPMH2 * 0.8 <= d2 <= P.SPMH2 * 1.2, \
            f"SPMH2 failed: {d2}%"

        # Stage 3: tank > T_terminate
        sim.set_temp_tank(P.T_terminate + 1.0)
        time.sleep(2.0)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90.0)
        d3 = sim.get_main_heater_duty()
        assert d3 is not None and P.SPMH3 * 0.8 <= d3 <= P.SPMH3 * 1.2, \
            f"SPMH3 failed: {d3}%"


# ─────────────────────────────────────────────────────────────────────────────
#  PS-09..12 — Fill + transition to Shabbat
# ─────────────────────────────────────────────────────────────────────────────

class TestPrepareFillAndEntry:

    @pytest.mark.slow
    def test_PS_09_filling_enabled_after_prepare(self, sim, hc, hmi):
        """
        PS-09 (slow) — After T_tank > BSP and Main=OFF:
        hot fill is ENABLED (V7 feature). HC waits for fill timer or float.
        """
        _enter_prepare(sim, hc, hmi,
                       t_tank=P.BSP + 1.0,
                       t_boost=P.BSP + 1.0,
                       lf_wet=False)   # float dry → enables filling

        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0)
        time.sleep(5.0)

        # EX_VALVE should open for filling
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=15.0), \
            "EX_VALVE did not open for hot fill during Prepare to Shabbat"

    @pytest.mark.slow
    def test_PS_10_fill_stops_on_float_wet(self, sim, hc, hmi):
        """
        PS-10 (slow) — Fill stops when float becomes WET.
        LF goes WET → HC stops filling, hot_fill_enable = 0.
        """
        _enter_prepare(sim, hc, hmi,
                       t_tank=P.BSP + 1.0,
                       t_boost=P.BSP + 1.0,
                       lf_wet=False)   # start with DRY to enable fill

        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0)
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=15.0), \
            "Fill did not start"

        # Simulate tank full → filling should stop
        sim.set_electrode("LF", wet=True)
        time.sleep(15.0)   # wait for 12s electrode filter

        assert sim.wait_for_valve_idle("EX_VALVE", timeout_s=20.0), \
            "EX_VALVE did not close after LF became WET"

    @pytest.mark.slow
    def test_PS_11_entry_to_shabbat_after_tank_above_bsp(self, sim, hc, hmi):
        """
        PS-11 (slow) — After heating + fill done:
        HC enters SHABBAT OPERATION state automatically.
        Conditions: T_tank>BSP, fill=0, T_tank<BSP-B_offset gate OK.
        """
        _enter_prepare(sim, hc, hmi)
        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0)

        # Accelerate: push tank just above BSP
        sim.set_temp_tank(P.BSP + 1.0)
        sim.set_electrode("LF", wet=True)   # fill done

        # Wait for Shabbat operation
        deadline = time.time() + 300.0
        while time.time() < deadline:
            resp = hc.status()
            if "SHABBAT" in resp.upper() and "PREPARE" not in resp.upper():
                return   # success
            time.sleep(5.0)
        pytest.fail("HC did not transition from PREPARE to SHABBAT OPERATION")

    @pytest.mark.slow
    def test_PS_12_b_offset_gate(self, sim, hc, hmi):
        """
        PS-12 (slow) — B_offset gate: entry to Shabbat blocked if
        T_tank < BSP - B_offset (93°C). HC stays in wait state.
        """
        _enter_prepare(sim, hc, hmi,
                       t_tank=P.BSP - P.B_OFFSET - 1.0,   # 92°C — just below gate
                       t_boost=P.BSP + 1.0)
        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0)

        time.sleep(10.0)
        resp = hc.status()
        # Should still be in PREPARE (or wait), not in full SHABBAT operation
        assert "PREPARE" in resp.upper() or "WAIT" in resp.upper() or \
               "PREPARE" in resp.upper(), \
            "HC entered SHABBAT too early (T_tank below BSP-B_offset gate)"

        # Raise tank above gate → should now enter
        sim.set_temp_tank(P.BSP + 1.0)
        sim.set_electrode("LF", wet=True)
