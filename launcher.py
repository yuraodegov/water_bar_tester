"""
launcher.py — Tamar HC HIL  ·  Unified test instrument (single window, 3 tabs)

Tabs:
  1. Water Bar Tester  — the existing HMI/HC GUI (embedded from water_bar_tester.py)
  2. Test Runner       — runs the tamar_hil/ pytest suite (SIM + HC + HMI)
  3. Manual Control    — live sensor injection + output monitor via the simulator

Run:  python launcher.py
"""

import os
import re
import sys
import time
import threading
import subprocess

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import water_bar_tester as wbt  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
#  THEME
# ─────────────────────────────────────────────────────────────────────────────

C = dict(
    bg="#1E1E2E", panel="#2A2A3E", card="#313150",
    text="#CDD6F4", muted="#6C7086", accent="#89B4FA",
    green="#A6E3A1", red="#F38BA8", yellow="#F9E2AF",
    cyan="#89DCEB", purple="#CBA6F7", orange="#FAB387",
    teal="#94E2D5", pink="#F5C2E7", dark="#11111B",
    btn_fg="#1E1E2E",
)


# ─────────────────────────────────────────────────────────────────────────────
#  TEST GROUPS (point at tamar_hil/ package)
# ─────────────────────────────────────────────────────────────────────────────

TEST_GROUPS = [
    {"id": "smoke", "label": "Smoke Test  —  Connection sanity",
     "file": "tamar_hil/test_smoke.py", "desc": "21 tests · Run FIRST",
     "req": ["sim"], "col": "#89B4FA"},
    {"id": "extra_hot", "label": "Extra Hot V6",
     "file": "tamar_hil/test_extra_hot_v6.py", "desc": "12 tests · EH-01..12",
     "req": ["sim", "hc"], "col": "#FF5722"},
    {"id": "hot_fill", "label": "Hot Fill V5",
     "file": "tamar_hil/test_hot_fill_v5.py", "desc": "13 tests · HF-01..13",
     "req": ["sim", "hc"], "col": "#FF9800"},
    {"id": "dispensing", "label": "Dispensing V01  (HC terminal)",
     "file": "tamar_hil/test_dispensing_v01.py", "desc": "22 tests · CD/AD/HD/XM",
     "req": ["sim", "hc"], "col": "#00BCD4"},
    {"id": "dispensing_hmi", "label": "Dispensing via HMI  (press 1-9)",
     "file": "tamar_hil/test_dispensing_hmi.py", "desc": "15 tests · full chain",
     "req": ["sim", "hc", "hmi"], "col": "#9C27B0"},
    {"id": "idle", "label": "Idle V7  +  Hysteresis",
     "file": "tamar_hil/test_idle_v7.py", "desc": "15 tests · IHP/ISP + hyst",
     "req": ["sim", "hc"], "col": "#607D8B"},
    {"id": "prepare_shabbat", "label": "Prepare to Shabbat V7  (HMI 9×10s)",
     "file": "tamar_hil/test_prepare_shabbat_v7.py", "desc": "12 tests · PS-01..12",
     "req": ["sim", "hc", "hmi"], "col": "#3F51B5"},
    {"id": "operation_shabbat", "label": "Operation Shabbat V6  (HMI 9×10s)",
     "file": "tamar_hil/test_operation_shabbat_v6.py", "desc": "10 tests · OS-01..10",
     "req": ["sim", "hc", "hmi"], "col": "#673AB7"},
    {"id": "shabbat_hmi", "label": "Shabbat HMI  —  Entry + flow",
     "file": "tamar_hil/test_shabbat_hmi.py", "desc": "16 tests · SHB-01..16",
     "req": ["sim", "hc", "hmi"], "col": "#F48FB1"},
    {"id": "cooling", "label": "Cooling V07",
     "file": "tamar_hil/test_cooling_v07.py", "desc": "13 tests · CL+CS",
     "req": ["sim", "hc"], "col": "#009688"},
    {"id": "washing", "label": "Washing HWT  (Installation)",
     "file": "tamar_hil/test_washing_hwt.py", "desc": "19 tests · WH-01..19",
     "req": ["sim", "hc"], "col": "#795548"},
]


# ─────────────────────────────────────────────────────────────────────────────
#  SERIAL HELPER (manual panel)
# ─────────────────────────────────────────────────────────────────────────────

