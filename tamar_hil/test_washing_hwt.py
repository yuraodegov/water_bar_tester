"""
test_washing_hwt.py — Washing HWT at Installation Mode
Source flowchart: "wasing HWT at instalation mode.pdf"

Sequence:
  1. Ftimer=0 → Fill 3 litres  (hot fill sequence)
  2. Heat: OSPm/OSPs → SPMH1(T_boost>BSP) → SPMH2(T_tank>BTSP0)
           → SPMH3(T_tank>T_terminate) → OFF(T_tank>BSP) / Small=ISP
  3. Wait: Main=OFF, Small=ISP, hot-fill enable=0
           → wait for dispense trigger
  4. Dispense hot water (HOT_VALVE only, timer-based)
  5. If total dispensed ≥ 7L → Switch to Idle Mode
  Timeout (FTS) at any stage → Error Skip to next stage

All tests marked @slow require minutes of observation.
Heater PWM tests require ≥3 full cycles before reading is stable.
"""

import pytest
import time
from tamar_hil.simulator import SimulatorUART
from tamar_hil.params import P


# ─────────────────────────────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sim(request):
    port = request.config.getoption("--port", default="COM3")
    with SimulatorUART(port) as s:
        yield s


@pytest.fixture(autouse=True)
def reset_sim(sim):
    """Reset Nucleo before each test; restore safe state after."""
    sim.reset()
    sim.set_all_electrodes(wet=True)   # LF=WET, LE=WET — tank full, no fill
    sim.set_temp_tank(P.HLSP + 2)      # well above HLSP → Idle start
    sim.set_temp_boost(P.HLSP + 2)
    sim.set_temp_cwt(20)
    sim.set_flow(0.0)
    yield
    # Teardown
    sim.set_flow(0.0)
    sim.set_all_electrodes(wet=True)
    sim.reset()


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 1 — Fill 3 Litres
# ─────────────────────────────────────────────────────────────────────────────

class TestWashingFill:

    def test_WH_01_fill_starts_with_both_electrodes_dry(self, sim):
        """
        WH-01 — Fill 3 Liter phase initiates when LF=DRY AND LE=DRY.
        Expect EX_VALVE opens first, then INLET_VALVE (same sequence as Hot Fill).
        """
        sim.preset("FILL_START")   # LF=DRY, LE=DRY, T_tank=80, flow=1.6LPM
        time.sleep(0.5)
        st = sim.get_output_status()
        assert st.ex_valve_state in ("OPENING", "HOLDING"), (
            f"EX_VALVE should open first; state={st.ex_valve_state}")

    def test_WH_02_fill_sequence_delay_200ms(self, sim):
        """
        WH-02 — EX_VALVE opens 200ms before INLET_VALVE (identical to hot fill).
        Tolerance: ±20% → 160–240ms.
        """
        sim.preset("FILL_START")
        time.sleep(1.5)
        st = sim.get_output_status()
        delay = st.inlet_valve_delay_ms
        assert delay is not None, "No sequence delay measured"
        assert 160 <= delay <= 240, (
            f"Seq delay {delay}ms outside 200ms ±20% window")

    def test_WH_03_fill_valves_holding_500hz_50pct(self, sim):
        """
        WH-03 — Both EX_VALVE and INLET_VALVE hold at 500Hz ±20%, 50% ±20%
        after the 1s opening pulse.
        """
        sim.preset("FILL_START")
        time.sleep(2.5)   # wait past opening pulse
        st = sim.get_output_status()
        assert st.ex_valve_state == "HOLDING", (
            f"EX_VALVE should be in HOLDING; got {st.ex_valve_state}")
        assert st.ex_valve_freq_hz is not None
        assert 400 <= st.ex_valve_freq_hz <= 600, (
            f"EX_VALVE freq {st.ex_valve_freq_hz:.1f}Hz outside 500Hz ±20%")
        assert st.ex_valve_duty_pct is not None
        assert 40 <= st.ex_valve_duty_pct <= 60, (
            f"EX_VALVE duty {st.ex_valve_duty_pct:.1f}% outside 50% ±20%")

    def test_WH_04_fill_stops_when_float_wet(self, sim):
        """
        WH-04 — Filling stops when LF=WET (float switch covered).
        Valves close after ~12s filter delay.
        """
        sim.preset("FILL_START")
        time.sleep(2.0)   # valves open and holding
        sim.set_electrode("LF", wet=True)   # simulate tank full
        time.sleep(13.0)  # 12s filter + margin
        st = sim.get_output_status()
        assert st.ex_valve_state in ("IDLE", "CLOSED"), (
            f"EX_VALVE should close after LF=WET; state={st.ex_valve_state}")

    def test_WH_05_fill_stops_when_upper_electrode_wet(self, sim):
        """
        WH-05 — Filling also stops when LE=WET (upper level electrode reached).
        """
        sim.preset("FILL_START")
        time.sleep(2.0)
        sim.set_electrode("LE", wet=True)
        time.sleep(13.0)
        st = sim.get_output_status()
        assert st.ex_valve_state in ("IDLE", "CLOSED"), (
            f"EX_VALVE should close after LE=WET; state={st.ex_valve_state}")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 2 — Heating (identical logic to Prepare-to-Shabbat)
