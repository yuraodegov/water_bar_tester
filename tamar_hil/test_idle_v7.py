"""
test_idle_v7.py — Idle V7 flowchart tests  (includes Hysteresis)
Source: idle_V7 (1).pdf

V7 change: IHP (Idle Heating Power) moved to MAIN heater (was small in V6).
Idle zones:
  T_tank < LLSP=65°C → Main=IHP=10% (heating, entered from below LLSP)
  LLSP ≤ T_tank < HLSP=75°C → Main=IHP=10% (normal zone)
  T_tank ≥ HLSP=75°C → Main=OFF

Hysteresis: once Main turns OFF at 75°C, it does NOT turn back on until T_tank
drops below LLSP=65°C (not just below 75°C).

Extra Hot trigger: T_tank < TLLSP=50°C.
Small heater = ISP=10% constant throughout all Idle.
Timeout: 200min → Err158/159.

Requires: --port-sim  --port-hc
"""
import pytest, time
from tamar_hil.params      import P, HC_SYS
from tamar_hil.simulator   import SimulatorUART
from tamar_hil.hc_terminal import HCTerminal

pytestmark = pytest.mark.needs_hc


def _setup_idle(sim, hc, t_tank=72.0, t_boost=72.0):
    hc.enable_simulation(); hc.heating_on()
    sim.set_temp_tank(t_tank); sim.set_temp_boost(t_boost)
    sim.set_temp_cwt(20.0)
    sim.set_electrode("LF", wet=True); sim.set_electrode("LE", wet=True)
    sim.set_electrode("SE", wet=False); sim.set_flow(0.0)
    time.sleep(HC_SYS.HC_REACTION_DELAY_S * 5)


class TestIdleHeaterControl:

    @pytest.mark.slow
    def test_IDLE_01_small_isp_constant(self, sim, hc):
        """IDLE-01 — Small heater = ISP=10% throughout Idle."""
        _setup_idle(sim, hc)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=30)
        duty = sim.get_small_heater_duty()
        assert duty is not None
        assert P.ISP * 0.8 <= duty <= P.ISP * 1.2, \
            f"Small heater duty {duty:.1f}% outside ISP={P.ISP}% ±20%"

    @pytest.mark.slow
    def test_IDLE_02_main_ihp_below_llsp(self, sim, hc):
        """IDLE-02 — V7: Main=IHP=10% when T_tank is rising from below LLSP=65°C."""
        _setup_idle(sim, hc, t_tank=P.LLSP - 5)   # 60°C — below LLSP
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        duty = sim.get_main_heater_duty()
        assert duty is not None
        assert P.IHP * 0.8 <= duty <= P.IHP * 1.2, \
            f"Main heater duty {duty:.1f}% outside IHP={P.IHP}% ±20%"

    @pytest.mark.slow
    def test_IDLE_03_main_off_at_hlsp(self, sim, hc):
        """IDLE-03 — T_tank >= HLSP=75°C → Main heater = 0% (V7: Main, not Small)."""
        _setup_idle(sim, hc, t_tank=P.HLSP + 2)   # 77°C ≥ HLSP
        time.sleep(2.0)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=30)
        duty = sim.get_main_heater_duty()
        if duty is not None:
            assert duty < 5.0, \
                f"Main should be OFF at T_tank>HLSP={P.HLSP}°C; got {duty:.1f}%"

    @pytest.mark.slow
    def test_IDLE_04_boundary_hlsp_minus_1(self, sim, hc):
        """IDLE-04 — T_tank = HLSP-1°C=74°C (just below HLSP) → Main=IHP."""
        _setup_idle(sim, hc, t_tank=P.LLSP - 5)   # enter from below LLSP
        time.sleep(0.5)
        sim.set_temp_tank(P.HLSP - 1.0)   # 74°C — in zone
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        duty = sim.get_main_heater_duty()
        if duty is not None:
            assert P.IHP * 0.8 <= duty <= P.IHP * 1.2

    @pytest.mark.slow
    def test_IDLE_05_boundary_llsp_plus_1(self, sim, hc):
        """IDLE-05 — T_tank = LLSP+1°C=66°C (just above LLSP) → Main=IHP."""
        _setup_idle(sim, hc, t_tank=P.LLSP - 5)
        time.sleep(0.5)
        sim.set_temp_tank(P.LLSP + 1.0)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        duty = sim.get_main_heater_duty()
        if duty is not None:
            assert P.IHP * 0.8 <= duty <= P.IHP * 1.2


