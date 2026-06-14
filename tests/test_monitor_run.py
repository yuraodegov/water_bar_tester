"""
tests/test_monitor_run.py — long-term monitoring run.

Runs a configurable dispense loop while periodically logging:
  - HMI counters (Total / Filter / Cold / Amb / FilterMinutes) every HMI_PERIOD
  - HC status (Ttank/Tboost/TCW + valve outputs + raw status) every HC_PERIOD
  - a purifier snapshot (liters + filter minutes) after every dispense

At the end it prints a SUMMARY: liters per water type, total liters,
elapsed time, filter minutes consumed, and number of dispenses.

Stop conditions (whichever happens first):
  - user pressed STOP            (self.stop_check())
  - fixed duration reached       config["monitor_minutes"]   (0 = ignore)
  - dispense cycle count reached config["monitor_cycles"]    (0 = ignore)

Config keys (all optional, sensible defaults):
  monitor_minutes        total run time in minutes      (default 30, 0 = unlimited)
  monitor_cycles         number of dispense cycles       (default 0  = unlimited)
  monitor_hmi_period     HMI counter poll seconds        (default 120 = 2 min)
  monitor_hc_period      HC status poll seconds          (default 60  = 1 min)
  monitor_press_ms       dispense press duration ms      (default 1000)
  monitor_pour_wait      wait after press seconds        (default 40)
  monitor_pause          pause between dispenses seconds (default 30)
"""
import time
from tests.test_base import BaseTest, TestResult

# dispense sequence used by the monitor loop: (button_id, label, type_key)
SEQUENCE = [
    (5, "COLD JUG", "cold"),
    (7, "AMB JUG", "amb"),
    (2, "HOT JUG", "total"),
    (8, "EXTRA HOT", "total"),
]