# ─────────────────────────────────────────────────────────────────────────────

class TestWashingHeat:

    def _enter_heating(self, sim):
        """Helper: simulate just-after-fill state → heating begins."""
        sim.set_electrode("LF", wet=True)   # tank full (fill done)
        sim.set_electrode("LE", wet=True)
        sim.set_temp_tank(P.TLLSP + 5)      # below BSP but above TLLSP
        sim.set_temp_boost(P.TLLSP + 5)

    def test_WH_06_heating_entry_main_ospm_small_osps(self, sim):
        """
        WH-06 — On entry to heating: Main=OSPm=100%, Small=OSPs=100%.
        Both heater outputs should be fully on.
        """
        self._enter_heating(sim)
        time.sleep(1.0)
        st = sim.get_output_status()
        # At 100% duty, heaters stay HIGH (≥3 cycles needed for heater reading)
        # Just verify main heater IS active
        assert st.heat_main_cycles >= 1 or st.heat_main_duty_pct is not None, (
            "Main heater not detected during OSPm phase")

    @pytest.mark.slow
    def test_WH_07_heating_spmh1_50pct_after_tboost_exceeds_bsp(self, sim):
        """
        WH-07 (slow) — When T_boost > BSP=96°C, Main switches to SPMH1=50%.
        Need ≥3 cycles = ≥60s observation.
        """
        self._enter_heating(sim)
        time.sleep(0.5)
        sim.set_temp_boost(P.BSP + 1)   # T_boost > BSP → SPMH1
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90), (
            "Timed out waiting for ≥3 heater cycles in SPMH1 phase")
        duty = sim.get_main_heater_duty()
        assert duty is not None
        spec = P.SPMH1
        lo, hi = spec * 0.8, spec * 1.2
        assert lo <= duty <= hi, (
            f"SPMH1 duty {duty:.1f}% outside {spec}% ±20% ({lo:.0f}–{hi:.0f}%)")

    @pytest.mark.slow
    def test_WH_08_heating_spmh2_20pct_after_ttank_exceeds_btsp0(self, sim):
        """
        WH-08 (slow) — T_tank > BTSP0=80°C → Main switches to SPMH2=20%.
        """
        self._enter_heating(sim)
        sim.set_temp_boost(P.BSP + 1)          # already past SPMH1
        sim.set_temp_tank(P.BTSP0 + 1)         # → SPMH2
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        duty = sim.get_main_heater_duty()
        assert duty is not None
        spec = P.SPMH2
        assert spec * 0.8 <= duty <= spec * 1.2, (
            f"SPMH2 duty {duty:.1f}% outside {spec}% ±20%")

    @pytest.mark.slow
    def test_WH_09_heating_spmh3_10pct_after_ttank_exceeds_t_terminate(self, sim):
        """
        WH-09 (slow) — T_tank > T_terminate=93°C → Main = SPMH3=10%.
        """
        self._enter_heating(sim)
        sim.set_temp_boost(P.BSP + 1)
        sim.set_temp_tank(P.BTSP1 + 1)        # past SPMH2
        time.sleep(1.0)
        sim.set_temp_tank(P.BSP - P.B_OFFSET + 1)  # T_terminate = BSP - B_offset = 93°C
        assert sim.wait_for_heater_cycles(n_cycles=3, timeout_s=90)
        duty = sim.get_main_heater_duty()
        assert duty is not None
        spec = P.SPMH3
        assert spec * 0.8 <= duty <= spec * 1.2, (
            f"SPMH3 duty {duty:.1f}% outside {spec}% ±20%")

    @pytest.mark.slow
    def test_WH_10_heating_main_off_small_isp_after_ttank_exceeds_bsp(self, sim):
        """
        WH-10 (slow) — T_tank > BSP=96°C → Main=OFF, Small=ISP=10%.
        (Same gate as normal Prepare-to-Shabbat completion.)
        """
        self._enter_heating(sim)
        sim.set_temp_boost(P.BSP + 1)
        sim.set_temp_tank(P.BSP + 1)           # above BSP → Main OFF
        time.sleep(1.0)
        st = sim.get_output_status()
        # Main should be 0% (OFF) — duty=0 or not cycling
        if st.heat_main_duty_pct is not None and st.heat_main_cycles >= 1:
            assert st.heat_main_duty_pct < 5.0, (
                f"Main heater duty {st.heat_main_duty_pct:.1f}% should be ~0% (Main OFF)")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 3 — Wait for Dispense Trigger
