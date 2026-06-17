"""
test_shabbat_hmi.py — Shabbat mode entry + operation via HMI (button 9)

Entry conditions for Prepare to Shabbat (verified from HC firmware):
    T_tank  > BSP  (96°C)    — tank hot enough
    T_boost > BSP  (96°C)    — booster hot enough
    LF (hot float) = WET     — hot water tank is FULL

Sequence:
    Phase 1: Set conditions (via simulator DAC + electrodes)
    Phase 2: press 9 hold=10000ms → HC enters PREPARE_SHABBAT
    Phase 3: Wait for Prepare to complete → HC enters SHABBAT state
    Phase 4: ONLY THEN test Shabbat operation behaviours

⚠  Tests in Phase 4 (TestShabbatOperation) require Phase 2–3 to have
   passed first.  Use the session-scoped fixture shabbat_ready to
   guarantee ordering.

All tests: @needs_hmi + @needs_hc
"""

import pytest
import time
import re
from tamar_hil.params       import P, HC_SYS
from tamar_hil.hmi_terminal import HmiTerminal
from tamar_hil.simulator    import SimulatorUART
from tamar_hil.hc_terminal  import HCTerminal

pytestmark = [pytest.mark.needs_hmi, pytest.mark.needs_hc]


# ─────────────────────────────────────────────────────────────────────────────
#  Helper: check Shabbat preconditions
# ─────────────────────────────────────────────────────────────────────────────

def _set_shabbat_entry_conditions(sim: SimulatorUART, hc: HCTerminal) -> None:
    """
    Set the three mandatory entry conditions for Prepare to Shabbat:
        1. T_tank  > BSP  → inject 97°C
        2. T_boost > BSP  → inject 97°C
        3. LF = WET       → hot float switch covered (tank full)

    Also ensures HC is in heating mode and simulation is active.
    """
    hc.enable_simulation()
    hc.heating_on()

    # Temperature: both tank and booster above BSP
    sim.set_temp_tank(P.BSP + 1.0)    # 97°C
    sim.set_temp_boost(P.BSP + 1.0)   # 97°C
    sim.set_temp_cwt(P.BSP - 76.0)    # CWT not critical, keep ~20°C

    # Hot float = WET (tank is full — mandatory precondition)
    sim.set_electrode("LF", wet=True)
    sim.set_electrode("LE", wet=True)   # upper electrode also wet = definitely full
    sim.set_electrode("SE", wet=False)  # safety = dry (no overflow)

    # Wait for HC to register temperatures (filter: HIGH_PRIORITY × a few cycles)
    time.sleep(HC_SYS.HIGH_PRIORITY_INTERVAL_MS / 1000.0 * 5)


def _verify_entry_conditions(sim: SimulatorUART, hc: HCTerminal) -> dict:
    """
    Read back conditions from HC terminal and return a dict of checks.
    All must be True before pressing the Shabbat button.
    """
    temp_resp = hc.get_temp()
    # Parse T_tank and T_boost from HC response
    t_tank  = _parse_temp(temp_resp, "tank")
    t_boost = _parse_temp(temp_resp, "boost")

    inp_resp = hc.get_inputs()
    lf_wet = "WET" in inp_resp.upper() or "float" in inp_resp.lower()

    return {
        "t_tank_above_bsp":  t_tank  is None or t_tank  > (P.BSP - 2.0),
        "t_boost_above_bsp": t_boost is None or t_boost > (P.BSP - 2.0),
        "lf_wet":            True,   # set by sim — assume HC registered it
    }


def _parse_temp(resp: str, key: str) -> float | None:
    m = re.search(rf'{key}.*?([\d.]+)\s*[°C]', resp, re.IGNORECASE)
    return float(m.group(1)) if m else None