class SimConn:
    """Non-blocking serial connection to the Nucleo simulator."""

    def __init__(self):
        self._ser = None
        self._lock = threading.Lock()

    def connect(self, port, baud=115200):
        try:
            self._ser = serial.Serial(port, baud, timeout=1.5)
            time.sleep(0.4)
            self._ser.reset_input_buffer()
            return True
        except Exception:
            self._ser = None
            return False

    def disconnect(self):
        with self._lock:
            if self._ser and self._ser.is_open:
                self._ser.close()
            self._ser = None

    @property
    def connected(self):
        return self._ser is not None and self._ser.is_open

    def send(self, cmd, wait_ms=300):
        if not self.connected:
            return ""
        with self._lock:
            try:
                self._ser.reset_input_buffer()
                self._ser.write((cmd.strip() + "\r\n").encode())
                time.sleep(wait_ms / 1000.0)
                buf = []
                while self._ser.in_waiting:
                    line = self._ser.readline().decode(errors="replace").rstrip()
                    if line:
                        buf.append(line)
                return "\n".join(buf)
            except Exception:
                return ""


def get_ports():
    if HAS_SERIAL:
        return sorted(p.device for p in serial.tools.list_ports.comports()) or ["COM3"]
    if sys.platform.startswith("win"):
        return [f"COM{i}" for i in range(1, 21)]
    return [f"/dev/ttyACM{i}" for i in range(6)]


def ansi(t):
    return re.sub(r'\x1b\[[0-9;]*[mA-Za-z]', '', t)


def _lbl(parent, text="", fg=None, font_=None, **kw):
    return tk.Label(parent, text=text, bg=kw.pop("bg", C["card"]),
                    fg=fg or C["text"], font=font_ or ("Segoe UI", 9), **kw)


def _btn(parent, text, cmd, bg=None, fg=None, **kw):
    kw.setdefault("font", ("Segoe UI", 9))
    return tk.Button(parent, text=text, command=cmd, bg=bg or C["panel"],
                     fg=fg or C["accent"], relief="flat", cursor="hand2",
                     activebackground=C["bg"], activeforeground=C["accent"],
                     **kw)


# ─────────────────────────────────────────────────────────────────────────────
#  TEST RUNNER TAB
# ─────────────────────────────────────────────────────────────────────────────

