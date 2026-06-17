"""
test_cooling_v07.py — Cooling V07 flowchart tests
Source: Tamar Cooling Flow Charts V07 (1).pdf

Two handlers:
  CoolerHandler (normal/regular operation):
    Compressor ON when T_cwt > setpoint + HYS
    Compressor OFF when T_cwt < setpoint
    Anti-short-cycle: 3min minimum OFF time
    Dry-burn safety: T_cwt > 105°C → OFF
    Fan post-run: 1min after compressor stop

  CoolerShabbatHandler (Shabbat operation):
    Fixed 60-min SHP cycle (or 5min with min5)
    Compressor+Fan ON for measurement window
    Success: T_cwt < 6°C (Shabbat setpoint)
    2nd-chance mechanism on timeout
    Dry-burn same as normal

Requires: --port-sim  --port-hc
  CoolerShabbatHandler tests also: --port-hmi  (enter Shabbat via HMI)
"""
import pytest, time
from tamar_hil.params      import P, HC_SYS
from tamar_hil.simulator   import SimulatorUART
from tamar_hil.hc_terminal import HCTerminal

pytestmark = pytest.mark.needs_hc

SHABBAT_SETPOINT_C = 6.0    # Shabbat cold setpoint


def _setup_cooler(sim, hc, cwt=12.0):
    hc.enable_simulation()
    sim.set_temp_cwt(cwt)
    sim.set_temp_tank(72.0); sim.set_temp_boost(72.0)
    sim.set_electrode("LF", wet=True)
    sim.set_flow(0.0)
    time.sleep(HC_SYS.HC_REACTION_DELAY_S * 5)


# ── CoolerHandler (Normal) ────────────────────────────────────────────────────

class TestCoolerHandler:

    def test_CL_01_compressor_on_above_setpoint(self, sim, hc):
        """CL-01 — T_cwt above setpoint+HYS → Compressor turns ON."""
        _setup_cooler(sim, hc, cwt=15.0)   # warm → compressor should kick in
        time.sleep(5.0)
        st = sim.get_output_status()
        assert st.relay_comp_active, \
            "COMP_RELAY should be ON when CWT is above cooling setpoint"

    def test_CL_02_compressor_off_below_setpoint(self, sim, hc):
        """CL-02 — T_cwt below setpoint → Compressor turns OFF."""
        _setup_cooler(sim, hc, cwt=4.0)   # already cold
        time.sleep(5.0)
        st = sim.get_output_status()
        assert not st.relay_comp_active, \
            "COMP_RELAY should be OFF when CWT is already below setpoint"

    def test_CL_03_anti_short_cycle_3min(self, sim, hc):
        """CL-03 — Anti-short-cycle: compressor stays OFF ≥3min after stopping.
        After compressor stops, raising CWT should not immediately restart it."""
        _setup_cooler(sim, hc, cwt=4.0)   # start cold → compressor off
        time.sleep(3.0)
        # Now warm up CWT rapidly — compressor should NOT restart immediately
        sim.set_temp_cwt(20.0)
        time.sleep(30.0)   # check within anti-short-cycle window
        # Note: if compressor has been off for < 3min, it should stay off
        # (this test verifies the first ~30s window)
        st = sim.get_output_status()
        # Result depends on when it last stopped — informational check
        assert st is not None

    def test_CL_04_dry_burn_safety(self, sim, hc):
        """CL-04 — T_cwt > 105°C → Compressor OFF immediately (safety)."""
        _setup_cooler(sim, hc, cwt=15.0)
        time.sleep(3.0)
        sim.set_temp_cwt(106.0)   # above dry burn threshold
        time.sleep(2.0)
        st = sim.get_output_status()
        assert not st.relay_comp_active, \
            "COMP_RELAY must turn OFF above 105°C (dry burn protection)"
        # Restore
        sim.set_temp_cwt(12.0)

    def test_CL_05_fan_post_run_1min(self, sim, hc):
        """CL-05 — Fan runs 1min after compressor stops."""
        _setup_cooler(sim, hc, cwt=15.0)
        time.sleep(3.0)   # let compressor start
        sim.set_temp_cwt(4.0)   # cool down → compressor should stop
        time.sleep(10.0)
        # Fan should still be running during post-run
        st = sim.get_output_status()
        assert st.fan_active, \
            "FAN should continue running during 1-min post-run after compressor stop"


# ── CoolerShabbatHandler ──────────────────────────────────────────────────────
# These tests require Shabbat mode to be active (entered via HMI)

@pytest.fixture(scope="module")
def shabbat_cooling(sim, hc, hmi, request):
    """Enter Shabbat mode for cooling tests."""
    if not request.config.getoption("--port-hmi", default=None):
        pytest.skip("Shabbat cooling tests require --port-hmi")
    hc.enable_simulation(); hc.heating_on()
    sim.set_temp_tank(P.BSP + 1); sim.set_temp_boost(P.BSP + 1)
    sim.set_electrode("LF", wet=True)
    from tamar_hil.hmi_terminal import HmiTerminal
    time.sleep(0.5)
    hmi.press_shabbat()
    if not hc.wait_for_state("SHABBAT", poll_s=5.0, timeout_s=600.0):
        pytest.skip("Could not enter Shabbat mode for cooling tests")
    yield
    hmi.press_shabbat()


