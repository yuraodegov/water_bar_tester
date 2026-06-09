import time
from tests.test_base import BaseTest


class TestLongTermVolume(BaseTest):
    NAME = "Long Term Volume"
    DESCRIPTION = "HOT JUG -> FILTERED -> COLD JUG -> AMB JUG"
    CATEGORY = "dispense"

    def run(self):

        err = self._require_hmi()
        if err:
            return err

        cycles = int(self.config.get("long_term_cycles", 17))
        pause_sec = int(self.config.get("long_term_pause_sec", 300))
        pour_wait = float(self.config.get("pour_wait_sec", 40))

        self.log(f"Starting Long Term Test")
        self.log(f"Cycles={cycles}")
        self.log(f"Pause={pause_sec}s")

        for cycle in range(1, cycles + 1):

            self.log("=" * 60)
            self.log(f"Cycle {cycle}/{cycles}")
            self.log("=" * 60)

            # HOT JUG
            self.log("HOT JUG")
            self.hmi.press(2, 1000)
            time.sleep(pour_wait)

            # FILTERED
            self.log("FILTERED")
            self.hmi.press(8, 1000)

            self.log(f"Waiting {pause_sec}s")
            time.sleep(pause_sec)

            # COLD JUG
            self.log("COLD JUG")
            self.hmi.press(5, 1000)
            time.sleep(pour_wait)

            self.log(f"Waiting {pause_sec}s")
            time.sleep(pause_sec)

            # AMB JUG
            self.log("AMB JUG")
            self.hmi.press(7, 1000)
            time.sleep(pour_wait)

            self.log(f"Waiting {pause_sec}s")
            time.sleep(pause_sec)

        return self._pass(
            f"Completed {cycles} cycles",
            {
                "cycles": cycles,
                "pause_sec": pause_sec
            }
        )