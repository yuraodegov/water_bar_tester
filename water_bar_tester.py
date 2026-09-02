"""
water_bar_tester.py — main GUI + CLI application.

GUI:  python water_bar_tester.py
CLI:  python water_bar_tester.py --cli --hmi-port COM5 --liters 50
"""
import sys
import os
import argparse
import threading
from datetime import datetime

import serial.tools.list_ports

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.hmi_serial import HmiSerial  # noqa: E402
from core.hydraulic_serial import HydraulicSerial  # noqa: E402
from core.hc_driver import HCDriver  # noqa: E402
from runner.runner import TestRunner, discover_tests  # noqa: E402


# Map raw CATEGORY -> display group
def _group_of(category: str) -> str:
    if category.startswith("cert"):
        return "Certificate / SSL"
    if category.startswith("ota"):
        return "OTA / Firmware"
    if category.startswith("shabbat"):
        return "Shabbat & Daily Cycle"
    if category.startswith("hc_"):
        return "HC (Hydraulic Controller)"
    if category.startswith("hmi_"):
        return "HMI (User Interface)"
    if category in ("dispense", "param", "temp"):
        return "HMI (User Interface)"
    if category == "cross":
        return "Cross-device"
    return "Other"


GROUP_ORDER = [
    "HMI (User Interface)",
    "HC (Hydraulic Controller)",
    "Cross-device",
    "Certificate / SSL",
    "OTA / Firmware",
    "Shabbat & Daily Cycle",
    "Other",
]


