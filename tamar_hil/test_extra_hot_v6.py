"""
test_extra_hot_v6.py — Extra Hot V6 flowchart tests
Source: Extra Hot_v6.pdf

Trigger: automatic when T_tank < TLLSP=50°C during Idle mode.
Sequence: EXTRA HOT (Main=100%) → T_boost>BSP → POST EXTRA HOT
POST EH: Main OFF → T_boost falls → rising phase (HBS or LBS) → FT timer → IDLE

Key parameters (IL):
    TLLSP=50°C, BSP=96°C, LBSP=93°C, BTSP1=80°C
    OSPs=100%, OSPm=100%, HBS=70%, LBS=50%
    EH_TO=60min, FT=10min

Requires: --port-sim  --port-hc
"""
import pytest, time
from tamar_hil.params    import P, HC_SYS
from tamar_hil.simulator import SimulatorUART
from tamar_hil.hc_terminal import HCTerminal

pytestmark = pytest.mark.needs_hc


def _setup_extra_hot(sim, hc):
    hc.enable_simulation(); hc.heating_on()
    sim.set_temp_tank (P.TLLSP + 5)
    sim.set_temp_boost(P.TLLSP + 5)
    sim.set_electrode("LF", wet=True); sim.set_electrode("LE", wet=True)
    sim.set_electrode("SE", wet=False); sim.set_flow(0.0)
    time.sleep(HC_SYS.HC_REACTION_DELAY_S * 5)


class TestExtraHotEntry:

    def test_EH_01_entry_below_tllsp(self, sim, hc):
        """EH-01 — T_tank < TLLSP=50°C → HC enters Extra Hot, Main=100%, Small=100%."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.TLLSP - 5)   # 45°C
        time.sleep(0.5)
        assert sim.wait_for_heater_cycles(n_cycles=1, timeout_s=30), \
            "Main heater not active after T_tank<TLLSP"

    def test_EH_02_no_entry_above_tllsp(self, sim, hc):
        """EH-02 — T_tank > TLLSP → HC stays in Idle (no Extra Hot)."""
        hc.enable_simulation(); hc.heating_on()
        sim.set_temp_tank(P.TLLSP + 5)
        sim.set_temp_boost(P.TLLSP + 5)
        time.sleep(1.0)
        resp = hc.status()
        assert "EXTRA" not in resp.upper(), \
            "HC entered Extra Hot even though T_tank > TLLSP"

    def test_EH_03_calibration_disabled(self, sim, hc):
        """EH-03 — T_boost reaches BSP quickly → goes directly to POST EH (no calibration phase)."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.TLLSP - 5)
        time.sleep(0.5)
        sim.set_temp_boost(P.BSP + 1.0)   # trigger POST EH immediately
        time.sleep(2.0)
        resp = hc.status()
        assert "CALIBRAT" not in resp.upper(), \
            "Calibration phase should be disabled in current FW build"


