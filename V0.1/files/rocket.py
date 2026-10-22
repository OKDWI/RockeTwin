"""
rocket.py — Virtual Rocket A: wires Tank/Valve/Sensor components together
into a full propulsion system, matching the real X-34 MPS topology.

This file does NOT introduce any new physics or numbers of its own — its
only job is WIRING. Every component it instantiates was already built and
tested in tank.py / valve.py / sensor.py. This is deliberate: if something
here is wrong, it's a wiring bug, not a physics bug, and the two concerns
stay easy to debug separately.

Topology source:
  [PM] Propellant Management and Conditioning Within the X-34 MPS
       (Brown et al., AIAA-98-3518), Figure 2 — schematic of the propellant
       management subsystems: RP-1 tank / FWD LOX / AFT LOX -> vent/relief
       valves + pressurization valves -> engine inlet valves -> "to engine"

Simplification made here, stated explicitly:
  The real X-34 has TWO LOX tanks (forward + aft) connected in series, with
  the aft tank as a simple pass-through [LV]. For v1, only the forward LOX
  tank is modeled as the LOX propellant source; the aft tank is omitted
  rather than modeled as an inert pass-through, since it holds no logic of
  its own. This matches the brief's own scope-reduction guidance (propulsion
  + propellant/tank only for v1) and is flagged here rather than silently
  simplified.
"""

import csv
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from components.tank import Tank, LOX_TANK_CONFIG, RP1_TANK_CONFIG
from components.valve import Valve, ValveConfig, ValveState
from components.sensor import pressure_sensor, temperature_sensor, discrete_position_sensor
from timeline import MissionTimeline
from faults import FaultInjector


