"""
tests/test_long_term_volume.py

Sequence per cycle:
  press 5 1000  COLD JUG    -> wait pour_wait_sec
  sleep pause_sec
  press 7 1000  AMB JUG     -> wait pour_wait_sec
  sleep pause_sec
  press 2 1000  HOT JUG     -> wait pour_wait_sec
  sleep 60s  (hot fill pause)
  press 8 1000  EXTRA HOT   -> wait pour_wait_sec
  sleep pause_sec
"""
import time
from tests.test_base import BaseTest, TestResult


class TestLongTermVolume(BaseTest):
    NAME = "Long Term Volume"
    DESCRIPTION = "Cycles: COLD JUG -> AMB JUG -> HOT JUG -> EXTRA HOT"
    CATEGORY = "dispense"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err

        cycles = int(self.config.get("long_term_cycles", 17))
        pause_sec = int(self.config.get("long_term_pause_sec", 300))
        pour_wait = float(self.config.get("pour_wait_sec", 40))
        hot_pause = 60

        self.log(f"[{self.NAME}] Starting: cycles={cycles} pause={pause_sec}s pour_wait={pour_wait}s")

        for cycle in range(1, cycles + 1):
            if getattr(self, '_stopped', False):
                return self._fail(f"Stopped at cycle {cycle}/{cycles}")

            self.log("=" * 55)
            self.log(f"  CYCLE {cycle}/{cycles}")
            self.log("=" * 55)

            # COLD JUG
            self.log("  >> COLD JUG (btn 5)")
            self.hmi.press(5, 1000)
            time.sleep(pour_wait)

            self.log(f"  pause {pause_sec}s")
            time.sleep(pause_sec)

            # AMB JUG
            self.log("  >> AMB JUG (btn 7)")
            self.hmi.press(7, 1000)
            time.sleep(pour_wait)

            self.log(f"  pause {pause_sec}s")
            time.sleep(pause_sec)

            # HOT JUG
            self.log("  >> HOT JUG (btn 2)")
            self.hmi.press(2, 1000)
            time.sleep(pour_wait)

            self.log(f"  pause {hot_pause}s (hot fill)")
            time.sleep(hot_pause)

            # EXTRA HOT
            self.log("  >> EXTRA HOT (btn 8)")
            self.hmi.press(8, 1000)
            time.sleep(pour_wait)

            self.log(f"  pause {pause_sec}s")
            time.sleep(pause_sec)

            self.log(f"  Cycle {cycle} done.")

        return self._pass(
            f"Completed {cycles} cycles",
            {"cycles": cycles, "pause_sec": pause_sec},
        )
