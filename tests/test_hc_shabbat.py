"""
tests/test_hc_shabbat.py — Modules 8/9: Prepare / Operation Shabbat (PS, OS).
Shabbat entry has no terminal command — these tests need Manual Shabbat from
HMI (or shabbat_bypass param). Reported as SKIPPED until enabled.
Param checks that DO work over terminal are included as active tests.
"""
from core.hc_driver import HCDriver
from core.hc_config import PROFILES
from tests.test_base import BaseTest, TestResult


def _hc(test):
    hydr = test.hydraulic
    if hydr is None or not hydr.is_connected() or not isinstance(hydr, HCDriver):
        return None
    return hydr


def _cfg(test):
    return PROFILES.get(test.config.get("hc_profile", "IL").upper(), PROFILES["IL"])


class TestPS01PrepStageParams(BaseTest):
    NAME = "PS-01 Prepare-shabbat stage params"
    DESCRIPTION = "spmh1/spmh2/spmh3 params match profile values."
    CATEGORY = "hc_shabbat"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        s1 = hc.hc_get_param("heater_spmh1")
        s2 = hc.hc_get_param("heater_spmh2")
        s3 = hc.hc_get_param("heater_spmh3")
        self.log(f"  spmh1={s1} spmh2={s2} spmh3={s3}")
        data = {"spmh1": s1, "spmh2": s2, "spmh3": s3,
                "expected": [cfg.SPMH1, cfg.SPMH2, cfg.SPMH3]}
        if [s1, s2, s3] == [cfg.SPMH1, cfg.SPMH2, cfg.SPMH3]:
            return self._pass("OK prep-shabbat stage duties match profile", data)
        return self._fail(f"stage duties {[s1, s2, s3]} != {[cfg.SPMH1, cfg.SPMH2, cfg.SPMH3]}", data)


class TestPS02PrepTimeout(BaseTest):
    NAME = "PS-02 Prepare-shabbat timeout fixed"
    DESCRIPTION = "heater_fts is fixed at firmware constant (170 min)."
    CATEGORY = "hc_shabbat"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        val = hc.hc_get_param("heater_fts")
        self.log(f"  heater_fts={val} (expected fixed 170)")
        data = {"heater_fts": val}
        if val == 170:
            return self._pass("OK heater_fts fixed at 170", data)
        return self._fail(f"heater_fts={val} != 170", data)


class TestPS03ShabbatEntryNeedsHMI(BaseTest):
    NAME = "PS-03 Shabbat entry -> Prepare [needs HMI]"
    DESCRIPTION = "Requires Manual Shabbat from HMI — skipped automatically."
    CATEGORY = "hc_shabbat"

    def run(self) -> TestResult:
        return self._pass(
            "SKIPPED: trigger Manual Shabbat from HMI, then assert START_PREPARE_SHABBAT",
            {"skipped": True}
        )


class TestOS01ShabbatHeatingParams(BaseTest):
    NAME = "OS-01 Operation-shabbat heating params"
    DESCRIPTION = "sihp / bsps / shp params readable and match profile where defined."
    CATEGORY = "hc_shabbat"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        sihp = hc.hc_get_param("heater_sihp")
        bsps = hc.hc_get_param("heater_bsps")
        shp = hc.hc_get_param("heater_shp")
        self.log(f"  sihp={sihp} bsps={bsps} shp={shp} (BSPS profile={cfg.BSPS})")
        data = {"sihp": sihp, "bsps": bsps, "shp": shp, "bsps_profile": cfg.BSPS}
        if bsps == cfg.BSPS:
            return self._pass(f"OK shabbat params, bsps={bsps} matches profile", data)
        return self._fail(f"bsps={bsps} != profile {cfg.BSPS}", data)


class TestOS02ShabbatTimeout(BaseTest):
    NAME = "OS-02 Operation-shabbat timeout param"
    DESCRIPTION = "heater_shabbat_timeout matches profile SHABBAT_TO."
    CATEGORY = "hc_shabbat"

    def run(self) -> TestResult:
        err = self._require_hydraulic()
        if err:
            return err
        hc = _hc(self)
        if not hc:
            return self._fail("HCDriver required")
        cfg = _cfg(self)
        val = hc.hc_get_param("heater_shabbat_timeout")
        self.log(f"  heater_shabbat_timeout={val} profile={cfg.SHABBAT_TO}")
        data = {"shabbat_timeout": val, "profile": cfg.SHABBAT_TO}
        if val == cfg.SHABBAT_TO:
            return self._pass(f"OK shabbat_timeout={val}", data)
        return self._fail(f"shabbat_timeout {val} != profile {cfg.SHABBAT_TO}", data)


class TestOS03ShabbatEndNeedsHMI(BaseTest):
    NAME = "OS-03 Operation Shabbat -> Idle at end [needs HMI]"
    DESCRIPTION = "Requires Operation-Shabbat state via HMI — skipped automatically."
    CATEGORY = "hc_shabbat"

    def run(self) -> TestResult:
        return self._pass("SKIPPED: enter Operation Shabbat via HMI, use min5", {"skipped": True})