# ════════════════════════════════════════════════════════════════════════
#  GUI
# ════════════════════════════════════════════════════════════════════════
def run_gui(parent=None):
    # parent=None  -> standalone window (original behavior)
    # parent=Frame -> embed the whole GUI into the given container (launcher tab)
    import tkinter as tk
    import tkinter.ttk as ttk
    import tkinter.messagebox as mb
    import tkinter.filedialog as fd

    embedded = parent is not None

    BG = "#1a1f2e"
    BG2 = "#242938"
    BG3 = "#2e3447"
    ACCENT = "#00bfff"
    ACCENT2 = "#005f88"
    TEXT = "#e0e6f0"
    DIM = "#7a8aaa"
    GREEN = "#22c55e"
    RED = "#ef4444"
    YELLOW = "#f59e0b"
    FM = ("Consolas", 10)
    FB = ("Consolas", 11, "bold")
    FH = ("Consolas", 13, "bold")

    if embedded:
        # build into the supplied container; it becomes our "root"
        root = parent
    else:
        root = tk.Tk()
        root.title("Water Bar Tester v2.1")
        root.geometry("560x780")
        root.configure(bg=BG)
        root.minsize(480, 600)

    hmi_dev = None
    hydr_dev = None
    runner = None
    log_window = None
    log_widget = None
    log_buffer = []

    all_tests = discover_tests()

    # ── logging (buffered; mirrored to popup if open) ────────────────
    def log(msg, color=TEXT):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        log_buffer.append((line, color))
        if log_widget is not None:
            try:
                log_widget.configure(state="normal")
                log_widget.insert("end", line + "\n", color)
                log_widget.configure(state="disabled")
                log_widget.see("end")
            except tk.TclError:
                pass
        # also mirror to mini status line
        mini_log_var.set(line[:70])

    def open_log_window():
        nonlocal log_window, log_widget
        if log_window is not None and tk.Toplevel.winfo_exists(log_window):
            log_window.lift()
            return
        log_window = tk.Toplevel(root)
        log_window.title("Water Bar Tester — Log")
        log_window.geometry("820x600")
        log_window.configure(bg=BG)

        bar = tk.Frame(log_window, bg=BG2)
        bar.pack(fill="x")
        tk.Button(bar, text="Save", command=save_log, bg=BG3, fg=TEXT,
                  font=FM, relief="flat", padx=10).pack(side="left", padx=4, pady=4)
        tk.Button(bar, text="Clear", command=clear_log, bg=BG3, fg=TEXT,
                  font=FM, relief="flat", padx=10).pack(side="left", pady=4)

        frame = tk.Frame(log_window, bg=BG)
        frame.pack(fill="both", expand=True)
        log_widget = tk.Text(frame, font=FM, bg="#0d1117", fg=TEXT,
                             state="disabled", wrap="none", relief="flat")
        sy = tk.Scrollbar(frame, orient="vertical", command=log_widget.yview)
        sx = tk.Scrollbar(frame, orient="horizontal", command=log_widget.xview)
        log_widget.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side="right", fill="y")
        sx.pack(side="bottom", fill="x")
        log_widget.pack(fill="both", expand=True)
        for c in [TEXT, ACCENT, GREEN, RED, YELLOW, DIM]:
            log_widget.tag_configure(c, foreground=c)

        # replay buffer
        log_widget.configure(state="normal")
        for line, color in log_buffer:
            log_widget.insert("end", line + "\n", color)
        log_widget.configure(state="disabled")
        log_widget.see("end")

        def _on_close():
            nonlocal log_window, log_widget
            log_window.destroy()
            log_window = None
            log_widget = None
        log_window.protocol("WM_DELETE_WINDOW", _on_close)

    def save_log():
        p = fd.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Text", "*.txt")],
            initialfile=f"water_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        if p:
            with open(p, "w", encoding="utf-8") as f:
                for line, _ in log_buffer:
                    f.write(line + "\n")
            log(f"Saved: {p}", ACCENT)

    def clear_log():
        log_buffer.clear()
        if log_widget is not None:
            log_widget.configure(state="normal")
            log_widget.delete("1.0", "end")
            log_widget.configure(state="disabled")

    def set_status(msg, ok=True):
        sv.set(msg)
        sl.configure(fg=GREEN if ok else RED)

    def refresh_ports():
        ports = [p.device for p in serial.tools.list_ports.comports()]
        hmi_combo["values"] = ports
        hydr_combo["values"] = ports
        if ports:
            hmi_combo.set(ports[0])
        if len(ports) > 1:
            hydr_combo.set(ports[1])

    def get_config():
        return {
            "hmi_port": hmi_port_var.get(),
            "hydraulic_port": hydr_port_var.get(),
            "hc_profile": profile_var.get(),
            "target_liters": float(target_var.get() or 1),
            "press_duration_ms": int(duration_var.get() or 1000),
            "pour_wait_sec": float(wait_var.get() or 40),
            "tolerance_ml": float(tol_var.get() or 150),
            "hot_min_temp": float(hot_min_var.get() or 85),
            "cold_max_temp": float(cold_max_var.get() or 11),
            "filter_max_liters": float(fmax_var.get() or 5000),
            "long_term_cycles": int(cycles_var.get() or 17),
            "long_term_pause_sec": int(pause_var.get() or 300),
            "use_hydraulic": use_hydr_var.get(),
            # monitor-run parameters
            "monitor_minutes": float(mon_min_var.get() or 30),
            "monitor_cycles": int(mon_cyc_var.get() or 0),
            "monitor_hmi_period": float(mon_hmi_var.get() or 120),
            "monitor_hc_period": float(mon_hc_var.get() or 60),
            "monitor_pause": float(mon_pause_var.get() or 30),
        }

    def selected_tests():
        sel = [n for n, v in test_vars.items() if v.get()]
        return sel if sel else list(all_tests.keys())

    # ── connect HMI ──────────────────────────────────────────────────
    def connect_hmi():
        nonlocal hmi_dev
        port = hmi_port_var.get().strip()
        if not port:
            mb.showwarning("No port", "Select HMI COM port.")
            return
        try:
            hmi_dev = HmiSerial(port, 115200, log_callback=log)
            hmi_dev.connect()
            hmi_status_lbl.configure(fg=GREEN, text=f"HMI: {port}")
            btn_hmi_conn.configure(state="disabled")
            btn_hmi_disc.configure(state="normal")
            _update_run_btn()
        except Exception as exc:
            log(f"[ERROR] HMI: {exc}", RED)

    def disconnect_hmi():
        nonlocal hmi_dev
        if hmi_dev:
            hmi_dev.disconnect()
            hmi_dev = None
        hmi_status_lbl.configure(fg=RED, text="HMI: --")
        btn_hmi_conn.configure(state="normal")
        btn_hmi_disc.configure(state="disabled")
        _update_run_btn()

    # ── connect Hydraulic (driver depends on mode) ───────────────────
    def connect_hydr():
        nonlocal hydr_dev
        port = hydr_port_var.get().strip()
        if not port:
            mb.showwarning("No port", "Select Hydraulic COM port.")
            return
        mode = hydr_mode_var.get()
        try:
            if mode == "HCDriver":
                hydr_dev = HCDriver(port, 115200, log_callback=log)
            else:
                hydr_dev = HydraulicSerial(port, 115200, log_callback=log)
            hydr_dev.connect()
            hydr_status_lbl.configure(fg=GREEN, text=f"HYDRAULIC: {port} [{mode}]")
            btn_hydr_conn.configure(state="disabled")
            btn_hydr_disc.configure(state="normal")
        except Exception as exc:
            log(f"[ERROR] HYDRAULIC: {exc}", RED)

    def disconnect_hydr():
        nonlocal hydr_dev
        if hydr_dev:
            hydr_dev.disconnect()
            hydr_dev = None
        hydr_status_lbl.configure(fg=RED, text="HYDRAULIC: --")
        btn_hydr_conn.configure(state="normal")
        btn_hydr_disc.configure(state="disabled")

    def _update_run_btn():
        ok = hmi_dev is not None and hmi_dev.is_connected()
        btn_run.configure(state="normal" if ok else "disabled")
        btn_monitor.configure(state="normal" if ok else "disabled")

    # ── manual button press ──────────────────────────────────────────
    def manual_press(btn_id, btn_name):
        if hmi_dev is None or not hmi_dev.is_connected():
            log("[ERROR] HMI not connected.", RED)
            return
        dur = int(duration_var.get() or 1000)
        log(f"[MANUAL] press {btn_id} {dur} ({btn_name})", ACCENT)

        def _t():
            resp = hmi_dev.press(btn_id, dur)
            root.after(0, lambda: log(f"  -> {resp}", DIM))
        threading.Thread(target=_t, daemon=True).start()

    def run_monitor():
        # run ONLY the long-term monitor test
        nonlocal runner
        if hmi_dev is None:
            mb.showwarning("Not connected", "Connect HMI first.")
            return
        monitor_name = None
        for name, cls in all_tests.items():
            if getattr(cls, "CATEGORY", "") == "monitor":
                monitor_name = name
                break
        if monitor_name is None:
            log("[ERROR] Monitor test not found in tests/.", RED)
            return
        btn_run.configure(state="disabled")
        btn_monitor.configure(state="disabled")
        btn_stop.configure(state="normal")
        progress.start(10)
        log("-" * 50, DIM)
        log("Starting MONITOR run... (press STOP to finish)", ACCENT)

        cfg = get_config()
        runner = TestRunner(hmi_dev, hydr_dev, cfg, log_callback=log)

        def _thread():
            try:
                results = runner.run([monitor_name])
                root.after(0, lambda: _on_finish(results))
            except Exception as exc:
                msg = f"[FATAL] {exc}"
                root.after(0, lambda m=msg: log(m, RED))
                root.after(0, _cleanup)
        threading.Thread(target=_thread, daemon=True).start()

    # ── run / stop ───────────────────────────────────────────────────
    def run_tests():
        nonlocal runner
        if hmi_dev is None:
            mb.showwarning("Not connected", "Connect HMI first.")
            return
        btn_run.configure(state="disabled")
        btn_stop.configure(state="normal")
        progress.start(10)
        log("-" * 50, DIM)
        log("Starting test session...", ACCENT)

        cfg = get_config()
        runner = TestRunner(hmi_dev, hydr_dev, cfg, log_callback=log)

        def _thread():
            try:
                results = runner.run(selected_tests())
                root.after(0, lambda: _on_finish(results))
            except Exception as exc:
                msg = f"[FATAL] {exc}"
                root.after(0, lambda m=msg: log(m, RED))
                root.after(0, _cleanup)
        threading.Thread(target=_thread, daemon=True).start()

    def _on_finish(results):
        _cleanup()
        report = runner.generate_report()
        log("-" * 50, DIM)
        for line in report.splitlines():
            c = GREEN if "✓" in line else (RED if "✗" in line else TEXT)
            log(line, c)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(BASE_DIR, "reports", f"report_{ts}.txt")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(report + "\n\n--- LOG ---\n\n")
                for line, _ in log_buffer:
                    f.write(line + "\n")
            log(f"Report -> {out}", ACCENT)
        except Exception as exc:
            log(f"[WARN] save failed: {exc}", YELLOW)
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        set_status(f"Done: {passed} passed, {failed} failed", ok=(failed == 0))

    def _cleanup():
        ok = hmi_dev is not None and hmi_dev.is_connected()
        btn_run.configure(state="normal" if ok else "disabled")
        btn_monitor.configure(state="normal" if ok else "disabled")
        btn_stop.configure(state="disabled")
        progress.stop()

    def stop_tests():
        if runner:
            runner.stop()
            log("[USER] Stop requested.", YELLOW)

    def send_cmd():
        cmd = cmd_var.get().strip()
        if not cmd:
            return
        dev = hmi_dev if cmd_target.get() == "HMI" else hydr_dev
        if dev is None:
            log(f"[ERROR] {cmd_target.get()} not connected.", RED)
            return

        def _t():
            resp = dev.send_command(cmd)
            root.after(0, lambda: log(f"-> {resp}", ACCENT))
        threading.Thread(target=_t, daemon=True).start()

    # ════════════════════════════════════════════════════════════════
    #  LAYOUT — scrollable left config, compact
    # ════════════════════════════════════════════════════════════════
    hdr = tk.Frame(root, bg=BG2, pady=6)
    hdr.pack(fill="x")
    tk.Label(hdr, text="WATER BAR TESTER", font=FH, bg=BG2, fg=ACCENT).pack(side="left", padx=12)
    sv = tk.StringVar(value="Not connected")
    sl = tk.Label(hdr, textvariable=sv, font=FM, bg=BG2, fg=RED)
    sl.pack(side="right", padx=12)

    # top action bar
    topbar = tk.Frame(root, bg=BG)
    topbar.pack(fill="x", padx=8, pady=4)
    btn_run = tk.Button(topbar, text="RUN TESTS", command=run_tests,
                        bg=ACCENT2, fg="white", font=FB, relief="flat",
                        padx=16, pady=5, state="disabled")
    btn_run.pack(side="left", padx=(0, 4))
    btn_monitor = tk.Button(topbar, text="MONITOR", command=run_monitor,
                            bg="#1d4ed8", fg="white", font=FB, relief="flat",
                            padx=12, pady=5, state="disabled")
    btn_monitor.pack(side="left", padx=(0, 4))
    btn_stop = tk.Button(topbar, text="STOP", command=stop_tests,
                         bg="#7f1d1d", fg="#fca5a5", font=FB, relief="flat",
                         padx=12, pady=5, state="disabled")
    btn_stop.pack(side="left", padx=(0, 4))
    tk.Button(topbar, text="Open Log", command=open_log_window,
              bg=BG3, fg=ACCENT, font=FB, relief="flat",
              padx=12, pady=5).pack(side="left")

    sty = ttk.Style()
    sty.theme_use("default")
    sty.configure("A.Horizontal.TProgressbar", troughcolor=BG3,
                  background=ACCENT, thickness=4)
    progress = ttk.Progressbar(root, mode="indeterminate", style="A.Horizontal.TProgressbar")
    progress.pack(fill="x", padx=8, pady=(0, 2))

    # mini log line
    mini_log_var = tk.StringVar(value="ready")
    tk.Label(root, textvariable=mini_log_var, font=("Consolas", 9), bg=BG,
             fg=DIM, anchor="w").pack(fill="x", padx=10)

    # scrollable config area
    canvas_frame = tk.Frame(root, bg=BG)
    canvas_frame.pack(fill="both", expand=True, padx=4, pady=4)
    canvas = tk.Canvas(canvas_frame, bg=BG2, highlightthickness=0)
    vsb = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    left = tk.Frame(canvas, bg=BG2)
    canvas.create_window((0, 0), window=left, anchor="nw", width=520)

    def _on_config(_e):
        canvas.configure(scrollregion=canvas.bbox("all"))
    left.bind("<Configure>", _on_config)

    def _on_wheel(e):
        canvas.yview_scroll(int(-e.delta / 120), "units")
    canvas.bind_all("<MouseWheel>", _on_wheel)

    def sec(txt):
        tk.Label(left, text=txt, font=FB, bg=BG2, fg=ACCENT,
                 anchor="w").pack(fill="x", padx=10, pady=(10, 1))
        tk.Frame(left, bg=ACCENT2, height=1).pack(fill="x", padx=10)

    def lrow(lbl, var, width=10):
        r = tk.Frame(left, bg=BG2)
        r.pack(fill="x", padx=10, pady=2)
        tk.Label(r, text=lbl, font=FM, bg=BG2, fg=DIM, width=16, anchor="w").pack(side="left")
        tk.Entry(r, textvariable=var, font=FM, bg=BG3, fg=TEXT,
                 insertbackground=ACCENT, width=width, relief="flat").pack(side="left")

    # HMI
    sec("HMI CONNECTION")
    hmi_port_var = tk.StringVar(value="COM5")
    r = tk.Frame(left, bg=BG2)
    r.pack(fill="x", padx=10, pady=2)
    tk.Label(r, text="HMI Port", font=FM, bg=BG2, fg=DIM, width=12, anchor="w").pack(side="left")
    hmi_combo = ttk.Combobox(r, textvariable=hmi_port_var, width=10, font=FM)
    hmi_combo.pack(side="left")
    tk.Button(r, text="Refresh", command=refresh_ports, bg=BG3, fg=ACCENT,
              font=FM, relief="flat", padx=4).pack(side="left", padx=2)
    hmi_status_lbl = tk.Label(left, text="HMI: --", font=FM, bg=BG2, fg=RED, anchor="w")
    hmi_status_lbl.pack(fill="x", padx=10)
    r2 = tk.Frame(left, bg=BG2)
    r2.pack(fill="x", padx=10, pady=3)
    btn_hmi_conn = tk.Button(r2, text="CONNECT HMI", command=connect_hmi,
                             bg=ACCENT2, fg="white", font=FM, relief="flat",
                             padx=8, pady=3)
    btn_hmi_conn.pack(side="left", expand=True, fill="x", padx=(0, 2))
    btn_hmi_disc = tk.Button(r2, text="DISC", command=disconnect_hmi, bg="#444",
                             fg=DIM, font=FM, relief="flat", padx=6, pady=3, state="disabled")
    btn_hmi_disc.pack(side="left")

    # Hydraulic
    sec("HYDRAULIC CONNECTION")
    hydr_port_var = tk.StringVar(value="COM24")
    r = tk.Frame(left, bg=BG2)
    r.pack(fill="x", padx=10, pady=2)
    tk.Label(r, text="Hydraulic Port", font=FM, bg=BG2, fg=DIM, width=14, anchor="w").pack(side="left")
    hydr_combo = ttk.Combobox(r, textvariable=hydr_port_var, width=10, font=FM)
    hydr_combo.pack(side="left")

    rm = tk.Frame(left, bg=BG2)
    rm.pack(fill="x", padx=10, pady=2)
    tk.Label(rm, text="Driver mode", font=FM, bg=BG2, fg=DIM, width=14, anchor="w").pack(side="left")
    hydr_mode_var = tk.StringVar(value="HCDriver")
    ttk.Combobox(rm, textvariable=hydr_mode_var,
                 values=["HCDriver", "HydraulicSerial"],
                 width=14, font=FM, state="readonly").pack(side="left")

    rp = tk.Frame(left, bg=BG2)
    rp.pack(fill="x", padx=10, pady=2)
    tk.Label(rp, text="HC Profile", font=FM, bg=BG2, fg=DIM, width=14, anchor="w").pack(side="left")
    profile_var = tk.StringVar(value="IL")
    ttk.Combobox(rp, textvariable=profile_var, values=["IL", "US"],
                 width=6, font=FM, state="readonly").pack(side="left")

    hydr_status_lbl = tk.Label(left, text="HYDRAULIC: --", font=FM, bg=BG2, fg=RED, anchor="w")
    hydr_status_lbl.pack(fill="x", padx=10)
    r3 = tk.Frame(left, bg=BG2)
    r3.pack(fill="x", padx=10, pady=3)
    btn_hydr_conn = tk.Button(r3, text="CONNECT HYDRAULIC", command=connect_hydr,
                              bg="#005544", fg="white", font=FM, relief="flat",
                              padx=8, pady=3)
    btn_hydr_conn.pack(side="left", expand=True, fill="x", padx=(0, 2))
    btn_hydr_disc = tk.Button(r3, text="DISC", command=disconnect_hydr, bg="#444",
                              fg=DIM, font=FM, relief="flat", padx=6, pady=3, state="disabled")
    btn_hydr_disc.pack(side="left")

    use_hydr_var = tk.BooleanVar(value=True)
    tk.Checkbutton(left, text="Use Hydraulic in tests", variable=use_hydr_var,
                   bg=BG2, fg=TEXT, selectcolor=BG3, font=FM,
                   activebackground=BG2).pack(anchor="w", padx=10)

    # Params
    sec("TEST PARAMETERS")
    target_var = tk.StringVar(value="1")
    duration_var = tk.StringVar(value="1000")
    wait_var = tk.StringVar(value="40")
    tol_var = tk.StringVar(value="150")
    hot_min_var = tk.StringVar(value="85")
    cold_max_var = tk.StringVar(value="11")
    fmax_var = tk.StringVar(value="5000")
    cycles_var = tk.StringVar(value="17")
    pause_var = tk.StringVar(value="300")
    lrow("Target (L)", target_var)
    lrow("Press dur (ms)", duration_var)
    lrow("Pour wait (s)", wait_var)
    lrow("Tolerance (ml)", tol_var)
    lrow("Hot min (C)", hot_min_var)
    lrow("Cold max (C)", cold_max_var)
    lrow("Filter max (L)", fmax_var)
    lrow("Long cycles", cycles_var)
    lrow("Long pause (s)", pause_var)

    # Monitor-run parameters
    sec("MONITOR PARAMETERS")
    mon_min_var = tk.StringVar(value="30")
    mon_cyc_var = tk.StringVar(value="0")
    mon_hmi_var = tk.StringVar(value="120")
    mon_hc_var = tk.StringVar(value="60")
    mon_pause_var = tk.StringVar(value="30")
    lrow("Run minutes (0=inf)", mon_min_var)
    lrow("Max cycles (0=inf)", mon_cyc_var)
    lrow("HMI poll (s)", mon_hmi_var)
    lrow("HC poll (s)", mon_hc_var)
    lrow("Pause (s)", mon_pause_var)

    # Manual buttons
    sec("MANUAL BUTTONS")
    BTN_LAYOUT = [
        (1, "HOT GLASS", "#7f1d1d"), (2, "HOT JUG", "#991b1b"),
        (4, "COLD GLASS", "#1e3a5f"), (5, "COLD JUG", "#1d4ed8"),
        (6, "AMB GLASS", "#064e3b"), (7, "AMB JUG", "#065f46"),
        (3, "MENU", "#3b3b5c"), (8, "FILTERED", "#4a1d96"),
    ]
    grid = tk.Frame(left, bg=BG2)
    grid.pack(fill="x", padx=10, pady=4)
    for i, (bid, bname, bcolor) in enumerate(BTN_LAYOUT):
        tk.Button(grid, text=f"{bid}: {bname}",
                  command=lambda _id=bid, _n=bname: manual_press(_id, _n),
                  bg=bcolor, fg="white", font=("Consolas", 9),
                  relief="flat", padx=4, pady=4, width=14
                  ).grid(row=i // 2, column=i % 2, padx=2, pady=2, sticky="ew")

    # Select tests — grouped, collapsible
    sec("SELECT TESTS")
    test_vars = {}
    group_frames = {}

    # group tests
    grouped = {}
    for name, cls in all_tests.items():
        g = _group_of(getattr(cls, "CATEGORY", "other"))
        grouped.setdefault(g, []).append(name)

    def make_group(group_name, names):
        header = tk.Frame(left, bg=BG3)
        header.pack(fill="x", padx=10, pady=(6, 0))
        state = {"open": True}
        arrow = tk.Label(header, text="▼", font=FM, bg=BG3, fg=ACCENT, width=2)
        arrow.pack(side="left")
        tk.Label(header, text=f"{group_name} ({len(names)})", font=FB, bg=BG3,
                 fg=ACCENT, anchor="w").pack(side="left", fill="x", expand=True)

        body = tk.Frame(left, bg=BG2)
        body.pack(fill="x", padx=10)
        group_frames[group_name] = body

        for n in names:
            v = tk.BooleanVar(value=True)
            test_vars[n] = v
            tk.Checkbutton(body, text=n, variable=v, bg=BG2, fg=TEXT,
                           selectcolor=BG3, font=("Consolas", 9),
                           activebackground=BG2, anchor="w").pack(fill="x")

        def toggle(_e=None):
            if state["open"]:
                body.pack_forget()
                arrow.configure(text="▶")
            else:
                body.pack(fill="x", padx=10)
                arrow.configure(text="▼")
            state["open"] = not state["open"]
            left.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))

        header.bind("<Button-1>", toggle)
        arrow.bind("<Button-1>", toggle)

    for gname in GROUP_ORDER:
        if gname in grouped:
            make_group(gname, sorted(grouped[gname]))

    selrow = tk.Frame(left, bg=BG2)
    selrow.pack(fill="x", padx=10, pady=4)
    tk.Button(selrow, text="All", command=lambda: [v.set(True) for v in test_vars.values()],
              bg=BG3, fg=ACCENT, font=FM, relief="flat", padx=6).pack(side="left")
    tk.Button(selrow, text="None", command=lambda: [v.set(False) for v in test_vars.values()],
              bg=BG3, fg=ACCENT, font=FM, relief="flat", padx=6).pack(side="left", padx=4)

    # manual command
    sec("MANUAL COMMAND")
    cr = tk.Frame(left, bg=BG2)
    cr.pack(fill="x", padx=10, pady=4)
    cmd_target = tk.StringVar(value="HMI")
    ttk.Combobox(cr, textvariable=cmd_target, values=["HMI", "HYDRAULIC"],
                 width=10, font=FM, state="readonly").pack(side="left", padx=(0, 4))
    cmd_var = tk.StringVar()
    ce = tk.Entry(cr, textvariable=cmd_var, font=FM, bg=BG3, fg=TEXT,
                  insertbackground=ACCENT, relief="flat")
    ce.pack(side="left", expand=True, fill="x", padx=4)
    ce.bind("<Return>", lambda e: send_cmd())
    tk.Button(cr, text="Send", command=send_cmd, bg=BG3, fg=ACCENT,
              font=FM, relief="flat", padx=8).pack(side="left")

    refresh_ports()
    log("Water Bar Tester v2.1 ready.", ACCENT)
    log(f"Discovered {len(all_tests)} tests.", DIM)
    log("Connect HMI (required) and Hydraulic (optional), then RUN.", DIM)

    if not embedded:
        root.mainloop()


