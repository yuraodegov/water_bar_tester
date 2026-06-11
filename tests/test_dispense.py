"""
tests/test_dispense.py — dispense tests for all 6 button modes.

Uses DELTA measurement: reads counters BEFORE and AFTER the pour and
compares the increments. This avoids problems with counters that hold
huge lifetime totals or that the firmware does not reset on command.

Per cycle:
  1. read baseline counters (total, filter, type)
  2. press button (press <id> <duration_ms>)
  3. wait pour_wait_sec
  4. read counters again, compute deltas
  5. compare delta_total vs delta_filter vs delta_type (and pulse if HC)
"""
import time
from tests.test_base import BaseTest, TestResult

TOLERANCE_ML = 150


def _run_dispense(test: BaseTest, button_id: int,
                  counter_key: str, label: str) -> TestResult:
    err = test._require_hmi()
    if err:
        return err

    target_ml = int(float(test.config.get("target_liters", 1)) * 1000)
    duration_ms = int(test.config.get("press_duration_ms", 1000))
    wait_sec = float(test.config.get("pour_wait_sec", 40))
    use_hydraulic = test.config.get("use_hydraulic", True)
    tolerance = float(test.config.get("tolerance_ml", TOLERANCE_ML))

    test.log(f"[{test.NAME}] btn={button_id} target={target_ml}ml wait={wait_sec}s (DELTA mode)")

    # ── baseline ─────────────────────────────────────────────────────
    base_total = test.hmi.get_counter("total")
    base_filter = test.hmi.get_counter("filter")
    base_type = test.hmi.get_counter(counter_key)
    test.log(f"  baseline total={base_total} filter={base_filter} {counter_key}={base_type}")

    if None in (base_total, base_filter, base_type):
        return test._fail("Baseline counter read None (check connection)")

    # ── press + wait ─────────────────────────────────────────────────
    resp = test.hmi.press(button_id, duration_ms)
    if resp is None:
        return test._fail(f"press {button_id} no response")
    test.log(f"  Waiting {wait_sec}s for dispense...")
    time.sleep(wait_sec)

    # ── after ────────────────────────────────────────────────────────
    after_total = test.hmi.get_counter("total")
    after_filter = test.hmi.get_counter("filter")
    after_type = test.hmi.get_counter(counter_key)

    if None in (after_total, after_filter, after_type):
        return test._fail("After-pour counter read None")

    d_total = after_total - base_total
    d_filter = after_filter - base_filter
    d_type = after_type - base_type

    hydr_ok = use_hydraulic and test.hydraulic and test.hydraulic.is_connected()
    pulse_ml = None
    if hydr_ok and hasattr(test.hydraulic, "get_pulse"):
        pulse_ml = test.hydraulic.get_pulse()

    test.log(f"  delta total={d_total:.0f} filter={d_filter:.0f} {counter_key}={d_type:.0f} pulse={pulse_ml}")

    data = {
        "button": button_id,
        "label": label,
        "target_ml": target_ml,
        "delta_total": d_total,
        "delta_filter": d_filter,
        f"delta_{counter_key}": d_type,
        "pulse_ml": pulse_ml,
    }

    errors = []

    # at least target volume dispensed (delta)
    if d_total < target_ml - tolerance:
        errors.append(f"delta_total({d_total:.0f}) < target({target_ml}) - tol({tolerance})")

    # filter delta tracks total delta
    if abs(d_total - d_filter) > tolerance:
        errors.append(f"delta total({d_total:.0f}) vs filter({d_filter:.0f}) diff={abs(d_total - d_filter):.0f}")

    # type counter delta tracks total delta
    if abs(d_total - d_type) > tolerance:
        errors.append(
            f"delta total({d_total:.0f}) vs {counter_key}({d_type:.0f}) diff={abs(d_total - d_type):.0f}"
        )

    # hydraulic pulse (absolute, if available)
    if pulse_ml is not None and abs(d_total - pulse_ml) > tolerance:
        errors.append(f"delta total({d_total:.0f}) vs pulse({pulse_ml:.0f}) diff={abs(d_total - pulse_ml):.0f}")

    if errors:
        return test._fail(" | ".join(errors), data)
    return test._pass(
        f"OK {label}: delta total={d_total:.0f}ml filter={d_filter:.0f} "
        f"{counter_key}={d_type:.0f} pulse={pulse_ml}",
        data,
    )


class TestColdGlass(BaseTest):
    NAME = "Cold Glass (btn 4)"
    DESCRIPTION = "press 4 COLD GLASS — delta total/filter/cold/pulse."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 4, "cold", "COLD GLASS")


class TestColdJug(BaseTest):
    NAME = "Cold Jug (btn 5)"
    DESCRIPTION = "press 5 COLD JUG — delta total/filter/cold/pulse."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 5, "cold", "COLD JUG")


class TestAmbGlass(BaseTest):
    NAME = "Ambient Glass (btn 6)"
    DESCRIPTION = "press 6 AMB GLASS — delta total/filter/amb/pulse."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 6, "amb", "AMB GLASS")


class TestAmbJug(BaseTest):
    NAME = "Ambient Jug (btn 7)"
    DESCRIPTION = "press 7 AMB JUG — delta total/filter/amb/pulse."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 7, "amb", "AMB JUG")


class TestHotGlass(BaseTest):
    NAME = "Hot Glass (btn 1)"
    DESCRIPTION = "press 1 HOT GLASS — delta total/filter/pulse."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 1, "total", "HOT GLASS")


class TestHotJug(BaseTest):
    NAME = "Hot Jug (btn 2)"
    DESCRIPTION = "press 2 HOT JUG — delta total/filter/pulse."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 2, "total", "HOT JUG")