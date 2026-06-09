"""
water_bar_tester.py — главный файл.
GUI с двумя COM портами (HMI + Hydraulic), 8 кнопками, выбором тестов.

python water_bar_tester.py          # GUI
python water_bar_tester.py --cli    # CLI
"""
import sys, os, argparse, threading, time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import serial.tools.list_ports
from core.hmi_serial       import HmiSerial,       BUTTONS
from core.hydraulic_serial import HydraulicSerial
from runner.runner         import TestRunner, discover_tests


# ════════════════════════════════════════════════════════════════════════
#  GUI
# ════════════════════════════════════════════════════════════════════════
def run_gui():
    import tkinter as tk
    import tkinter.ttk as ttk
    import tkinter.messagebox as mb
    import tkinter.filedialog as fd

    # ── цвета ────────────────────────────────────────────────────────
    BG       = "#1a1f2e"
    BG2      = "#242938"
    BG3      = "#2e3447"
    ACCENT   = "#00bfff"
    ACCENT2  = "#005f88"
    TEXT     = "#e0e6f0"
    DIM      = "#7a8aaa"
    GREEN    = "#22c55e"
    RED      = "#ef4444"
    YELLOW   = "#f59e0b"
    FM       = ("Consolas", 10)
    FB       = ("Consolas", 11, "bold")
    FH       = ("Consolas", 13, "bold")

    root = tk.Tk()
    root.title("💧 Water Bar Tester v2.0")
    root.geometry("1100x750")
    root.configure(bg=BG)
    root.resizable(True, True)

    # ── состояние ────────────────────────────────────────────────────
    hmi_dev:  HmiSerial        = None
    hydr_dev: HydraulicSerial  = None
    runner:   TestRunner       = None

    all_tests = discover_tests()

    # ── helpers ──────────────────────────────────────────────────────
    def log(msg, color=TEXT):
        log_txt.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        log_txt.insert("end", f"[{ts}] {msg}\n", color)
        log_txt.configure(state="disabled")
        log_txt.see("end")

    def set_status(msg, ok=True):
        sv.set(msg)
        sl.configure(fg=GREEN if ok else RED)

    def refresh_ports():
        ports = [p.device for p in serial.tools.list_ports.comports()]
        hmi_combo['values']  = ports
        hydr_combo['values'] = ports
        if ports:
            hmi_combo.set(ports[0])
            if len(ports) > 1:
                hydr_combo.set(ports[1])

    def get_config():
        return {
            "hmi_port":        hmi_port_var.get(),
            "hydraulic_port":  hydr_port_var.get(),
            "target_liters":   float(target_var.get() or 1),
            "press_duration_ms": int(duration_var.get() or 1000),
            "pour_wait_sec":   float(wait_var.get() or 40),
            "tolerance_ml":    float(tol_var.get() or 150),
            "hot_min_temp":    float(hot_min_var.get() or 85),
            "cold_max_temp":   float(cold_max_var.get() or 11),
            "filter_max_liters": float(fmax_var.get() or 5000),
            "use_hydraulic":   use_hydr_var.get(),
        }

    def selected_tests():
        sel = [n for n, v in test_vars.items() if v.get()]
        return sel if sel else list(all_tests.keys())

    # ── подключение ──────────────────────────────────────────────────
    def connect_hmi():
        nonlocal hmi_dev
        port = hmi_port_var.get().strip()
        if not port:
            mb.showwarning("No port", "Select HMI COM port.")
            return
        try:
            hmi_dev = HmiSerial(port, 115200, log_callback=log)
            hmi_dev.connect()
            hmi_status_lbl.configure(fg=GREEN, text=f"● HMI: {port}")
            btn_hmi_conn.configure(state="disabled")
            btn_hmi_disc.configure(state="normal")
            _update_run_btn()
        except Exception as e:
            log(f"[ERROR] HMI: {e}", RED)

    def disconnect_hmi():
        nonlocal hmi_dev
        if hmi_dev:
            hmi_dev.disconnect()
            hmi_dev = None
        hmi_status_lbl.configure(fg=RED, text="○ HMI: --")
        btn_hmi_conn.configure(state="normal")
        btn_hmi_disc.configure(state="disabled")
        _update_run_btn()

    def connect_hydr():
        nonlocal hydr_dev
        port = hydr_port_var.get().strip()
        if not port:
            mb.showwarning("No port", "Select Hydraulic COM port.")
            return
        try:
            hydr_dev = HydraulicSerial(port, 115200, log_callback=log)
            hydr_dev.connect()
            hydr_status_lbl.configure(fg=GREEN, text=f"● HYDRAULIC: {port}")
            btn_hydr_conn.configure(state="disabled")
            btn_hydr_disc.configure(state="normal")
            _update_run_btn()
        except Exception as e:
            log(f"[ERROR] HYDRAULIC: {e}", RED)

    def disconnect_hydr():
        nonlocal hydr_dev
        if hydr_dev:
            hydr_dev.disconnect()
            hydr_dev = None
        hydr_status_lbl.configure(fg=RED, text="○ HYDRAULIC: --")
        btn_hydr_conn.configure(state="normal")
        btn_hydr_disc.configure(state="disabled")
        _update_run_btn()

    def _update_run_btn():
        ok = hmi_dev is not None and hmi_dev.is_connected()
        btn_run.configure(state="normal" if ok else "disabled")

    # ── ручное нажатие кнопок ─────────────────────────────────────────
    def manual_press(btn_id: int, btn_name: str):
        if hmi_dev is None or not hmi_dev.is_connected():
            log("[ERROR] HMI not connected.", RED)
            return
        dur = int(duration_var.get() or 1000)
        log(f"[MANUAL] press {btn_id} {dur}  ({btn_name})", ACCENT)
        def _t():
            resp = hmi_dev.press(btn_id, dur)
            root.after(0, lambda: log(f"  → {resp}", DIM))
        threading.Thread(target=_t, daemon=True).start()

    # ── запуск тестов ─────────────────────────────────────────────────
    def run_tests():
        nonlocal runner
        if hmi_dev is None:
            mb.showwarning("Not connected", "Connect HMI first.")
            return
        btn_run.configure(state="disabled")
        btn_stop.configure(state="normal")
        progress.start(10)
        log("─" * 50, DIM)
        log("Starting test session...", ACCENT)

        cfg = get_config()
        runner = TestRunner(hmi_dev, hydr_dev, cfg, log_callback=log)

        def _thread():
            try:
                results = runner.run(selected_tests())
                root.after(0, lambda: _on_finish(results))
            except Exception as e:
                root.after(0, lambda: log(f"[FATAL] {e}", RED))
                root.after(0, _cleanup)

        threading.Thread(target=_thread, daemon=True).start()

    def _on_finish(results):
        _cleanup()
        report = runner.generate_report()
        log("─" * 50, DIM)
        for line in report.splitlines():
            c = GREEN if "✓" in line else (RED if "✗" in line else TEXT)
            log(line, c)
        # сохранить
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = os.path.join(BASE_DIR, "reports", f"report_{ts}.txt")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        try:
            with open(out, "w", encoding="utf-8") as f:
                f.write(report + "\n\n--- LOG ---\n\n")
                if hmi_dev:  f.write(hmi_dev.get_full_log())
                if hydr_dev: f.write("\n\n" + hydr_dev.get_full_log())
            log(f"Report → {out}", ACCENT)
        except Exception as e:
            log(f"[WARN] save failed: {e}", YELLOW)

        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        set_status(f"Done: {passed} passed, {failed} failed", ok=(failed == 0))

    def _cleanup():
        btn_run.configure(state="normal" if (hmi_dev and hmi_dev.is_connected()) else "disabled")
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
            root.after(0, lambda: log(f"→ {resp}", ACCENT))
        threading.Thread(target=_t, daemon=True).start()

    def save_log():
        p = fd.asksaveasfilename(defaultextension=".txt",
                                 filetypes=[("Text", "*.txt")])
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(log_txt.get("1.0", "end"))
            log(f"Saved: {p}", ACCENT)

    # ════════════════════════════════════════════════════════════════
    #  LAYOUT
    # ════════════════════════════════════════════════════════════════

    # header
    hdr = tk.Frame(root, bg=BG2, pady=6)
    hdr.pack(fill="x")
    tk.Label(hdr, text="💧 WATER BAR TESTER", font=FH, bg=BG2, fg=ACCENT).pack(side="left", padx=14)
    sv = tk.StringVar(value="Not connected")
    sl = tk.Label(hdr, textvariable=sv, font=FM, bg=BG2, fg=RED)
    sl.pack(side="right", padx=14)

    # main
    main = tk.Frame(root, bg=BG)
    main.pack(fill="both", expand=True, padx=6, pady=4)

    # ── LEFT PANEL ──────────────────────────────────────────────────
    left = tk.Frame(main, bg=BG2, width=290)
    left.pack(side="left", fill="y", padx=(0, 4))
    left.pack_propagate(False)

    def sec(txt):
        tk.Label(left, text=txt, font=FB, bg=BG2, fg=ACCENT,
                 anchor="w").pack(fill="x", padx=10, pady=(10, 1))
        tk.Frame(left, bg=ACCENT2, height=1).pack(fill="x", padx=10)

    def lrow(lbl, var, width=10):
        r = tk.Frame(left, bg=BG2)
        r.pack(fill="x", padx=10, pady=2)
        tk.Label(r, text=lbl, font=FM, bg=BG2, fg=DIM,
                 width=16, anchor="w").pack(side="left")
        tk.Entry(r, textvariable=var, font=FM, bg=BG3, fg=TEXT,
                 insertbackground=ACCENT, width=width,
                 relief="flat").pack(side="left")

    # ── HMI port ────────────────────────────────────────────────────
    sec("HMI CONNECTION")
    hmi_port_var = tk.StringVar(value="COM5")
    r = tk.Frame(left, bg=BG2); r.pack(fill="x", padx=10, pady=2)
    tk.Label(r, text="HMI Port", font=FM, bg=BG2, fg=DIM,
             width=12, anchor="w").pack(side="left")
    hmi_combo = ttk.Combobox(r, textvariable=hmi_port_var, width=8, font=FM)
    hmi_combo.pack(side="left")
    tk.Button(r, text="⟳", command=refresh_ports, bg=BG3, fg=ACCENT,
              font=FM, relief="flat", padx=3).pack(side="left", padx=2)

    hmi_status_lbl = tk.Label(left, text="○ HMI: --", font=FM, bg=BG2, fg=RED, anchor="w")
    hmi_status_lbl.pack(fill="x", padx=10)

    r2 = tk.Frame(left, bg=BG2); r2.pack(fill="x", padx=10, pady=3)
    btn_hmi_conn = tk.Button(r2, text="CONNECT HMI", command=connect_hmi,
                              bg=ACCENT2, fg="white", font=FM, relief="flat",
                              padx=8, pady=3)
    btn_hmi_conn.pack(side="left", expand=True, fill="x", padx=(0,2))
    btn_hmi_disc = tk.Button(r2, text="DISC", command=disconnect_hmi,
                              bg="#444", fg=DIM, font=FM, relief="flat",
                              padx=6, pady=3, state="disabled")
    btn_hmi_disc.pack(side="left")

    # ── Hydraulic port ───────────────────────────────────────────────
    sec("HYDRAULIC CONNECTION")
    hydr_port_var = tk.StringVar(value="COM24")
    r = tk.Frame(left, bg=BG2); r.pack(fill="x", padx=10, pady=2)
    tk.Label(r, text="Hydraulic Port", font=FM, bg=BG2, fg=DIM,
             width=14, anchor="w").pack(side="left")
    hydr_combo = ttk.Combobox(r, textvariable=hydr_port_var, width=8, font=FM)
    hydr_combo.pack(side="left")

    hydr_status_lbl = tk.Label(left, text="○ HYDRAULIC: --", font=FM, bg=BG2, fg=RED, anchor="w")
    hydr_status_lbl.pack(fill="x", padx=10)

    r3 = tk.Frame(left, bg=BG2); r3.pack(fill="x", padx=10, pady=3)
    btn_hydr_conn = tk.Button(r3, text="CONNECT HYDRAULIC", command=connect_hydr,
                               bg="#005544", fg="white", font=FM, relief="flat",
                               padx=8, pady=3)
    btn_hydr_conn.pack(side="left", expand=True, fill="x", padx=(0,2))
    btn_hydr_disc = tk.Button(r3, text="DISC", command=disconnect_hydr,
                               bg="#444", fg=DIM, font=FM, relief="flat",
                               padx=6, pady=3, state="disabled")
    btn_hydr_disc.pack(side="left")

    use_hydr_var = tk.BooleanVar(value=True)
    tk.Checkbutton(left, text="Use Hydraulic in tests", variable=use_hydr_var,
                   bg=BG2, fg=TEXT, selectcolor=BG3, font=FM,
                   activebackground=BG2).pack(anchor="w", padx=10)

    # ── params ───────────────────────────────────────────────────────
    sec("TEST PARAMETERS")
    target_var   = tk.StringVar(value="1")
    duration_var = tk.StringVar(value="1000")
    wait_var     = tk.StringVar(value="40")
    tol_var      = tk.StringVar(value="150")
    hot_min_var  = tk.StringVar(value="85")
    cold_max_var = tk.StringVar(value="11")
    fmax_var     = tk.StringVar(value="5000")
    lrow("Target (L)",      target_var)
    lrow("Press dur (ms)",  duration_var)
    lrow("Pour wait (s)",   wait_var)
    lrow("Tolerance (ml)",  tol_var)
    lrow("Hot min (°C)",    hot_min_var)
    lrow("Cold max (°C)",   cold_max_var)
    lrow("Filter max (L)",  fmax_var)

    # ── 8 кнопок ручного нажатия ─────────────────────────────────────
    sec("MANUAL BUTTONS")
    BTN_LAYOUT = [
        (1, "HOT GLASS",  "#7f1d1d"),
        (2, "HOT JUG",    "#991b1b"),
        (4, "COLD GLASS", "#1e3a5f"),
        (5, "COLD JUG",   "#1d4ed8"),
        (6, "AMB GLASS",  "#064e3b"),
        (7, "AMB JUG",    "#065f46"),
        (3, "MENU",       "#3b3b5c"),
        (8, "FILTERED",   "#4a1d96"),
    ]
    btn_grid = tk.Frame(left, bg=BG2)
    btn_grid.pack(fill="x", padx=10, pady=4)
    for i, (bid, bname, bcolor) in enumerate(BTN_LAYOUT):
        col = i % 2
        row = i // 2
        b = tk.Button(btn_grid, text=f"{bid}: {bname}",
                      command=lambda _id=bid, _n=bname: manual_press(_id, _n),
                      bg=bcolor, fg="white", font=("Consolas", 9),
                      relief="flat", padx=4, pady=4, width=13)
        b.grid(row=row, column=col, padx=2, pady=2, sticky="ew")

    # ── select tests ─────────────────────────────────────────────────
    sec("SELECT TESTS")
    test_frame = tk.Frame(left, bg=BG2)
    test_frame.pack(fill="x", padx=10, pady=2)
    test_vars = {}
    for name in all_tests:
        v = tk.BooleanVar(value=True)
        test_vars[name] = v
        tk.Checkbutton(test_frame, text=name, variable=v,
                       bg=BG2, fg=TEXT, selectcolor=BG3,
                       font=("Consolas", 9), activebackground=BG2,
                       anchor="w").pack(fill="x")

    br = tk.Frame(left, bg=BG2)
    br.pack(fill="x", padx=10, pady=2)
    tk.Button(br, text="All",  command=lambda: [v.set(True)  for v in test_vars.values()],
              bg=BG3, fg=ACCENT, font=FM, relief="flat", padx=6).pack(side="left")
    tk.Button(br, text="None", command=lambda: [v.set(False) for v in test_vars.values()],
              bg=BG3, fg=ACCENT, font=FM, relief="flat", padx=6).pack(side="left", padx=4)

    # ── RIGHT PANEL ──────────────────────────────────────────────────
    right = tk.Frame(main, bg=BG)
    right.pack(side="left", fill="both", expand=True)

    rr = tk.Frame(right, bg=BG)
    rr.pack(fill="x", pady=4)
    btn_run = tk.Button(rr, text="▶  RUN TESTS", command=run_tests,
                        bg=ACCENT2, fg="white", font=FB,
                        relief="flat", padx=20, pady=6, state="disabled")
    btn_run.pack(side="left", padx=(0,4))
    btn_stop = tk.Button(rr, text="■  STOP", command=stop_tests,
                         bg="#7f1d1d", fg="#fca5a5", font=FB,
                         relief="flat", padx=14, pady=6, state="disabled")
    btn_stop.pack(side="left")

    sty = ttk.Style(); sty.theme_use("default")
    sty.configure("A.Horizontal.TProgressbar",
                  troughcolor=BG3, background=ACCENT, thickness=4)
    progress = ttk.Progressbar(right, mode="indeterminate",
                                style="A.Horizontal.TProgressbar")
    progress.pack(fill="x", pady=(0,4))

    # log
    lf = tk.Frame(right, bg=BG)
    lf.pack(fill="both", expand=True)
    log_txt = tk.Text(lf, font=FM, bg="#0d1117", fg=TEXT,
                      state="disabled", wrap="none", relief="flat")
    sy = tk.Scrollbar(lf, orient="vertical",   command=log_txt.yview)
    sx = tk.Scrollbar(lf, orient="horizontal", command=log_txt.xview)
    log_txt.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
    sy.pack(side="right",  fill="y")
    sx.pack(side="bottom", fill="x")
    log_txt.pack(fill="both", expand=True)
    for c in [TEXT, ACCENT, GREEN, RED, YELLOW, DIM]:
        log_txt.tag_configure(c, foreground=c)

    # manual cmd
    cr = tk.Frame(right, bg=BG)
    cr.pack(fill="x", pady=4)
    cmd_target = tk.StringVar(value="HMI")
    ttk.Combobox(cr, textvariable=cmd_target, values=["HMI","HYDRAULIC"],
                 width=11, font=FM, state="readonly").pack(side="left", padx=(0,4))
    cmd_var = tk.StringVar()
    ce = tk.Entry(cr, textvariable=cmd_var, font=FM, bg=BG3, fg=TEXT,
                  insertbackground=ACCENT, relief="flat")
    ce.pack(side="left", expand=True, fill="x", padx=4)
    ce.bind("<Return>", lambda e: send_cmd())
    tk.Button(cr, text="Send", command=send_cmd,
              bg=BG3, fg=ACCENT, font=FM, relief="flat", padx=8).pack(side="left")

    br2 = tk.Frame(right, bg=BG)
    br2.pack(fill="x")
    tk.Button(br2, text="💾 Save log", command=save_log,
              bg=BG3, fg=TEXT, font=FM, relief="flat", padx=8).pack(side="left", padx=(0,4))
    tk.Button(br2, text="🗑 Clear",
              command=lambda: [log_txt.configure(state="normal"),
                               log_txt.delete("1.0","end"),
                               log_txt.configure(state="disabled")],
              bg=BG3, fg=TEXT, font=FM, relief="flat", padx=8).pack(side="left")

    # init
    refresh_ports()
    log("Water Bar Tester v2.0 ready.", ACCENT)
    log(f"Discovered {len(all_tests)} tests: {', '.join(all_tests.keys())}", DIM)
    log("Connect HMI and optionally Hydraulic, then RUN.", DIM)

    root.mainloop()