class RunnerTab(tk.Frame):

    def __init__(self, master, pv_sim, pv_hc, pv_hmi, **kw):
        super().__init__(master, bg=C["bg"], **kw)
        self._pv_sim, self._pv_hc, self._pv_hmi = pv_sim, pv_hc, pv_hmi
        self._slow = tk.BooleanVar(value=False)
        self._verbose = tk.BooleanVar(value=True)
        self._stop_fail = tk.BooleanVar(value=False)
        self._group_vars = {g["id"]: tk.BooleanVar(value=True) for g in TEST_GROUPS}
        self._process = None
        self._running = False
        self._t0 = 0.0
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(1, weight=1)
        self._build_options_bar()
        self._build_groups()
        self._build_output()
        self._build_run_bar()

    def _build_options_bar(self):
        bar = tk.Frame(self, bg=C["panel"], pady=6, padx=12)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        _lbl(bar, "Options:", bg=C["panel"], fg=C["muted"]).pack(
            side="left", padx=(0, 8))
        for var, txt, col in [
            (self._slow, "Include @slow (overnight)", C["yellow"]),
            (self._verbose, "Verbose (-v)", C["text"]),
            (self._stop_fail, "Stop on first fail (-x)", C["red"]),
        ]:
            tk.Checkbutton(bar, text=txt, variable=var, bg=C["panel"], fg=col,
                           selectcolor=C["bg"], activebackground=C["panel"],
                           activeforeground=col, font=("Segoe UI", 9)).pack(
                side="left", padx=8)
        _btn(bar, "Select all", self._sel_all, bg=C["panel"],
             fg=C["accent"]).pack(side="right")
        _btn(bar, "Clear all", self._clr_all, bg=C["panel"],
             fg=C["muted"]).pack(side="right", padx=4)

    def _build_groups(self):
        outer = tk.Frame(self, bg=C["panel"], padx=6, pady=6)
        outer.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=8)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)
        _lbl(outer, "Test Groups", bg=C["panel"], fg=C["accent"],
             font_=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        canvas = tk.Canvas(outer, bg=C["card"], highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")
        inner = tk.Frame(canvas, bg=C["card"])
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        for g in TEST_GROUPS:
            row = tk.Frame(inner, bg=C["card"], pady=3)
            row.pack(fill="x", padx=4)
            _lbl(row, "●", fg=g["col"], font_=("Segoe UI", 11)).pack(side="left")
            tk.Checkbutton(row, variable=self._group_vars[g["id"]], bg=C["card"],
                           selectcolor=C["panel"],
                           activebackground=C["card"]).pack(side="left")
            txt = tk.Frame(row, bg=C["card"])
            txt.pack(side="left", fill="x", expand=True)
            _lbl(txt, g["label"], font_=("Segoe UI", 9, "bold")).pack(anchor="w")
            _lbl(txt, g["desc"], fg=C["muted"], font_=("Segoe UI", 8)).pack(
                anchor="w")
            bf = tk.Frame(row, bg=C["card"])
            bf.pack(side="right", padx=4)
            bc = {"sim": C["accent"], "hc": C["green"], "hmi": C["yellow"]}
            for r in g["req"]:
                _lbl(bf, r.upper(), bg=bc[r], fg=C["btn_fg"],
                     font_=("Segoe UI", 7, "bold")).pack(side="left", padx=1)

    def _build_output(self):
        outer = tk.Frame(self, bg=C["panel"], padx=6, pady=6)
        outer.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=8)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)
        _lbl(outer, "Output", bg=C["panel"], fg=C["accent"],
             font_=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        self._out = scrolledtext.ScrolledText(
            outer, bg=C["dark"], fg=C["text"], font=("Consolas", 9),
            wrap="word", state="disabled", relief="flat",
            insertbackground=C["text"])
        self._out.grid(row=1, column=0, sticky="nsew")
        for tag, col in [("pass", C["green"]), ("fail", C["red"]),
                         ("warn", C["yellow"]), ("muted", C["muted"]),
                         ("hdr", C["accent"])]:
            self._out.tag_configure(tag, foreground=col)

    def _build_run_bar(self):
        bar = tk.Frame(self, bg=C["panel"], pady=8, padx=12)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure(4, weight=1)
        self._btn_run = tk.Button(bar, text="▶  RUN SELECTED", command=self._run,
                                  bg=C["accent"], fg=C["btn_fg"],
                                  font=("Segoe UI", 11, "bold"), relief="flat",
                                  padx=20, pady=8, cursor="hand2")
        self._btn_run.grid(row=0, column=0, padx=(0, 6))
        self._btn_stop = tk.Button(bar, text="■  STOP", command=self._stop,
                                   bg=C["red"], fg=C["btn_fg"],
                                   font=("Segoe UI", 11, "bold"), relief="flat",
                                   padx=16, pady=8, cursor="hand2",
                                   state="disabled")
        self._btn_stop.grid(row=0, column=1, padx=4)
        _btn(bar, "Clear", self._clear_out, bg=C["panel"], fg=C["muted"],
             pady=8).grid(row=0, column=2, padx=4)
        self._status_var = tk.StringVar(value="Ready")
        self._timer_var = tk.StringVar(value="")
        _lbl(bar, textvariable=self._timer_var, bg=C["panel"], fg=C["accent"],
             font_=("Consolas", 10)).grid(row=0, column=5, padx=20)
        _lbl(bar, textvariable=self._status_var, bg=C["panel"], fg=C["muted"],
             font_=("Segoe UI", 9)).grid(row=0, column=4, padx=8)

    def _sel_all(self):
        for v in self._group_vars.values():
            v.set(True)

    def _clr_all(self):
        for v in self._group_vars.values():
            v.set(False)

    def _clear_out(self):
        self._out.configure(state="normal")
        self._out.delete("1.0", "end")
        self._out.configure(state="disabled")

    def _build_cmd(self):
        sel = [g for g in TEST_GROUPS if self._group_vars[g["id"]].get()]
        if not sel:
            messagebox.showwarning("No tests selected",
                                   "Select at least one group.")
            return None
        cmd = [sys.executable, "-m", "pytest"] + [g["file"] for g in sel]
        cmd += [f"--port-sim={self._pv_sim.get()}"]
        if any("hc" in g["req"] for g in sel) and self._pv_hc.get():
            cmd += [f"--port-hc={self._pv_hc.get()}"]
        if any("hmi" in g["req"] for g in sel) and self._pv_hmi.get():
            cmd += [f"--port-hmi={self._pv_hmi.get()}"]
        if not self._slow.get():
            cmd += ["-m", "not slow"]
        if self._verbose.get():
            cmd += ["-v"]
        if self._stop_fail.get():
            cmd += ["-x"]
        cmd += ["--tb=short", "--no-header"]
        return cmd

    def _run(self):
        cmd = self._build_cmd()
        if not cmd:
            return
        self._clear_out()
        ts = time.strftime("%H:%M:%S")
        self._write(f"{'-'*56}\n  {ts}  SIM={self._pv_sim.get()}"
                    f"  HC={self._pv_hc.get()}  HMI={self._pv_hmi.get()}\n"
                    f"{'-'*56}\n\n", "muted")
        self._btn_run.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._running = True
        self._t0 = time.time()
        self._status_var.set("Running…")
        self._tick()
        threading.Thread(target=self._run_th, args=(cmd,), daemon=True).start()

    def _run_th(self, cmd):
        try:
            self._process = subprocess.Popen(
                cmd, cwd=BASE_DIR, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                encoding="utf-8", errors="replace")
            for line in self._process.stdout:
                self.after(0, self._append_line, line.rstrip())
            self._process.wait()
            rc = self._process.returncode
        except Exception as e:
            self.after(0, self._write, f"ERROR: {e}\n", "fail")
            rc = -1
        self.after(0, self._done, rc)

    def _done(self, rc):
        self._running = False
        el = time.time() - self._t0
        self._btn_run.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        m, s = divmod(int(el), 60)
        if rc == 0:
            self._status_var.set(f"✓ Passed  ({m:02d}:{s:02d})")
            self._write(f"\n{'='*56}\n  ✓  ALL PASSED  {m:02d}:{s:02d}\n"
                        f"{'='*56}\n", "pass")
        elif rc == 1:
            self._status_var.set(f"✗ Failed  ({m:02d}:{s:02d})")
            self._write(f"\n{'='*56}\n  ✗  FAILED  {m:02d}:{s:02d}\n"
                        f"{'='*56}\n", "fail")
        else:
            self._status_var.set(f"Stopped (rc={rc})")

    def _stop(self):
        if self._process and self._running:
            self._process.terminate()
            self._running = False
            self._btn_stop.configure(state="disabled")
            self._btn_run.configure(state="normal")
            self._status_var.set("Stopped")

    def _tick(self):
        if not self._running:
            self._timer_var.set("")
            return
        el = time.time() - self._t0
        m, s = divmod(int(el), 60)
        h, m = divmod(m, 60)
        self._timer_var.set(f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}")
        self.after(500, self._tick)

    def _write(self, text, tag=""):
        self._out.configure(state="normal")
        if tag:
            self._out.insert("end", text, tag)
        else:
            self._out.insert("end", text)
        self._out.see("end")
        self._out.configure(state="disabled")

    def _append_line(self, line):
        cl = ansi(line)
        if not cl:
            self._write("\n")
            return
        lo = cl.lower()
        if "passed" in lo and "failed" not in lo:
            tag = "pass"
        elif "failed" in lo or "error" in lo:
            tag = "fail"
        elif "warning" in lo:
            tag = "warn"
        elif "skip" in lo:
            tag = "muted"
        elif cl.startswith("=") or cl.startswith("-"):
            tag = "hdr"
        else:
            tag = ""
        self._write(cl + "\n", tag)


# ─────────────────────────────────────────────────────────────────────────────
#  MANUAL CONTROL TAB
# ─────────────────────────────────────────────────────────────────────────────

CHANNELS = [
    ("EX_VALVE", C["orange"]), ("COMP_RELAY", C["purple"]),
    ("HEAT_MAIN", C["orange"]), ("HEAT_SML", C["yellow"]),
    ("FAN", C["teal"]), ("HOT_VLV", C["red"]),
    ("COLD_VLV", C["cyan"]), ("INLET_VLV", C["orange"]),
    ("AMB_VLV", C["green"]), ("BREATHER", C["pink"]),
]


class ManualTab(tk.Frame):

    POLL_MS = 600

    def __init__(self, master, pv_sim, **kw):
        super().__init__(master, bg=C["bg"], **kw)
        self._port_var = pv_sim
        self._conn = SimConn()
        self._polling = False
        self._poll_job = None
        self._elec = {k: tk.BooleanVar(value=True)
                      for k in ("LF", "LE", "SE", "TRAY", "COLD")}
        self._temps = {"T_tank": tk.DoubleVar(value=72.0),
                       "T_boost": tk.DoubleVar(value=72.0),
                       "CWT": tk.DoubleVar(value=20.0),
                       "Board": tk.DoubleVar(value=25.0)}
        self._flow = tk.DoubleVar(value=0.0)
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_conn_bar()
        self._build_inject()
        self._build_monitor()
        self._build_presets()

    def _section(self, parent, title):
        outer = tk.Frame(parent, bg=C["panel"], pady=4, padx=4)
        _lbl(outer, title, bg=C["panel"], fg=C["accent"],
             font_=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 3))
        inner = tk.Frame(outer, bg=C["card"], padx=8, pady=6)
        inner.pack(fill="both", expand=True)
        return outer, inner

    def _build_conn_bar(self):
        bar = tk.Frame(self, bg=C["panel"], pady=6, padx=12)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        _lbl(bar, "Terminal 1 — Simulator:", bg=C["panel"],
             fg=C["muted"]).pack(side="left")
        self._combo = ttk.Combobox(bar, textvariable=self._port_var,
                                   values=get_ports(), width=10,
                                   font=("Consolas", 10))
        self._combo.pack(side="left", padx=6)
        self._btn = _btn(bar, "Connect", self._toggle, bg=C["green"],
                         fg=C["btn_fg"], font=("Segoe UI", 9, "bold"),
                         padx=12, pady=2)
        self._btn.pack(side="left", padx=6)
        self._led = tk.Label(bar, text="●", fg=C["red"], bg=C["panel"],
                             font=("Segoe UI", 14))
        self._led.pack(side="left")
        self._st = _lbl(bar, "Disconnected", bg=C["panel"], fg=C["muted"])
        self._st.pack(side="left", padx=6)
        _btn(bar, "↻ Ports",
             lambda: self._combo.configure(values=get_ports()),
             bg=C["panel"], fg=C["muted"]).pack(side="right")

    def _build_inject(self):
        col = tk.Frame(self, bg=C["bg"])
        col.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=8)

        outer, tc = self._section(col, "Temperatures  (inject via DAC → HC ADC)")
        outer.pack(fill="x", pady=(0, 8))
        for label, key, lo, hi, fg in [
            ("T_tank  (HWT boiler)", "T_tank", 0, 130, C["orange"]),
            ("T_boost (HWT flange)", "T_boost", 0, 130, C["red"]),
            ("CWT     (cold tank)", "CWT", 0, 60, C["cyan"]),
            ("Board   (PCB)", "Board", 0, 100, C["muted"]),
        ]:
            self._temp_row(tc, label, key, lo, hi, fg)

        outer, ec = self._section(col, "Electrodes  (inject via BC547)")
        outer.pack(fill="x", pady=(0, 8))
        for name, desc, fg in [
            ("LF", "Float switch  P1-18", C["teal"]),
            ("LE", "Upper level   P1-11", C["green"]),
            ("SE", "Overflow safe P1-14", C["yellow"]),
            ("TRAY", "Drip tray     P1-17", C["purple"]),
            ("COLD", "Cold path     P3-1", C["cyan"]),
        ]:
            self._elec_row(ec, name, desc, fg)

        outer, fc = self._section(col, "Flow meter  (PWM via TIM2)")
        outer.pack(fill="x", pady=(0, 8))
        self._flow_row(fc)

    def _temp_row(self, parent, label, key, lo, hi, fg):
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", pady=2)
        row.columnconfigure(2, weight=1)
        _lbl(row, label, fg=fg, width=22, anchor="w").grid(
            row=0, column=0, padx=(0, 6))
        var = self._temps[key]
        spin = tk.Spinbox(row, from_=lo, to=hi, increment=0.5, textvariable=var,
                          width=7, font=("Consolas", 10), bg=C["dark"], fg=fg,
                          insertbackground=fg, buttonbackground=C["panel"],
                          relief="flat",
                          command=lambda k=key: self._send_temp(k))
        spin.grid(row=0, column=1, padx=4)
        spin.bind("<Return>", lambda e, k=key: self._send_temp(k))
        sl = tk.Scale(row, from_=lo, to=hi, resolution=0.5, variable=var,
                      orient="horizontal", bg=C["card"], fg=fg,
                      troughcolor=C["panel"], highlightthickness=0,
                      sliderrelief="flat", showvalue=False, length=180,
                      command=lambda v, k=key: self._send_temp(k))
        sl.grid(row=0, column=2, sticky="ew", padx=4)
        _lbl(row, "°C", fg=C["muted"], width=3).grid(row=0, column=3)

    def _elec_row(self, parent, name, desc, fg):
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", pady=2)
        _lbl(row, name, fg=fg, width=6,
             font_=("Segoe UI", 9, "bold")).pack(side="left")
        _lbl(row, desc, fg=C["muted"], width=20).pack(side="left", padx=4)
        btn = tk.Button(row, text="WET ●", font=("Segoe UI", 9, "bold"),
                        relief="flat", cursor="hand2", padx=10,
                        command=lambda n=name: self._toggle_elec(n))
        btn.pack(side="right", padx=4)
        self._elec[name]._btn = btn
        self._update_elec_btn(name)

    def _flow_row(self, parent):
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", pady=4)
        row.columnconfigure(2, weight=1)
        _lbl(row, "Flow rate", fg=C["cyan"], width=12).grid(
            row=0, column=0, padx=(0, 4))
        spin = tk.Spinbox(row, from_=0, to=2.5, increment=0.1,
                          textvariable=self._flow, width=6,
                          font=("Consolas", 11), bg=C["dark"], fg=C["cyan"],
                          insertbackground=C["cyan"], buttonbackground=C["panel"],
                          relief="flat", command=self._send_flow)
        spin.grid(row=0, column=1, padx=4)
        spin.bind("<Return>", lambda e: self._send_flow())
        sl = tk.Scale(row, from_=0, to=2.5, resolution=0.1, variable=self._flow,
                      orient="horizontal", bg=C["card"], fg=C["cyan"],
                      troughcolor=C["panel"], highlightthickness=0,
                      sliderrelief="flat", showvalue=False, length=160,
                      command=lambda v: self._send_flow())
        sl.grid(row=0, column=2, sticky="ew", padx=4)
        _lbl(row, "L/min", fg=C["muted"]).grid(row=0, column=3)
        _btn(row, "■ STOP", lambda: (self._flow.set(0.0), self._send_flow()),
             bg=C["red"], fg=C["btn_fg"], font=("Segoe UI", 9, "bold"),
             padx=10).grid(row=0, column=4, padx=6)

    def _build_monitor(self):
        col = tk.Frame(self, bg=C["bg"])
        col.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=8)
        outer, mc = self._section(col, "Live Output Monitor  (STATUS OUT)")
        outer.pack(fill="both", expand=True)
        hdr = tk.Frame(mc, bg=C["panel"])
        hdr.pack(fill="x", pady=(0, 4))
        for txt, w in [("Channel", 14), ("State", 8), ("Freq (Hz)", 10),
                       ("Duty %", 8), ("Spec", 6)]:
            _lbl(hdr, txt, fg=C["accent"], bg=C["panel"], width=w, anchor="w",
                 font_=("Segoe UI", 8, "bold")).pack(side="left")
        self._rows = {}
        for ch, fg in CHANNELS:
            self._rows[ch] = self._monitor_row(mc, ch, fg)
        self._last = tk.StringVar(value="Not connected")
        _lbl(mc, textvariable=self._last, fg=C["muted"], bg=C["card"],
             font_=("Segoe UI", 8)).pack(anchor="e", pady=(4, 0))

    def _monitor_row(self, parent, ch, fg):
        row = tk.Frame(parent, bg=C["card"])
        row.pack(fill="x", pady=1)
        led = tk.StringVar(value="●")
        lw = _lbl(row, textvariable=led, fg=C["muted"], bg=C["card"], width=2,
                  font_=("Segoe UI", 10))
        lw.pack(side="left")
        _lbl(row, ch, fg=fg, width=13, anchor="w",
             font_=("Consolas", 9, "bold")).pack(side="left")
        state = tk.StringVar(value="—")
        _lbl(row, textvariable=state, fg=C["text"], width=9, anchor="w",
             font_=("Consolas", 9)).pack(side="left")
        freq = tk.StringVar(value="—")
        _lbl(row, textvariable=freq, fg=C["cyan"], width=10, anchor="w",
             font_=("Consolas", 9)).pack(side="left")
        duty = tk.StringVar(value="—")
        _lbl(row, textvariable=duty, fg=C["yellow"], width=8, anchor="w",
             font_=("Consolas", 9)).pack(side="left")
        spec = tk.StringVar(value="")
        sl = _lbl(row, textvariable=spec, fg=C["green"], width=6, anchor="w",
                  font_=("Consolas", 9, "bold"))
        sl.pack(side="left")
        return {"led": lw, "led_var": led, "state": state, "freq": freq,
                "duty": duty, "spec": spec, "spec_lbl": sl}

    def _build_presets(self):
        bar = tk.Frame(self, bg=C["panel"], pady=8, padx=12)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        _lbl(bar, "Quick Presets:", bg=C["panel"], fg=C["muted"]).pack(
            side="left", padx=(0, 8))
        for label, bg, cmd in [
            ("IDLE", C["teal"], "PRESET IDLE"),
            ("FILL START", C["green"], "PRESET FILL_START"),
            ("FILL STOP", C["yellow"], "PRESET FILL_STOP"),
            ("HOT DISP", C["red"], "PRESET HOT_DISP"),
            ("COLD DISP", C["cyan"], "PRESET COLD_DISP"),
            ("AMB DISP", C["purple"], "PRESET AMB_DISP"),
            ("EXTRA HOT", C["orange"], "PRESET EXTRA_HOT"),
            ("SHABBAT", C["pink"], "PRESET SHABBAT"),
            ("RESET", C["muted"], "RESET"),
        ]:
            _btn(bar, label, lambda c=cmd: self._send(c), bg=bg, fg=C["btn_fg"],
                 font=("Segoe UI", 8, "bold"), padx=8, pady=4).pack(
                side="left", padx=2)

    # ── actions ──
    def _toggle(self):
        if self._conn.connected:
            self._stop_poll()
            self._conn.disconnect()
            self._led.configure(fg=C["red"])
            self._st.configure(text="Disconnected")
            self._btn.configure(text="Connect", bg=C["green"])
        else:
            port = self._port_var.get()
            if self._conn.connect(port):
                self._led.configure(fg=C["green"])
                self._st.configure(text=f"Connected  {port}")
                self._btn.configure(text="Disconnect", bg=C["red"])
                self._start_poll()
            else:
                messagebox.showerror("Connection failed", f"Cannot open {port}.")

    def _send(self, cmd):
        if not self._conn.connected:
            messagebox.showinfo("Not connected", "Connect first.")
            return ""
        return self._conn.send(cmd)

    def _send_temp(self, key):
        val = self._temps[key].get()
        hc = {"T_tank": "TANK", "T_boost": "BOOST", "CWT": "CWT",
              "Board": "BOARD"}[key]
        self._conn.send(f"TEMP {hc} {val:.1f}", wait_ms=120)

    def _toggle_elec(self, name):
        v = self._elec[name]
        v.set(not v.get())
        self._update_elec_btn(name)
        self._conn.send(f"ELEC {name} {0 if v.get() else 1}", wait_ms=120)

    def _update_elec_btn(self, name):
        v = self._elec[name]
        if v.get():
            v._btn.configure(text="WET ●", bg=C["cyan"], fg=C["btn_fg"])
        else:
            v._btn.configure(text="DRY ○", bg=C["muted"], fg=C["text"])

    def _send_flow(self):
        self._conn.send(f"FLOW {self._flow.get():.2f}", wait_ms=120)

    def _start_poll(self):
        self._polling = True
        self._poll()

    def _stop_poll(self):
        self._polling = False
        if self._poll_job:
            self.after_cancel(self._poll_job)
            self._poll_job = None

    def _poll(self):
        if not self._polling or not self._conn.connected:
            return
        threading.Thread(target=self._fetch, daemon=True).start()
        self._poll_job = self.after(self.POLL_MS, self._poll)

    def _fetch(self):
        raw = self._conn.send("STATUS OUT", wait_ms=400)
        if raw:
            self.after(0, self._update, raw)

    def _update(self, raw):
        self._last.set(f"Updated {time.strftime('%H:%M:%S')}")
        for ch, w in self._rows.items():
            self._update_ch(ch, w, raw)

    def _update_ch(self, ch, w, raw):
        m = re.search(rf'{re.escape(ch)}[^\n]*', raw, re.IGNORECASE)
        if not m:
            w["led_var"].set("○")
            w["led"].configure(fg=C["muted"])
            for k in ("state", "freq", "duty", "spec"):
                w[k].set("—" if k != "spec" else "")
            return
        line = m.group(0)
        state = "IDLE"
        for s in ("OPENING", "HOLDING", "CLOSED", "ON ", "OFF", "PWM"):
            if s in line.upper():
                state = s.strip()
                break
        w["state"].set(state)
        if state in ("OPENING",):
            w["led_var"].set("●")
            w["led"].configure(fg=C["yellow"])
        elif state in ("HOLDING", "ON", "PWM"):
            w["led_var"].set("●")
            w["led"].configure(fg=C["green"])
        else:
            w["led_var"].set("○")
            w["led"].configure(fg=C["muted"])
        mf = re.search(r'Freq=([\d.]+)Hz', line)
        w["freq"].set(f"{float(mf.group(1)):.1f}" if mf else "—")
        md = re.search(r'Duty=([\d.]+)%', line)
        w["duty"].set(f"{float(md.group(1)):.1f}" if md else "—")
        if "PASS" in line:
            w["spec"].set("✓")
            w["spec_lbl"].configure(fg=C["green"])
        elif "FAIL" in line:
            w["spec"].set("✗")
            w["spec_lbl"].configure(fg=C["red"])
        else:
            w["spec"].set("")


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN APP — 3 tabs
# ─────────────────────────────────────────────────────────────────────────────

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Tamar HC HIL — Unified Test Instrument")
        self.configure(bg=C["bg"])
        self.minsize(1060, 760)
        w, h = 1140, 820
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._pv_sim = tk.StringVar(value="COM3")
        self._pv_hc = tk.StringVar(value="COM4")
        self._pv_hmi = tk.StringVar(value="COM5")

        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=C["bg"], pady=10)
        hdr.pack(fill="x", padx=20)
        tk.Label(hdr, text="Tamar HC HIL — Test & Control",
                 font=("Segoe UI", 15, "bold"), bg=C["bg"],
                 fg=C["accent"]).pack(side="left")

        pb = tk.Frame(self, bg=C["panel"], pady=6, padx=14)
        pb.pack(fill="x")
        _lbl(pb, "Ports:", bg=C["panel"], fg=C["muted"]).pack(side="left")
        for label, var, col in [("SIM", self._pv_sim, C["accent"]),
                                ("HC", self._pv_hc, C["green"]),
                                ("HMI", self._pv_hmi, C["yellow"])]:
            _lbl(pb, label, bg=C["panel"], fg=col,
                 font_=("Segoe UI", 9, "bold")).pack(side="left", padx=(10, 2))
            ttk.Combobox(pb, textvariable=var, values=get_ports(), width=9,
                         font=("Consolas", 10)).pack(side="left")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=C["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=C["panel"],
                        foreground=C["muted"], padding=[16, 7],
                        font=("Segoe UI", 10))
        style.map("TNotebook.Tab", background=[("selected", C["card"])],
                  foreground=[("selected", C["accent"])])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=0, pady=0)

        # Tab 1 — Water Bar Tester (embedded from water_bar_tester.py)
        self._wbt_tab = tk.Frame(nb, bg="#1a1f2e")
        nb.add(self._wbt_tab, text="  Water Bar Tester  ")
        wbt.run_gui(parent=self._wbt_tab)

        # Tab 2 — Test Runner
        self._runner = RunnerTab(nb, self._pv_sim, self._pv_hc, self._pv_hmi)
        nb.add(self._runner, text="  Test Runner  ")

        # Tab 3 — Manual Control
        self._manual = ManualTab(nb, self._pv_sim)
        nb.add(self._manual, text="  Manual Control  ")


if __name__ == "__main__":
    App().mainloop()