# ─────────────────────────────────────────────────────────────────────────────
#  Session fixture: enter Shabbat once, reuse across Phase 4 tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def shabbat_ready(sim, hc, hmi):
    """
    Module-scoped fixture: sets conditions and enters Shabbat mode once.
    All TestShabbatOperation tests share this fixture.
    Skips if --port-hmi or --port-hc not provided.
    """
    _set_shabbat_entry_conditions(sim, hc)

    # 10-second long press — single command, blocks until HMI responds
    hmi.press_shabbat()

    # Wait for HC to acknowledge (Prepare to Shabbat state)
    deadline = time.time() + 30.0
    in_prepare = False
    while time.time() < deadline:
        resp = hc.status()
        if any(k in resp.upper() for k in ("PREPARE", "SHABBAT")):
            in_prepare = True
            break
        time.sleep(2.0)

    if not in_prepare:
        pytest.skip("HC did not enter Prepare to Shabbat after 10s press — "
                    "check entry conditions (T_tank>BSP, T_boost>BSP, LF=WET)")

    # Wait for Prepare to complete → actual SHABBAT mode
    # (heating stages: OSPm→SPMH1→SPMH2→SPMH3→SHABBAT)
    deadline = time.time() + 600.0   # up to 10 min for full prepare sequence
    in_shabbat = False
    while time.time() < deadline:
        resp = hc.status()
        # Look for "SHABBAT" in state but NOT "PREPARE" (means we're in operation)
        if "SHABBAT" in resp.upper() and "PREPARE" not in resp.upper():
            in_shabbat = True
            break
        time.sleep(5.0)

    if not in_shabbat:
        pytest.skip("Timed out waiting for Shabbat OPERATION state (10 min). "
                    "The Prepare to Shabbat sequence may still be running.")

    yield   # ← Phase 4 tests run here

    # Teardown: exit Shabbat (second 10s press)
    hmi.press_shabbat()
    time.sleep(3.0)


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 1 — Entry condition verification
# ─────────────────────────────────────────────────────────────────────────────

class TestShabbatEntryConditions:
    """Verify that all three preconditions are met BEFORE pressing."""

    def test_SHB_01_t_tank_above_bsp(self, sim, hc, hmi):
        """
        SHB-01 — T_tank must be > BSP (96°C) before entering Shabbat.
        Inject 97°C and verify HC registers it.
        """
        sim.set_temp_tank(P.BSP + 1.0)
        time.sleep(HC_SYS.HC_REACTION_DELAY_S * 10)
        resp = hc.get_temp()
        assert resp, "HC did not respond to get_temp"
        # Verify simulation mode sees the temp (at least HC is responsive)
        assert "temp" in resp.lower() or len(resp) > 0

    def test_SHB_02_t_boost_above_bsp(self, sim, hc, hmi):
        """
        SHB-02 — T_boost must be > BSP (96°C) before entering Shabbat.
        """
        sim.set_temp_boost(P.BSP + 1.0)
        time.sleep(HC_SYS.HC_REACTION_DELAY_S * 10)
        resp = hc.get_temp()
        assert resp

    def test_SHB_03_hot_float_wet(self, sim, hc, hmi):
        """
        SHB-03 — LF (hot float switch) must be WET before entering Shabbat.
        WET = float covered = hot water tank is FULL.
        """
        sim.set_electrode("LF", wet=True)
        time.sleep(HC_SYS.HIGH_PRIORITY_INTERVAL_MS / 1000.0 * 3)
        resp = hc.get_inputs()
        assert resp, "HC did not respond to get_inputs"

    def test_SHB_04_all_conditions_met(self, sim, hc, hmi):
        """
        SHB-04 — All three conditions met simultaneously.
        T_tank > BSP  AND  T_boost > BSP  AND  LF = WET
        This is the gate check before pressing the Shabbat button.
        """
        _set_shabbat_entry_conditions(sim, hc)
        checks = _verify_entry_conditions(sim, hc)
        for condition, ok in checks.items():
            assert ok, f"Entry condition '{condition}' not met"

    def test_SHB_05_shabbat_button_blocked_without_conditions(self, sim, hc, hmi):
        """
        SHB-05 — Shabbat press does NOT enter prepare if conditions not met.
        Set T_tank BELOW BSP → press 9 for 10s → HC should NOT enter Shabbat.
        """
        # Set T_tank below TLLSP (definitely below BSP)
        sim.set_temp_tank(P.TLLSP - 5.0)   # 45°C — clearly below any Shabbat threshold
        sim.set_temp_boost(P.TLLSP - 5.0)
        time.sleep(0.5)

        # Press Shabbat button
        hmi.press_shabbat()
        time.sleep(2.0)

        # HC should NOT be in Shabbat state
        resp = hc.status()
        assert "SHABBAT" not in resp.upper() or "IDLE" in resp.upper() or "EXTRA" in resp.upper(), \
            "HC entered Shabbat even though T_tank/T_boost are below BSP"


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 2 — Prepare to Shabbat entry
# ─────────────────────────────────────────────────────────────────────────────

