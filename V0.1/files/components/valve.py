"""
valve.py — Valve component for the Virtual Rocket A simulator.

Unlike tank.py (continuous physics), a valve is fundamentally a DISCRETE
state machine — this is the direct lesson from Livingstone/PITEX: aerospace
telemetry isn't just floating-point sensor values, it's also states like
OPEN / CLOSED / FAULT (brief section 16). This file models that.

Sources:
  [LV]  The Livingstone Model of a Main Propulsion System (Bajwa & Sweet, 2002)
        -> nominal/fault modes + fault ranks (Table 1)
  [TR]  Transient Region Coverage in PITEX (Balaban et al., 2004)
        -> the "opening"/"closing" intermediate transient states and their
           timeout-based resolution logic
  [FC]  fault_catalog.csv (this project) — real PITEX-tested fault scenarios
        with injection timestamps, used to drive which faults are plausible
"""

from dataclasses import dataclass, field
from enum import Enum


class ValveState(str, Enum):
    # Steady states [LV]
    OPEN = "open"
    CLOSED = "closed"
    # Transient states [TR] — the "loosely constrained intermediate modes"
    OPENING = "opening"
    CLOSING = "closing"
    # Fault states [LV] — with their Livingstone fault rank in the comment
    STUCK_OPEN = "stuck_open"      # rank 2-3 depending on component, [LV] Table 1
    STUCK_CLOSED = "stuck_closed"  # rank 1-2 depending on component, [LV] Table 1
    UNKNOWN_FAULT = "unknown_fault"  # rank 4-6, catch-all mode, [LV]


@dataclass
class ValveConfig:
    """Static parameters for a valve type. Transition time is the one number
    NOT given a specific value in the papers (PITEX only says valves take
    "tens to hundreds of milliseconds" generically) — so a default is used
    and flagged as an ASSUMPTION rather than cited."""

    component_id: str            # e.g. "sv31", "vr01" — matches data_dictionary.csv
    component_name: str
    transition_time_seconds: float = 0.5   # ASSUMPTION — PITEX transient monitor
                                            # used a 0.5s check interval [TR], reused here
    stuck_open_rank: int = 2      # [LV] Table 1, varies by component — override per-instance
    stuck_closed_rank: int = 1    # [LV] Table 1


@dataclass
class Valve:
    """A single valve with true (hidden) discrete state.

    As with Tank, this object holds GROUND TRUTH. A downstream Sensor/Monitor
    layer (not yet built) is responsible for turning `.state` into a noisy,
    possibly-delayed *observation* — Livingstone/PITEX never diagnosed off
    the true state directly, only off monitored microswitch/pressure readings.
    """

    config: ValveConfig
    state: ValveState = ValveState.CLOSED
    _commanded_state: ValveState = field(default=ValveState.CLOSED, repr=False)
    _transition_elapsed: float = field(default=0.0, repr=False)
    _fault_active: ValveState = field(default=None, repr=False)  # set by inject_fault()

    # ---- commanding (nominal operation) ----
    def command(self, target: ValveState):
        """Issue an OPEN/CLOSED command. Mirrors Livingstone's rule [LV]:
        nominal-mode transitions only happen as a result of an explicit
        controller command, never spontaneously."""
        if target not in (ValveState.OPEN, ValveState.CLOSED):
            raise ValueError("Can only command OPEN or CLOSED")
        if self._fault_active is not None:
            return  # a stuck/faulted valve does not respond to commands [LV]

        self._commanded_state = target
        self._transition_elapsed = 0.0
        self.state = ValveState.OPENING if target == ValveState.OPEN else ValveState.CLOSING

    # ---- fault injection (see fault_catalog.csv for real injection timestamps) ----
    def inject_fault(self, fault: ValveState):
        """Faults can occur from ANY mode, at any time — [LV] explicitly states
        fault-mode transitions are not modeled as command-driven, unlike
        nominal transitions."""
        if fault not in (ValveState.STUCK_OPEN, ValveState.STUCK_CLOSED, ValveState.UNKNOWN_FAULT):
            raise ValueError("Not a recognized fault mode")
        self._fault_active = fault
        self.state = fault

    def clear_fault(self):
        self._fault_active = None
        self.state = self._commanded_state

    # ---- per-tick update ----
    def update(self, dt_seconds: float):
        """Advances the valve through its transient period, if one is active.

        This directly implements the PITEX Transient Framework idea [TR]:
        rather than instantly snapping open<->closed, the valve spends
        `transition_time_seconds` in an OPENING/CLOSING state first. Any
        sensor reading taken during that window is expected to be unsettled
        — that's the "transient region" the PITEX papers spent significant
        effort handling.
        """
        if self._fault_active is not None:
            return  # faulted valves don't progress through transitions

        if self.state in (ValveState.OPENING, ValveState.CLOSING):
            self._transition_elapsed += dt_seconds
            if self._transition_elapsed >= self.config.transition_time_seconds:
                self.state = self._commanded_state  # snap to final steady state
                self._transition_elapsed = 0.0

    def is_settled(self) -> bool:
        """True once the valve has left its transient period — this is the
        exact signal PITEX's transient monitor was built to detect [TR]."""
        return self.state in (ValveState.OPEN, ValveState.CLOSED,
                               ValveState.STUCK_OPEN, ValveState.STUCK_CLOSED,
                               ValveState.UNKNOWN_FAULT)

    def flow_allowed(self) -> bool:
        """Whether propellant/pressurant can currently flow through this valve.
        Used by Tank/pressurization logic elsewhere to decide if flow=0 or flow>0,
        matching the nominal-mode constraints in [LV] Table 1
        (e.g. 'closed: flow=0')."""
        return self.state in (ValveState.OPEN, ValveState.STUCK_OPEN)


# Pre-built instances for the components most referenced in fault_catalog.csv,
# with per-component fault ranks pulled from data_dictionary.csv.
SV31 = Valve(ValveConfig(component_id="sv31", component_name="LOX Tank Vent Relief Servo Valve",
                          stuck_open_rank=3, stuck_closed_rank=2))
VR01 = Valve(ValveConfig(component_id="vr01", component_name="LOX Vent Relief Valve",
                          stuck_open_rank=2, stuck_closed_rank=1))
SV03 = Valve(ValveConfig(component_id="sv03", component_name="LOX Tank Pressurization Valve",
                          stuck_open_rank=3, stuck_closed_rank=2))
PV03 = Valve(ValveConfig(component_id="pv03", component_name="LOX Feed/Engine Inlet Valve",
                          stuck_open_rank=2, stuck_closed_rank=1))
SV02 = Valve(ValveConfig(component_id="sv02", component_name="RP-1 Tank Pressurization Valve",
                          stuck_open_rank=3, stuck_closed_rank=2))
VR06 = Valve(ValveConfig(component_id="vr06", component_name="RP-1 Vent Relief Valve",
                          stuck_open_rank=2, stuck_closed_rank=1))
