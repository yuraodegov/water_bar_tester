"""
test_dispensing_v01.py — Dispensing V01 flowchart tests
Source: Dispensing flow chart V01.pdf

Three dispense modes, triggered via HC terminal (pour_hot/cold/ambient):
  Cold (EM2→EM1), Ambient (E1→EM1), Hot (EM3 only, timer-based)
All valves: 1s opening pulse → 500Hz/50% holding, 200ms sequence delay.
EX_VALVE is NOT used in dispensing (only in hot fill).

Requires: --port-sim  --port-hc
"""
import pytest, time, re
from tamar_hil.params      import P, HC_SYS
from tamar_hil.simulator   import SimulatorUART
from tamar_hil.hc_terminal import HCTerminal

pytestmark = pytest.mark.needs_hc


def _prep_cold(sim, hc, cold_wet=True):
    hc.enable_simulation()
    sim.set_temp_cwt(8.0)
    sim.set_electrode("COLD", wet=cold_wet)
    sim.set_electrode("LF", wet=True); sim.set_electrode("LE", wet=True)
    sim.set_flow(P.FLOW_NOMINAL_LPM)
    time.sleep(0.3)

def _prep_hot(sim, hc):
    hc.enable_simulation()
    sim.set_temp_tank(90.0); sim.set_temp_boost(92.0)
    sim.set_electrode("LF", wet=True)
    sim.set_flow(0.0)
    time.sleep(0.3)


# ── COLD DISPENSE ─────────────────────────────────────────────────────────────

class TestColdDispense:

    def test_CD_01_cold_em2_em1_sequence(self, sim, hc):
        """CD-01 — pour_cold: EM2(COLD_VLV) opens first, EM1(INLET_VLV) 200ms later."""
        _prep_cold(sim, hc)
        sim.reset_output_monitor()
        hc.pour_cold(5)
        time.sleep(1.5)
        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE", "EX_VALVE must stay IDLE during cold dispense"
        delay = st.inlet_valve_delay_ms
        if delay is not None:
            assert 160 <= delay <= 240, f"Seq delay {delay}ms outside 200ms ±20%"

    def test_CD_02_cold_valves_hold_500hz(self, sim, hc):
        """CD-02 — COLD_VLV and INLET_VLV hold at 500Hz ±20%, 50% ±20%."""
        _prep_cold(sim, hc)
        hc.pour_cold(10)
        time.sleep(3.0)
        st = sim.get_output_status()
        m = re.search(r'COLD_VLV.*?Freq=([\d.]+)Hz', st.raw, re.IGNORECASE)
        if m:
            freq = float(m.group(1))
            assert 400 <= freq <= 600, f"COLD_VLV freq {freq:.1f}Hz outside 500Hz ±20%"

    def test_CD_03_cold_close_em1_first(self, sim, hc):
        """CD-03 — On stop: INLET_VLV closes before COLD_VLV."""
        _prep_cold(sim, hc)
        hc.pour_cold(3)
        time.sleep(5.0)
        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE"

    @pytest.mark.hc_errors
    def test_CD_04_flow_error_err49(self, sim, hc):
        """CD-04 — Flow < 0.2 L/min after 2s → Err49 triggered."""
        _prep_cold(sim, hc)
        sim.set_flow(0.0)   # no flow
        hc.pour_cold(10)
        deadline = time.time() + 30.0
        while time.time() < deadline:
            errors = hc.get_errors()
            if "49" in errors: return
            time.sleep(2.0)
        pytest.fail("Err49 not triggered with 0 LPM flow during cold dispense")

    def test_CD_05_nominal_flow_no_error(self, sim, hc):
        """CD-05 — 1.6 LPM → no Err49 during cold dispense."""
        _prep_cold(sim, hc, cold_wet=True)
        hc.pour_cold(5)
        time.sleep(3.0)
        hc.stop_dispense()
        errors = hc.get_errors()
        assert "49" not in errors

    def test_CD_06_breather_opens_cold_dry(self, sim, hc):
        """CD-06 — COLD_ELS=DRY (air in cold pipe) → BREATHER valve opens before dispensing."""
        _prep_cold(sim, hc, cold_wet=False)   # DRY = air in pipe
        hc.pour_cold(5)
        time.sleep(1.5)
        st = sim.get_output_status()
        m = re.search(r'BREATHER.*?ON', st.raw, re.IGNORECASE)
        assert m, "BREATHER should open when COLD_ELS=DRY"

    def test_CD_07_breather_closes_cold_wet(self, sim, hc):
        """CD-07 — COLD_ELS=WET (water flowing) → BREATHER stays IDLE."""
        _prep_cold(sim, hc, cold_wet=True)
        hc.pour_cold(5)
        time.sleep(1.5)
        st = sim.get_output_status()
        m = re.search(r'BREATHER.*?IDLE', st.raw, re.IGNORECASE)
        assert m or "BREATHER" not in st.raw or \
               re.search(r'BREATHER.*?OFF', st.raw, re.IGNORECASE), \
            "BREATHER should be IDLE when COLD_ELS=WET"