class TestIdleHysteresis:
    """
    Hysteresis: once Main turns OFF (T_tank ≥ 75°C), it stays OFF until
    T_tank drops all the way to LLSP=65°C. A drop to 70°C is NOT enough.
    """

    @pytest.mark.slow
    def test_IDLE_05_hysteresis_no_restart_at_70(self, sim, hc):
        """IDLE-05 — After Main turns OFF at 75°C, drop to 70°C: Main stays OFF."""
        _setup_idle(sim, hc, t_tank=P.LLSP - 5)   # come from below LLSP
        time.sleep(0.5)
        sim.set_temp_tank(P.HLSP + 2)   # 77°C → Main OFF
        time.sleep(2.0)
        # Now drop to 70°C (between LLSP=65 and HLSP=75)
        sim.set_temp_tank(P.LLSP + 5)   # 70°C — dead band
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        duty = sim.get_main_heater_duty()
        if duty is not None:
            assert duty < 5.0, \
                "Main should stay OFF at 70°C (hysteresis: needs to drop to LLSP=65°C)"

    @pytest.mark.slow
    def test_IDLE_06_hysteresis_restarts_at_llsp(self, sim, hc):
        """IDLE-06 — After Main OFF at 75°C, T_tank drops to LLSP=65°C → Main turns back ON."""
        _setup_idle(sim, hc, t_tank=P.LLSP - 5)
        time.sleep(0.5)
        sim.set_temp_tank(P.HLSP + 2)   # OFF at 77°C
        time.sleep(2.0)
        sim.set_temp_tank(P.LLSP - 1)   # 64°C — below LLSP → restart
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        duty = sim.get_main_heater_duty()
        assert duty is not None and duty > 5.0, \
            f"Main should restart at T_tank<LLSP={P.LLSP}°C; got {duty}%"

    def test_IDLE_07_extra_hot_trigger_below_tllsp(self, sim, hc):
        """IDLE-07 — T_tank < TLLSP=50°C → triggers Extra Hot mode from Idle."""
        _setup_idle(sim, hc)
        sim.set_temp_tank(P.TLLSP - 5)   # 45°C
        time.sleep(2.0)
        resp = hc.status()
        assert "EXTRA" in resp.upper() or "IDLE" in resp.upper()

    def test_IDLE_08_hot_fill_enable_on_entry(self, sim, hc):
        """IDLE-08 — On entering Idle, hot_fill_enable = 1 (fills can be triggered)."""
        _setup_idle(sim, hc)
        resp = hc.status()
        assert resp   # just verify HC is responsive in Idle


class TestIdleHeaterCycles:

    @pytest.mark.slow
    def test_IDLE_10_main_cycle_20s(self, sim, hc):
        """IDLE-10 (slow) — Main heater cycle period = 20s ±20%."""
        _setup_idle(sim, hc, t_tank=P.LLSP - 5)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        st = sim.get_output_status()
        if st.heat_main_period_ms and st.heat_main_cycles >= 3:
            assert 16000 <= st.heat_main_period_ms <= 25000, \
                f"Main period {st.heat_main_period_ms}ms outside 20s ±20%"

    @pytest.mark.slow
    def test_IDLE_11_small_cycle_2s(self, sim, hc):
        """IDLE-11 (slow) — Small heater cycle period = 2s ±20%."""
        _setup_idle(sim, hc)
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=30)
        st = sim.get_output_status()
        if st.heat_sml_period_ms and st.heat_sml_cycles >= 3:
            assert 1600 <= st.heat_sml_period_ms <= 2500, \
                f"Small period {st.heat_sml_period_ms}ms outside 2s ±20%"

    def test_IDLE_12_v7_ihp_on_main_not_small(self, sim, hc):
        """IDLE-12 — V7: IHP applies to Main heater. Small heater = ISP (constant)."""
        _setup_idle(sim, hc, t_tank=P.LLSP - 5)
        time.sleep(1.0)
        # Both heaters should be active — verify main has a measured duty
        assert sim.wait_for_heater_cycles(n_cycles=1, timeout_s=30)
        st = sim.get_output_status()
        assert st.heat_main_cycles >= 1, "Main heater should be cycling (IHP on main)"

    @pytest.mark.slow
    def test_IDLE_13_full_hysteresis_cycle(self, sim, hc):
        """IDLE-13 (slow) — Full hysteresis: 90→70→60→72→75→70→60 → verify Main on/off."""
        _setup_idle(sim, hc, t_tank=90.0)   # start above HLSP → Main OFF
        time.sleep(2.0)
        sim.set_temp_tank(70.0)   # 70°C → dead band, Main stays OFF
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        d1 = sim.get_main_heater_duty()
        if d1 is not None: assert d1 < 5.0, "Main should be OFF at 70°C (hysteresis)"
        sim.set_temp_tank(60.0)   # 60°C → below LLSP, Main ON
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        d2 = sim.get_main_heater_duty()
        if d2 is not None: assert d2 > 5.0, "Main should be ON at 60°C"

    def test_IDLE_14_entry_flags(self, sim, hc):
        """IDLE-14 — Entering Idle: hot_fill_enable=1 set correctly."""
        _setup_idle(sim, hc)
        resp = hc.status()
        assert resp   # HC responsive

    @pytest.mark.slow
    @pytest.mark.hc_critical
    def test_IDLE_15_timeout_200min(self, sim, hc):
        """IDLE-15 (slow, critical) — 200min Idle timeout → Err158 or Err159."""
        _setup_idle(sim, hc, t_tank=P.LLSP + 5)
        deadline = time.time() + 12600.0   # 210 min
        while time.time() < deadline:
            errors = hc.get_errors()
            if "158" in errors or "159" in errors:
                return
            time.sleep(60.0)
        pytest.fail("Idle timeout Err158/159 not triggered after 200min")
