"""
tests/test_dispense.py — dispense tests for all 6 button modes.

Volume is measured by LISTENING to the device console stream, not by
reading counters. The device reports the dispensed/refilled volume on the
HC console:

  Hot dispense   -> tank refills, prints  "HOT <N> mil"  and "HW fil: <N>"
                    (the Total counter does NOT move for hot water)
  Cold / Ambient -> prints  "Flow meter <N>"  and "COLD <N> mil" / "AMB <N> mil"

Per cycle:
  1. press button (press <id> <duration_ms>) via HMI
  2. listen to the HC stream until the volume line appears (and, for hot,
     until "Hot filling ... -> FULL" so the tank finished refilling)
  3. parse the reported volume and compare to target +/- tolerance
  4. settle pause so the next test does not start mid-refill
"""
import re
import time
from tests.test_base import BaseTest, TestResult

TOLERANCE_ML = 150
SETTLE_SEC = 60         # pause after a pour before the next test
HOT_RE = [re.compile(r'HOT\s+(\d+)\s*mil', re.I),
          re.compile(r'HW\s*fil:\s*(\d+)', re.I)]
COLD_RE = [re.compile(r'Flow\s*meter\s+(\d+)', re.I),
           re.compile(r'COLD\s+(\d+)\s*mil', re.I),
           re.compile(r'AMB\s+(\d+)\s*mil', re.I)]


def _extract(lines, patterns):
    """Return the largest integer matched by any pattern across lines."""
    best = None
    for ln in lines:
        for rx in patterns:
            m = rx.search(ln)
            if m:
                v = int(m.group(1))
                if best is None or v > best:
                    best = v
    return best


def _run_dispense(test: BaseTest, button_id: int,
                  kind: str, label: str,
                  expected_ml: int) -> TestResult:
    """kind: 'hot' | 'cold' | 'amb'."""
    err = test._require_hmi()
    if err:
        return err

    cfg_key = "expected_" + label.lower().replace(" ", "_") + "_ml"
    target_ml = int(test.config.get(cfg_key, expected_ml))
    duration_ms = int(test.config.get("press_duration_ms", 1000))
    wait_sec = float(test.config.get("pour_wait_sec", 40))
    settle_sec = float(test.config.get("dispense_settle_sec", SETTLE_SEC))
    tolerance = float(test.config.get("tolerance_ml", TOLERANCE_ML))

    # The volume lines are printed on the HC console — we listen there.
    stream = test.hydraulic if (test.hydraulic
                                and test.hydraulic.is_connected()) else None
    if stream is None:
        return test._fail("HC (hydraulic) must be connected to read dispense "
                          "volume from the device stream.")

    test.log(f"[{test.NAME}] btn={button_id} target={target_ml}ml "
             f"wait={wait_sec}s kind={kind} (STREAM mode)")

    # flush whatever is buffered, then press
    stream.listen(0.3)
    resp = test.hmi.press(button_id, duration_ms)
    if resp is None:
        return test._fail(f"press {button_id} no response")

    # listen for the volume report
    patterns = HOT_RE if kind == "hot" else COLD_RE
    stop = "-> FULL" if kind == "hot" else "Flow meter"
    test.log(f"  listening HC stream up to {wait_sec}s for volume...")
    lines = stream.listen(wait_sec, stop_substr=stop)
    # for hot, the "HOT <N> mil" sometimes prints just after "-> FULL"
    if kind == "hot":
        lines += stream.listen(6.0, stop_substr="HW fil")

    vol = _extract(lines, patterns)
    captured = " | ".join(lines[-8:]) if lines else "(nothing)"
    test.log(f"  stream tail: {captured}")
    test.log(f"  measured volume = {vol} ml (target {target_ml})")

    data = {"button": button_id, "label": label, "kind": kind,
            "target_ml": target_ml, "measured_ml": vol,
            "captured_lines": len(lines)}

    if vol is None:
        # settle anyway so the rig returns to rest
        time.sleep(settle_sec)
        return test._fail(
            f"No volume line found in HC stream for {label}. "
            f"Expected 'HOT N mil' (hot) or 'Flow meter N' (cold/amb). "
            f"Captured: {captured}", data)

    errors = []
    if vol < target_ml - tolerance:
        errors.append(f"measured({vol}) < target({target_ml}) - tol({tolerance:.0f})")
    if vol > target_ml + tolerance:
        errors.append(f"measured({vol}) > target({target_ml}) + tol({tolerance:.0f})")

    # settle: let the tank finish refilling before the next test presses
    time.sleep(settle_sec)

    if errors:
        return test._fail(" | ".join(errors), data)
    return test._pass(
        f"OK {label}: measured={vol}ml target={target_ml}ml "
        f"(tol +/-{tolerance:.0f})", data)


class TestColdGlass(BaseTest):
    NAME = "Cold Glass (btn 4)"
    DESCRIPTION = "press 4 COLD GLASS — measured via 'Flow meter N'."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 4, "cold", "COLD GLASS", expected_ml=200)


class TestColdJug(BaseTest):
    NAME = "Cold Jug (btn 5)"
    DESCRIPTION = "press 5 COLD JUG — measured via 'Flow meter N'."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 5, "cold", "COLD JUG", expected_ml=1000)


class TestAmbGlass(BaseTest):
    NAME = "Ambient Glass (btn 6)"
    DESCRIPTION = "press 6 AMB GLASS — measured via 'Flow meter N'."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 6, "amb", "AMB GLASS", expected_ml=200)


class TestAmbJug(BaseTest):
    NAME = "Ambient Jug (btn 7)"
    DESCRIPTION = "press 7 AMB JUG — measured via 'Flow meter N'."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 7, "amb", "AMB JUG", expected_ml=1000)


class TestHotGlass(BaseTest):
    NAME = "Hot Glass (btn 1)"
    DESCRIPTION = "press 1 HOT GLASS — measured via 'HOT N mil' (tank refill)."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 1, "hot", "HOT GLASS", expected_ml=150)


class TestHotJug(BaseTest):
    NAME = "Hot Jug (btn 2)"
    DESCRIPTION = "press 2 HOT JUG — measured via 'HOT N mil' (tank refill)."
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        return _run_dispense(self, 2, "hot", "HOT JUG", expected_ml=1000)
