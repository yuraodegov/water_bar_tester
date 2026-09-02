"""
tests/test_certificate.py — device SSL certificate provisioning checks.

These verify the certificate flow that ssl_tool.py automates, but as part of
the test suite:
  CERT-01  device returns a VSN (get_vsn)
  CERT-02  device generates a CSR (generatecsr <VSN> <slot>)
  CERT-03  the CSR is signed by the Strauss API and the PEM is valid
           (only runs when STRAUSS_API_TOKEN is set; otherwise INFO/skip)

Commands are sent over the HMI console (same port the app already uses).
CERT-03 needs network + the API token in the environment; without it the
test reports INFO instead of failing, so an offline bench stays green.
"""
import base64
import os
import re

from tests.test_base import BaseTest, TestResult

API_BASE = os.environ.get(
    "STRAUSS_API_BASE_URL",
    "https://sweltstcostumerapp.strauss-water.com/techapp/api/v1/device")


def _vsn_from(resp: str):
    if not resp:
        return None
    # device replies "VSN:SODAWWR" — require the colon and reject the literal
    # token "VSN" (which also appears inside the echoed "get_vsn" command).
    for m in re.finditer(r"VSN\s*:\s*([A-Za-z0-9_\-]+)", resp, re.IGNORECASE):
        val = m.group(1).strip()
        if val and val.upper() != "VSN":
            return val
    # fallback: a standalone identifier line that is not echo/prompt/keyword
    skip = {"GET_VSN", "VSN", "CMD", "EXECUTE", "OK", "ERROR", "FAILED"}
    for ln in resp.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith(">") and ln.upper() not in skip:
            if re.fullmatch(r"[A-Za-z0-9_\-]{4,}", ln):
                return ln
    return None


def _csr_from(resp: str):
    if resp and "-----BEGIN" in resp:
        m = re.search(r"(-----BEGIN.*?-----END[^\-]+-----)", resp, re.DOTALL)
        if m:
            return m.group(1).strip()
    return None


class TestCert01Vsn(BaseTest):
    NAME = "CERT-01 Device returns VSN"
    DESCRIPTION = "get_vsn returns a non-empty device serial (VSN)."
    CATEGORY = "cert"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        resp = self.hmi.send_command("get_vsn")
        vsn = _vsn_from(resp)
        self.log(f"  VSN = {vsn}")
        data = {"vsn": vsn}
        if vsn:
            return self._pass(f"OK VSN readable: {vsn}", data)
        return self._fail(f"No VSN parsed from get_vsn reply: {resp[:80]!r}",
                          data)


class TestCert02Csr(BaseTest):
    NAME = "CERT-02 Device generates CSR"
    DESCRIPTION = "generatecsr <VSN> <slot> returns a PEM certificate request."
    CATEGORY = "cert"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        slot = int(self.config.get("cert_slot", 0))
        vsn = _vsn_from(self.hmi.send_command("get_vsn"))
        if not vsn:
            return self._fail("cannot generate CSR without a VSN")
        resp = self.hmi.send_command(f"generatecsr {vsn} {slot}") or ""
        csr = _csr_from(resp)
        data = {"vsn": vsn, "slot": slot, "has_csr": bool(csr)}
        if "CMD EXECUTE ERROR" in resp or resp.strip() == "FAILED":
            return self._fail(
                f"device rejected generatecsr for VSN={vsn} slot={slot} "
                f"(CMD EXECUTE ERROR)", data)
        if csr:
            self.log(f"  CSR generated ({len(csr)} bytes)")
            self._csr = csr           # cache for CERT-03 within same run
            return self._pass(f"OK CSR generated for {vsn} (slot {slot})", data)
        # some firmwares emit a bare base64 block without PEM headers
        blob = "".join(ln.strip() for ln in resp.splitlines()
                       if re.fullmatch(r"[A-Za-z0-9+/=]{16,}", ln.strip()))
        if len(blob) > 100:
            data["has_csr"] = True
            return self._pass(f"OK CSR (base64) generated for {vsn}", data)
        return self._fail(f"No CSR in reply: {resp[:80]!r}", data)


class TestCert03Sign(BaseTest):
    NAME = "CERT-03 Sign CSR via API and verify PEM"
    DESCRIPTION = ("Sign the device CSR through the Strauss API and validate "
                   "the returned certificate. Needs STRAUSS_API_TOKEN.")
    CATEGORY = "cert"

    def run(self) -> TestResult:
        err = self._require_hmi()
        if err:
            return err
        token = os.environ.get("STRAUSS_API_TOKEN", "")
        if not token:
            return self._pass(
                "INFO STRAUSS_API_TOKEN not set — skipping online CSR signing",
                {"skipped": True})
        try:
            import requests
            from cryptography import x509
        except ImportError as e:
            return self._pass(f"INFO signing libs missing ({e}); skipped",
                              {"skipped": True})

        slot = int(self.config.get("cert_slot", 0))
        vsn = _vsn_from(self.hmi.send_command("get_vsn"))
        if not vsn:
            return self._fail("cannot sign without a VSN")
        csr = _csr_from(self.hmi.send_command(f"generatecsr {vsn} {slot}") or "")
        if not csr:
            return self._fail("device did not return a CSR to sign")

        csr_b64 = "".join(ln.strip() for ln in csr.splitlines()
                          if ln.strip() and "BEGIN" not in ln
                          and "END" not in ln)
        url = f"{API_BASE}/{vsn}/signCSR"
        try:
            r = requests.post(url, json={"csr": csr_b64},
                              headers={"Content-Type": "application/json",
                                       "Authorization": token},
                              timeout=30, verify=True)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            return self._fail(f"API sign failed: {e}", {"vsn": vsn})

        cert_b64 = next((payload[k] for k in
                         ("certificate", "cert", "signed_cert", "pem", "data")
                         if payload.get(k)), None)
        if not cert_b64:
            return self._fail(f"no certificate field in API response: "
                              f"{list(payload)}")
        pem = cert_b64 if str(cert_b64).lstrip().startswith("-----BEGIN") \
            else base64.b64decode(cert_b64).decode(errors="ignore")
        try:
            cert = x509.load_pem_x509_certificate(pem.encode())
        except Exception as e:
            return self._fail(f"signed cert is not valid PEM: {e}")
        subj = cert.subject.rfc4514_string()
        self.log(f"  signed cert subject: {subj}")
        return self._pass(f"OK CSR signed, valid cert for {vsn} ({subj})",
                          {"vsn": vsn, "subject": subj})
