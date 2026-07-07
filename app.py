"""
app.py — Tamar HC · Unified Test Instrument (single window)

One window, one connection (HMI + HC + SIM), one test list.

Left  : unified, scrollable test checklist
          - Water Bar Tester checks (HMI / HC / Cross)  -> in-process engine
          - Tamar HIL groups (Smoke / Extra Hot / ...)   -> pytest
Right : control + monitor + output log
          - Manual Control (temperature / electrode / flow injection + presets)
          - WBT manual buttons (press 1-8) and manual command
          - Test parameters / Monitor parameters
          - Live Output Monitor (10 channels)
          - Output log (all test results stream here)
Bottom: RUN SELECTED / MONITOR / STOP + progress + timer

Run:  python app.py
"""

import os
import re
import sys
import time
import shutil
import threading
import subprocess
from datetime import datetime

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

FROZEN = getattr(sys, "frozen", False)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_DIR = os.path.dirname(sys.executable) if FROZEN else BASE_DIR
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ── reuse Water Bar Tester backend (engine only, no GUI) ─────────────────────
from core.hmi_serial import HmiSerial          # noqa: E402
from core.hydraulic_serial import HydraulicSerial  # noqa: E402
from core.hc_driver import HCDriver            # noqa: E402
from runner.runner import TestRunner, discover_tests  # noqa: E402
from water_bar_tester import _group_of, GROUP_ORDER   # noqa: E402
from core.version import get_version                  # noqa: E402

APP_VERSION = get_version()


# ─────────────────────────────────────────────────────────────────────────────
#  THEME
# ─────────────────────────────────────────────────────────────────────────────

C = dict(
    bg="#1a1f2e", panel="#242938", card="#2e3447", soft="#202637",
    text="#e0e6f0", muted="#7a8aaa", accent="#00bfff", accent2="#005f88",
    green="#22c55e", red="#ef4444", yellow="#f59e0b", cyan="#38bdf8",
    purple="#a78bfa", orange="#fb923c", teal="#2dd4bf", pink="#f472b6",
    dark="#0d1117", white="#ffffff", btnfg="#0d1117",
)
FM = ("Consolas", 10)
FB = ("Consolas", 11, "bold")
FH = ("Consolas", 14, "bold")
FS = ("Consolas", 9)


# ─────────────────────────────────────────────────────────────────────────────
#  TAMAR HIL TEST GROUPS (pytest)
# ─────────────────────────────────────────────────────────────────────────────

TEST_GROUPS = [
    {"id": "smoke", "label": "Smoke — Connection sanity",
     "file": "tamar_hil/test_smoke.py", "n": 21, "req": ["sim"]},
    {"id": "extra_hot", "label": "Extra Hot V6",
     "file": "tamar_hil/test_extra_hot_v6.py", "n": 12, "req": ["sim", "hc"]},
    {"id": "hot_fill", "label": "Hot Fill V5",
     "file": "tamar_hil/test_hot_fill_v5.py", "n": 13, "req": ["sim", "hc"]},
    {"id": "dispensing", "label": "Dispensing V01 (HC terminal)",
     "file": "tamar_hil/test_dispensing_v01.py", "n": 22, "req": ["sim", "hc"]},
    {"id": "dispensing_hmi", "label": "Dispensing via HMI (press 1-9)",
     "file": "tamar_hil/test_dispensing_hmi.py", "n": 15,
     "req": ["sim", "hc", "hmi"]},
    {"id": "idle", "label": "Idle V7 + Hysteresis",
     "file": "tamar_hil/test_idle_v7.py", "n": 15, "req": ["sim", "hc"]},
    {"id": "prepare_shabbat", "label": "Prepare to Shabbat V7 (HMI 9x10s)",
     "file": "tamar_hil/test_prepare_shabbat_v7.py", "n": 12,
     "req": ["sim", "hc", "hmi"]},
    {"id": "operation_shabbat", "label": "Operation Shabbat V6 (HMI 9x10s)",
     "file": "tamar_hil/test_operation_shabbat_v6.py", "n": 10,
     "req": ["sim", "hc", "hmi"]},
    {"id": "shabbat_hmi", "label": "Shabbat HMI — Entry + flow",
     "file": "tamar_hil/test_shabbat_hmi.py", "n": 16,
     "req": ["sim", "hc", "hmi"]},
    {"id": "cooling", "label": "Cooling V07",
     "file": "tamar_hil/test_cooling_v07.py", "n": 13, "req": ["sim", "hc"]},
    {"id": "washing", "label": "Washing HWT (Installation)",
     "file": "tamar_hil/test_washing_hwt.py", "n": 19, "req": ["sim", "hc"]},
]

CHANNELS = [
    ("EX_VALVE", C["orange"]), ("COMP_RELAY", C["purple"]),
    ("HEAT_MAIN", C["orange"]), ("HEAT_SML", C["yellow"]),
    ("FAN", C["teal"]), ("HOT_VLV", C["red"]),
    ("COLD_VLV", C["cyan"]), ("INLET_VLV", C["orange"]),
    ("AMB_VLV", C["green"]), ("BREATHER", C["pink"]),
]


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_ports():
    if HAS_SERIAL:
        return sorted(p.device for p in serial.tools.list_ports.comports())
    if sys.platform.startswith("win"):
        return [f"COM{i}" for i in range(1, 21)]
    return [f"/dev/ttyACM{i}" for i in range(6)]


def ansi(t):
    return re.sub(r'\x1b\[[0-9;]*[mA-Za-z]', '', t)


def real_python():
    if not FROZEN:
        return sys.executable
    for c in [os.path.join(RUN_DIR, "venv", "Scripts", "python.exe"),
              os.path.join(RUN_DIR, "venv", "bin", "python"),
              os.path.join(RUN_DIR, ".venv", "Scripts", "python.exe")]:
        if os.path.isfile(c):
            return c
    return shutil.which("python") or shutil.which("python3") or "python"


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

    def send(self, cmd, wait_ms=250):
        if not self.connected:
            return ""
        with self._lock:
            try:
                self._ser.reset_input_buffer()
                self._ser.write((cmd.strip() + "\r\n").encode())
                time.sleep(wait_ms / 1000.0)
                buf = []
                while self._ser.in_waiting:
                    ln = self._ser.readline().decode(errors="replace").rstrip()
                    if ln:
                        buf.append(ln)
                return "\n".join(buf)
            except Exception:
                return ""


# small widget helpers
def lbl(parent, text="", fg=None, bg=None, font=None, **kw):
    return tk.Label(parent, text=text, bg=bg or C["panel"], fg=fg or C["text"],
                    font=font or FM, **kw)


def btn(parent, text, cmd, bg=None, fg=None, font=None, **kw):
    return tk.Button(parent, text=text, command=cmd, bg=bg or C["card"],
                     fg=fg or C["accent"], relief="flat", cursor="hand2",
                     font=font or FM, **kw)


