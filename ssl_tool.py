"""
ssl_tool.py — Strauss water-bar certificate manager.

Flow: read VSN from the device over COM -> generate a CSR on the device ->
sign the CSR through the Strauss API -> save the PEM -> optionally upload to
Azure Blob Storage. Usable from the CLI or a small Tk GUI (--gui).

SECURITY: the API token is NOT stored in this file. Set it in the
environment variable STRAUSS_API_TOKEN before running:
    Windows (PowerShell):  $env:STRAUSS_API_TOKEN="<token>"
    Linux/macOS:           export STRAUSS_API_TOKEN="<token>"
Keep tokens out of source control (add any .env file to .gitignore).
"""
import base64
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone

import serial
import serial.tools.list_ports
import requests
from cryptography import x509

try:
    import tkinter as tk
    from tkinter import scrolledtext
    _HAS_TK = True
except Exception:                       # headless environment, CLI still works
    _HAS_TK = False


# ============================================================
# CONFIG — override via environment where sensitive
# ============================================================
CONFIG = {
    "com_port": os.environ.get("SSL_TOOL_COM", "COM5"),
    "baud_rate": 115200,
    "com_timeout": 10,                  # seconds to wait for a device reply

    "api_base_url": os.environ.get(
        "STRAUSS_API_BASE_URL",
        "https://sweltstcostumerapp.strauss-water.com/techapp/api/v1/device"),
    # NEVER hard-code the token; read it from the environment only.
    "api_token": os.environ.get("STRAUSS_API_TOKEN", ""),

    "azure_connection_string": os.environ.get(
        "AZURE_STORAGE_CONNECTION_STRING", ""),
    "azure_container": "device-certificates",

    "save_dir": os.path.join(os.path.expanduser("~"), "ssl_tool_out"),
}

os.makedirs(CONFIG["save_dir"], exist_ok=True)

