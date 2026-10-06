"""
faults.py — Drives fault injection for the Virtual Rocket A simulator using
the real PITEX fault scenarios extracted into fault_catalog.csv.

This file does not invent any fault timing or fault type — every entry in
FAULT_ACTIONS below is a direct translation of one row in fault_catalog.csv
(itself extracted from PITEX Table 1, Real-World Challenges paper) into a
concrete call against the RocketA wiring built in rocket.py.

IMPORTANT — coverage is intentionally partial. fault_catalog.csv has 24
scenarios; only 14 are mappable onto what v1 of RocketA actually models
(7 valves + a handful of discrete sensors). The other 10 reference
regulators, dual-sensor faults, and the aft LOX tank — none of which exist
in the simulator yet. Those are listed explicitly in UNMODELED_SCENARIOS
rather than silently ignored, so the gap is visible in code, not just in
someone's memory.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from components.valve import ValveState


@dataclass
class FaultScenario:
    scenario_id: int
    component_id: str
    description: str
    injection_time_s: float
    nasa_reference: str


def load_fault_catalog(path: str = "fault_catalog.csv") -> list[FaultScenario]:
    scenarios = []
    with open(path) as f:
        for row in csv.DictReader(f):
            scenarios.append(FaultScenario(
                scenario_id=int(row["scenario_id"]),
                component_id=row["component_id"],
                description=row["description"],
                injection_time_s=float(row["fault_injection_time_seconds"]),
                nasa_reference=row["nasa_reference"],
            ))
    return scenarios


# ---------------------------------------------------------------------------
# Mapping: scenario_id -> function(rocket) that applies the fault.
# Built by hand against fault_catalog.csv's `description` text, not parsed
# automatically — free-text parsing of "sticks closed" vs "fails closed"
# is fragile and not worth trusting for something that ends up as ground
# truth in your dataset. Each mapping is one line, easy to audit against
# the CSV directly.
# ---------------------------------------------------------------------------

FAULT_ACTIONS: dict[int, Callable] = {
    # --- LOX feed/vent valves, directly modeled in rocket.py ---
    1:  lambda r: r.inject_valve_fault("pv03", ValveState.STUCK_CLOSED),   # PV03 sticks closed
    3:  lambda r: r.inject_valve_fault("sv31", ValveState.STUCK_OPEN),    # SV31 sticks open
    4:  lambda r: r.inject_valve_fault("sv31", ValveState.STUCK_OPEN),    # SV31 fails open
    5:  lambda r: r.inject_valve_fault("vr01", ValveState.STUCK_OPEN),    # VR01 sticks open
    6:  lambda r: r.inject_valve_fault("vr01", ValveState.STUCK_OPEN),    # VR01 fails open
    7:  lambda r: r.inject_valve_fault("sv31", ValveState.STUCK_CLOSED),  # SV31 sticks closed
    8:  lambda r: r.inject_valve_fault("sv31", ValveState.STUCK_CLOSED),  # SV31 fails closed
    9:  lambda r: r.inject_valve_fault("vr01", ValveState.STUCK_CLOSED),  # VR01 sticks closed
    12: lambda r: r.inject_valve_fault("sv03", ValveState.STUCK_OPEN),    # SV03 sticks open
    13: lambda r: r.inject_valve_fault("sv03", ValveState.STUCK_CLOSED),  # SV03 sticks closed

    # --- RP-1 feed/vent/pressurization valves ---
    16: lambda r: r.inject_valve_fault("pv02", ValveState.STUCK_CLOSED),  # PV02 fails closed
    17: lambda r: r.inject_valve_fault("vr06", ValveState.STUCK_OPEN),    # VR06 fails open
    18: lambda r: r.inject_valve_fault("sv02", ValveState.STUCK_CLOSED),  # SV02 sticks closed
    19: lambda r: r.inject_valve_fault("sv02", ValveState.STUCK_OPEN),    # SV02 sticks open

    # --- microswitch (discrete sensor) faults, mapped onto the sensors
    #     wired in rocket.py rather than the valve itself, since the fault
    #     is described as being IN the microswitch reading, not the valve
    #     behavior — the valve moves correctly, the sensor lies about it ---
    14: lambda r: r.sensors["mmsw205x"].inject_fault(),  # open microswitch fails on SV31
    15: lambda r: r.sensors["mmsw203x"].inject_fault(),  # close microswitch fails on PV03
    # scenario 20 is a compound fault (microswitch fault THEN valve fails
    # closed) — modeled here as both effects fired at the same timestamp,
    # since fault_catalog.csv gives one onset time for the whole scenario
    20: lambda r: (r.sensors["mmsw205x"].inject_fault(),
                   r.inject_valve_fault("sv31", ValveState.STUCK_CLOSED)),
}


# Scenarios NOT mappable in v1 — component doesn't exist in RocketA yet.
# Listed with the specific reason, so extending the simulator later has a
# ready-made checklist instead of a re-read of the whole PITEX paper.
UNMODELED_SCENARIOS = {
    2:  "sv33 (LOX Feed Servo Valve) not modeled — only pv03 modeled for LOX feed in v1",
    10: "rg11 regulator not modeled — no Regulator component exists yet",
    11: "rg11 regulator not modeled — no Regulator component exists yet",
    21: "rg11_rg01 dual regulator fault not modeled — no Regulator component exists yet",
    22: "mpre202p/mpre212p LOX vent line sensors not wired in RocketA v1 (only mpre104p is)",
    23: "mpre202p/mpre212p LOX vent line sensors not wired in RocketA v1 (only mpre104p is)",
    24: "aft LOX tank not modeled — v1 scope note in rocket.py explicitly omits it",
}


class FaultInjector:
    """Fires fault scenarios into a RocketA instance at the right mission
    time. Call `.check(rocket)` once per tick, after rocket.tick()."""

    def __init__(self, scenario_ids: list[int], catalog: Optional[list[FaultScenario]] = None):
        catalog = catalog or load_fault_catalog()
        by_id = {s.scenario_id: s for s in catalog}

        self.scenarios: list[FaultScenario] = []
        for sid in scenario_ids:
            if sid in UNMODELED_SCENARIOS:
                raise ValueError(
                    f"Scenario {sid} is not modeled in v1: {UNMODELED_SCENARIOS[sid]}"
                )
            if sid not in FAULT_ACTIONS:
                raise ValueError(f"Scenario {sid} has no fault action mapping")
            self.scenarios.append(by_id[sid])

        self._fired = set()

    def check(self, rocket) -> list[FaultScenario]:
        """Call once per tick. Returns any scenarios fired THIS tick (so the
        caller can log them into rocket.active_faults / the events file)."""
        fired_this_tick = []
        for s in self.scenarios:
            if s.scenario_id in self._fired:
                continue
            if rocket.mission_time_s >= s.injection_time_s:
                FAULT_ACTIONS[s.scenario_id](rocket)
                self._fired.add(s.scenario_id)
                rocket.active_faults.append({
                    "scenario_id": s.scenario_id,
                    "component_id": s.component_id,
                    "description": s.description,
                    "onset_time": s.injection_time_s,
                })
                fired_this_tick.append(s)
        return fired_this_tick
