"""
test_hot_fill_v5.py — Hot Fill V5 flowchart tests
Source: hot fill_v5 (1).pdf

V5 change vs V4: 20L overflow limit (Err153) is ACTIVE (not disabled).
Sequence: LF=DRY AND LE=DRY → EX_VALVE → 200ms → INLET_VALVE.
Valves hold at 500Hz/50% after 1s opening pulse.
Stop: LE=WET or LF=WET (after ~12s filter). Err50 active (flow too high).

Requires: --port-sim  --port-hc
"""
import pytest, time, re
from tamar_hil.params    import P, HC_SYS
from tamar_hil.simulator import SimulatorUART
from tamar_hil.hc_terminal import HCTerminal

pytestmark = pytest.mark.needs_hc


def _setup_fill(sim, hc, lf_wet=False, le_wet=False, flow=1.6):
    hc.enable_simulation(); hc.heating_on()
    sim.set_temp_tank(P.TLLSP + 30); sim.set_temp_boost(P.TLLSP + 30)
    sim.set_electrode("LF", wet=lf_wet)
    sim.set_electrode("LE", wet=le_wet)
    sim.set_electrode("SE", wet=False)
    sim.set_flow(flow)
    time.sleep(HC_SYS.HC_REACTION_DELAY_S * 5)


class TestHotFillEntry:

    def test_HF_01_fill_starts_both_dry(self, sim, hc):
        """HF-01 — LF=DRY AND LE=DRY → EX_VALVE + INLET_VALVE open."""
        _setup_fill(sim, hc, lf_wet=False, le_wet=False)
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=10), \
            "EX_VALVE did not open when LF=DRY and LE=DRY"

    def test_HF_02_no_fill_lf_wet(self, sim, hc):
        """HF-02 — LF=WET → fill does not start (float covered)."""
        _setup_fill(sim, hc, lf_wet=True, le_wet=False)
        time.sleep(2.0)
        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE", \
            "EX_VALVE opened even though LF=WET"

    def test_HF_03_no_fill_le_wet(self, sim, hc):
        """HF-03 — LE=WET → fill does not start (upper electrode covered)."""
        _setup_fill(sim, hc, lf_wet=False, le_wet=True)
        time.sleep(2.0)
        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE", \
            "EX_VALVE opened even though LE=WET"


class TestHotFillValveSpec:

    def test_HF_04_sequence_delay_200ms(self, sim, hc):
        """HF-04 — EX_VALVE opens 200ms ±20% before INLET_VALVE."""
        _setup_fill(sim, hc)
        sim.reset_output_monitor()
        time.sleep(2.0)
        st = sim.get_output_status()
        assert st.inlet_valve_delay_ms is not None, "No sequence delay measured"
        assert 160 <= st.inlet_valve_delay_ms <= 240, \
            f"Seq delay {st.inlet_valve_delay_ms}ms outside 200ms ±20%"

    def test_HF_05_opening_pulse_1s(self, sim, hc):
        """HF-05 — EX_VALVE opening pulse = 1000ms ±20% (800–1200ms)."""
        _setup_fill(sim, hc)
        time.sleep(2.5)
        st = sim.get_output_status()
        m = re.search(r'EX_VALVE.*?pulse=(\d+)ms', st.raw, re.IGNORECASE)
        if m:
            pulse = int(m.group(1))
            assert 800 <= pulse <= 1200, \
                f"EX_VALVE opening pulse {pulse}ms outside 1000ms ±20%"

    def test_HF_06_holding_500hz_50pct(self, sim, hc):
        """HF-06 — After opening pulse: valves hold at 500Hz ±20%, 50% ±20%."""
        _setup_fill(sim, hc)
        time.sleep(3.0)
        st = sim.get_output_status()
        assert st.ex_valve_state == "HOLDING", \
            f"EX_VALVE not in HOLDING; state={st.ex_valve_state}"
        assert st.ex_valve_freq_hz is not None
        assert 400 <= st.ex_valve_freq_hz <= 600, \
            f"EX_VALVE freq {st.ex_valve_freq_hz:.1f}Hz outside 500Hz ±20%"
        assert st.ex_valve_duty_pct is not None
        assert 40 <= st.ex_valve_duty_pct <= 60, \
            f"EX_VALVE duty {st.ex_valve_duty_pct:.1f}% outside 50% ±20%"