@dataclass
class RocketA:
    """The full Virtual Rocket A vehicle.

    Holds:
      - two Tanks (LOX forward, RP-1)
      - the valves referenced by fault_catalog.csv
      - one Sensor per physical sensor tag that appears in data_dictionary.csv
        for these components
      - mission_time_s, the single clock everything is driven from
    """

    mission_time_s: float = 0.0
    rocket_id: str = "ROCKET_A"

    def __post_init__(self):
        # --- tanks (ground truth) ---
        self.lox_tank = Tank(LOX_TANK_CONFIG)
        self.rp1_tank = Tank(RP1_TANK_CONFIG)

        # --- valves (ground truth) --- component_ids match fault_catalog.csv
        self.valves = {
            "vr01": Valve(ValveConfig("vr01", "LOX Vent Relief Valve", stuck_open_rank=2, stuck_closed_rank=1)),
            "sv31": Valve(ValveConfig("sv31", "LOX Vent Relief Servo Valve", stuck_open_rank=3, stuck_closed_rank=2)),
            "sv03": Valve(ValveConfig("sv03", "LOX Tank Pressurization Valve", stuck_open_rank=3, stuck_closed_rank=2)),
            "pv03": Valve(ValveConfig("pv03", "LOX Feed/Engine Inlet Valve", stuck_open_rank=2, stuck_closed_rank=1)),
            "vr06": Valve(ValveConfig("vr06", "RP-1 Vent Relief Valve", stuck_open_rank=2, stuck_closed_rank=1)),
            "sv02": Valve(ValveConfig("sv02", "RP-1 Tank Pressurization Valve", stuck_open_rank=3, stuck_closed_rank=2)),
            "pv02": Valve(ValveConfig("pv02", "RP-1 Feed Valve", stuck_open_rank=2, stuck_closed_rank=1)),
        }
        # Start feed/vent valves closed, matching captive-carry lockup phase [PM]/[Overview]
        for v in self.valves.values():
            v.state = ValveState.CLOSED

        # --- sensors (the only noisy layer) --- tags match data_dictionary.csv
        self.sensors = {
            "mpre104p": pressure_sensor("mpre104p", "forwardLO2", lambda: self.lox_tank.pressure_psia,
                                         range_min_psia=55, range_max_psia=61),
            "mrtd104t": temperature_sensor("mrtd104t", "forwardLO2", lambda: self.lox_tank.temperature_r,
                                            range_min_r=155, range_max_r=165),
            "mpre105p": pressure_sensor("mpre105p", "rp1Tank", lambda: self.rp1_tank.pressure_psia,
                                         range_min_psia=47, range_max_psia=53),
            "mrtd105t": temperature_sensor("mrtd105t", "rp1Tank", lambda: self.rp1_tank.temperature_r,
                                            range_min_r=490, range_max_r=530),
            "mmsw203x": discrete_position_sensor("mmsw203x", "pv03", lambda: self.valves["pv03"].flow_allowed()),
            "mmsw205x": discrete_position_sensor("mmsw205x", "sv31", lambda: self.valves["sv31"].flow_allowed()),
            "mmsw301x": discrete_position_sensor("mmsw301x", "pv02", lambda: self.valves["pv02"].flow_allowed()),
        }

        # --- mission phase, driven externally by timeline.py (not yet built) ---
        self.flight_phase = "LOCKUP"

        # --- fault bookkeeping, driven externally by faults.py (not yet built) ---
        self.active_faults = []   # list of dicts: {scenario_id, component_id, description, onset_time}

    # ------------------------------------------------------------------
    # Wiring helpers — these encode the topology from [PM] Figure 2:
    # tank -> pressurization/vent valves -> feed valve -> "to engine"
    # ------------------------------------------------------------------
    def command_lox_feed_open(self):
        self.valves["pv03"].command(ValveState.OPEN)

    def command_lox_vent_open(self):
        self.valves["vr01"].command(ValveState.OPEN)
        self.valves["sv31"].command(ValveState.OPEN)

    def command_rp1_feed_open(self):
        self.valves["pv02"].command(ValveState.OPEN)

    def command_rp1_vent_open(self):
        self.valves["vr06"].command(ValveState.OPEN)

    def command_pressurization_enable(self):
        self.valves["sv03"].command(ValveState.OPEN)
        self.valves["sv02"].command(ValveState.OPEN)

    # ------------------------------------------------------------------
    # Fault injection passthrough — faults.py will call these using
    # fault_catalog.csv rows, rather than reaching into .valves directly.
    # ------------------------------------------------------------------
    def inject_valve_fault(self, component_id: str, fault: ValveState):
        if component_id in self.valves:
            self.valves[component_id].inject_fault(fault)

    def inject_tank_leak(self, propellant: str, extra_rate_lbm_s: float):
        tank = self.lox_tank if propellant.upper() == "LOX" else self.rp1_tank
        tank.start_leak(extra_rate_lbm_s)

    # ------------------------------------------------------------------
    # The one per-tick update — advances every component by dt_seconds.
    # ------------------------------------------------------------------

    def tick(self, dt_seconds: float = 1.0, before_update=None) -> dict:
        """Advance one simulation step and return one telemetry sample.

        before_update, when supplied, runs after the mission clock advances
        but before valves and tanks update. It is used to apply due timeline
        commands and fault injections consistently.
        """
        if dt_seconds <= 0:
            raise ValueError("dt_seconds must be positive")

        self.mission_time_s += dt_seconds

        if before_update is not None:
            before_update()

        for valve in self.valves.values():
            valve.update(dt_seconds)

        self.lox_tank.update(
            dt_seconds,
            feed_valve_open=self.valves["pv03"].flow_allowed(),
            vent_stuck_open=(
                    self.valves["vr01"].state == ValveState.STUCK_OPEN
            ),
            vent_stuck_closed=(
                    self.valves["vr01"].state == ValveState.STUCK_CLOSED
            ),
        )

        self.rp1_tank.update(
            dt_seconds,
            feed_valve_open=self.valves["pv02"].flow_allowed(),
            vent_stuck_open=(
                    self.valves["vr06"].state == ValveState.STUCK_OPEN
            ),
            vent_stuck_closed=(
                    self.valves["vr06"].state == ValveState.STUCK_CLOSED
            ),
        )

        return self._read_telemetry_row()

    def _read_telemetry_row(self) -> dict:
        """This is the ONLY place true state and sensor readings mix in one
        row — and only because a real telemetry row is exactly this: sensor
        tag -> noisy reading. Hidden state is captured SEPARATELY via
        true_state_row(), never merged into this dict."""
        row = {
            "rocket_id": self.rocket_id,
            "mission_time_s": round(self.mission_time_s, 2),
            "flight_phase": self.flight_phase,
        }
        for tag, sensor in self.sensors.items():
            row[tag] = round(sensor.read(), 4)
        for cid, valve in self.valves.items():
            row[f"{cid}_state"] = valve.state.value
        return row

    def true_state_row(self) -> dict:
        """Hidden ground truth — used ONLY for model evaluation, never as
        model input. Mirrors the brief's three-tier data design (section 20)."""
        return {
            "mission_time_s": round(self.mission_time_s, 2),
            "lox_mass_lbm": round(self.lox_tank.propellant_mass_lbm, 3),
            "lox_true_pressure_psia": round(self.lox_tank.pressure_psia, 4),
            "rp1_mass_lbm": round(self.rp1_tank.propellant_mass_lbm, 3),
            "rp1_true_pressure_psia": round(self.rp1_tank.pressure_psia, 4),
            "lox_tank_mode": self.lox_tank.mode,
            "rp1_tank_mode": self.rp1_tank.mode,
            "active_faults": [f["component_id"] for f in self.active_faults],
        }