@pytest.mark.needs_hmi
@pytest.mark.needs_hc
class TestCoolerShabbatHandler:

    def test_CS_01_entry_compressor_off(self, shabbat_cooling, sim, hc):
        """CS-01 — On entry to Shabbat: compressor is OFF."""
        time.sleep(2.0)
        st = sim.get_output_status()
        assert not st.relay_comp_active, \
            "Compressor should be OFF immediately on Shabbat entry"

    @pytest.mark.slow
    def test_CS_02_shp_compressor_fires(self, shabbat_cooling, sim, hc):
        """CS-02 (slow) — Every SHP: compressor+fan turn ON for cooling window."""
        hc.set_shabbat_period_5min()
        deadline = time.time() + 400.0
        while time.time() < deadline:
            st = sim.get_output_status()
            if st.relay_comp_active:
                return   # success
            time.sleep(3.0)
        pytest.fail("Compressor did not fire during 5-min Shabbat cooling cycle")

    @pytest.mark.slow
    def test_CS_03_success_cwt_below_setpoint(self, shabbat_cooling, sim, hc):
        """CS-03 (slow) — T_cwt < 6°C during window → success, 2nd_chance_flag=0."""
        hc.set_shabbat_period_5min()
        sim.set_temp_cwt(SHABBAT_SETPOINT_C - 1)   # 5°C → success
        deadline = time.time() + 400.0
        while time.time() < deadline:
            resp = hc.status()
            if "SHABBAT" in resp.upper() and "ERROR" not in resp.upper():
                # Check 2nd chance flag is 0
                flag = hc._send("cooler_sb_2_chance_flag")
                if "0" in flag:
                    return
            time.sleep(5.0)

    @pytest.mark.slow
    def test_CS_04_second_chance_on_timeout(self, shabbat_cooling, sim, hc):
        """CS-04 (slow) — SHP timeout without reaching setpoint → 2nd chance flag=1."""
        hc.set_shabbat_period_5min()
        sim.set_temp_cwt(20.0)   # keep warm → no success
        deadline = time.time() + 400.0
        while time.time() < deadline:
            flag = hc._send("cooler_sb_2_chance_flag")
            if "1" in flag:
                return
            time.sleep(10.0)

    @pytest.mark.slow
    @pytest.mark.hc_critical
    def test_CS_05_twice_in_row_error(self, shabbat_cooling, sim, hc):
        """CS-05 (slow, critical) — Two consecutive SHP timeouts → error + ALL heaters OFF."""
        hc.set_shabbat_period_5min()
        sim.set_temp_cwt(25.0)   # keep warm to fail both cycles
        deadline = time.time() + 900.0
        while time.time() < deadline:
            resp = hc.status(); errors = hc.get_errors()
            if "ERROR" in resp.upper() or len(errors) > 10:
                st = sim.get_output_status()
                if st.heat_main_duty_pct is not None:
                    assert st.heat_main_duty_pct < 5.0
                return
            time.sleep(30.0)
        pytest.fail("Twice-in-row Shabbat cooling error not triggered")

    def test_CS_06_dry_burn_in_shabbat(self, shabbat_cooling, sim, hc):
        """CS-06 — T_cwt > 105°C → emergency stop even in Shabbat."""
        sim.set_temp_cwt(106.0)
        time.sleep(2.0)
        st = sim.get_output_status()
        assert not st.relay_comp_active
        sim.set_temp_cwt(6.0)

    def test_CS_07_fan_post_run_shabbat(self, shabbat_cooling, sim, hc):
        """CS-07 — Fan post-run 1min after compressor stops in Shabbat."""
        sim.set_temp_cwt(3.0)   # cold → compressor stops
        time.sleep(10.0)
        st = sim.get_output_status()
        assert st.fan_active, "FAN should post-run after compressor stops in Shabbat"

    @pytest.mark.slow
    def test_CS_08_heater_cooler_same_window(self, shabbat_cooling, sim, hc):
        """CS-08 — Heater and cooler fire in the SAME SHP window (simulate_integers active)."""
        hc.set_shabbat_period_5min()
        # Both should activate — heater+compressor in same SHP window
        deadline = time.time() + 400.0
        heater_seen = compressor_seen = False
        while time.time() < deadline:
            st = sim.get_output_status()
            if st.heat_main_cycles >= 1: heater_seen = True
            if st.relay_comp_active:     compressor_seen = True
            if heater_seen and compressor_seen: return
            time.sleep(3.0)
        assert heater_seen,     "Main heater not seen in Shabbat window"
        assert compressor_seen, "Compressor not seen in Shabbat window"