# ════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════
def run_cli(args):
    cfg = {
        "hmi_port": args.hmi_port,
        "hydraulic_port": args.hydr_port,
        "hc_profile": args.profile,
        "target_liters": args.liters,
        "press_duration_ms": 1000,
        "pour_wait_sec": 40,
        "tolerance_ml": 150,
        "hot_min_temp": 85,
        "cold_max_temp": 11,
        "filter_max_liters": 5000,
        "long_term_cycles": 17,
        "long_term_pause_sec": 300,
        "use_hydraulic": bool(args.hydr_port),
    }
    hmi = HmiSerial(args.hmi_port, 115200)
    hydr = None
    if args.hydr_port:
        if args.hydr_mode == "HCDriver":
            hydr = HCDriver(args.hydr_port, 115200)
        else:
            hydr = HydraulicSerial(args.hydr_port, 115200)
    try:
        hmi.connect()
        if hydr:
            hydr.connect()
        r = TestRunner(hmi, hydr, cfg)
        tests = args.tests.split(",") if args.tests else None
        r.run(tests)
        print(r.generate_report())
    finally:
        hmi.disconnect()
        if hydr:
            hydr.disconnect()


# ════════════════════════════════════════════════════════════════════════
#  ENTRY
# ════════════════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cli", action="store_true")
    p.add_argument("--hmi-port", default="COM5")
    p.add_argument("--hydr-port", default=None)
    p.add_argument("--hydr-mode", default="HCDriver",
                   choices=["HCDriver", "HydraulicSerial"])
    p.add_argument("--profile", default="IL", choices=["IL", "US"])
    p.add_argument("--liters", type=float, default=1)
    p.add_argument("--tests", default=None)
    args = p.parse_args()
    if args.cli:
        run_cli(args)
    else:
        run_gui()


if __name__ == "__main__":
    main()