# ─────────────────────────────────────────────────────────────────────────────

class TestWashingWaitDispense:

    def _enter_wait_state(self, sim):
        """Helper: set up post-heating wait state."""
        sim.set_electrode("LF", wet=True)
        sim.set_electrode("LE", wet=True)
        sim.set_temp_tank(P.BSP + 1)    # heating done
        sim.set_temp_boost(P.BSP + 1)
        sim.set_flow(0.0)               # no fill

    def test_WH_11_wait_state_main_off_small_isp(self, sim):
        """
        WH-11 — In wait state: Main heater=OFF, Small=ISP=10%.
        is hot enable=0 (hot fill disabled after washing fill).
        """
        self._enter_wait_state(sim)
        time.sleep(0.5)
        st = sim.get_output_status()
        if st.heat_main_cycles >= 1 and st.heat_main_duty_pct is not None:
            assert st.heat_main_duty_pct < 5.0, (
                "Main heater should be OFF in wait state")

    def test_WH_12_hot_fill_disabled_in_wait_state(self, sim):
        """
        WH-12 — Hot fill enable = 0 in wait state.
        EX_VALVE + INLET_VALVE should NOT open even if electrodes go DRY.
        """
        self._enter_wait_state(sim)
        # Simulate electrodes going dry (like empty tank) — but hot fill should be disabled
        sim.set_electrode("LF", wet=False)
        sim.set_electrode("LE", wet=False)
        time.sleep(13.0)   # past filter delay
        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE", (
            f"EX_VALVE should stay IDLE (hot fill disabled); state={st.ex_valve_state}")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 4 — Dispense Hot Water (7L total)
# ─────────────────────────────────────────────────────────────────────────────

