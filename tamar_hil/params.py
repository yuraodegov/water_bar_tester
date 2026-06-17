"""
params.py — FW PRD D001628 Rev 20.0 parameter definitions
Tamar Shabbat — Hydraulic Controller firmware parameters (IL default).

Source: Firmware PRD - Tamar-Shabbat.docx, Rev 20.0 (19/05/2026)
All temperatures in °C.  All duty cycles in %.  All times in minutes (unless noted).

Usage in tests:
    from tamar_hil.params import P          # IL default
    from tamar_hil.params import IL, US     # explicit region
"""

from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────────────────────
#  Full parameter set — covers all flowcharts
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TamarParams:
    """All PRD D001628 parameters for one region variant."""

    # ── Temperature thresholds (°C) ──────────────────────────────────────────
    TLLSP:   float   # Abs. lower setpoint — T_tank below this → Extra Hot
    LLSP:    float   # Lower calib. setpoint — Main ON below LLSP in Idle
    HLSP:    float   # Upper calib. setpoint — Main OFF at/above HLSP in Idle
    BSP:     float   # Boiling setpoint — T_boost target in Extra Hot / Wash
    LBSP:    float   # Low boiling SP = BSP - 3°C (hysteresis lower bound)
    BTSP0:   float   # Tank threshold 0 — SPMH2 gate (Prep Shabbat / Wash)
    BTSP1:   float   # Tank threshold 1 — LBS/HBS gate in POST Extra Hot
    B_OFFSET: float  # Gate offset: T_terminate = BSP - B_OFFSET
    BSPS:    float   # Shabbat boiling setpoint (T_tank target in Shabbat)
    Tdry:    float   # Dry-burn safety: T_boost above this → emergency stop

    # ── Derived thresholds (computed) ─────────────────────────────────────────
    @property
    def Ttank_terminate(self) -> float:
        """T_tank >= this exits POST EXTRA HOT (= BSP - B_OFFSET)."""
        return self.BSP - self.B_OFFSET

    @property
    def T_terminate(self) -> float:
        """Alias for Ttank_terminate."""
        return self.BSP - self.B_OFFSET

    # ── Heater duty cycles (%) ────────────────────────────────────────────────
    ISP:   int    # Idle small heater duty
    IHP:   int    # Idle main heater duty
    OSPS:  int    # Extra Hot / Washing small heater duty (constant)
    OSPm:  int    # Extra Hot main heater entry duty (= 100%)
    LBS:   int    # Low boiling support (T_tank >= BTSP1 in POST EH)
    HBS:   int    # High boiling support (T_tank <  BTSP1 in POST EH)
    SPMH1: int    # Prep-to-Shabbat / Washing heater stage 1 (T_boost > BSP)
    SPMH2: int    # Prep-to-Shabbat / Washing heater stage 2 (T_tank > BTSP0)
    SPMH3: int    # Prep-to-Shabbat / Washing heater stage 3 (T_tank > T_terminate)
    SIHP:  int    # Shabbat operation main heater duty (every SHP cycle)

    # ── Timer durations (minutes) ─────────────────────────────────────────────
    EH_TO_min:    int   # Extra Hot overall timeout
    FT_min:       int   # POST Extra Hot / Prep-Shabbat "boiling support" duration
    IDLE_TO_min:  int   # Idle heating timeout (Err158/159)
    SHP_min:      int   # Shabbat operation cycle period (60 min)
    STO_min:      int   # Shabbat operation "twice-in-row" timeout
    FTS_min:      int   # Fill-to-Shabbat timeout (Prep to Shabbat FTS)
    FILL_TO_min:  int   # Hot fill timeout (40 min in Prep to Shabbat)
    WASH_DISP_L:  float # Washing mode: total dispense target (7 L)

    # ── Flow ──────────────────────────────────────────────────────────────────
    FLOW_PULSES_PER_LITER: int    # 518 pulses / litre  (1.93 mL/pulse)
    FLOW_NOMINAL_LPM:      float  # Nominal flow rate used in fill tests

    # ── Valve timing spec (ms) ────────────────────────────────────────────────
    VALVE_OPEN_PULSE_MS: int    # Opening DC pulse duration = 1000ms
    VALVE_HOLD_FREQ_HZ:  float  # Holding frequency = 500Hz
    VALVE_HOLD_DUTY_PCT: float  # Holding duty = 50%
    VALVE_SEQ_DELAY_MS:  int    # Inter-valve sequence delay = 200ms
    SPEC_TOL_PCT:        float  # ±20% on all spec values

    # ── Calibration (currently DISABLED in shipping FW) ──────────────────────
    Cdelay_s:  int      # 20 s
    CMT_s:     int      # 5 s
    SDEVmax:   float    # 0.5°C