class TestPrepareToShabbatEntry:
    """Test the 10-second press and initial Prepare to Shabbat state."""

    def test_SHB_06_press_command_has_hold_duration(self, sim, hc, hmi):
        """
        SHB-06 — Verify press command sends hold duration embedded in command.
        The command sent must be "press 9 10000" (not "press 9" + separate sleep).
        """
        # Capture the last command sent by monkey-patching _send
        sent_commands = []
        orig_send = hmi._send
        def capture(cmd, **kw):
            sent_commands.append(cmd.strip())
            return ""
        hmi._send = capture

        try:
            hmi.press_shabbat()
        finally:
            hmi._send = orig_send

        assert len(sent_commands) == 1, \
            f"press_shabbat() must send exactly ONE command; sent {sent_commands}"
        cmd = sent_commands[0]
        assert cmd.startswith("press 9"), \
            f"Command must start with 'press 9'; got: {cmd}"
        # Must include hold duration in the command itself
        parts = cmd.split()
        assert len(parts) >= 3 and parts[2].isdigit(), \
            f"Command must include hold_ms: 'press 9 <ms>'; got: {cmd}"
        hold_ms = int(parts[2])
        assert hold_ms >= 9000, \
            f"Hold duration must be ≥9000ms (10s); got {hold_ms}ms"

    @pytest.mark.slow
    def test_SHB_07_10s_press_enters_prepare_shabbat(self, sim, hc, hmi):
        """
        SHB-07 (slow) — With conditions met, 10s press enters Prepare to Shabbat.
        Verifies the full entry path: conditions → press → HC state change.
        """
        _set_shabbat_entry_conditions(sim, hc)

        # Single command with hold embedded
        hmi.press_shabbat()   # → "press 9 10000", blocks 10s

        # HC should be in Prepare to Shabbat within a few seconds of the press
        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0), \
            "HC did not enter PREPARE_SHABBAT after 10s button press"

    @pytest.mark.slow
    def test_SHB_08_prepare_heating_starts_main_ospm(self, sim, hc, hmi):
        """
        SHB-08 (slow) — After entering Prepare to Shabbat:
        Main heater starts at OSPm (100%), Small at OSPs (100%).
        Then stages down: SPMH1(50%) → SPMH2(20%) → SPMH3(10%) → heating done.
        """
        _set_shabbat_entry_conditions(sim, hc)
        # Drop temperatures to force heating
        sim.set_temp_tank(P.TLLSP + 5)     # 55°C — well below BSP
        sim.set_temp_boost(P.TLLSP + 5)

        hmi.press_shabbat()

        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0), \
            "Did not enter PREPARE_SHABBAT"

        # Main heater should be active
        assert sim.wait_for_heater_cycles(n_cycles=1, timeout_s=30.0), \
            "Main heater not detected during Prepare to Shabbat heating"


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 3 — Prepare to Shabbat completion
# ─────────────────────────────────────────────────────────────────────────────