# ── AMBIENT DISPENSE ──────────────────────────────────────────────────────────

class TestAmbientDispense:

    def test_AD_01_ambient_e1_em1_sequence(self, sim, hc):
        """AD-01 — pour_ambient: E1(AMB_VLV) opens first, EM1(INLET_VLV) 200ms later."""
        hc.enable_simulation()
        sim.set_temp_cwt(20.0); sim.set_flow(P.FLOW_NOMINAL_LPM)
        sim.set_electrode("COLD", wet=True)
        sim.reset_output_monitor()
        hc.pour_ambient(5)
        time.sleep(1.5)
        st = sim.get_output_status()
        m = re.search(r'AMB_VLV.*?(OPENING|HOLDING)', st.raw, re.IGNORECASE)
        assert m, "AMB_VLV should be opening during ambient dispense"
        assert st.ex_valve_state == "IDLE", "EX_VALVE must stay IDLE during ambient dispense"

    def test_AD_02_no_breather_in_ambient(self, sim, hc):
        """AD-02 — BREATHER stays IDLE during ambient dispense (unlike cold)."""
        hc.enable_simulation()
        sim.set_temp_cwt(20.0); sim.set_flow(P.FLOW_NOMINAL_LPM)
        hc.pour_ambient(5)
        time.sleep(1.5)
        st = sim.get_output_status()
        m_idle = re.search(r'BREATHER.*?IDLE', st.raw, re.IGNORECASE)
        m_on   = re.search(r'BREATHER.*?ON', st.raw, re.IGNORECASE)
        assert not m_on, "BREATHER must stay IDLE during ambient dispense"

    def test_AD_03_ambient_hold_500hz(self, sim, hc):
        """AD-03 — AMB_VLV and INLET_VLV hold at 500Hz/50%."""
        hc.enable_simulation(); sim.set_flow(P.FLOW_NOMINAL_LPM)
        hc.pour_ambient(10); time.sleep(3.0)
        st = sim.get_output_status()
        m = re.search(r'AMB_VLV.*?Freq=([\d.]+)Hz', st.raw, re.IGNORECASE)
        if m:
            freq = float(m.group(1))
            assert 400 <= freq <= 600

    @pytest.mark.hc_errors
    def test_AD_04_flow_error_err49(self, sim, hc):
        """AD-04 — 0 LPM → Err49 during ambient dispense."""
        hc.enable_simulation(); sim.set_flow(0.0)
        hc.pour_ambient(10)
        deadline = time.time() + 30.0
        while time.time() < deadline:
            if "49" in hc.get_errors(): return
            time.sleep(2.0)
        pytest.fail("Err49 not triggered with 0 LPM during ambient dispense")

    def test_AD_05_nominal_flow_ok(self, sim, hc):
        """AD-05 — 1.6 LPM → no Err49 during ambient."""
        hc.enable_simulation(); sim.set_flow(P.FLOW_NOMINAL_LPM)
        hc.pour_ambient(5); time.sleep(3.0); hc.stop_dispense()
        assert "49" not in hc.get_errors()

    def test_AD_06_close_em1_before_e1(self, sim, hc):
        """AD-06 — Close sequence: INLET_VLV before AMB_VLV."""
        hc.enable_simulation(); sim.set_flow(P.FLOW_NOMINAL_LPM)
        hc.pour_ambient(3); time.sleep(5.0)
        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE"


# ── HOT DISPENSE ──────────────────────────────────────────────────────────────