def _hover_scroll(canvas):
    """Scroll a canvas with the wheel only while the pointer is over it."""
    def _on(_e):
        canvas.bind_all(
            "<MouseWheel>",
            lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units"))
        canvas.bind_all("<Button-4>", lambda ev: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>", lambda ev: canvas.yview_scroll(1, "units"))

    def _off(_e):
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")
    canvas.bind("<Enter>", _on)
    canvas.bind("<Leave>", _off)


def section(parent, text):
    lbl(parent, text, fg=C["accent"], bg=parent["bg"], font=FB,
        anchor="w").pack(fill="x", padx=8, pady=(10, 1))
    tk.Frame(parent, bg=C["accent2"], height=1).pack(fill="x", padx=8)


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN APPLICATION
# ─────────────────────────────────────────────────────────────────────────────

class App(tk.Tk):

    POLL_MS = 700

    def __init__(self):
        super().__init__()
        self.title(f"Tamar HC — Unified Test Instrument  ({APP_VERSION})")
        self.configure(bg=C["bg"])
        self.minsize(1180, 800)
        w, h = 1320, 880
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")

        # ── backend state ──
        self.hmi_dev = None
        self.hydr_dev = None
        self.sim = SimConn()
        self.runner = None
        self._wbt_running = False
        self._proc = None
        self._proc_running = False
        self._polling = False
        self._poll_job = None
        self._t0 = 0.0
        self._log_buffer = []

        self.all_tests = discover_tests()

        # ── port + option vars ──
        self.pv_hmi = tk.StringVar(value="COM5")
        self.pv_hc = tk.StringVar(value="COM4")
        self.pv_sim = tk.StringVar(value="COM3")
        self.hydr_mode = tk.StringVar(value="HCDriver")
        self.profile = tk.StringVar(value="IL")
        self.use_hydr = tk.BooleanVar(value=True)

        # WBT params
        self.p_target = tk.StringVar(value="1")
        self.p_dur = tk.StringVar(value="1000")
        self.p_wait = tk.StringVar(value="40")
        self.p_tol = tk.StringVar(value="150")
        self.p_hotmin = tk.StringVar(value="85")
        self.p_coldmax = tk.StringVar(value="11")
        self.p_fmax = tk.StringVar(value="5000")
        self.p_cycles = tk.StringVar(value="17")
        self.p_pause = tk.StringVar(value="300")
        self.p_settle = tk.StringVar(value="60")
        # monitor params
        self.m_min = tk.StringVar(value="30")
        self.m_cyc = tk.StringVar(value="0")
        self.m_hmi = tk.StringVar(value="120")
        self.m_hc = tk.StringVar(value="60")
        self.m_pause = tk.StringVar(value="30")
        # shabbat / daily-cycle params
        self.sh_year = tk.StringVar(value=str(datetime.now().year))
        self.sh_count = tk.StringVar(value="1")      # 0 = all shabbats in year
        self.sh_wait = tk.StringVar(value="60")      # "wait a minute" between steps
        self.sh_daystep = tk.StringVar(value="2")    # 24h cycle step (hours)
        self.sh_enter_to = tk.StringVar(value="60")  # max wait for STATE: SHABBAT
        self.sh_exit_settle = tk.StringVar(value="180")  # pause at exit-1min (3min)
        # tamar run options
        self.opt_slow = tk.BooleanVar(value=False)
        self.opt_verbose = tk.BooleanVar(value=True)
        self.opt_x = tk.BooleanVar(value=False)

        # manual injection vars
        self.temps = {"T_tank": tk.DoubleVar(value=72.0),
                      "T_boost": tk.DoubleVar(value=72.0),
                      "CWT": tk.DoubleVar(value=20.0),
                      "Board": tk.DoubleVar(value=25.0)}
        self.elec = {k: tk.BooleanVar(value=True)
                     for k in ("LF", "LE", "SE", "TRAY", "COLD")}
        self.flow = tk.DoubleVar(value=0.0)

        self.sel_count = tk.StringVar(value="")
        self.timer_var = tk.StringVar(value="")
        self.test_vars = {}     # WBT test name -> BooleanVar
        self.group_vars = {}    # tamar group id -> BooleanVar
        self.mon_rows = {}

        self._build_style()
        self._build_header()
        self._build_connection()
        self._build_main()

        self._log("Unified Test Instrument ready.", C["accent"])
        self._log(f"Discovered {len(self.all_tests)} WBT tests + "
                  f"{sum(g['n'] for g in TEST_GROUPS)} Tamar HIL tests.", C["muted"])
        self._refresh_ports()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ════════════════════════════════════════════════════════════════════
    #  STYLE / HEADER
    # ════════════════════════════════════════════════════════════════════
    def _build_style(self):
        st = ttk.Style()
        try:
            st.theme_use("default")
        except Exception:
            pass
        st.configure("A.Horizontal.TProgressbar", troughcolor=C["card"],
                     background=C["accent"], thickness=5)

    def _build_header(self):
        h = tk.Frame(self, bg=C["panel"], pady=6)
        h.pack(fill="x")
        lbl(h, "TAMAR HC — UNIFIED TEST INSTRUMENT", fg=C["accent"],
            bg=C["panel"], font=FH).pack(side="left", padx=14)
        self.status_var = tk.StringVar(value="Not connected")
        self.status_lbl = lbl(h, "", fg=C["red"], bg=C["panel"], font=FM)
        self.status_lbl.configure(textvariable=self.status_var)
        self.status_lbl.pack(side="right", padx=14)

    # ════════════════════════════════════════════════════════════════════
    #  CONNECTION  (single panel, all 3 ports)
    # ════════════════════════════════════════════════════════════════════
    def _build_connection(self):
        bar = tk.Frame(self, bg=C["soft"], pady=7, padx=12)
        bar.pack(fill="x")

        lbl(bar, "Connection:", fg=C["muted"], bg=C["soft"]).pack(side="left")
        self.combos = {}
        for name, var, col in [("HMI", self.pv_hmi, C["accent"]),
                               ("HC", self.pv_hc, C["green"]),
                               ("SIM", self.pv_sim, C["yellow"])]:
            lbl(bar, name, fg=col, bg=C["soft"], font=FB).pack(
                side="left", padx=(12, 2))
            cb = ttk.Combobox(bar, textvariable=var, width=9, font=FM)
            cb.pack(side="left")
            self.combos[name] = cb
            led = lbl(bar, "●", fg=C["red"], bg=C["soft"], font=("Consolas", 12))
            led.pack(side="left", padx=(3, 0))
            setattr(self, f"_led_{name.lower()}", led)

        btn(bar, "Refresh", self._refresh_ports, bg=C["card"],
            fg=C["accent"], padx=6).pack(side="left", padx=(12, 2))
        self.btn_connect = btn(bar, "CONNECT", self._connect_all,
                               bg=C["accent2"], fg=C["white"], font=FB,
                               padx=14, pady=2)
        self.btn_connect.pack(side="left", padx=4)
        self.btn_disc = btn(bar, "DISCONNECT", self._disconnect_all,
                            bg="#444", fg=C["muted"], padx=8, pady=2,
                            state="disabled")
        self.btn_disc.pack(side="left")

        # hydraulic mode / profile / use-hydraulic
        lbl(bar, "Driver", fg=C["muted"], bg=C["soft"]).pack(
            side="left", padx=(16, 2))
        ttk.Combobox(bar, textvariable=self.hydr_mode,
                     values=["HCDriver", "HydraulicSerial"], width=14,
                     font=FM, state="readonly").pack(side="left")
        lbl(bar, "Profile", fg=C["muted"], bg=C["soft"]).pack(
            side="left", padx=(10, 2))
        ttk.Combobox(bar, textvariable=self.profile, values=["IL", "US"],
                     width=5, font=FM, state="readonly").pack(side="left")
        tk.Checkbutton(bar, text="Use Hydraulic in tests",
                       variable=self.use_hydr, bg=C["soft"], fg=C["text"],
                       selectcolor=C["card"], activebackground=C["soft"],
                       font=FM).pack(side="left", padx=10)

    # ════════════════════════════════════════════════════════════════════
    #  MAIN  (left list | right control+monitor / log)
    # ════════════════════════════════════════════════════════════════════
    def _build_main(self):
        outer = tk.PanedWindow(self, orient="horizontal", bg=C["bg"],
                               sashwidth=5, bd=0)
        outer.pack(fill="both", expand=True, padx=4, pady=4)

        left = tk.Frame(outer, bg=C["panel"], width=380)
        outer.add(left, minsize=320)
        self._build_test_list(left)

        right = tk.PanedWindow(outer, orient="vertical", bg=C["bg"],
                               sashwidth=5, bd=0)
        outer.add(right)

        top = tk.PanedWindow(right, orient="horizontal", bg=C["bg"],
                             sashwidth=5, bd=0)
        right.add(top, minsize=330)
        ctrl = tk.Frame(top, bg=C["panel"])
        top.add(ctrl, minsize=440)
        self._build_control(ctrl)
        mon = tk.Frame(top, bg=C["panel"], width=380)
        top.add(mon, minsize=330)
        self._build_monitor(mon)

        logf = tk.Frame(right, bg=C["panel"])
        right.add(logf, minsize=150)
        self._build_log(logf)

    # ── LEFT: unified test list ──────────────────────────────────────────
    def _build_test_list(self, parent):
        self._build_run_controls(parent)   # RUN / STOP / MONITOR above tests
        section(parent, "SELECT TESTS")
        bar = tk.Frame(parent, bg=C["panel"])
        bar.pack(fill="x", padx=8, pady=2)
        btn(bar, "All", self._select_all, bg=C["card"], padx=6).pack(side="left")
        btn(bar, "None", self._select_none, bg=C["card"], padx=6).pack(
            side="left", padx=4)
        lbl(bar, "", fg=C["muted"], bg=C["panel"]).pack(side="right")
        bar.winfo_children()[-1].configure(textvariable=self.sel_count)

        wrap = tk.Frame(parent, bg=C["panel"])
        wrap.pack(fill="both", expand=True, padx=4, pady=4)
        canvas = tk.Canvas(wrap, bg=C["panel"], highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=C["panel"])
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _hover_scroll(canvas)

        # WBT groups
        grouped = {}
        for name, cls in self.all_tests.items():
            g = _group_of(getattr(cls, "CATEGORY", "other"))
            grouped.setdefault(g, []).append(name)
        for gname in GROUP_ORDER:
            if gname in grouped:
                self._make_group(inner, f"WBT — {gname}",
                                 sorted(grouped[gname]), kind="wbt")
        # Tamar HIL group
        self._make_tamar_group(inner)
        self._update_sel_count()

    def _make_group(self, parent, title, names, kind):
        container = tk.Frame(parent, bg=C["panel"])
        container.pack(fill="x")
        header = tk.Frame(container, bg=C["card"])
        header.pack(fill="x", padx=6, pady=(6, 0))
        state = {"open": True}
        arrow = lbl(header, "▼", fg=C["accent"], bg=C["card"], width=2)
        arrow.pack(side="left")
        lbl(header, f"{title} ({len(names)})", fg=C["accent"], bg=C["card"],
            font=FB, anchor="w").pack(side="left", fill="x", expand=True)
        body = tk.Frame(container, bg=C["panel"])
        body.pack(fill="x", padx=6)
        for n in names:
            v = tk.BooleanVar(value=True)
            self.test_vars[n] = v
            tk.Checkbutton(body, text=n, variable=v, bg=C["panel"],
                           fg=C["text"], selectcolor=C["card"], font=FS,
                           activebackground=C["panel"], anchor="w",
                           command=self._update_sel_count).pack(fill="x")

        def toggle(_e=None):
            if state["open"]:
                body.pack_forget()
                arrow.configure(text="▶")
            else:
                body.pack(fill="x", padx=6)
                arrow.configure(text="▼")
            state["open"] = not state["open"]
        header.bind("<Button-1>", toggle)
        arrow.bind("<Button-1>", toggle)

    def _make_tamar_group(self, parent):
        total = sum(g["n"] for g in TEST_GROUPS)
        container = tk.Frame(parent, bg=C["panel"])
        container.pack(fill="x")
        header = tk.Frame(container, bg=C["card"])
        header.pack(fill="x", padx=6, pady=(6, 0))
        state = {"open": True}
        arrow = lbl(header, "▼", fg=C["yellow"], bg=C["card"], width=2)
        arrow.pack(side="left")
        lbl(header, f"Tamar HIL ({total})", fg=C["yellow"], bg=C["card"],
            font=FB, anchor="w").pack(side="left", fill="x", expand=True)
        body = tk.Frame(container, bg=C["panel"])
        body.pack(fill="x", padx=6)
        for g in TEST_GROUPS:
            v = tk.BooleanVar(value=False)
            self.group_vars[g["id"]] = v
            row = tk.Frame(body, bg=C["panel"])
            row.pack(fill="x")
            tk.Checkbutton(row, variable=v, bg=C["panel"], selectcolor=C["card"],
                           activebackground=C["panel"],
                           command=self._update_sel_count).pack(side="left")
            lbl(row, f"{g['label']}  ({g['n']})", fg=C["text"], bg=C["panel"],
                font=FS, anchor="w").pack(side="left", fill="x", expand=True)
            bc = {"sim": C["accent"], "hc": C["green"], "hmi": C["yellow"]}
            for r in g["req"]:
                lbl(row, r.upper(), fg=C["btnfg"], bg=bc[r],
                    font=("Consolas", 7, "bold")).pack(side="left", padx=1)

        def toggle(_e=None):
            if state["open"]:
                body.pack_forget()
                arrow.configure(text="▶")
            else:
                body.pack(fill="x", padx=6)
                arrow.configure(text="▼")
            state["open"] = not state["open"]
        header.bind("<Button-1>", toggle)
        arrow.bind("<Button-1>", toggle)

    def _select_all(self):
        for v in self.test_vars.values():
            v.set(True)
        for v in self.group_vars.values():
            v.set(True)
        self._update_sel_count()

    def _select_none(self):
        for v in self.test_vars.values():
            v.set(False)
        for v in self.group_vars.values():
            v.set(False)
        self._update_sel_count()

    def _update_sel_count(self):
        w = sum(1 for v in self.test_vars.values() if v.get())
        t = sum(g["n"] for g in TEST_GROUPS if self.group_vars[g["id"]].get())
        self.sel_count.set(f"{w} WBT + {t} HIL")

    # ── RIGHT TOP-LEFT: control column ───────────────────────────────────
    def _build_control(self, parent):
        canvas = tk.Canvas(parent, bg=C["panel"], highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        col = tk.Frame(canvas, bg=C["panel"])
        win = canvas.create_window((0, 0), window=col, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        col.bind("<Configure>",
                 lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _hover_scroll(canvas)

        # Manual Control — temperatures
        section(col, "MANUAL CONTROL — Temperatures (inject via DAC)")
        for label, key, lo, hi, fg in [
            ("T_tank (boiler)", "T_tank", 0, 130, C["orange"]),
            ("T_boost (flange)", "T_boost", 0, 130, C["red"]),
            ("CWT (cold)", "CWT", 0, 60, C["cyan"]),
            ("Board (PCB)", "Board", 0, 100, C["muted"]),
        ]:
            self._temp_row(col, label, key, lo, hi, fg)

        # Electrodes
        section(col, "Electrodes (inject via BC547)")
        for name, desc, fg in [
            ("LF", "Float P1-18", C["teal"]),
            ("LE", "Upper P1-11", C["green"]),
            ("SE", "Safe P1-14", C["yellow"]),
            ("TRAY", "Tray P1-17", C["purple"]),
            ("COLD", "Cold P3-1", C["cyan"]),
        ]:
            self._elec_row(col, name, desc, fg)

        # Flow
        section(col, "Flow meter (TIM2 PWM)")
        self._flow_row(col)

        # Presets
        section(col, "Quick Presets")
        pf = tk.Frame(col, bg=C["panel"])
        pf.pack(fill="x", padx=8, pady=2)
        presets = [("IDLE", C["teal"]), ("FILL_START", C["green"]),
                   ("FILL_STOP", C["yellow"]), ("HOT_DISP", C["red"]),
                   ("HOT_DISP_LOW", C["red"]), ("COLD_DISP", C["cyan"]),
                   ("COLD_DRY", C["cyan"]), ("AMB_DISP", C["purple"]),
                   ("EXTRA_HOT", C["orange"]), ("SHABBAT", C["pink"]),
                   ("RESET", C["muted"])]
        for i, (name, col_) in enumerate(presets):
            cmd = name if name != "RESET" else "RESET"
            b = btn(pf, name, lambda c=cmd: self._sim_send(
                f"PRESET {c}" if c != "RESET" else "RESET"),
                bg=col_, fg=C["btnfg"], font=("Consolas", 8, "bold"), padx=4)
            b.grid(row=i // 3, column=i % 3, padx=2, pady=2, sticky="ew")
        for cc in range(3):
            pf.columnconfigure(cc, weight=1)

        # WBT manual buttons
        section(col, "HMI Manual Buttons (press)")
        gf = tk.Frame(col, bg=C["panel"])
        gf.pack(fill="x", padx=8, pady=2)
        BTN_LAYOUT = [
            (1, "HOT GLASS", "#7f1d1d"), (2, "HOT JUG", "#991b1b"),
            (4, "COLD GLASS", "#1e3a5f"), (5, "COLD JUG", "#1d4ed8"),
            (6, "AMB GLASS", "#064e3b"), (7, "AMB JUG", "#065f46"),
            (3, "MENU", "#3b3b5c"), (8, "FILTERED", "#4a1d96"),
        ]
        for i, (bid, bname, bcol) in enumerate(BTN_LAYOUT):
            btn(gf, f"{bid}: {bname}",
                lambda _id=bid, _n=bname: self._manual_press(_id, _n),
                bg=bcol, fg=C["white"], font=FS, padx=4, pady=4).grid(
                row=i // 2, column=i % 2, padx=2, pady=2, sticky="ew")
        gf.columnconfigure(0, weight=1)
        gf.columnconfigure(1, weight=1)

        # Manual command
        section(col, "Manual Command")
        cr = tk.Frame(col, bg=C["panel"])
        cr.pack(fill="x", padx=8, pady=4)
        self.cmd_target = tk.StringVar(value="HMI")
        ttk.Combobox(cr, textvariable=self.cmd_target,
                     values=["HMI", "HC", "SIM"], width=6, font=FM,
                     state="readonly").pack(side="left", padx=(0, 4))
        self.cmd_var = tk.StringVar()
        ce = tk.Entry(cr, textvariable=self.cmd_var, font=FM, bg=C["card"],
                      fg=C["text"], insertbackground=C["accent"], relief="flat")
        ce.pack(side="left", expand=True, fill="x", padx=4)
        ce.bind("<Return>", lambda e: self._send_manual_cmd())
        btn(cr, "Send", self._send_manual_cmd, bg=C["card"], padx=8).pack(
            side="left")

        # Test parameters
        section(col, "Test Parameters (WBT)")
        for label, var in [("Target (L)", self.p_target),
                           ("Press dur (ms)", self.p_dur),
                           ("Pour wait (s)", self.p_wait),
                           ("Dispense settle (s)", self.p_settle),
                           ("Tolerance (ml)", self.p_tol),
                           ("Hot min (C)", self.p_hotmin),
                           ("Cold max (C)", self.p_coldmax),
                           ("Filter max (L)", self.p_fmax),
                           ("Long cycles", self.p_cycles),
                           ("Long pause (s)", self.p_pause)]:
            self._param_row(col, label, var)

        # Monitor parameters
        section(col, "Monitor Parameters (WBT)")
        for label, var in [("Run minutes (0=inf)", self.m_min),
                           ("Max cycles (0=inf)", self.m_cyc),
                           ("HMI poll (s)", self.m_hmi),
                           ("HC poll (s)", self.m_hc),
                           ("Pause (s)", self.m_pause)]:
            self._param_row(col, label, var)

        # Shabbat / daily-cycle parameters
        section(col, "Shabbat & Daily Cycle")
        # year selector (dropdown of available schedule years)
        try:
            from shabbat_schedules import SCHEDULES
            years = [str(y) for y in sorted(SCHEDULES.keys())]
        except Exception:
            years = [str(datetime.now().year)]
        yr = tk.Frame(col, bg=C["panel"])
        yr.pack(fill="x", padx=8, pady=1)
        lbl(yr, "Year", fg=C["muted"], bg=C["panel"], width=18,
            anchor="w").pack(side="left")
        ttk.Combobox(yr, textvariable=self.sh_year, values=years, width=8,
                     font=FM, state="readonly").pack(side="left")
        # count: 1 = one shabbat, 0 = whole year (run one after another)
        self._param_row(col, "Shabbats (0=all)", self.sh_count)
        self._param_row(col, "Enter timeout (s)", self.sh_enter_to)
        self._param_row(col, "Exit settle (s)", self.sh_exit_settle)
        self._param_row(col, "Step wait (s)", self.sh_wait)
        self._param_row(col, "Day step (h)", self.sh_daystep)
        lbl(col, "SHB-AUTO runs N Shabbats; DAY-24H runs a full day.",
            fg=C["muted"], bg=C["panel"], font=FS, anchor="w").pack(
            fill="x", padx=8, pady=(1, 4))

        # Tamar run options
        section(col, "Tamar HIL Run Options")
        of = tk.Frame(col, bg=C["panel"])
        of.pack(fill="x", padx=8, pady=2)
        for var, txt, fg in [(self.opt_slow, "Include @slow", C["yellow"]),
                             (self.opt_verbose, "Verbose -v", C["text"]),
                             (self.opt_x, "Stop on fail -x", C["red"])]:
            tk.Checkbutton(of, text=txt, variable=var, bg=C["panel"], fg=fg,
                           selectcolor=C["card"], activebackground=C["panel"],
                           font=FS).pack(anchor="w")

    def _param_row(self, parent, label, var):
        r = tk.Frame(parent, bg=C["panel"])
        r.pack(fill="x", padx=8, pady=1)
        lbl(r, label, fg=C["muted"], bg=C["panel"], width=18,
            anchor="w").pack(side="left")
        tk.Entry(r, textvariable=var, font=FM, bg=C["card"], fg=C["text"],
                 insertbackground=C["accent"], width=10, relief="flat").pack(
            side="left")

    def _temp_row(self, parent, label, key, lo, hi, fg):
        r = tk.Frame(parent, bg=C["panel"])
        r.pack(fill="x", padx=8, pady=1)
        lbl(r, label, fg=fg, bg=C["panel"], width=16, anchor="w").pack(
            side="left")
        var = self.temps[key]
        sp = tk.Spinbox(r, from_=lo, to=hi, increment=0.5, textvariable=var,
                        width=6, font=FM, bg=C["dark"], fg=fg,
                        insertbackground=fg, relief="flat",
                        command=lambda k=key: self._send_temp(k))
        sp.pack(side="left", padx=3)
        sp.bind("<Return>", lambda e, k=key: self._send_temp(k))
        tk.Scale(r, from_=lo, to=hi, resolution=0.5, variable=var,
                 orient="horizontal", bg=C["panel"], fg=fg,
                 troughcolor=C["card"], highlightthickness=0,
                 sliderrelief="flat", showvalue=False, length=150,
                 command=lambda v, k=key: self._send_temp(k)).pack(
            side="left", fill="x", expand=True, padx=3)

    def _elec_row(self, parent, name, desc, fg):
        r = tk.Frame(parent, bg=C["panel"])
        r.pack(fill="x", padx=8, pady=1)
        lbl(r, name, fg=fg, bg=C["panel"], width=5, font=FB,
            anchor="w").pack(side="left")
        lbl(r, desc, fg=C["muted"], bg=C["panel"], width=12,
            anchor="w").pack(side="left")
        b = tk.Button(r, text="WET", font=FS, relief="flat", cursor="hand2",
                      width=6, command=lambda n=name: self._toggle_elec(n))
        b.pack(side="right")
        self.elec[name]._btn = b
        self._paint_elec(name)

    def _flow_row(self, parent):
        r = tk.Frame(parent, bg=C["panel"])
        r.pack(fill="x", padx=8, pady=2)
        lbl(r, "Flow L/min", fg=C["cyan"], bg=C["panel"], width=10).pack(
            side="left")
        sp = tk.Spinbox(r, from_=0, to=2.5, increment=0.1, textvariable=self.flow,
                        width=6, font=FM, bg=C["dark"], fg=C["cyan"],
                        insertbackground=C["cyan"], relief="flat",
                        command=self._send_flow)
        sp.pack(side="left", padx=3)
        sp.bind("<Return>", lambda e: self._send_flow())
        tk.Scale(r, from_=0, to=2.5, resolution=0.1, variable=self.flow,
                 orient="horizontal", bg=C["panel"], fg=C["cyan"],
                 troughcolor=C["card"], highlightthickness=0,
                 sliderrelief="flat", showvalue=False, length=120,
                 command=lambda v: self._send_flow()).pack(
            side="left", fill="x", expand=True, padx=3)
        btn(r, "STOP", lambda: (self.flow.set(0.0), self._send_flow()),
            bg=C["red"], fg=C["btnfg"], font=FS, padx=6).pack(side="left")

    # ── RIGHT TOP-RIGHT: live monitor ────────────────────────────────────
    def _build_monitor(self, parent):
        section(parent, "LIVE OUTPUT MONITOR (STATUS OUT)")
        head = tk.Frame(parent, bg=C["card"])
        head.pack(fill="x", padx=8, pady=(2, 0))
        for t, w in [("Channel", 13), ("State", 9), ("Freq", 8),
                     ("Duty", 7), ("Spec", 5)]:
            lbl(head, t, fg=C["accent"], bg=C["card"], width=w, anchor="w",
                font=("Consolas", 8, "bold")).pack(side="left")
        body = tk.Frame(parent, bg=C["panel"])
        body.pack(fill="both", expand=True, padx=8)
        for ch, fg in CHANNELS:
            self.mon_rows[ch] = self._mon_row(body, ch, fg)
        self.mon_updated = tk.StringVar(value="not polling")
        lbl(parent, "", fg=C["muted"], bg=C["panel"], font=FS).pack(
            anchor="e", padx=8)
        lbl(parent, "", fg=C["muted"], bg=C["panel"]).pack()  # spacer

    def _mon_row(self, parent, ch, fg):
        r = tk.Frame(parent, bg=C["panel"])
        r.pack(fill="x", pady=1)
        led = lbl(r, "○", fg=C["muted"], bg=C["panel"], width=2,
                  font=("Consolas", 10))
        led.pack(side="left")
        lbl(r, ch, fg=fg, bg=C["panel"], width=12, anchor="w", font=FS).pack(
            side="left")
        sv = tk.StringVar(value="—")
        fv = tk.StringVar(value="—")
        dv = tk.StringVar(value="—")
        spv = tk.StringVar(value="")
        lbl(r, "", fg=C["text"], bg=C["panel"], width=9, anchor="w", font=FS,
            ).pack(side="left")
        # use textvariables
        r.winfo_children()[-1].configure(textvariable=sv)
        for var, col, w in [(fv, C["cyan"], 8), (dv, C["yellow"], 7)]:
            lab = lbl(r, "", fg=col, bg=C["panel"], width=w, anchor="w", font=FS)
            lab.configure(textvariable=var)
            lab.pack(side="left")
        spl = lbl(r, "", fg=C["green"], bg=C["panel"], width=5, anchor="w",
                  font=FS)
        spl.configure(textvariable=spv)
        spl.pack(side="left")
        return {"led": led, "state": sv, "freq": fv, "duty": dv,
                "spec": spv, "spec_lbl": spl}

    # ── RIGHT BOTTOM: log + terminal ─────────────────────────────────────
    def _build_log(self, parent):
        bar = tk.Frame(parent, bg=C["card"])
        bar.pack(fill="x")
        lbl(bar, "OUTPUT LOG / TERMINAL", fg=C["accent"], bg=C["card"],
            font=FB).pack(side="left", padx=8, pady=2)
        btn(bar, "Save", self._save_log, bg=C["card"], padx=8).pack(
            side="right", padx=2)
        btn(bar, "Clear", self._clear_log, bg=C["card"], padx=8).pack(
            side="right")
        btn(bar, "Open in window", self._open_log_window, bg=C["card"],
            padx=8).pack(side="right", padx=2)
        self.log_widget = scrolledtext.ScrolledText(
            parent, bg=C["dark"], fg=C["text"], font=FM, wrap="word",
            state="disabled", relief="flat", insertbackground=C["text"])
        self.log_widget.pack(fill="both", expand=True)
        for tag, col in [("pass", C["green"]), ("fail", C["red"]),
                         ("warn", C["yellow"]), ("muted", C["muted"]),
                         ("accent", C["accent"]), ("text", C["text"])]:
            self.log_widget.tag_configure(tag, foreground=col)

        # ── command line: [target] [entry .......] [Send] ──
        cmd_bar = tk.Frame(parent, bg=C["soft"])
        cmd_bar.pack(fill="x")
        self.term_target = tk.StringVar(value="HMI")
        ttk.Combobox(cmd_bar, textvariable=self.term_target,
                     values=["HMI", "HC", "SIM"], width=5, font=FM,
                     state="readonly").pack(side="left", padx=(6, 4), pady=4)
        self.term_entry = tk.Entry(cmd_bar, bg=C["dark"], fg=C["green"],
                                   font=FM, insertbackground=C["green"],
                                   relief="flat")
        self.term_entry.pack(side="left", fill="x", expand=True, padx=2, pady=4)
        self.term_entry.bind("<Return>", lambda e: self._term_send())
        self.term_entry.bind("<Up>", self._term_history_up)
        self.term_entry.bind("<Down>", self._term_history_down)
        btn(cmd_bar, "Send", self._term_send, bg=C["accent2"], fg=C["white"],
            font=FB, padx=12).pack(side="left", padx=4)

        # ── editable quick-command buttons ──
        self.quick_cmds = [
            {"label": "get_temp", "target": "HMI", "cmd": "get_temp"},
            {"label": "PTD?", "target": "HMI", "cmd": "get_param 124"},
            {"label": "press 1", "target": "HMI", "cmd": "press 1 1000"},
            {"label": "press 4", "target": "HMI", "cmd": "press 4 1000"},
            {"label": "HC temp", "target": "HC", "cmd": "get_temp"},
            {"label": "simulate=63", "target": "HC", "cmd": "simulate=63"},
            {"label": "HC outputs", "target": "HC", "cmd": "get_outputs"},
            {"label": "STATUS OUT", "target": "SIM", "cmd": "STATUS OUT"},
            {"label": "PRESET IDLE", "target": "SIM", "cmd": "PRESET IDLE"},
            {"label": "RESET", "target": "SIM", "cmd": "RESET"},
        ]
        self._term_history = []
        self._term_hist_idx = 0
        self.quick_bar = tk.Frame(parent, bg=C["soft"])
        self.quick_bar.pack(fill="x")
        lbl(self.quick_bar, "Quick (right-click to edit):", fg=C["muted"],
            bg=C["soft"], font=FS).pack(side="left", padx=(6, 4))
        self.quick_holder = tk.Frame(self.quick_bar, bg=C["soft"])
        self.quick_holder.pack(side="left", fill="x", expand=True)
        btn(self.quick_bar, "+ Add", self._quick_add, bg=C["card"],
            font=FS, padx=6).pack(side="right", padx=4)
        self._render_quick()
        self.log_window = None

    # ── terminal send / history ──
    def _term_send(self):
        cmd = self.term_entry.get().strip()
        if not cmd:
            return
        self._term_history.append(cmd)
        self._term_hist_idx = len(self._term_history)
        self.term_entry.delete(0, "end")
        self._send_to(self.term_target.get(), cmd)

    def _term_history_up(self, _e):
        if self._term_history and self._term_hist_idx > 0:
            self._term_hist_idx -= 1
            self.term_entry.delete(0, "end")
            self.term_entry.insert(0, self._term_history[self._term_hist_idx])
        return "break"

    def _term_history_down(self, _e):
        if self._term_hist_idx < len(self._term_history) - 1:
            self._term_hist_idx += 1
            self.term_entry.delete(0, "end")
            self.term_entry.insert(0, self._term_history[self._term_hist_idx])
        else:
            self.term_entry.delete(0, "end")
            self._term_hist_idx = len(self._term_history)
        return "break"

    # ── quick command buttons (editable, like a terminal) ──
    def _render_quick(self):
        for w in self.quick_holder.winfo_children():
            w.destroy()
        tcol = {"HMI": C["accent"], "HC": C["green"], "SIM": C["yellow"]}
        for i, q in enumerate(self.quick_cmds):
            b = tk.Button(self.quick_holder,
                          text=q["label"], font=FS, relief="flat",
                          cursor="hand2", padx=6, pady=2,
                          bg=C["card"], fg=tcol.get(q["target"], C["text"]),
                          command=lambda qq=q: self._send_to(qq["target"],
                                                             qq["cmd"]))
            b.grid(row=i // 5, column=i % 5, padx=2, pady=2, sticky="ew")
            b.bind("<Button-3>", lambda e, idx=i: self._quick_edit(idx))
        for c in range(5):
            self.quick_holder.columnconfigure(c, weight=1)

    def _quick_add(self):
        self.quick_cmds.append({"label": "new", "target": "HMI", "cmd": ""})
        self._render_quick()
        self._quick_edit(len(self.quick_cmds) - 1)

    def _quick_edit(self, idx):
        q = self.quick_cmds[idx]
        dlg = tk.Toplevel(self)
        dlg.title("Edit quick command")
        dlg.configure(bg=C["panel"])
        dlg.transient(self)
        dlg.grab_set()
        lbl(dlg, "Label", bg=C["panel"]).grid(row=0, column=0, sticky="e",
                                              padx=6, pady=4)
        e_label = tk.Entry(dlg, bg=C["dark"], fg=C["text"], font=FM)
        e_label.insert(0, q["label"])
        e_label.grid(row=0, column=1, padx=6, pady=4)
        lbl(dlg, "Target", bg=C["panel"]).grid(row=1, column=0, sticky="e",
                                               padx=6, pady=4)
        v_tgt = tk.StringVar(value=q["target"])
        ttk.Combobox(dlg, textvariable=v_tgt, values=["HMI", "HC", "SIM"],
                     width=6, state="readonly", font=FM).grid(
            row=1, column=1, sticky="w", padx=6, pady=4)
        lbl(dlg, "Command", bg=C["panel"]).grid(row=2, column=0, sticky="e",
                                                padx=6, pady=4)
        e_cmd = tk.Entry(dlg, bg=C["dark"], fg=C["green"], font=FM, width=28)
        e_cmd.insert(0, q["cmd"])
        e_cmd.grid(row=2, column=1, padx=6, pady=4)

        def save():
            q["label"] = e_label.get().strip() or "cmd"
            q["target"] = v_tgt.get()
            q["cmd"] = e_cmd.get().strip()
            self._render_quick()
            dlg.destroy()

        def delete():
            self.quick_cmds.pop(idx)
            self._render_quick()
            dlg.destroy()
        bf = tk.Frame(dlg, bg=C["panel"])
        bf.grid(row=3, column=0, columnspan=2, pady=8)
        btn(bf, "Save", save, bg=C["accent2"], fg=C["white"], padx=12).pack(
            side="left", padx=4)
        btn(bf, "Delete", delete, bg="#7f1d1d", fg="#fca5a5", padx=12).pack(
            side="left", padx=4)

    def _open_log_window(self):
        if self.log_window and tk.Toplevel.winfo_exists(self.log_window):
            self.log_window.lift()
            return
        win = tk.Toplevel(self)
        win.title("Output Log")
        win.configure(bg=C["dark"])
        win.geometry("900x600")
        txt = scrolledtext.ScrolledText(win, bg=C["dark"], fg=C["text"],
                                        font=FM, wrap="word", relief="flat")
        txt.pack(fill="both", expand=True)
        txt.insert("end", "\n".join(self._log_buffer) + "\n")
        txt.see("end")
        self.log_window = win
        self.log_window_txt = txt

    # ── BOTTOM run bar ───────────────────────────────────────────────────
    def _build_run_controls(self, parent):
        wrap = tk.Frame(parent, bg=C["soft"], pady=6, padx=6)
        wrap.pack(fill="x", padx=4, pady=(6, 0))
        row = tk.Frame(wrap, bg=C["soft"])
        row.pack(fill="x")
        self.btn_run = tk.Button(row, text="▶ RUN TESTS",
                                 command=self._run_selected, bg=C["accent2"],
                                 fg=C["white"], font=FB, relief="flat",
                                 padx=10, pady=5, state="disabled")
        self.btn_run.pack(side="left", padx=(0, 4))
        self.btn_stop = tk.Button(row, text="■ STOP", command=self._stop,
                                  bg="#7f1d1d", fg="#fca5a5", font=FB,
                                  relief="flat", padx=10, pady=5,
                                  state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        self.btn_monitor = tk.Button(row, text="MONITOR",
                                     command=self._run_monitor, bg="#1d4ed8",
                                     fg=C["white"], font=FB, relief="flat",
                                     padx=10, pady=5, state="disabled")
        self.btn_monitor.pack(side="left", padx=4)
        lbl(row, "", fg=C["accent"], bg=C["soft"],
            font=("Consolas", 11)).pack(side="right")
        row.winfo_children()[-1].configure(textvariable=self.timer_var)
        self.progress = ttk.Progressbar(wrap, mode="indeterminate",
                                        style="A.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(4, 0))

    # ════════════════════════════════════════════════════════════════════
    #  LOGGING
    # ════════════════════════════════════════════════════════════════════
    def _log(self, msg, color=None):
        tag = {"#22c55e": "pass", "#ef4444": "fail", "#f59e0b": "warn",
               "#7a8aaa": "muted", "#00bfff": "accent"}.get(color, "text")
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self._log_buffer.append(line)
        try:
            self.log_widget.configure(state="normal")
            self.log_widget.insert("end", line + "\n", tag)
            self.log_widget.see("end")
            self.log_widget.configure(state="disabled")
        except Exception:
            pass
        self._mirror(line)

    def _log_raw(self, text, tag="text"):
        try:
            self.log_widget.configure(state="normal")
            self.log_widget.insert("end", text + "\n", tag)
            self.log_widget.see("end")
            self.log_widget.configure(state="disabled")
        except Exception:
            pass
        self._log_buffer.append(text)
        self._mirror(text)

    def _mirror(self, line):
        win = getattr(self, "log_window", None)
        if win is not None:
            try:
                if tk.Toplevel.winfo_exists(win):
                    self.log_window_txt.insert("end", line + "\n")
                    self.log_window_txt.see("end")
                else:
                    self.log_window = None
            except Exception:
                self.log_window = None

    def _clear_log(self):
        self._log_buffer.clear()
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")

    def _save_log(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Text", "*.txt")],
            initialfile=f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write("\n".join(self._log_buffer))
            self._log(f"Saved: {p}", C["accent"])

    # ════════════════════════════════════════════════════════════════════
    #  PORTS / CONNECTION
    # ════════════════════════════════════════════════════════════════════
    def _refresh_ports(self):
        ports = get_ports()
        for cb in self.combos.values():
            cb["values"] = ports

    def _connect_all(self):
        # HMI (required for WBT + Tamar HMI tests)
        hmi_port = self.pv_hmi.get().strip()
        hc_port = self.pv_hc.get().strip()
        sim_port = self.pv_sim.get().strip()
        ok_any = False
        if hmi_port:
            try:
                self.hmi_dev = HmiSerial(hmi_port, 115200, log_callback=self._log)
                self.hmi_dev.connect()
                self._led_hmi.configure(fg=C["green"])
                ok_any = True
            except Exception as e:
                self._log(f"[ERROR] HMI: {e}", C["red"])
        if hc_port:
            try:
                if self.hydr_mode.get() == "HCDriver":
                    self.hydr_dev = HCDriver(hc_port, 115200, log_callback=self._log)
                else:
                    self.hydr_dev = HydraulicSerial(hc_port, 115200,
                                                    log_callback=self._log)
                self.hydr_dev.connect()
                self._led_hc.configure(fg=C["green"])
                ok_any = True
            except Exception as e:
                self._log(f"[ERROR] HC: {e}", C["red"])
        if sim_port:
            if self.sim.connect(sim_port):
                self._led_sim.configure(fg=C["green"])
                ok_any = True
                self._start_poll()
            else:
                self._log(f"[ERROR] SIM: cannot open {sim_port}", C["red"])
        if ok_any:
            self.status_var.set("Connected")
            self.status_lbl.configure(fg=C["green"])
            self.btn_connect.configure(state="disabled")
            self.btn_disc.configure(state="normal")
            self.btn_run.configure(state="normal")
            self.btn_monitor.configure(state="normal")

    def _disconnect_all(self):
        self._stop_poll()
        if self.hmi_dev:
            try:
                self.hmi_dev.disconnect()
            except Exception:
                pass
            self.hmi_dev = None
        if self.hydr_dev:
            try:
                self.hydr_dev.disconnect()
            except Exception:
                pass
            self.hydr_dev = None
        self.sim.disconnect()
        for n in ("hmi", "hc", "sim"):
            getattr(self, f"_led_{n}").configure(fg=C["red"])
        self.status_var.set("Not connected")
        self.status_lbl.configure(fg=C["red"])
        self.btn_connect.configure(state="normal")
        self.btn_disc.configure(state="disabled")
        self.btn_run.configure(state="disabled")
        self.btn_monitor.configure(state="disabled")

    def _release_for_pytest(self):
        """Close GUI-held serial ports so pytest can open them."""
        self._stop_poll()
        if self.hmi_dev:
            try:
                self.hmi_dev.disconnect()
            except Exception:
                pass
        if self.hydr_dev:
            try:
                self.hydr_dev.disconnect()
            except Exception:
                pass
        self.sim.disconnect()

    def _reacquire_after_pytest(self):
        """Re-open the GUI connections after a pytest run finishes."""
        self.after(800, self._connect_all_quiet)

    def _connect_all_quiet(self):
        if self.pv_hmi.get().strip():
            try:
                self.hmi_dev = HmiSerial(self.pv_hmi.get().strip(), 115200,
                                         log_callback=self._log)
                self.hmi_dev.connect()
                self._led_hmi.configure(fg=C["green"])
            except Exception:
                self._led_hmi.configure(fg=C["red"])
        if self.pv_hc.get().strip():
            try:
                if self.hydr_mode.get() == "HCDriver":
                    self.hydr_dev = HCDriver(self.pv_hc.get().strip(), 115200,
                                             log_callback=self._log)
                else:
                    self.hydr_dev = HydraulicSerial(self.pv_hc.get().strip(),
                                                    115200, log_callback=self._log)
                self.hydr_dev.connect()
                self._led_hc.configure(fg=C["green"])
            except Exception:
                self._led_hc.configure(fg=C["red"])
        if self.pv_sim.get().strip() and self.sim.connect(self.pv_sim.get().strip()):
            self._led_sim.configure(fg=C["green"])
            self._start_poll()

    # ════════════════════════════════════════════════════════════════════
    #  MANUAL CONTROL (simulator)
    # ════════════════════════════════════════════════════════════════════
    def _send_to(self, target, cmd):
        """Unified command send. Uses the correct method per device:
        HMI -> send_command (CRLF), HC(HCDriver) -> hc_cmd (bare CR!),
        HC(HydraulicSerial) -> send_command, SIM -> SimConn.send."""
        if not cmd:
            return
        if target == "SIM":
            if not self.sim.connected:
                self._log("[SIM] not connected.", C["red"])
                return
            self._log(f"[SIM] > {cmd}", C["accent"])

            def _ts():
                resp = self.sim.send(cmd)
                self.after(0, lambda: self._log(f"  {resp or '(no reply)'}",
                                                C["muted"]))
            threading.Thread(target=_ts, daemon=True).start()
            return
        if target == "HMI":
            dev = self.hmi_dev
        else:
            dev = self.hydr_dev
        if dev is None or (hasattr(dev, "is_connected")
                           and not dev.is_connected()):
            self._log(f"[{target}] not connected.", C["red"])
            return
        self._log(f"[{target}] > {cmd}", C["accent"])

        def _t():
            try:
                if target == "HC" and isinstance(dev, HCDriver):
                    resp = dev.hc_cmd(cmd)          # bare CR — firmware needs it
                else:
                    resp = dev.send_command(cmd)    # HMI / HydraulicSerial
            except Exception as exc:
                resp = f"ERROR: {exc}"
            self.after(0, lambda r=resp: self._log(f"  {r or '(no reply)'}",
                                                   C["muted"]))
        threading.Thread(target=_t, daemon=True).start()

    def _sim_send(self, cmd):
        self._send_to("SIM", cmd)
        return ""

    def _send_temp(self, key):
        if not self.sim.connected:
            return
        hc = {"T_tank": "TANK", "T_boost": "BOOST", "CWT": "CWT",
              "Board": "BOARD"}[key]
        self.sim.send(f"TEMP {hc} {self.temps[key].get():.1f}", wait_ms=120)

    def _toggle_elec(self, name):
        v = self.elec[name]
        v.set(not v.get())
        self._paint_elec(name)
        # Firmware convention (cmd_parser.c): 0 = WET, 1 = DRY
        if self.sim.connected:
            self.sim.send(f"ELEC {name} {0 if v.get() else 1}", wait_ms=120)
        else:
            self._log("[SIM] not connected (electrode not sent).", C["yellow"])

    def _paint_elec(self, name):
        v = self.elec[name]
        if v.get():
            v._btn.configure(text="WET", bg=C["cyan"], fg=C["btnfg"])
        else:
            v._btn.configure(text="DRY", bg=C["muted"], fg=C["text"])

    def _send_flow(self):
        if self.sim.connected:
            self.sim.send(f"FLOW {self.flow.get():.2f}", wait_ms=120)

    def _manual_press(self, bid, bname):
        if self.hmi_dev is None or not self.hmi_dev.is_connected():
            self._log("[ERROR] HMI not connected.", C["red"])
            return
        dur = int(self.p_dur.get() or 1000)
        self._log(f"[HMI] > press {bid} {dur} ({bname})", C["accent"])

        def _t():
            try:
                resp = self.hmi_dev.press(bid, dur)
            except Exception as exc:
                resp = f"ERROR: {exc}"
            self.after(0, lambda r=resp: self._log(f"  {r or '(no reply)'}",
                                                   C["muted"]))
        threading.Thread(target=_t, daemon=True).start()

    def _send_manual_cmd(self):
        cmd = self.cmd_var.get().strip()
        if not cmd:
            return
        self._send_to(self.cmd_target.get(), cmd)

    # ════════════════════════════════════════════════════════════════════
    #  LIVE MONITOR POLLING
    # ════════════════════════════════════════════════════════════════════
    def _start_poll(self):
        self._polling = True
        self._poll()

    def _stop_poll(self):
        self._polling = False
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None

    def _poll(self):
        if not self._polling or not self.sim.connected:
            return
        if not self._proc_running:
            threading.Thread(target=self._fetch_status, daemon=True).start()
        self._poll_job = self.after(self.POLL_MS, self._poll)

    def _fetch_status(self):
        raw = self.sim.send("STATUS OUT", wait_ms=350)
        if raw:
            self.after(0, self._apply_status, raw)

    def _apply_status(self, raw):
        for ch, w in self.mon_rows.items():
            self._apply_ch(ch, w, raw)

    def _apply_ch(self, ch, w, raw):
        m = re.search(rf'{re.escape(ch)}[^\n]*', raw, re.IGNORECASE)
        if not m:
            w["led"].configure(fg=C["muted"])
            w["state"].set("—")
            w["freq"].set("—")
            w["duty"].set("—")
            w["spec"].set("")
            return
        line = m.group(0)
        state = "IDLE"
        for s in ("OPENING", "HOLDING", "CLOSED", "PWM", "ON", "OFF"):
            if s in line.upper():
                state = s
                break
        w["state"].set(state)
        if state == "OPENING":
            w["led"].configure(fg=C["yellow"])
        elif state in ("HOLDING", "ON", "PWM"):
            w["led"].configure(fg=C["green"])
        else:
            w["led"].configure(fg=C["muted"])
        mf = re.search(r'Freq=([\d.]+)', line)
        w["freq"].set(f"{float(mf.group(1)):.1f}" if mf else "—")
        md = re.search(r'Duty=([\d.]+)', line)
        w["duty"].set(f"{float(md.group(1)):.1f}" if md else "—")
        if "PASS" in line.upper():
            w["spec"].set("✓")
            w["spec_lbl"].configure(fg=C["green"])
        elif "FAIL" in line.upper():
            w["spec"].set("✗")
            w["spec_lbl"].configure(fg=C["red"])
        else:
            w["spec"].set("")

    # ════════════════════════════════════════════════════════════════════
    #  RUN  (WBT in-process  +  Tamar HIL via pytest)
    # ════════════════════════════════════════════════════════════════════
    def _get_config(self):
        return {
            "hmi_port": self.pv_hmi.get(),
            "hydraulic_port": self.pv_hc.get(),
            "hc_profile": self.profile.get(),
            "target_liters": float(self.p_target.get() or 1),
            "press_duration_ms": int(self.p_dur.get() or 1000),
            "pour_wait_sec": float(self.p_wait.get() or 40),
            "tolerance_ml": float(self.p_tol.get() or 150),
            "hot_min_temp": float(self.p_hotmin.get() or 85),
            "cold_max_temp": float(self.p_coldmax.get() or 11),
            "filter_max_liters": float(self.p_fmax.get() or 5000),
            "long_term_cycles": int(self.p_cycles.get() or 17),
            "long_term_pause_sec": int(self.p_pause.get() or 300),
            "dispense_settle_sec": float(self.p_settle.get() or 60),
            "use_hydraulic": self.use_hydr.get(),
            "monitor_minutes": float(self.m_min.get() or 30),
            "monitor_cycles": int(self.m_cyc.get() or 0),
            "monitor_hmi_period": float(self.m_hmi.get() or 120),
            "monitor_hc_period": float(self.m_hc.get() or 60),
            "monitor_pause": float(self.m_pause.get() or 30),
            "shabbat_year": int(self.sh_year.get() or datetime.now().year),
            "shabbat_count": int(self.sh_count.get() or 1),
            "stage_wait_sec": float(self.sh_wait.get() or 3),
            "day_step_hours": int(self.sh_daystep.get() or 2),
            "shabbat_enter_timeout_sec": float(self.sh_enter_to.get() or 60),
            "shabbat_exit_settle_sec": float(self.sh_exit_settle.get() or 180),
        }

    def _selected_wbt(self):
        return [n for n, v in self.test_vars.items() if v.get()]

    def _selected_tamar(self):
        return [g for g in TEST_GROUPS if self.group_vars[g["id"]].get()]

    def _run_selected(self):
        wbt = self._selected_wbt()
        tamar = self._selected_tamar()
        if not wbt and not tamar:
            messagebox.showwarning("Nothing selected",
                                   "Select at least one test.")
            return
        self.btn_run.configure(state="disabled")
        self.btn_monitor.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress.start(10)
        self._t0 = time.time()
        self._tick()
        self._log("=" * 56, C["muted"])
        self._log(f"RUN: {len(wbt)} WBT + "
                  f"{sum(g['n'] for g in tamar)} Tamar HIL", C["accent"])
        threading.Thread(target=self._run_sequence, args=(wbt, tamar),
                         daemon=True).start()

    def _run_sequence(self, wbt, tamar):
        # 1) WBT in-process (uses already-open hmi/hc)
        if wbt:
            if self.hmi_dev is None or not self.hmi_dev.is_connected():
                self.after(0, lambda: self._log(
                    "[SKIP] WBT tests need HMI connected.", C["yellow"]))
            else:
                self.after(0, lambda: self._log(
                    f"--- Water Bar Tester: {len(wbt)} tests ---", C["accent"]))
                try:
                    self.runner = TestRunner(self.hmi_dev, self.hydr_dev,
                                             self._get_config(),
                                             log_callback=self._log_thread)
                    results = self.runner.run(wbt)
                    rep = self.runner.generate_report()
                    self.after(0, self._save_report, rep, results)
                except Exception as exc:
                    self.after(0, lambda m=str(exc): self._log(f"[FATAL] {m}", C["red"]))

        # 2) Tamar HIL via pytest (needs ports released)
        if tamar:
            if not self.pv_sim.get().strip():
                self.after(0, lambda: self._log(
                    "[SKIP] Tamar HIL needs the Simulator (SIM) port. "
                    "Set SIM and connect the Nucleo, then run again.",
                    C["yellow"]))
            else:
                self.after(0, lambda: self._log(
                    f"--- Tamar HIL: {sum(g['n'] for g in tamar)} tests ---",
                    C["accent"]))
                self.after(0, self._release_for_pytest)
                time.sleep(1.0)
                self._run_pytest(tamar)
                self.after(0, self._reacquire_after_pytest)

        self.after(0, self._run_done)

    def _log_thread(self, msg, color=None):
        # TestRunner calls this from a worker thread
        self.after(0, lambda: self._log(msg, color))

    def _save_report(self, report, results):
        for line in report.splitlines():
            tag = "pass" if "✓" in line else ("fail" if "✗" in line else "text")
            self._log_raw(line, tag)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(RUN_DIR, "reports", f"report_{ts}.txt")
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(report + "\n\n--- LOG ---\n\n")
                f.write("\n".join(self._log_buffer))
            self._log(f"Report -> {out}", C["accent"])
        except Exception as e:
            self._log(f"[WARN] report save failed: {e}", C["yellow"])
        # regression: compare against the previous baseline, then update it
        try:
            self._regression_compare(results)
            self._save_baseline(results)
        except Exception as e:
            self._log(f"[WARN] regression step failed: {e}", C["yellow"])

    def _baseline_path(self):
        return os.path.join(RUN_DIR, "reports", "baseline.json")

    def _save_baseline(self, results):
        import json
        data = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "results": {r.test_name: bool(r.passed) for r in results}}
        os.makedirs(os.path.dirname(self._baseline_path()), exist_ok=True)
        with open(self._baseline_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _regression_compare(self, results):
        """Compare this run with the saved baseline and report changes."""
        import json
        path = self._baseline_path()
        if not os.path.isfile(path):
            self._log("[REGRESSION] No baseline yet — this run becomes the "
                      "baseline.", C["muted"])
            return
        with open(path, encoding="utf-8") as f:
            base = json.load(f)
        prev = base.get("results", {})
        now = {r.test_name: bool(r.passed) for r in results}

        regressed, fixed, new = [], [], []
        for name, ok in now.items():
            if name not in prev:
                new.append(name)
            elif prev[name] and not ok:
                regressed.append(name)        # was PASS, now FAIL
            elif not prev[name] and ok:
                fixed.append(name)            # was FAIL, now PASS
        removed = [n for n in prev if n not in now]

        self._log("=" * 56, C["muted"])
        self._log(f"[REGRESSION] vs baseline ({base.get('timestamp', '?')})",
                  C["accent"])
        if regressed:
            self._log(f"  REGRESSED (was PASS, now FAIL): {len(regressed)}",
                      C["red"])
            for n in regressed:
                self._log(f"    ✗ {n}", C["red"])
        if fixed:
            self._log(f"  FIXED (was FAIL, now PASS): {len(fixed)}", C["green"])
            for n in fixed:
                self._log(f"    ✓ {n}", C["green"])
        if new:
            self._log(f"  NEW tests: {len(new)}", C["muted"])
        if removed:
            self._log(f"  REMOVED tests: {len(removed)}", C["muted"])
        if not (regressed or fixed or new or removed):
            self._log("  No changes vs baseline — stable.", C["green"])

    def _build_pytest_cmd(self, groups):
        cmd = [real_python(), "-m", "pytest"] + [g["file"] for g in groups]
        if self.pv_sim.get().strip():
            cmd += [f"--port-sim={self.pv_sim.get().strip()}"]
        if any("hc" in g["req"] for g in groups) and self.pv_hc.get().strip():
            cmd += [f"--port-hc={self.pv_hc.get().strip()}"]
        if any("hmi" in g["req"] for g in groups) and self.pv_hmi.get().strip():
            cmd += [f"--port-hmi={self.pv_hmi.get().strip()}"]
        if not self.opt_slow.get():
            cmd += ["-m", "not slow"]
        if self.opt_verbose.get():
            cmd += ["-v"]
        if self.opt_x.get():
            cmd += ["-x"]
        cmd += ["--tb=short", "--no-header"]
        return cmd

    def _run_pytest(self, groups):
        cmd = self._build_pytest_cmd(groups)
        self._proc_running = True
        try:
            self._proc = subprocess.Popen(
                cmd, cwd=RUN_DIR, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                encoding="utf-8", errors="replace")
            for line in self._proc.stdout:
                self.after(0, self._log_pytest, line.rstrip())
            self._proc.wait()
        except Exception as exc:
            self.after(0, lambda m=str(exc): self._log(f"[ERROR] pytest: {m}", C["red"]))
        self._proc_running = False

    def _log_pytest(self, line):
        cl = ansi(line)
        if not cl:
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
        else:
            tag = "text"
        self._log_raw(cl, tag)

    def _run_monitor(self):
        if self.hmi_dev is None or not self.hmi_dev.is_connected():
            messagebox.showwarning("Not connected", "Connect HMI first.")
            return
        monitor_name = None
        for name, cls in self.all_tests.items():
            if getattr(cls, "CATEGORY", "") == "monitor":
                monitor_name = name
                break
        if monitor_name is None:
            self._log("[ERROR] Monitor test not found.", C["red"])
            return
        self.btn_run.configure(state="disabled")
        self.btn_monitor.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress.start(10)
        self._t0 = time.time()
        self._tick()
        self._log("Starting MONITOR run... (STOP to finish)", C["accent"])

        def _t():
            try:
                self.runner = TestRunner(self.hmi_dev, self.hydr_dev,
                                         self._get_config(),
                                         log_callback=self._log_thread)
                results = self.runner.run([monitor_name])
                rep = self.runner.generate_report()
                self.after(0, self._save_report, rep, results)
            except Exception as exc:
                self.after(0, lambda m=str(exc): self._log(f"[FATAL] {m}", C["red"]))
            self.after(0, self._run_done)
        threading.Thread(target=_t, daemon=True).start()

    def _run_done(self):
        el = int(time.time() - self._t0)
        m, s = divmod(el, 60)
        self.progress.stop()
        self.btn_stop.configure(state="disabled")
        ok = self.hmi_dev is not None or self.sim.connected
        self.btn_run.configure(state="normal" if ok else "disabled")
        self.btn_monitor.configure(state="normal" if ok else "disabled")
        self._log("=" * 56, C["muted"])
        self._log(f"DONE  ({m:02d}:{s:02d})", C["accent"])
        self.timer_var.set("")

    def _stop(self):
        if self.runner:
            self.runner.stop()
            self._log("[USER] WBT stop requested.", C["yellow"])
        if self._proc and self._proc_running:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._log("[USER] pytest stopped.", C["yellow"])

    def _tick(self):
        if self.btn_stop["state"] == "disabled":
            self.timer_var.set("")
            return
        el = int(time.time() - self._t0)
        m, s = divmod(el, 60)
        h, m = divmod(m, 60)
        self.timer_var.set(f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}")
        self.after(500, self._tick)

    def _on_close(self):
        try:
            self._stop_poll()
            self._disconnect_all()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()