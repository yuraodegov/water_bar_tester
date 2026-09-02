"""
tests/test_ota.py — firmware (FOTA) monitoring checks.

OTA-01  fota_slot_info returns readable versions (main fw + FIZZ addon)
OTA-02  watch the device FOTA stream for download/install progress
        (only when shabbat_ota_watch_sec > 0; otherwise INFO/skip — the
        actual update is triggered from the server, not by the test)

The update itself is assigned on the server (see ota_update.py: login +
assign_firmware_version); the device downloads it over MQTT. These tests
verify the device side: current versions and progress reporting.
"""
import time

from tests.test_base import BaseTest, TestResult

try:
    from ota_update import parse_fota_slot_info, scan_fota_progress
except Exception:                       # pragma: no cover
    parse_fota_slot_info = scan_fota_progress = None


class TestOta01SlotInfo(BaseTest):
    NAME = "OTA-01 fota_slot_info versions readable"
    DESCRIPTION = ("fota_slot_info returns the running firmware version and "
                   "the FIZZ addon version.")
    CATEGORY = "ota"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        if parse_fota_slot_info is None:
            return self._fail("ota_update.py not importable")
        resp = self.hmi.send_command("fota_slot_info") or ""
        info = parse_fota_slot_info(resp)
        self.log(f"  fw running={info.get('fw_running')} "
                 f"(slot {info.get('fw_slot')}), "
                 f"addon={info.get('addon_running') or info.get('addon_ver')}")
        data = dict(info)
        if info.get("fw_running") or info.get("addon_ver"):
            return self._pass(
                f"OK versions: fw={info.get('fw_running')} "
                f"addon={info.get('addon_running') or info.get('addon_ver')}",
                data)
        return self._fail(f"No versions parsed from fota_slot_info: "
                          f"{resp[:80]!r}", data)


class TestOta02WatchProgress(BaseTest):
    NAME = "OTA-02 Watch FOTA download/install progress"
    DESCRIPTION = ("Listen for FOTA progress the device reports over MQTT "
                   "(download 1->0, install 1->0). Enabled via ota_watch_sec.")
    CATEGORY = "ota"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        watch = float(self.config.get("ota_watch_sec", 0))
        if watch <= 0:
            return self._pass(
                "INFO OTA watch disabled (set ota_watch_sec > 0 to observe an "
                "update triggered from the server)", {"skipped": True})

        # collect the console stream for `watch` seconds and scan for progress
        lines = []
        deadline = time.time() + watch
        last_log = 0
        while time.time() < deadline:
            if self.stop_check():
                break
            chunk = self.hmi.read_lines(2.0) if hasattr(self.hmi, "read_lines") \
                else []
            if chunk:
                lines.extend(chunk)
            elapsed = int(time.time() - (deadline - watch))
            if elapsed - last_log >= 30:
                last_log = elapsed
                self.log(f"    watching FOTA... {elapsed}s")
        prog = scan_fota_progress(lines)
        data = dict(prog)
        self.log(f"  progress: {prog}")
        dl, inst = prog["download_state"], prog["install_state"]
        if dl == -1:
            return self._fail("FOTA download error (state -1)", data)
        if inst == 0:
            return self._pass(
                f"OK FOTA install completed (version "
                f"{prog['install_version']})", data)
        if dl is None and inst is None:
            return self._pass(
                "INFO no FOTA activity seen in the watch window "
                "(no update was in progress)", data)
        return self._pass(
            f"INFO FOTA in progress (download={dl}, install={inst})", data)