LOG_FILE = os.path.join(CONFIG["save_dir"], "ssl_tool.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)


def _redact(text: str) -> str:
    """Keep secrets out of the log: mask the token if it appears in text."""
    tok = CONFIG.get("api_token")
    if tok and tok in text:
        text = text.replace(tok, tok[:6] + "…REDACTED")
    return text


# ============================================================
# COM PORT
# ============================================================
def list_com_ports():
    return [p.device for p in serial.tools.list_ports.comports()]


def send_command(ser: serial.Serial, cmd: str, wait: float = 3.0,
                 idle: float = 0.4) -> str:
    """Send a command and read the full reply.

    Instead of a single fixed read, drain the port until it stays quiet for
    `idle` seconds (or `wait` total elapses), so long CSR/PEM replies are not
    truncated.
    """
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    logging.info(">> %s", cmd)
    deadline = time.time() + wait
    chunks, last = [], time.time()
    while time.time() < deadline:
        n = ser.in_waiting
        if n:
            chunks.append(ser.read(n))
            last = time.time()
        elif chunks and (time.time() - last) >= idle:
            break                       # reply finished
        else:
            time.sleep(0.05)
    text = b"".join(chunks).decode(errors="ignore")
    logging.info("<< %s", _redact(text[:200]))
    return text


def _open_serial(port: str, baud: int, timeout: float) -> serial.Serial:
    """Open a serial port with a clear error if it is busy/missing."""
    try:
        return serial.Serial(port, baud, timeout=timeout)
    except serial.SerialException as e:
        raise RuntimeError(
            f"Cannot open {port}: {e}. Is the port correct and not in use "
            f"by another program?") from e


def get_vsn(port: str, baud: int = 115200, timeout: float = 10) -> str:
    """Read the VSN from the device via `get_vsn`."""
    with _open_serial(port, baud, timeout) as ser:
        resp = send_command(ser, "get_vsn", wait=2.0)
    m = re.search(r"VSN[:\s]+([A-Za-z0-9_\-]+)", resp, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    lines = [ln.strip() for ln in resp.splitlines() if ln.strip()]
    if lines:
        return lines[0]
    raise ValueError(f"Could not parse VSN from reply: {resp!r}")


def get_csr_from_device(port: str, vsn: str, slot: int = 0,
                        baud: int = 115200, timeout: float = 10) -> str:
    """Run `generatecsr <VSN> <slot>` and return the CSR text (PEM if present)."""
    with _open_serial(port, baud, timeout) as ser:
        resp = send_command(ser, f"generatecsr {vsn} {slot}", wait=3.0)
    if "-----BEGIN" in resp:
        m = re.search(r"(-----BEGIN.*?-----END[^\-]+-----)", resp, re.DOTALL)
        if m:
            return m.group(1).strip()
    return resp.strip()


# ============================================================
# API — sign CSR
# ============================================================
def sign_csr(vsn: str, csr_text: str) -> str:
    """POST the CSR to /device/{VSN}/signCSR and return the signed PEM."""
    if not CONFIG["api_token"]:
        raise RuntimeError(
            "STRAUSS_API_TOKEN is not set. Export it in the environment "
            "before signing (see the module docstring).")

    lines = [ln.strip() for ln in csr_text.splitlines()
             if ln.strip() and "BEGIN" not in ln and "END" not in ln]
    csr_b64 = "".join(lines)

    url = f"{CONFIG['api_base_url']}/{vsn}/signCSR"
    headers = {
        "Content-Type": "application/json",
        "Authorization": CONFIG["api_token"],
    }
    payload = {"csr": csr_b64}

    logging.info("POST %s", url)
    r = requests.post(url, json=payload, headers=headers, timeout=30,
                      verify=True)
    r.raise_for_status()

    try:
        data = r.json()
    except ValueError as e:
        raise ValueError(
            f"API did not return JSON: {r.text[:120]!r}") from e
    logging.info("Response keys: %s", list(data.keys()))

    cert_b64 = None
    for key in ("certificate", "cert", "signed_cert", "pem", "data"):
        if key in data and data[key]:
            cert_b64 = data[key]
            break
    if not cert_b64:
        raise ValueError(f"No certificate field in response: {data}")

    # the field may already be PEM, or base64 of PEM
    if isinstance(cert_b64, str) and cert_b64.lstrip().startswith("-----BEGIN"):
        decoded = cert_b64
    else:
        try:
            decoded = base64.b64decode(cert_b64).decode(errors="ignore")
        except Exception as e:
            raise ValueError(f"Cannot base64-decode certificate: {e}") from e
    if not decoded.strip().startswith("-----BEGIN"):
        raise ValueError(f"Response is not PEM: {decoded[:100]!r}")
    return decoded


# ============================================================
# AZURE BLOB UPLOAD (optional)
# ============================================================
def upload_to_azure(pem_text: str, vsn: str) -> str:
    conn_str = CONFIG.get("azure_connection_string", "")
    if not conn_str:
        raise ValueError(
            "AZURE_STORAGE_CONNECTION_STRING is not set in the environment.")
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError as e:
        raise RuntimeError(
            "azure-storage-blob is not installed (pip install "
            "azure-storage-blob).") from e
    blob_name = f"{vsn}.pem"
    client = BlobServiceClient.from_connection_string(conn_str)
    container = client.get_container_client(CONFIG["azure_container"])
    container.upload_blob(blob_name, pem_text.encode(), overwrite=True)
    url = f"{client.url}{CONFIG['azure_container']}/{blob_name}"
    logging.info("Uploaded to Azure: %s", url)
    return url


# ============================================================
# HELPERS
# ============================================================
def save_file(content: str, filename: str) -> str:
    path = os.path.join(CONFIG["save_dir"], filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logging.info("Saved: %s", path)
    return path


def parse_cert_info(pem: str) -> dict:
    cert = x509.load_pem_x509_certificate(pem.encode())
    try:
        not_before = cert.not_valid_before_utc.isoformat()
        not_after = cert.not_valid_after_utc.isoformat()
    except AttributeError:
        not_before = cert.not_valid_before.isoformat()
        not_after = cert.not_valid_after.isoformat()
    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "not_before": not_before,
        "not_after": not_after,
        "serial_number": str(cert.serial_number),
    }


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


# ============================================================
# FULL FLOW: COM -> CSR -> sign -> PEM -> Azure
# ============================================================
def full_flow(port: str, slot: int = 0, upload_azure: bool = False,
              log_fn=print) -> dict:
    result = {}

    log_fn("Connecting to device...")
    vsn = get_vsn(port, CONFIG["baud_rate"], CONFIG["com_timeout"])
    log_fn(f"VSN: {vsn}")
    result["vsn"] = vsn

    log_fn(f"Generating CSR (slot {slot})...")
    csr_text = get_csr_from_device(port, vsn, slot,
                                   CONFIG["baud_rate"], CONFIG["com_timeout"])
    csr_path = save_file(csr_text, f"csr_{vsn}_{_utc_stamp()}.csr")
    log_fn(f"CSR saved: {csr_path}")
    result["csr_path"] = csr_path

    log_fn("Signing CSR via API...")
    pem_text = sign_csr(vsn, csr_text)
    pem_path = save_file(pem_text, f"{vsn}.pem")
    log_fn(f"PEM saved: {pem_path}")
    result["pem_path"] = pem_path

    info = parse_cert_info(pem_text)
    log_fn(f"Certificate: {info['subject']}")
    log_fn(f"Valid until: {info['not_after']}")
    result["cert_info"] = info

    if upload_azure:
        log_fn("Uploading to Azure...")
        result["azure_url"] = upload_to_azure(pem_text, vsn)
        log_fn(f"Azure URL: {result['azure_url']}")

    return result


# ============================================================
# CLI
# ============================================================
def cli_main():
    while True:
        print("\n=== SSL TOOL (CLI) ===")
        print("1) Full flow (VSN -> CSR -> sign -> PEM -> Azure)")
        print("2) Get VSN only")
        print("3) Generate CSR only")
        print("4) Sign CSR from file")
        print("5) Settings")
        print("6) Exit")
        c = input("Choice: ").strip()

        if c == "1":
            port = input(f"COM port [{CONFIG['com_port']}]: ").strip() \
                or CONFIG["com_port"]
            slot = int(input("Slot [0]: ").strip() or "0")
            azure = input("Upload to Azure? (y/n): ").strip().lower() == "y"
            try:
                full_flow(port, slot, azure)
            except Exception as e:
                logging.exception("full_flow failed")
                print("Error:", e)

        elif c == "2":
            port = input(f"COM port [{CONFIG['com_port']}]: ").strip() \
                or CONFIG["com_port"]
            try:
                print("VSN:", get_vsn(port))
            except Exception as e:
                print("Error:", e)

        elif c == "3":
            port = input(f"COM port [{CONFIG['com_port']}]: ").strip() \
                or CONFIG["com_port"]
            vsn = input("VSN (Enter for auto): ").strip()
            slot = int(input("Slot [0]: ").strip() or "0")
            try:
                if not vsn:
                    vsn = get_vsn(port)
                    print("VSN:", vsn)
                csr = get_csr_from_device(port, vsn, slot)
                print("Saved:", save_file(csr, f"csr_{vsn}_{_utc_stamp()}.csr"))
            except Exception as e:
                print("Error:", e)

        elif c == "4":
            fp = input("Path to CSR file: ").strip()
            vsn = input("Device VSN: ").strip()
            try:
                with open(fp, encoding="utf-8") as f:
                    csr_text = f.read()
                pem = sign_csr(vsn, csr_text)
                print("PEM saved:", save_file(pem, f"{vsn}.pem"))
                print(json.dumps(parse_cert_info(pem), indent=2,
                                 ensure_ascii=False))
            except Exception as e:
                print("Error:", e)

        elif c == "5":
            print(f"com_port:     {CONFIG['com_port']}")
            print(f"api_base_url: {CONFIG['api_base_url']}")
            tok = CONFIG["api_token"]
            print(f"api_token:    {'set (' + tok[:6] + '…)' if tok else 'NOT set — export STRAUSS_API_TOKEN'}")
            if input("Change COM port? (y/n): ").strip().lower() == "y":
                CONFIG["com_port"] = input("New port: ").strip()

        elif c == "6":
            print("Exit")
            break


# ============================================================
# GUI
# ============================================================
def gui_main():
    if not _HAS_TK:
        print("tkinter not available; use the CLI instead.")
        return
    root = tk.Tk()
    root.title("SSL Tool — Strauss Bar Certificate Manager")
    root.geometry("900x650")
    root.configure(bg="#1e1e2e")
    C = {"bg": "#1e1e2e", "panel": "#2a2a3e", "accent": "#7c6af7",
         "green": "#50fa7b", "red": "#ff5555", "text": "#cdd6f4"}

    def lbl(parent, text, **kw):
        return tk.Label(parent, text=text, bg=C["bg"], fg=C["text"],
                        font=("Consolas", 10), **kw)

    def entry(parent, width=40):
        return tk.Entry(parent, width=width, bg=C["panel"], fg=C["text"],
                        insertbackground=C["text"], relief="flat",
                        font=("Consolas", 10))

    def btn(parent, text, cmd, color=None):
        return tk.Button(parent, text=text, command=cmd,
                         bg=color or C["accent"], fg="white", relief="flat",
                         font=("Consolas", 10, "bold"), padx=12, pady=6,
                         cursor="hand2")

    top = tk.Frame(root, bg=C["bg"])
    top.pack(fill="x", padx=16, pady=(16, 4))
    lbl(top, "COM Port:").grid(row=0, column=0, sticky="w")
    port_entry = entry(top, 10)
    port_entry.insert(0, CONFIG["com_port"])
    port_entry.grid(row=0, column=1, padx=(4, 16))
    lbl(top, "Slot:").grid(row=0, column=2, sticky="w")
    slot_entry = entry(top, 4)
    slot_entry.insert(0, "0")
    slot_entry.grid(row=0, column=3, padx=(4, 16))
    azure_var = tk.BooleanVar(value=False)
    tk.Checkbutton(top, text="Upload Azure", variable=azure_var, bg=C["bg"],
                   fg=C["text"], selectcolor=C["panel"],
                   font=("Consolas", 10)).grid(row=0, column=4, padx=8)

    mid = tk.Frame(root, bg=C["bg"])
    mid.pack(fill="x", padx=16, pady=4)
    lbl(mid, "VSN:").grid(row=0, column=0, sticky="w")
    vsn_var = tk.StringVar(value="—")
    tk.Label(mid, textvariable=vsn_var, bg=C["bg"], fg=C["green"],
             font=("Consolas", 11, "bold")).grid(row=0, column=1, sticky="w",
                                                  padx=8)

    log_area = scrolledtext.ScrolledText(
        root, height=20, bg=C["panel"], fg=C["text"], font=("Consolas", 9),
        relief="flat", insertbackground=C["text"])
    log_area.pack(fill="both", expand=True, padx=16, pady=8)

    def log(msg, color=None):
        tag = f"tag_{len(log_area.tag_names())}"
        log_area.insert(tk.END, msg + "\n", tag)
        if color:
            log_area.tag_config(tag, foreground=color)
        log_area.see(tk.END)

    bf = tk.Frame(root, bg=C["bg"])
    bf.pack(fill="x", padx=16, pady=(0, 16))

    def run_full_flow():
        port = port_entry.get().strip()
        slot = int(slot_entry.get().strip() or "0")
        azure = azure_var.get()
        log_area.delete("1.0", tk.END)
        import threading

        def worker():
            try:
                result = full_flow(port, slot, azure,
                                   log_fn=lambda m: log(m, C["green"]))
                vsn_var.set(result.get("vsn", "—"))
                log("Done!", C["green"])
            except Exception as e:
                log(f"Error: {e}", C["red"])
                logging.exception("GUI full_flow error")
        threading.Thread(target=worker, daemon=True).start()

    def run_get_vsn():
        try:
            v = get_vsn(port_entry.get().strip())
            vsn_var.set(v)
            log(f"VSN: {v}", C["green"])
        except Exception as e:
            log(f"Error: {e}", C["red"])

    btn(bf, "Full flow", run_full_flow, C["accent"]).pack(side="left", padx=4)
    btn(bf, "Get VSN", run_get_vsn, "#44475a").pack(side="left", padx=4)
    root.mainloop()


# ============================================================
if __name__ == "__main__":
    if "--gui" in sys.argv:
        gui_main()
    else:
        cli_main()