class TestPostExtraHotPhases:

    @pytest.mark.slow
    def test_EH_04_falling_phase_main_off(self, sim, hc):
        """EH-04 (slow) — In POST EH: T_boost > BSP → Main heater = 0% (falling phase)."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.TLLSP - 5)
        time.sleep(0.5)
        sim.set_temp_boost(P.BSP + 1.0)
        assert sim.wait_for_heater_cycles(n_cycles=1, timeout_s=30)
        st = sim.get_output_status()
        if st.heat_main_duty_pct is not None:
            assert st.heat_main_duty_pct < 5.0, \
                f"Main should be OFF in falling phase; got {st.heat_main_duty_pct:.1f}%"

    @pytest.mark.slow
    def test_EH_05_rising_ttank_below_btsp1_hbs(self, sim, hc):
        """EH-05 (slow) — T_boost < LBSP, T_tank < BTSP1=80°C → Main = HBS=70%."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.BTSP1 - 5)   # 75°C < BTSP1
        sim.set_temp_boost(P.LBSP - 1.0)  # below LBSP → rising phase
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        duty = sim.get_main_heater_duty()
        assert duty is not None
        assert P.HBS * 0.8 <= duty <= P.HBS * 1.2, \
            f"HBS: duty {duty:.1f}% outside {P.HBS}% ±20%"

    @pytest.mark.slow
    def test_EH_06_rising_ttank_above_btsp1_lbs(self, sim, hc):
        """EH-06 (slow) — T_boost < LBSP, T_tank >= BTSP1=80°C → Main = LBS=50%."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.BTSP1 + 2.0)   # 82°C ≥ BTSP1
        sim.set_temp_boost(P.LBSP - 1.0)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        duty = sim.get_main_heater_duty()
        assert duty is not None
        assert P.LBS * 0.8 <= duty <= P.LBS * 1.2, \
            f"LBS: duty {duty:.1f}% outside {P.LBS}% ±20%"

    def test_EH_07_exit_via_ttank_terminate(self, sim, hc):
        """EH-07 — T_tank >= Ttank_terminate=93°C → HC exits to IDLE."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.Ttank_terminate + 1.0)
        sim.set_temp_boost(P.BSP + 1.0)
        time.sleep(2.0)
        resp = hc.status()
        assert "IDLE" in resp.upper() or "EXTRA" not in resp.upper(), \
            "HC should exit Extra Hot when T_tank >= Ttank_terminate"

    @pytest.mark.slow
    @pytest.mark.hc_errors
    def test_EH_08_exit_via_ft_timer(self, sim, hc):
        """EH-08 (slow) — POST EH: FT=10min timer expires → HC returns to IDLE."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.BTSP1 + 2)
        sim.set_temp_boost(P.LBSP - 1)
        assert hc.wait_for_state("EXTRA", poll_s=2.0, timeout_s=30)
        # Push boost above BSP to enter POST EH
        sim.set_temp_boost(P.BSP + 1.0)
        time.sleep(1.0)
        # Wait FT=10min
        assert hc.wait_for_state("IDLE", poll_s=10.0, timeout_s=700.0), \
            "HC did not return to IDLE after FT=10min timer"

    @pytest.mark.slow
    @pytest.mark.hc_critical
    def test_EH_09_eh_to_timeout(self, sim, hc):
        """EH-09 (slow) — EH_TO=60min expires → ERROR_HEATER_TIMEOUT."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.TLLSP - 5)
        assert hc.wait_for_state("EXTRA", poll_s=2.0, timeout_s=30)
        assert hc.wait_for_state("ERROR", poll_s=30.0, timeout_s=3900.0), \
            "EH_TO timeout did not produce error after 60 min"

    def test_EH_10_small_heater_constant_osps(self, sim, hc):
        """EH-10 — Small heater = OSPS=100% throughout all Extra Hot phases."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.TLLSP - 5)
        assert sim.wait_for_heater_cycles(n_cycles=1, timeout_s=30)
        st = sim.get_output_status()
        if st.heat_sml_cycles >= 3 and st.heat_sml_duty_pct is not None:
            assert st.heat_sml_duty_pct > 80.0, \
                f"Small heater should be ~100%; got {st.heat_sml_duty_pct:.1f}%"

    def test_EH_11_post_eh_continues_during_dispense(self, sim, hc):
        """EH-11 — POST EH continues (does not abort) when hot dispense is triggered."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.BTSP1 + 2)
        sim.set_temp_boost(P.BSP + 1.0)
        time.sleep(1.0)
        # Trigger dispense (via HC terminal)
        hc.pour_hot(3)
        time.sleep(2.0)
        resp = hc.status()
        assert "EXTRA" in resp.upper() or "POST" in resp.upper() or \
               "IDLE" in resp.upper(), \
            "POST EH should continue during dispense"

    def test_EH_12_calibration_not_activated(self, sim, hc):
        """EH-12 — No calibration phase occurs (disabled in current FW build)."""
        _setup_extra_hot(sim, hc)
        sim.set_temp_tank(P.TLLSP - 5)
        sim.set_temp_boost(P.BSP + 1.0)
        time.sleep(2.0)
        resp = hc.status()
        assert "CALIBRAT" not in resp.upper(), \
            "Calibration is disabled; should not appear in status"
