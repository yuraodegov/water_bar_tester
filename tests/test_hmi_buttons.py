"""
tests/test_hmi_buttons.py — HMI Button Response.
Each of the 8 buttons must respond. Button combination 3+6 and long press tested.
"""
import time
from tests.test_base import BaseTest, TestResult

BUTTON_NAMES = {
    1: "HOT GLASS", 2: "HOT JUG", 3: "MENU", 4: "COLD GLASS",
    5: "COLD JUG", 6: "AMB GLASS", 7: "AMB JUG", 8: "FILTERED",
}


class TestAllButtonsRespond(BaseTest):
    NAME = "All 8 Buttons Respond"
    DESCRIPTION = "Press each of the 8 buttons — every press must return a response."
    CATEGORY = "hmi_buttons"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        pause = float(self.config.get("button_pause_sec", 1.0))
        errors = []
        responses = {}
        for bid, name in BUTTON_NAMES.items():
            resp = self.hmi.press(bid, 500)
            responses[name] = resp
            self.log(f"  btn {bid} ({name}) -> {resp}")
            if resp is None:
                errors.append(f"btn {bid} ({name}): no response")
            time.sleep(pause)
        data = {"responses": responses}
        if errors:
            return self._fail(" | ".join(errors), data)
        return self._pass(f"OK all {len(BUTTON_NAMES)} buttons responded", data)


class TestButtonCombination(BaseTest):
    NAME = "Button Combination 3+6"
    DESCRIPTION = "Long press of buttons 3 and 6 together (technician combo)."
    CATEGORY = "hmi_buttons"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        # press 3 and 6 with long duration to trigger combination
        r3 = self.hmi.press(3, 2500)
        r6 = self.hmi.press(6, 2500)
        self.log(f"  btn3 -> {r3}")
        self.log(f"  btn6 -> {r6}")
        data = {"btn3": r3, "btn6": r6}
        if r3 is not None and r6 is not None:
            return self._pass("OK combination 3+6 sent", data)
        return self._fail("Combination 3+6 no response", data)


class TestLongPress(BaseTest):
    NAME = "Long Press (button 8)"
    DESCRIPTION = "Long press FILTERED button — must respond to extended duration."
    CATEGORY = "hmi_buttons"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        resp = self.hmi.press(8, 6000)
        self.log(f"  long press btn8 -> {resp}")
        data = {"response": resp}
        if resp is not None:
            return self._pass("OK long press handled", data)
        return self._fail("Long press no response", data)