class TestMonitorRun(BaseTest):
    NAME = "Monitor Run (long-term)"
    DESCRIPTION = (
        "Long dispense loop logging HMI counters every 2 min and HC status "
        "every 1 min, with a purifier snapshot after each dispense and a "
        "final liters/time/type summary."
    )
    CATEGORY = "monitor"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err

        cfg = self.config
        run_minutes = float(cfg.get("monitor_minutes", 30))
        max_cycles = int(cfg.get("monitor_cycles", 0))
        hmi_period = float(cfg.get("monitor_hmi_period", 120))
        hc_period = float(cfg.get("monitor_hc_period", 60))
        press_ms = int(cfg.get("monitor_press_ms", 1000))
        pour_wait = float(cfg.get("monitor_pour_wait", 40))
        pause = float(cfg.get("monitor_pause", 30))

        has_hc = (
            self.hydraulic is not None
            and self.hydraulic.is_connected()
            and hasattr(self.hydraulic, "hc_status")
        )

        start = time.time()
        deadline = start + run_minutes * 60 if run_minutes > 0 else None
        next_hmi = start
        next_hc = start

        # baseline counters for liters bookkeeping
        base = self._read_counters()
        self.log(f"[MONITOR] start baseline: {base}")

        per_type = {"cold": 0.0, "amb": 0.0, "total": 0.0}
        dispense_count = 0
        snapshots = []  # purifier snapshots after each dispense
        seq_idx = 0

        self.log(
            f"[MONITOR] run_minutes={run_minutes} max_cycles={max_cycles} "
            f"hmi_period={hmi_period}s hc_period={hc_period}s"
        )

        def stopped():
            if self.stop_check():
                self.log("[MONITOR] STOP requested by user.")
                return True
            if deadline and time.time() >= deadline:
                self.log("[MONITOR] time limit reached.")
                return True
            if max_cycles and dispense_count >= max_cycles:
                self.log("[MONITOR] cycle limit reached.")
                return True
            return False

        while not stopped():
            now = time.time()

            # periodic HMI counter log (every 2 min)
            if now >= next_hmi:
                c = self._read_counters()
                elapsed = int(now - start)
                self.log(
                    f"[MONITOR {elapsed}s] HMI counters: "
                    f"total={c['total']} filter={c['filter']} "
                    f"cold={c['cold']} amb={c['amb']} fmin={c['fmin']}"
                )
                next_hmi = now + hmi_period

            # periodic HC status log (every 1 min)
            if has_hc and now >= next_hc:
                self._log_hc_status()
                next_hc = now + hc_period

            # one dispense from the rotating sequence
            btn, label, tkey = SEQUENCE[seq_idx % len(SEQUENCE)]
            seq_idx += 1

            before = self._read_counters()
            self.log(f"[MONITOR] >> {label} (btn {btn})")
            self.hmi.press(btn, press_ms)

            # wait for the pour, but stay responsive to STOP
            waited = 0.0
            while waited < pour_wait and not self.stop_check():
                time.sleep(2)
                waited += 2

            after = self._read_counters()
            d_total = self._delta(after["total"], before["total"])
            d_type = self._delta(after.get(tkey), before.get(tkey))
            per_type[tkey] = per_type.get(tkey, 0.0) + d_total
            dispense_count += 1

            # purifier snapshot: liters + filter minutes after this dispense
            snap = {
                "n": dispense_count,
                "label": label,
                "delta_total_ml": d_total,
                "delta_type_ml": d_type,
                "filter_l": (after["filter"] or 0) / 1000.0,
                "filter_minutes": after["fmin"],
            }
            snapshots.append(snap)
            self.log(
                f"[MONITOR] snapshot #{dispense_count} {label}: "
                f"+{d_total:.0f}ml total, filter={snap['filter_l']:.2f}L, "
                f"fmin={after['fmin']}"
            )

            # pause between dispenses (responsive to STOP)
            waited = 0.0
            while waited < pause and not self.stop_check():
                time.sleep(2)
                waited += 2

        # ── build summary ────────────────────────────────────────────
        end = time.time()
        elapsed_s = int(end - start)
        final = self._read_counters()
        total_l = self._delta(final["total"], base["total"]) / 1000.0
        filter_l = self._delta(final["filter"], base["filter"]) / 1000.0
        fmin_used = self._delta(final["fmin"], base["fmin"])

        self.log("=" * 55)
        self.log("           MONITOR RUN SUMMARY")
        self.log("=" * 55)
        self.log(f"  Elapsed time     : {elapsed_s // 60} min {elapsed_s % 60} s")
        self.log(f"  Dispenses        : {dispense_count}")
        self.log(f"  Total dispensed  : {total_l:.2f} L")
        self.log(f"  Filter delta     : {filter_l:.2f} L")
        self.log(f"  Filter minutes   : {int(fmin_used)} min")
        self.log("  By type:")
        self.log(f"    Cold  : {per_type.get('cold', 0) / 1000.0:.2f} L")
        self.log(f"    Amb   : {per_type.get('amb', 0) / 1000.0:.2f} L")
        self.log(f"    Hot   : {per_type.get('total', 0) / 1000.0:.2f} L")
        self.log("=" * 55)

        data = {
            "elapsed_sec": elapsed_s,
            "dispenses": dispense_count,
            "total_liters": round(total_l, 3),
            "filter_liters": round(filter_l, 3),
            "filter_minutes": int(fmin_used),
            "cold_liters": round(per_type.get("cold", 0) / 1000.0, 3),
            "amb_liters": round(per_type.get("amb", 0) / 1000.0, 3),
            "hot_liters": round(per_type.get("total", 0) / 1000.0, 3),
            "snapshots": len(snapshots),
        }
        return self._pass(
            f"Monitor done: {dispense_count} dispenses, {total_l:.2f} L, "
            f"{elapsed_s // 60}m{elapsed_s % 60}s",
            data,
        )

    # ── helpers ──────────────────────────────────────────────────────
    def _read_counters(self) -> dict:
        return {
            "total": self.hmi.get_counter("total"),
            "filter": self.hmi.get_counter("filter"),
            "cold": self.hmi.get_counter("cold"),
            "amb": self.hmi.get_counter("amb"),
            "fmin": self.hmi.get_counter(6),
        }

    @staticmethod
    def _delta(after, before):
        if after is None or before is None:
            return 0.0
        d = after - before
        return d if d >= 0 else 0.0

    def _log_hc_status(self):
        try:
            st = self.hydraulic.hc_status()
        except Exception as exc:
            self.log(f"[MONITOR] HC status failed: {exc}")
            return
        outs = st.get("outputs", {})
        self.log(
            f"[MONITOR] HC: heater={st.get('heater')} "
            f"dispenser={st.get('dispenser')} hot_filling={st.get('hot_filling')} "
            f"cooler={st.get('cooler')}"
        )
        try:
            temps = self.hydraulic.hc_temps()
            self.log(
                f"[MONITOR] HC temps: Ttank={temps.get('ttank')} "
                f"Tboost={temps.get('tboost')} TCW={temps.get('tcw')}"
            )
        except Exception:
            pass
        self.log(
            f"[MONITOR] HC valves: EXTRA={outs.get('EXTRA_VALVE')} "
            f"HOT={outs.get('HOT_VALVE')} COLD={outs.get('COLD_VALVE')} "
            f"INLET={outs.get('INLET_VALVE')} AMBIENT={outs.get('AMBIENT_VALVE')}"
        )