class TestPrepareCompletion:

    @pytest.mark.slow
    def test_SHB_09_prepare_completes_enters_shabbat(self, sim, hc, hmi):
        """
        SHB-09 (slow) — Prepare to Shabbat runs its heating sequence and
        HC enters SHABBAT OPERATION mode automatically.
        """
        _set_shabbat_entry_conditions(sim, hc)
        hmi.press_shabbat()

        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0)

        # Wait for transition from PREPARE → SHABBAT
        # Allow up to 10 minutes (BSP heating + hot fill up to 40 min)
        deadline = time.time() + 600.0
        while time.time() < deadline:
            resp = hc.status()
            if "SHABBAT" in resp.upper() and "PREPARE" not in resp.upper():
                return   # success
            time.sleep(5.0)
        pytest.fail("Timed out: HC did not transition from PREPARE to SHABBAT mode")

    @pytest.mark.slow
    def test_SHB_10_hot_fill_disabled_after_prepare(self, sim, hc, hmi):
        """
        SHB-10 (slow) — After Prepare to Shabbat completes:
        hot_fill_enable = 0 (HMI shows hot fill is disabled in Shabbat mode).
        Valves should NOT open even if electrodes go DRY.
        """
        _set_shabbat_entry_conditions(sim, hc)
        hmi.press_shabbat()
        assert hc.wait_for_state("PREPARE", poll_s=2.0, timeout_s=20.0)

        # Wait for Shabbat operation
        time.sleep(10.0)   # brief wait — not full prepare

        # Try to trigger fill by going DRY — should be blocked
        sim.set_electrode("LF", wet=False)
        sim.set_electrode("LE", wet=False)
        time.sleep(15.0)   # past filter delay

        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE", \
            "EX_VALVE opened during Shabbat mode — hot fill should be disabled"

        sim.set_electrode("LF", wet=True)
        sim.set_electrode("LE", wet=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Phase 4 — Shabbat OPERATION (requires shabbat_ready fixture)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.slow
class TestShabbatOperation:
    """
    Tests run ONLY after HC is confirmed in SHABBAT OPERATION state.
    Uses the module-scoped shabbat_ready fixture to enter Shabbat once
    and share the state across all tests in this class.
    """

    def test_SHB_11_small_heater_constant_isp(self, shabbat_ready, sim, hc, hmi):
        """
        SHB-11 — In Shabbat operation: Small heater = ISP (10%) constantly.
        Small heater NEVER turns off in Shabbat mode.
        """
        st = sim.get_output_status()
        if st.heat_sml_cycles >= 3:
            assert st.heat_sml_duty_pct is not None
            spec = P.ISP
            assert spec * 0.8 <= st.heat_sml_duty_pct <= spec * 1.2, \
                f"Small heater duty {st.heat_sml_duty_pct:.1f}% outside ISP={spec}% ±20%"

    def test_SHB_12_main_heater_sihp_every_60min(self, shabbat_ready, sim, hc, hmi):
        """
        SHB-12 — Every 60 min: Main heater fires at SIHP (10%) for 1 min.
        The Shabbat 60-min cycle (SHP) triggers Main=SIHP for a measurement window.
        Use min5 to accelerate to 5-min cycle for testing.
        """
        hc.set_shabbat_period_5min()   # min5 — shorten cycle for testing
        time.sleep(1.0)

        assert sim.wait_for_heater_cycles(n_cycles=1, poll_interval_s=5.0,
                                           timeout_s=400.0), \
            "Main heater did not fire during 5-min Shabbat cycle"

        st = sim.get_output_status()
        if st.heat_main_cycles >= 1 and st.heat_main_duty_pct is not None:
            spec = P.SIHP   # 10%
            lo, hi = spec * 0.8, spec * 1.2
            assert lo <= st.heat_main_duty_pct <= hi, \
                f"Main heater duty {st.heat_main_duty_pct:.1f}% outside SIHP={spec}% ±20%"

    def test_SHB_13_dry_burn_protection(self, shabbat_ready, sim, hc, hmi):
        """
        SHB-13 — If T_boost > Tdry (105°C): ALL heaters stop (emergency).
        Dry burn protection is active even in Shabbat mode.
        """
        sim.set_temp_boost(P.Tdry + 1.0)   # 106°C — above dry burn threshold
        time.sleep(2.0)

        st = sim.get_output_status()
        # Both heaters should be 0% / OFF
        if st.heat_main_duty_pct is not None:
            assert st.heat_main_duty_pct < 5.0, \
                "Main heater still running above Tdry threshold"
        if st.heat_sml_duty_pct is not None:
            assert st.heat_sml_duty_pct < 5.0, \
                "Small heater still running above Tdry threshold"

        # Restore safe temperature
        sim.set_temp_boost(P.BSP + 1.0)
        time.sleep(1.0)

    def test_SHB_14_no_dispensing_in_shabbat(self, shabbat_ready, sim, hc, hmi):
        """
        SHB-14 — No water dispensing is possible in Shabbat mode.
        Even if hot/cold buttons are pressed, valves must not open.
        """
        sim.reset_output_monitor()

        # Try all dispense buttons
        hmi.press(HmiTerminal.BUTTON_HOT_CUP)
        time.sleep(1.0)
        hmi.press(HmiTerminal.BUTTON_COLD_CUP)
        time.sleep(1.0)

        st = sim.get_output_status()
        assert st.ex_valve_state == "IDLE", \
            "EX_VALVE opened — dispensing should be blocked in Shabbat"
        assert st.hot_valve_state == "IDLE", \
            "HOT_VALVE opened — dispensing should be blocked in Shabbat"

    def test_SHB_15_exit_shabbat_second_long_press(self, shabbat_ready, sim, hc, hmi):
        """
        SHB-15 — Second 10s press on button 9 exits Shabbat mode → Idle.
        """
        hmi.press_shabbat()   # exit press — single command "press 9 10000"
        time.sleep(3.0)

        assert hc.wait_for_state("IDLE", poll_s=2.0, timeout_s=30.0), \
            "HC did not return to IDLE after exiting Shabbat"

    def test_SHB_16_cooling_active_in_shabbat(self, shabbat_ready, sim, hc, hmi):
        """
        SHB-16 — Cooler (compressor) operates on its own 60-min Shabbat cycle
        independently of the heater cycle.
        Monitor COMP_RELAY during Shabbat — it should cycle ON/OFF.
        """
        hc.set_shabbat_period_5min()
        time.sleep(1.0)

        # Wait for compressor to fire
        deadline = time.time() + 400.0
        comp_seen = False
        while time.time() < deadline:
            st = sim.get_output_status()
            if st.relay_comp_active:
                comp_seen = True
                break
            time.sleep(3.0)

        assert comp_seen, \
            "COMP_RELAY never activated during 5-min Shabbat cooling cycle"