# ─────────────────────────────────────────────────────────────────────────────
#  IL (Israel) — default region
# ─────────────────────────────────────────────────────────────────────────────
IL = TamarParams(
    # Temperature thresholds
    TLLSP    = 50.0,
    LLSP     = 65.0,   # FW code: < 65 (not 70 — code comment verified)
    HLSP     = 75.0,
    BSP      = 96.0,
    LBSP     = 93.0,   # BSP - 3
    BTSP0    = 80.0,
    BTSP1    = 80.0,   # PRD Rev 18
    B_OFFSET = 3.0,
    BSPS     = 94.0,   # Shabbat boiling setpoint
    Tdry     = 105.0,  # Dry-burn emergency stop

    # Duty cycles
    ISP    = 10,
    IHP    = 10,
    OSPS   = 100,
    OSPm   = 100,
    LBS    = 50,
    HBS    = 70,
    SPMH1  = 50,
    SPMH2  = 20,
    SPMH3  = 10,
    SIHP   = 10,

    # Timers
    EH_TO_min   = 60,
    FT_min      = 10,
    IDLE_TO_min = 200,
    SHP_min     = 60,
    STO_min     = 50,   # Shabbat "twice-in-row" timeout
    FTS_min     = 75,   # Fill-to-Shabbat timeout
    FILL_TO_min = 40,   # Fill timeout in Prep-to-Shabbat
    WASH_DISP_L = 7.0,  # 7 litres total dispense in washing mode

    # Flow
    FLOW_PULSES_PER_LITER = 518,    # 1000 / 1.93 mL/pulse
    FLOW_NOMINAL_LPM      = 1.6,

    # Valve timing
    VALVE_OPEN_PULSE_MS = 1000,
    VALVE_HOLD_FREQ_HZ  = 500.0,
    VALVE_HOLD_DUTY_PCT = 50.0,
    VALVE_SEQ_DELAY_MS  = 200,
    SPEC_TOL_PCT        = 20.0,

    # Calibration
    Cdelay_s = 20,
    CMT_s    = 5,
    SDEVmax  = 0.5,
)

# ─────────────────────────────────────────────────────────────────────────────
#  US (United States)
# ─────────────────────────────────────────────────────────────────────────────
US = TamarParams(
    TLLSP    = 60.0,
    LLSP     = 75.0,
    HLSP     = 80.0,
    BSP      = 95.0,
    LBSP     = 92.0,
    BTSP0    = 80.0,
    BTSP1    = 80.0,
    B_OFFSET = 3.0,
    BSPS     = 92.0,
    Tdry     = 105.0,
    ISP      = 10,
    IHP      = 10,
    OSPS     = 100,
    OSPm     = 100,
    LBS      = 90,
    HBS      = 100,
    SPMH1    = 50,
    SPMH2    = 20,
    SPMH3    = 10,
    SIHP     = 10,
    EH_TO_min    = 120,
    FT_min       = 10,
    IDLE_TO_min  = 200,
    SHP_min      = 60,
    STO_min      = 50,
    FTS_min      = 75,
    FILL_TO_min  = 40,
    WASH_DISP_L  = 7.0,
    FLOW_PULSES_PER_LITER = 518,
    FLOW_NOMINAL_LPM      = 1.6,
    VALVE_OPEN_PULSE_MS = 1000,
    VALVE_HOLD_FREQ_HZ  = 500.0,
    VALVE_HOLD_DUTY_PCT = 50.0,
    VALVE_SEQ_DELAY_MS  = 200,
    SPEC_TOL_PCT        = 20.0,
    Cdelay_s = 20,
    CMT_s    = 5,
    SDEVmax  = 0.5,
)

# ─────────────────────────────────────────────────────────────────────────────
#  Default — import P for IL in all tests
# ─────────────────────────────────────────────────────────────────────────────
P = IL

# ─────────────────────────────────────────────────────────────────────────────
#  Shared constants (same for both regions)
# ─────────────────────────────────────────────────────────────────────────────
HEATER_MAIN_CYCLE_S  = 20     # Main heater PWM cycle = 20 s
HEATER_SMALL_CYCLE_S =  2     # Small heater PWM cycle = 2 s
DUTY_TOLERANCE_PCT   = 20     # ±20% tolerance on all duty measurements
SETTLE_CYCLES        =  3     # Min full cycles before measuring duty

# ─────────────────────────────────────────────────────────────────────────────
#  HC System constants — from old_main.h (HC firmware)
# ─────────────────────────────────────────────────────────────────────────────
class HC_SYS:
    """
    HC firmware system constants extracted from old_main.h.
    Use these in tests that need to account for HC task timing.
    """
    # Task intervals (ms)
    HIGH_PRIORITY_INTERVAL_MS = 10    # HC processes electrodes/flow every 10ms
    LOW_PRIORITY_INTERVAL_MS  = 100   # HC updates UI/HMI every 100ms

    # HMI temperature update threshold (millidegrees)
    # HC only sends temp update to HMI when change >= this value
    HMI_UPDATE_TEMP_DIF_MDEG  = 500   # 0.5°C minimum step for HMI to react

    # Simulation mode flags (production firmware — all disabled)
    # These are overridden by terminal: simulate=63
    ELECTRODE_SIMULATOR       = False
    FLOW_SIMULATOR            = False
    COOLER_SIMULATOR          = False
    HEATER_SIMULATOR          = False

    # Minimum temperature change step for simulator DAC injection
    # DAC change must be >= 0.5°C for HC to register and notify HMI
    MIN_TEMP_STEP_DEG         = 0.5

    # After changing a simulated input, allow HC task to process it
    HC_REACTION_DELAY_S       = 0.02   # 2× high-priority interval (20ms)