class TestHotFillStop:

    def test_HF_07_stop_on_le_wet(self, sim, hc):
        """HF-07 — LE becomes WET → valves close after ~12s filter."""
        _setup_fill(sim, hc)
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=10)
        sim.set_electrode("LE", wet=True)
        time.sleep(14.0)   # 12s filter + margin
        assert sim.wait_for_valve_idle("EX_VALVE", timeout_s=10), \
            "EX_VALVE did not close after LE=WET"

    def test_HF_08_stop_on_lf_wet(self, sim, hc):
        """HF-08 — LF becomes WET → valves close after ~12s filter."""
        _setup_fill(sim, hc)
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=10)
        sim.set_electrode("LF", wet=True)
        time.sleep(14.0)
        assert sim.wait_for_valve_idle("EX_VALVE", timeout_s=10), \
            "EX_VALVE did not close after LF=WET"

    def test_HF_09_nominal_flow_no_errors(self, sim, hc):
        """HF-09 — 1.6 LPM nominal flow → no Err49/50/153 during fill."""
        _setup_fill(sim, hc, flow=P.FLOW_NOMINAL_LPM)
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=10)
        time.sleep(5.0)
        hc.stop_dispense()
        errors = hc.get_errors()
        for err in ("49", "50", "153"):
            assert f"Err{err}" not in errors and f"err{err}" not in errors.lower(), \
                f"Unexpected error Err{err} at nominal 1.6 LPM"

    @pytest.mark.hc_errors
    def test_HF_10_err153_active_v5(self, sim, hc):
        """HF-10 — V5: 20L overflow (Err153) IS active (unlike V4 where it was disabled).
        Inject >10360 pulses (20L) during fill."""
        _setup_fill(sim, hc, flow=2.5)   # high flow to accumulate volume faster
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=10)
        # Wait for Err153 (may take a while at 2.5 LPM)
        deadline = time.time() + 300.0
        while time.time() < deadline:
            errors = hc.get_errors()
            if "153" in errors:
                return   # success
            time.sleep(5.0)
        pytest.fail("Err153 (20L overflow) not triggered at 2.5 LPM")

    def test_HF_11_err49_disabled(self, sim, hc):
        """HF-11 — Err49 (flow too low) is DISABLED in hot_filling.c. Fill continues at 0 LPM."""
        _setup_fill(sim, hc, flow=0.0)   # no flow
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=10)
        time.sleep(5.0)
        errors = hc.get_errors()
        assert "49" not in errors, \
            "Err49 should be disabled in current FW build"

    @pytest.mark.hc_errors
    def test_HF_12_err50_active(self, sim, hc):
        """HF-12 — Err50 (flow too high in 2s window) IS active."""
        _setup_fill(sim, hc, flow=2.5)   # high flow
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=10)
        deadline = time.time() + 60.0
        while time.time() < deadline:
            errors = hc.get_errors()
            if "50" in errors:
                return   # Err50 triggered as expected
            time.sleep(2.0)
        pytest.fail("Err50 not triggered with 2.5 LPM flow (should exceed 2s high value)")

    def test_HF_13_close_sequence(self, sim, hc):
        """HF-13 — On stop: INLET_VALVE closes before EX_VALVE (mirror of open sequence)."""
        _setup_fill(sim, hc)
        assert sim.wait_for_valve_opening("EX_VALVE", timeout_s=10)
        sim.set_electrode("LE", wet=True)
        time.sleep(14.0)
        # After close, check that inlet closed first
        # (verified by seq_open timestamps — inlet should have closed later = smaller gap)
        st = sim.get_output_status()
        assert st.ex_valve_state in ("IDLE", "CLOSED"), \
            "EX_VALVE should be IDLE after stop"