# ---------------------------------------------------------------------------
# Batch mode — generate a full mission to disk (telemetry + state + events),
# matching the three-directory split described in the brief (section 29).
#
# Phase commanding is driven by timeline.py (real DRM timestamps from
# mission_timeline.csv). Fault injection, if requested, is driven by
# faults.py (real PITEX scenarios from fault_catalog.csv). This function
# no longer hardcodes either — both concerns were factored out on purpose,
# matching the modular design goal from the start of this project.
# ---------------------------------------------------------------------------
def generate_mission(duration_s: float = 9776, dt_seconds: float = 1.0,
                      mission_id: str = "mission_0001",
                      fault_scenario_ids: Optional[list[int]] = None) -> dict:
    """Runs one full mission in batch mode. Returns dict of row-lists;
    caller is responsible for writing to telemetry/, state/, events/ per
    the brief's dataset structure (see write_mission_csv)."""
    rocket = RocketA()
    timeline = MissionTimeline()
    timeline.advance(rocket)
    injector = FaultInjector(fault_scenario_ids) if fault_scenario_ids else None

    telemetry_rows, state_rows = [], []

    t = 0.0

    def before_update():
        timeline.advance(rocket)
        if injector:
            injector.check(rocket)

    t = 0.0
    while t < duration_s:
        telemetry_row = rocket.tick(
            dt_seconds,
            before_update=before_update,
        )

        telemetry_rows.append(telemetry_row)
        state_rows.append(rocket.true_state_row())
        t = rocket.mission_time_s


    return {"telemetry": telemetry_rows, "state": state_rows, "events": rocket.active_faults}


def write_mission_csv(mission_data: dict, out_dir: str, mission_id: str):
    out = Path(out_dir)
    (out / "telemetry").mkdir(parents=True, exist_ok=True)
    (out / "state").mkdir(parents=True, exist_ok=True)
    (out / "events").mkdir(parents=True, exist_ok=True)

    def _write(rows, path):
        if not rows:
            return
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    _write(mission_data["telemetry"], out / "telemetry" / f"{mission_id}.csv")
    _write(mission_data["state"], out / "state" / f"{mission_id}.csv")
    _write(mission_data["events"], out / "events" / f"{mission_id}.csv")


# ---------------------------------------------------------------------------
# Streaming mode — same rocket, same tick(), timeline, and fault injection
# as batch mode, just yields forever instead of stopping. This is what the
# live demo uses; the wiring is identical to generate_mission() on purpose
# (same "one generator, two output modes" design from the project brief).
# ---------------------------------------------------------------------------
def stream_mission(dt_seconds: float = 1.0, realtime: bool = False,
                    fault_scenario_ids: Optional[list[int]] = None):
    rocket = RocketA()
    timeline = MissionTimeline()
    timeline.advance(rocket)
    injector = FaultInjector(fault_scenario_ids) if fault_scenario_ids else None


    def before_update():
        timeline.advance(rocket)
        if injector:
            injector.check(rocket)

    while True:
        telemetry_row = rocket.tick(
            dt_seconds,
            before_update=before_update,
        )

        yield telemetry_row

        if realtime:
            time.sleep(dt_seconds)
