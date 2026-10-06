"""
timeline.py — Drives mission phase progression for the Virtual Rocket A
simulator using the real captive-carry Design Reference Mission timestamps
extracted into mission_timeline.csv.

Like faults.py, this file introduces no new numbers or physics — it only
decides WHEN to call the command_* methods that already exist on RocketA,
using timestamps taken directly from the PITEX Overview / Real-World
Challenges papers' Design Reference Mission (mission_timeline.csv).

This replaces the hardcoded `commanded = {...}` dict that was living inside
rocket.py's generate_mission()/stream_mission() — that was a placeholder
noted explicitly in rocket.py's own docstring, now properly factored out.
"""

import csv
from dataclasses import dataclass
from typing import Callable


@dataclass
class PhaseEvent:
    phase_order: int
    phase_name: str
    event: str
    time_s: float
    nasa_reference: str


def load_mission_timeline(path: str = "mission_timeline.csv") -> list[PhaseEvent]:
    events = []
    with open(path) as f:
        for row in csv.DictReader(f):
            events.append(PhaseEvent(
                phase_order=int(row["phase_order"]),
                phase_name=row["phase_name"],
                event=row["event"],
                time_s=float(row["time_seconds"]),
                nasa_reference=row["nasa_reference"],
            ))
    return sorted(events, key=lambda e: e.time_s)


# ---------------------------------------------------------------------------
# Mapping: phase_name -> function(rocket) that fires the commands associated
# with entering that phase. LOCKUP has no command (it's the starting state);
# FREE_FLIGHT similarly has no further command in v1 scope (end of the
# modeled captive-carry window — matches rocket.py's scope, which does not
# model powered flight).
# ---------------------------------------------------------------------------
PHASE_ACTIONS: dict[str, Callable] = {
    "LOCKUP": lambda r: None,
    "ASCENT": lambda r: None,
    "LOX_CONDITIONING": lambda r: r.command_lox_vent_open(),
    "PRESSURIZATION": lambda r: r.command_pressurization_enable(),
    "RP1_BLEED": lambda r: r.command_rp1_feed_open(),
    "LOX_CHILLDOWN_BLEED": lambda r: r.command_lox_feed_open(),
    "FREE_FLIGHT": lambda r: None,
}


class MissionTimeline:
    """Fires phase transitions into a RocketA instance at the right mission
    time. Call `.advance(rocket)` once per tick, after rocket.tick()."""

    def __init__(self, events: list[PhaseEvent] = None):
        self.events = events or load_mission_timeline()
        self._entered = set()

    def advance(self, rocket) -> PhaseEvent | None:
        """Call once per tick. Returns the PhaseEvent entered THIS tick, if
        any (so the caller can log a phase-change record if desired)."""
        for e in self.events:
            if e.phase_name in self._entered:
                continue
            if rocket.mission_time_s >= e.time_s:
                action = PHASE_ACTIONS.get(e.phase_name)
                if action:
                    action(rocket)
                rocket.flight_phase = e.phase_name
                self._entered.add(e.phase_name)
                return e
        return None

    def is_mission_complete(self, rocket) -> bool:
        """True once the last phase (FREE_FLIGHT) has been entered — this is
        the end of the captive-carry window this simulator models."""
        return "FREE_FLIGHT" in self._entered