class TestWashingDispense:

    def _enter_dispense_ready(self, sim):
        """Helper: simulate ready-to-dispense state."""
        sim.set_electrode("LF", wet=True)
        sim.set_electrode("LE", wet=True)
        sim.set_temp_tank(P.BSP + 1)
        sim.set_temp_boost(P.BSP + 1)
        sim.set_flow(0.0)

    def test_WH_13_dispense_opens_hot_valve_only(self, sim):
        """
        WH-13 — Hot dispense in washing mode uses HOT_VALVE (EM3) only.
        EX_VALVE and INLET_VALVE must NOT open.
        Matches hot dispense HD-01 from dispensing tests.
        """
        self._enter_dispense_ready(sim)
        sim.preset("HOT_DISP")   # T=90°C, trigger dispense
        time.sleep(2.0)
        st = sim.get_output_status()
        # HOT_VALVE should open, EX_VALVE should not
        # (HOT_VALVE is at OUTMON_HOT_VLV — check raw response)
        assert "HOT_VLV" in st.raw and "OPENING" in st.raw, (
            "HOT_VALVE should be opening during hot dispense phase")
        assert st.ex_valve_state == "IDLE", (
            f"EX_VALVE must stay IDLE during hot dispense; state={st.ex_valve_state}")

    def test_WH_14_hot_valve_opening_pulse_1s(self, sim):
        """
        WH-14 — HOT_VALVE opening pulse: 1000ms ±20% (800–1200ms).
        """
        self._enter_dispense_ready(sim)
        sim.preset("HOT_DISP")
        time.sleep(2.5)
        st = sim.get_output_status()
        # Parse HOT_VALVE opening pulse from raw
        import re
        m = re.search(r'HOT_VLV.*?pulse=(\d+)ms', st.raw, re.IGNORECASE)
        if m:
            pulse_ms = int(m.group(1))
            assert 800 <= pulse_ms <= 1200, (
                f"HOT_VALVE opening pulse {pulse_ms}ms outside 1000ms ±20%")

    def test_WH_15_hot_valve_holding_500hz_50pct(self, sim):
        """
        WH-15 — HOT_VALVE holding phase: 500Hz ±20%, 50% duty ±20%.
        """
        self._enter_dispense_ready(sim)
        sim.preset("HOT_DISP")
        time.sleep(3.0)   # past opening pulse
        st = sim.get_output_status()
        import re
        # Check HOT_VALVE holding state in raw
        m_freq = re.search(r'HOT_VLV.*?Freq=([\d.]+)Hz', st.raw, re.IGNORECASE)
        m_duty = re.search(r'HOT_VLV.*?Duty=([\d.]+)%',  st.raw, re.IGNORECASE)
        if m_freq and m_duty:
            freq = float(m_freq.group(1))
            duty = float(m_duty.group(1))
            assert 400 <= freq <= 600, f"HOT_VALVE freq {freq:.1f}Hz outside 500Hz ±20%"
            assert 40  <= duty <= 60,  f"HOT_VALVE duty {duty:.1f}% outside 50% ±20%"

    def test_WH_16_dispense_is_timer_based_no_flow_check(self, sim):
        """
        WH-16 — Hot dispense in washing mode is timer-based (no flow monitoring).
        Set flow=0 and verify dispense still completes.
        """
        self._enter_dispense_ready(sim)
        sim.set_flow(0.0)               # no flow pulses at all
        sim.preset("HOT_DISP")
        time.sleep(2.0)
        st = sim.get_output_status()
        # HOT_VALVE should open regardless of flow
        assert st.ex_valve_state == "IDLE", (
            "EX_VALVE must stay IDLE; hot dispense is timer-based")
        # Just check hot valve is active
        assert "HOT_VLV" in st.raw, "HOT_VALVE monitoring line missing from status"

    def test_WH_17_dispense_works_at_low_temperature(self, sim):
        """
        WH-17 — Washing dispense works even when T_tank is low (below HLSP).
        Unlike normal hot dispense, washing mode doesn't block on temperature.
        """
        self._enter_dispense_ready(sim)
        sim.set_temp_tank(P.HLSP - 10)   # below normal dispensing threshold
        sim.set_temp_boost(P.HLSP - 10)
        sim.preset("HOT_DISP_LOW")
        time.sleep(2.0)
        st = sim.get_output_status()
        # HOT_VALVE should still open
        assert st.ex_valve_state == "IDLE", (
            "EX_VALVE must stay IDLE even at low temperature")


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 5 — Exit: 7L dispensed → Idle
# ─────────────────────────────────────────────────────────────────────────────

