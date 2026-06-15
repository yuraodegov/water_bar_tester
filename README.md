# Water Bar Tester

Test automation tool for a Strauss Water water bar / dispenser. It drives the
device over two serial ports — the **HMI** controller (ESP32, button/counter
side) and the **HC** Hydraulic Controller (Tamar HC, heater/cooler/valve
side) — runs a suite of functional and parameter checks, and produces a
pass/fail report. It ships both as a desktop GUI and a headless CLI for CI.

---

## Features

- **Dual-port control** — talks to the HMI (buttons, counters, eeprom params)
  and the HC (status, temperatures, heater/cooler/valve state machine, eeprom
  params) at the same time.
- **~194 tests** across HMI, HC, cross-device and long-term categories,
  auto-discovered from the `tests/` folder.
- **Per-parameter baseline checks** — every HC and HMI eeprom parameter is its
  own test with an editable IL / US baseline (exact-match).
- **MONITOR mode** — long-term dispense loop that polls counters and HC status,
  then prints a summary (liters by type, filter minutes, dispense count).
- **GUI** with a popup log, collapsible test groups, profile/driver selectors
  and a manual-command field.
- **CLI** for headless runs and CI.
- **GitHub Actions** pipeline: lint → syntax check → Windows `.exe` build.

---

## Requirements

- Python 3.11
- Windows (for real device runs and the packaged `.exe`); the CLI and the lint
  / syntax stages also run on Linux.

Python dependencies (`requirements.txt`):

```
pyserial>=3.5
pyinstaller>=6.0
```

Install:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

---

## Quick start

### GUI

```powershell
python water_bar_tester.py
```

1. Set the HMI port (required) and the Hydraulic/HC port (optional).
2. Pick the profile (IL / US) and the hydraulic driver mode.
3. Connect both devices.
4. Press **RUN TESTS**, or **MONITOR** for a long-term run.

Use **Open Log** for the full serial transcript, and the manual-command field
to send a single command to either device (pick HMI or HYDRAULIC as target).

### CLI

```powershell
python water_bar_tester.py --cli --hmi-port COM8 --hydr-port COM24 --profile IL
```

CLI options:

| Flag | Default | Description |
|------|---------|-------------|
| `--cli` | off | Run headless (no GUI). |
| `--hmi-port` | `COM5` | HMI serial port. |
| `--hydr-port` | `None` | HC / hydraulic serial port (optional). |
| `--hydr-mode` | `HCDriver` | Hydraulic driver: `HCDriver` or `HydraulicSerial`. |
| `--profile` | `IL` | Parameter baseline profile: `IL` or `US`. |
| `--liters` | `1` | Target dispense volume (liters). |
| `--tests` | `None` | Comma-separated test-name filter (substring match). |

---

## Project layout

```
water_bar_tester/
├── water_bar_tester.py        # GUI + CLI entry point
├── requirements.txt
├── core/
│   ├── base_serial.py         # BaseSerial: connect / send / ANSI strip / logging
│   ├── hmi_serial.py          # HmiSerial: buttons, counters, get/set_param
│   ├── hydraulic_serial.py    # HydraulicSerial: simple pour / get_temp driver
│   ├── hc_driver.py           # HCDriver: Tamar HC status / params / temps
│   └── hc_config.py           # IL / US Profile objects + PROFILES dict
├── runner/
│   └── runner.py              # discover_tests() + TestRunner + report
├── tests/
│   ├── test_base.py           # BaseTest, TestResult, _pass / _fail helpers
│   └── test_*.py              # individual test suites (see below)
└── .github/workflows/build.yml
```

---

## Architecture

### Serial layer

`BaseSerial` handles the connection, writing commands, reading replies,
stripping ANSI / ESP-IDF log colour codes, and logging. Two device drivers
build on it:

- **`HmiSerial`** — the ESP32 HMI. Presses virtual buttons (`press <n> <ms>`),
  reads counters (`get_counter <id>`), and reads/writes eeprom parameters by
  numeric id (`get_param <id>` / `set_param <id> <value>`). Counter parsing
  matches the specific `[NN]` index to avoid picking up async `SET [..]` log
  lines.
- **`HCDriver`** — the Tamar HC. Reads `status` (inputs, outputs, sub-module
  states), parses temperatures from the status block, reads all eeprom params
  from the bare `get_param` dump, and calls dedicated commands such as
  `heater_calibration`. The HC streams async log lines continuously; commands
  that parse output use a small collision-retry wrapper so an async byte glued
  to a command does not turn into a spurious `Bad command`.

`HydraulicSerial` is a simpler alternative hydraulic driver, selectable via
`--hydr-mode`.

### Test framework

Every test subclasses `BaseTest` and returns a `TestResult` via `_pass(...)`
or `_fail(...)`. `discover_tests()` walks the `tests/` package, imports each
module, and collects all `BaseTest` subclasses automatically — so adding a
test file (or a generated class) is enough to register it. Files that fail to
import are skipped with a `[WARN]` rather than breaking the whole run.

`TestRunner` runs the selected tests, supports a stop flag (the GUI STOP
button), and `generate_report()` prints an ordered summary: totals, pass rate,
failed-first list with reasons, then the passed list.

---

## Test suites

