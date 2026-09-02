"""
ota_update.py — Strauss water-bar firmware (FOTA) helper.

Two sides:
  * DEVICE side (over COM): read installed versions with `fota_slot_info`
    and watch the FOTA progress the device reports over MQTT
    (`Fota downloading state: 1/0/-1`, `Fota Install: 1/0, ..., <ver>`).
  * SERVER side (over HTTPS): log in, then assign a desired firmware
    version to the device; the device downloads it via MQTT on its own.

SECURITY — nothing sensitive is hard-coded. Provide credentials via the
environment before running:
    STRAUSS_OTA_USER      login username
    STRAUSS_OTA_PASS      login password
    STRAUSS_LOGIN_URL     (optional) override login endpoint
    STRAUSS_FW_URL        (optional) override firmware endpoint
Never commit tokens/keys. Rotate any secret that has been shared.
"""
import os
import re
import time

import requests

LOGIN_URL = os.environ.get(
    "STRAUSS_LOGIN_URL",
    "https://sweltstcostumerapp.strauss-water.com/public/internal/login")
FW_URL = os.environ.get(
    "STRAUSS_FW_URL",
    "https://sweltstoperatorapp.strauss-water.com/internal/element/firmware")


# ────────────────────────────────────────────────────────────────────────
#  DEVICE side — versions and progress (parsed from the COM stream)
# ────────────────────────────────────────────────────────────────────────
def parse_fota_slot_info(resp: str) -> dict:
    """Parse the reply of `fota_slot_info` into a version dict."""
    if not resp:
        return {}
    out = {}
    pats = {
        "fw_factory": r"fw factory:\s*([\d.]+)",
        "fw_ota0": r"fw\s+ota_0:\s*([\d.]+)",
        "fw_ota1": r"fw\s+ota_1:\s*([\d.]+)",
        "fw_running": r"fw running:\s*([\d.]+)",
        "fw_slot": r"fw running:[^,]*,\s*slot:\s*(\w+)",
        "addon_ver": r"fw_ver\s*:\s*([\d.]+)",
        "addon_factory": r"fw addon fizz factory:\s*([\d.]+)",
        "addon_ota": r"fw addon fizz\s+ota:\s*([\d.]+)",
        "addon_running": r"fw addon fizz running:\s*([\d.]+)",
        "addon_crc32": r"fw_crc32\s*:\s*(\d+)",
        "addon_size": r"fw_size\s*:\s*(\d+)",
    }
    for key, pat in pats.items():
        m = re.search(pat, resp, re.IGNORECASE)
        out[key] = m.group(1) if m else None
    return out


# FOTA progress lines the device prints over MQTT
_DL_RE = re.compile(r"Fota downloading state:\s*(-?\d+)", re.IGNORECASE)
_INST_RE = re.compile(r"Fota Install:\s*(-?\d+)[^,]*,[^,]*,\s*([\d.]+)",
                      re.IGNORECASE)


def scan_fota_progress(lines) -> dict:
    """Scan stream lines for FOTA download/install progress.

    Returns the latest download state (1=downloading, 0=done, -1=error),
    install state (1=installing, 0=done) and the install version if seen.
    """
    dl_state = inst_state = inst_ver = None
    for ln in lines:
        m = _DL_RE.search(ln)
        if m:
            dl_state = int(m.group(1))
        m = _INST_RE.search(ln)
        if m:
            inst_state = int(m.group(1))
            inst_ver = m.group(2)
    return {"download_state": dl_state, "install_state": inst_state,
            "install_version": inst_ver}


# ────────────────────────────────────────────────────────────────────────
#  SERVER side — login + assign a desired firmware version
# ────────────────────────────────────────────────────────────────────────
def login(username: str = None, password: str = None) -> str:
    """Log in and return the access token. Credentials come from the
    environment unless passed explicitly."""
    username = username or os.environ.get("STRAUSS_OTA_USER", "")
    password = password or os.environ.get("STRAUSS_OTA_PASS", "")
    if not username or not password:
        raise RuntimeError(
            "Set STRAUSS_OTA_USER and STRAUSS_OTA_PASS in the environment.")
    r = requests.post(LOGIN_URL, json={"username": username,
                                       "password": password},
                      timeout=30, verify=True)
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise ValueError(f"No access_token in login response: {list(data)}")
    return token


def assign_firmware_version(token: str, device_file: str, hw_revision: str,
                            desired_version: str,
                            install_time: int = 77) -> dict:
    """Assign a desired firmware version to a device via updateCloudAndTwins.

    device_file    e.g. "S00037VG_S3231310040.csv"
    hw_revision    e.g. "P_HV_00.31"
    desired_version e.g. "1.001.028"
    The device then downloads it over MQTT on its own.
    """
    url = f"{FW_URL}/updateCloudAndTwins"
    body = {
        "deviceToUpdateFileName": device_file,
        "systemHardwareRevision": [hw_revision],
        "desiredFirmwareVersion": desired_version,
        "desiredInstallTime": install_time,
    }
    r = requests.post(url, json=body,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json"},
                      timeout=60, verify=True)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return {"status_code": r.status_code, "text": r.text[:200]}


def install_firmware_by_psn(token: str, psn: str, body: dict) -> dict:
    """Assign firmware to a single device by PSN (installFirmware/{PSN}).
    `body` is the JSON payload shown in Postman (slot/time/component).
    """
    url = f"{FW_URL}/installFirmware/{psn}"
    r = requests.post(url, json=body,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json"},
                      timeout=60, verify=True)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return {"status_code": r.status_code, "text": r.text[:200]}


# ────────────────────────────────────────────────────────────────────────
#  CLI demo
# ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import serial

    port = os.environ.get("SSL_TOOL_COM", "COM8")
    print(f"Reading fota_slot_info on {port} ...")
    try:
        with serial.Serial(port, 115200, timeout=5) as ser:
            ser.reset_input_buffer()
            ser.write(b"fota_slot_info\r\n")
            time.sleep(2)
            raw = ser.read(ser.in_waiting or 4096).decode(errors="ignore")
        print(parse_fota_slot_info(raw))
    except Exception as e:
        print("Device read failed:", e)