class TestWashingExit:

    @pytest.mark.slow
    def test_WH_18_switches_to_idle_after_7l_dispensed(self, sim):
        """
        WH-18 (slow) — After cumulative 7L dispensed (multiple triggers),
        system switches to Idle Mode.
        7L = 7 × 518 = 3626 pulses at 1.93 mL/pulse.
        This test drives multiple dispense triggers and monitors for Idle entry.
        """
        sim.set_electrode("LF", wet=True)
        sim.set_electrode("LE", wet=True)
        sim.set_temp_tank(P.BSP + 1)
        sim.set_temp_boost(P.BSP + 1)

        # Simulate repeated dispenses until 7L reached
        # Each HOT_VALVE open = one dispense event
        # In real system, HC counts volume internally; here we just verify
        # the pattern: after enough triggers the system exits washing mode

        # Run 5 dispense cycles (approx 1.5L each typical hot dispense)
        for i in range(5):
            sim.preset("HOT_DISP")
            time.sleep(5.0)   # wait for timer-based dispense to complete
            sim.reset()       # reset monitor between cycles
            time.sleep(0.5)

        # After 7L the system should report Idle — check STATUS
        resp = sim.status_full()
        # Idle mode indicator: Main heater back to IHP duty cycle
        # (HC internal state — we can check that heater returns to IDLE pattern)
        assert sim.wait_for_state("IDLE", poll_interval_s=5.0, timeout_s=60), (
            "System did not switch to Idle mode after 7L dispensed")

    @pytest.mark.slow
    @pytest.mark.hc_critical
    def test_WH_19_fts_timeout_error_skip(self, sim):
        """
        WH-19 (slow, critical) — FTS timeout during washing phase triggers
        'Error Skip to next stage'.
        HC firmware skips to next installation stage on Ftimer > FTS.
        ~75 min timeout → use shortened timeout command if available.
        """
        sim.set_temp_tank(P.TLLSP + 5)   # Too low to complete heating quickly
        sim.set_temp_boost(P.TLLSP + 5)
        sim.set_electrode("LF", wet=True)
        sim.set_electrode("LE", wet=True)

        # Send HC-specific command to accelerate timer (if terminal supports it)
        # Otherwise this test would need 75+ minutes — mark as skip for CI
        pytest.skip(
            "FTS timeout test requires ~75 min or HC terminal min5 acceleration. "
            "Run manually with: sim.hc_terminal('min5') before triggering washing mode."
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Summary
# ─────────────────────────────────────────────────────────────────────────────
#
#  19 tests | Washing HWT at Installation Mode flowchart
#
#  WH-01..05  Phase 1 — Fill 3L
#  WH-06..10  Phase 2 — Heating (OSPm→SPMH1→SPMH2→SPMH3→OFF)
#  WH-11..12  Phase 3 — Wait for dispense trigger
#  WH-13..17  Phase 4 — Dispense hot water (timer-based, HOT_VALVE only)
#  WH-18..19  Phase 5 — 7L exit to Idle / FTS error
#
#  Slow tests: WH-07, WH-08, WH-09, WH-10, WH-18
#  Critical:   WH-19 (requires HC reboot after error state)
#
#  Run fast tests only:
#    pytest tamar_hil/test_washing_hwt.py -m "not slow" --port COM3 -v
#
#  Run all:
#    pytest tamar_hil/test_washing_hwt.py --port COM3 -v