| File | Area | Notes |
|------|------|-------|
| `test_hmi_buttons.py` | HMI | All 8 buttons respond, combinations, long press. |
| `test_hmi_counters.py` | HMI | Counter monotonicity and delta consistency. |
| `test_hmi_filter_flow.py` | HMI | Filter counter / minutes / status. |
| `test_hmi_params.py` | HMI | Param dump, range rejection, set/get round-trip. |
| `test_dispense.py` | HMI | Per-type volumes (Hot Glass 150, Cold/Amb Glass 200, Jugs 1000) in DELTA mode. |
| `test_filter_counter.py` | HMI | Filter_ml tracking. |
| `test_temperature.py` | HC | Temperature read. |
| `test_hc_state_machine.py` | HC | Power-on → Idle, Extra-Hot, Shabbat transitions. |
| `test_hc_idle_heating.py` | HC | Idle-heating setpoints and timeouts. |
| `test_hc_extra_hot.py` | HC | Extra-hot stage duties, boil-to-setpoint, timeout. |
| `test_hc_hot_dispense.py` | HC | Dispense duties, hot valve open/close. |
| `test_hc_hot_filling.py` | HC | Hot-fill start/stop, overfill, timeout. |
| `test_hc_cooler.py` | HC | Compressor on/off, hysteresis, fan PWM. |
| `test_hc_errors.py` | HC | Dry burn, leakage, electrodes, reset behaviour. |
| `test_hc_calibration.py` | HC | Calibration flag + calibration params. |
| `test_hc_shabbat.py` | HC | Prepare / operation shabbat params. |
| `test_hc_params_check.py` | HC | One exact-match test per HC eeprom param (IL/US). |
| `test_hmi_params_check.py` | HMI | One exact-match test per HMI eeprom param. |
| `test_cross_temperature.py` | Cross | HMI vs HC temperature agreement. |
| `test_long_term_volume.py` | Long-term | Repeated button-cycle volume run. |
| `test_monitor_run.py` | Long-term | MONITOR loop with periodic polling + summary. |

Some HC state-machine and shabbat tests are marked `[needs HMI]` and are
**SKIPPED** automatically — they require a manual trigger from the HMI screen.

---

## Parameter baseline checks

`test_hc_params_check.py` and `test_hmi_params_check.py` generate **one test
per parameter**. Each test reads the live value and compares it to a baseline
with an exact match. Baselines live in editable dicts at the top of each file,
so when a default legitimately changes you just edit the number.

- **HC** keeps two baselines — `IL_DEFAULTS` and `US_DEFAULTS` — because the
  IL-220 and US-115 units differ on several heater duty / setpoint params and
  on `cooler_shabbat_timeout`. The active profile comes from `--profile` /
  the GUI selector.
- **HMI** keeps a single `HMI_DEFAULTS` dict keyed by numeric param id, each
  entry being `(expected_value, name)`.

> Note: some HMI entries are user settings that legitimately change at runtime
> (language, region, wake-up times, child lock). Remove any id from
> `HMI_DEFAULTS` you do not want enforced.

To add or remove a parameter check, just edit the baseline dict — the test
classes are generated from its keys.

---

## Profiles (IL / US)

`core/hc_config.py` defines `IL` and `US` `Profile` objects and a `PROFILES`
dict. The profile selects which parameter baselines apply and feeds
profile-dependent test expectations. Known differences captured from real
device dumps:

| Param | IL-220 | US-115 |
|-------|--------|--------|
| `heater_lbs` | 50 | 90 |
| `heater_hbs` | 70 | 100 |
| `heater_hdisp` | 70 | 100 |
| `heater_isp` | 10 | 50 |
| `heater_sihp` | 10 | 20 |
| `heater_hlsp` | 75 | 80 |
| `heater_llsp` | 65 | 75 |
| `heater_spmh1..3` | 50 / 20 / 10 | 100 / 100 / 100 |

All other HC parameters are identical between the two profiles.

---

## Continuous integration

`.github/workflows/build.yml` runs on push / PR to `main` and on release:

1. **lint** — `flake8 . --max-line-length=120 --exclude=.github`
2. **check** — parses every `.py` file to catch syntax / import errors.
3. **build-exe** — on Windows, packages a single-file `WaterBarTester.exe`
   with PyInstaller (bundling `tests`, `core`, `runner` and the pyserial
   hidden imports), uploads it as an artifact, and attaches it to GitHub
   Releases.

Run the same checks locally before pushing:

```powershell
flake8 . --max-line-length=120 --exclude=.github,venv
python -c "from runner.runner import discover_tests; print(len(discover_tests()))"
```

The discover count should match the number of tests in `tests/` (currently
194).

---

## Building the executable locally

```powershell
pyinstaller --onefile --windowed --name WaterBarTester `
  --add-data "tests;tests" `
  --add-data "core;core" `
  --add-data "runner;runner" `
  --hidden-import serial `
  --hidden-import serial.tools `
  --hidden-import serial.tools.list_ports `
  water_bar_tester.py
```

The result is `dist/WaterBarTester.exe`.

---

## Conventions

- All code comments are written in **English only**.
- Line length is capped at **120** for flake8.
- New tests go in `tests/` as `BaseTest` subclasses and are picked up
  automatically — no manual registration needed.