# ════════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════════
def run_cli(args):
    from core.hmi_serial       import HmiSerial
    from core.hydraulic_serial import HydraulicSerial
    from runner.runner         import TestRunner

    cfg = {
        "hmi_port":        args.hmi_port,
        "hydraulic_port":  args.hydr_port,
        "target_liters":   args.liters,
        "press_duration_ms": 1000,
        "pour_wait_sec":   40,
        "tolerance_ml":    150,
        "hot_min_temp":    85,
        "cold_max_temp":   11,
        "filter_max_liters": 5000,
        "use_hydraulic":   bool(args.hydr_port),
    }
    hmi  = HmiSerial(args.hmi_port, 115200)
    hydr = HydraulicSerial(args.hydr_port, 115200) if args.hydr_port else None
    try:
        hmi.connect()
        if hydr:
            hydr.connect()
        runner = TestRunner(hmi, hydr, cfg)
        tests  = args.tests.split(",") if args.tests else None
        runner.run(tests)
        print(runner.generate_report())
    finally:
        hmi.disconnect()
        if hydr:
            hydr.disconnect()


# ════════════════════════════════════════════════════════════════════════
#  ENTRY
# ════════════════════════════════════════════════════════════════════════
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cli",       action="store_true")
    p.add_argument("--hmi-port",  default="COM5")
    p.add_argument("--hydr-port", default=None)
    p.add_argument("--liters",    type=float, default=1)
    p.add_argument("--tests",     default=None)
    args = p.parse_args()
    if args.cli:
        run_cli(args)
    else:
        run_gui()

if __name__ == "__main__":
    main()