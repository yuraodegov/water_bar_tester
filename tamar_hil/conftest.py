"""
conftest.py — Tamar HC HIL test suite — 3-connection setup

Connection map:
  Terminal 1 (--port-sim)  -> Nucleo-G071RB simulator  (sensor injection + output monitor)
  Terminal 2 (--port-hc)   -> HC STM32 terminal UART   (P1-2/3, ADDON_TX/RX, simulate=63...)
  Terminal 3 (--port-hmi)  -> HMI ESP32 terminal        (press 1..9, get_param, set_param...)

Run with all three connections:
    pytest tamar_hil/ --port-sim COM3 --port-hc COM4 --port-hmi COM5 -m "not slow" -v

Run with simulator only (sensor/monitor tests only):
    pytest tamar_hil/ --port-sim COM3 -m "not slow and not needs_hc and not needs_hmi" -v
"""

import pytest
import time
from tamar_hil.simulator import SimulatorUART
from tamar_hil.hc_terminal import HCTerminal
from tamar_hil.hmi_terminal import HmiTerminal


# ─────────────────────────────────────────────────────────────────────────────
#  CLI options
# ─────────────────────────────────────────────────────────────────────────────

def pytest_addoption(parser):
    parser.addoption("--port-sim", "--port", action="store", default="COM3",
                     help="Nucleo simulator serial port (sensor injection + monitor)")
    parser.addoption("--port-hc", action="store", default=None,
                     help="HC STM32 terminal UART (P1-2/3)")
    parser.addoption("--port-hmi", action="store", default=None,
                     help="HMI ESP32 terminal — press 1..9 button simulation")


# ─────────────────────────────────────────────────────────────────────────────
#  Markers
# ─────────────────────────────────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line("markers", "slow: test requires extended time")
    config.addinivalue_line("markers", "needs_hc: test requires --port-hc")
    config.addinivalue_line("markers", "needs_hmi: test requires --port-hmi")
    config.addinivalue_line("markers", "hc_errors: test triggers HC error state")
    config.addinivalue_line("markers", "hc_critical: test triggers HC error requiring reboot")
    config.addinivalue_line("markers", "with_ptd: test exercises push-to-drink safety lock")


# ─────────────────────────────────────────────────────────────────────────────
#  Session-scoped fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def sim(request):
    """Terminal 1 — Nucleo-G071RB HIL simulator (sensors + output monitor)."""
    port = request.config.getoption("--port-sim")
    with SimulatorUART(port) as s:
        time.sleep(0.5)
        s.reset()
        yield s


@pytest.fixture(scope="session")
def hc(request):
    """Terminal 2 — HC STM32 terminal UART. None if --port-hc not given."""
    port = request.config.getoption("--port-hc")
    if not port:
        yield None
        return
    with HCTerminal(port) as t:
        t.enable_simulation()
        t.heating_on()
        yield t


@pytest.fixture(scope="session")
def hmi(request):  # noqa: F811
    """Terminal 3 — HMI ESP32 terminal. None if --port-hmi not given."""
    port = request.config.getoption("--port-hmi")
    if not port:
        yield None
        return
    with HmiTerminal(port) as h:
        yield h


# ─────────────────────────────────────────────────────────────────────────────
#  Auto-skip markers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _check_connection_requirements(request):
    if request.node.get_closest_marker("needs_hc"):
        if not request.config.getoption("--port-hc"):
            pytest.skip("Requires --port-hc (HC terminal, Terminal 2)")
    if request.node.get_closest_marker("needs_hmi"):
        if not request.config.getoption("--port-hmi"):
            pytest.skip("Requires --port-hmi (HMI terminal, Terminal 3)")


# ─────────────────────────────────────────────────────────────────────────────
#  Per-test reset / recovery (autouse)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def test_recovery(request, sim, hc, hmi):
    # ── SETUP ──
    sim.reset_output_monitor()
    sim.set_all_electrodes(wet=True)
    sim.set_flow(0.0)

    yield   # test runs here

    # ── TEARDOWN ──
    sim.set_flow(0.0)
    markers = [m.name for m in request.node.iter_markers()]

    if "hc_critical" in markers:
        _full_recovery(sim, hc)
    elif "hc_errors" in markers:
        if hc:
            _clear_hc_errors(hc)
        sim.reset()
        sim.set_all_electrodes(wet=True)
        time.sleep(0.5)
    else:
        sim.reset()
        sim.set_all_electrodes(wet=True)
        time.sleep(0.2)


# ─────────────────────────────────────────────────────────────────────────────
#  Recovery helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clear_hc_errors(hc: HCTerminal) -> None:
    import re
    try:
        resp = hc.get_errors()
        for eid in re.findall(r'(?:ERR|error)[^0-9]*?(\d+)', resp, re.IGNORECASE):
            try:
                hc.clear_error(int(eid))
            except Exception:
                pass
    except Exception:
        pass
    time.sleep(0.3)


@pytest.fixture(autouse=True)
def _manage_push_to_drink(request, hmi):
    if hmi is None:
        yield
        return

    test_ptd = bool(request.node.get_closest_marker("with_ptd"))
    was_on = False

    if not test_ptd:
        was_on = hmi.is_push_to_drink_enabled()
        if was_on:
            hmi.set_push_to_drink(False)
    yield
    if not test_ptd:
        if was_on:
            hmi.set_push_to_drink(True)


def _full_recovery(sim: SimulatorUART, hc: HCTerminal) -> None:
    try:
        sim.reset()
    except Exception:
        pass
    if hc:
        try:
            hc.reset()
            time.sleep(2.5)
            hc.enable_simulation()
            hc.heating_on()
        except Exception:
            pass
    sim.set_all_electrodes(wet=True)
    time.sleep(0.5)