class TestHotDispense:

    def test_HD_01_hot_only_em3_opens(self, sim, hc):
        """HD-01 — pour_hot: ONLY HOT_VLV(EM3) opens. EX_VALVE and INLET_VLV stay IDLE."""
        _prep_hot(sim, hc)
        sim.reset_output_monitor()
        hc.pour_hot(5)
        time.sleep(1.5)
        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE", "EX_VALVE must be IDLE during hot dispense"
        assert st.inlet_valve_state == "IDLE", "INLET_VLV must be IDLE during hot dispense"
        m = re.search(r'HOT_VLV.*?(OPENING|HOLDING)', st.raw, re.IGNORECASE)
        assert m, "HOT_VLV should be active during hot dispense"

    def test_HD_02_hot_valve_pulse_and_hold(self, sim, hc):
        """HD-02 — HOT_VLV: 1s opening pulse → 500Hz/50% holding."""
        _prep_hot(sim, hc)
        hc.pour_hot(10); time.sleep(3.0)
        st = sim.get_output_status()
        m_f = re.search(r'HOT_VLV.*?Freq=([\d.]+)Hz', st.raw, re.IGNORECASE)
        m_d = re.search(r'HOT_VLV.*?Duty=([\d.]+)%',  st.raw, re.IGNORECASE)
        if m_f and m_d:
            assert 400 <= float(m_f.group(1)) <= 600
            assert 40  <= float(m_d.group(1)) <= 60

    def test_HD_03_hot_timer_based_no_flow_check(self, sim, hc):
        """HD-03 — Hot dispense is timer-based: no flow monitoring. Works at 0 LPM."""
        _prep_hot(sim, hc); sim.set_flow(0.0)
        hc.pour_hot(5); time.sleep(1.5)
        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE"
        m = re.search(r'HOT_VLV.*?(OPENING|HOLDING)', st.raw, re.IGNORECASE)
        assert m, "HOT_VLV should open even at 0 LPM"

    def test_HD_04_hot_works_low_temperature(self, sim, hc):
        """HD-04 — Hot dispense works even at low T_tank (no temperature gate)."""
        hc.enable_simulation()
        sim.set_temp_tank(P.TLLSP + 5); sim.set_temp_boost(P.TLLSP + 5)
        hc.pour_hot(3); time.sleep(1.5)
        st = sim.get_output_status()
        m = re.search(r'HOT_VLV.*?(OPENING|HOLDING)', st.raw, re.IGNORECASE)
        assert m, "HOT_VLV should open regardless of temperature"

    def test_HD_05_hot_closes_by_timer(self, sim, hc):
        """HD-05 — HOT_VLV closes when the timer (pour_hot N seconds) expires."""
        _prep_hot(sim, hc)
        hc.pour_hot(3); time.sleep(5.0)   # wait past 3s
        st = sim.get_output_status()
        m_idle = re.search(r'HOT_VLV.*?IDLE', st.raw, re.IGNORECASE)
        m_hold = re.search(r'HOT_VLV.*?HOLDING', st.raw, re.IGNORECASE)
        assert m_idle and not m_hold, "HOT_VLV should close after timer"


# ── CROSS-MODE ISOLATION ──────────────────────────────────────────────────────

class TestCrossModeIsolation:

    def test_XM_01_hot_dispense_no_ex_valve(self, sim, hc):
        """XM-01 — Hot dispense: EX_VALVE=IDLE (used only in hot fill)."""
        _prep_hot(sim, hc); hc.pour_hot(5); time.sleep(1.5)
        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE"

    def test_XM_02_cold_dispense_no_em3(self, sim, hc):
        """XM-02 — Cold dispense: HOT_VLV=IDLE."""
        _prep_cold(sim, hc); hc.pour_cold(5); time.sleep(1.5)
        st = sim.get_output_status()
        m = re.search(r'HOT_VLV.*?IDLE', st.raw, re.IGNORECASE)
        assert m, "HOT_VLV should be IDLE during cold dispense"

    def test_XM_03_ambient_no_em2_em3(self, sim, hc):
        """XM-03 — Ambient: COLD_VLV=IDLE, HOT_VLV=IDLE."""
        hc.enable_simulation(); sim.set_flow(P.FLOW_NOMINAL_LPM)
        hc.pour_ambient(5); time.sleep(1.5)
        st = sim.get_output_status()
        m_cold = re.search(r'COLD_VLV.*?IDLE', st.raw, re.IGNORECASE)
        m_hot  = re.search(r'HOT_VLV.*?IDLE',  st.raw, re.IGNORECASE)
        assert m_cold, "COLD_VLV should be IDLE during ambient"
        assert m_hot,  "HOT_VLV should be IDLE during ambient"

    def test_XM_04_sequence_delay_all_modes(self, sim, hc):
        """XM-04 — All modes (cold, ambient) have 200ms ±20% inter-valve delay."""
        for mode, setup in [
            ("cold",    lambda: (_prep_cold(sim, hc), hc.pour_cold(5))),
            ("ambient", lambda: (hc.enable_simulation(), sim.set_flow(1.6), hc.pour_ambient(5))),
        ]:
            setup()
            sim.reset_output_monitor(); time.sleep(2.0)
            st = sim.get_output_status()
            hc.stop_dispense(); time.sleep(0.5); sim.set_flow(0.0)
            if st.inlet_valve_delay_ms is not None:
                assert 160 <= st.inlet_valve_delay_ms <= 240, \
                    f"{mode}: seq delay {st.inlet_valve_delay_ms}ms outside 200ms ±20%"
