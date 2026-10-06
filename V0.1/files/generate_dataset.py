"""
generate_dataset.py — Generates a batch of N missions for actual ML training,
using randomized fault onset times rather than only the fixed PITEX
timestamps in fault_catalog.csv.

Why randomized onset times are needed:
  fault_catalog.csv gives one exact injection time per scenario (that's what
  NASA's own PITEX team tested). A model trained on faults that ALWAYS occur
  at the identical second would trivially learn "onset always at t=2706.9"
  rather than actually learning to recognize the fault's telemetry signature.
  Randomizing onset time within a broad window forces the model to detect
  the SHAPE of the fault, not memorize its timing.

Only fault templates that were verified to be actually visible in telemetry
(see tank.py's vent_stuck_open/vent_stuck_closed wiring, and the earlier
feed-valve fixes) are used here — this file deliberately does NOT reuse
fault_catalog.csv's full 24-scenario list, since several of those either
aren't modeled at all (UNMODELED_SCENARIOS in faults.py) or, prior to the
vent fix, produced no telemetry signature.
"""

import csv
import random
from pathlib import Path

from components.valve import ValveState
from rocket import RocketA
from timeline import MissionTimeline

# Fault templates verified to produce a real, distinguishable telemetry
# signature (see the tank.py vent-bleed / vent-rise fix, and the earlier
# feed-valve gating fix). component_id -> ValveState to inject.
FAULT_TEMPLATES = {
    "vr01_stuck_open":   ("vr01", ValveState.STUCK_OPEN),    # LOX vent bleeds down, never recovers
    "vr01_stuck_closed": ("vr01", ValveState.STUCK_CLOSED),  # LOX vent can't relieve, pressure climbs
    "vr06_stuck_open":   ("vr06", ValveState.STUCK_OPEN),    # RP-1 vent equivalent
    "vr06_stuck_closed": ("vr06", ValveState.STUCK_CLOSED),  # RP-1 vent equivalent
    "pv03_stuck_closed": ("pv03", ValveState.STUCK_CLOSED),  # LOX feed valve fails closed (real PITEX scenario 1)
    "pv02_stuck_closed": ("pv02", ValveState.STUCK_CLOSED),  # RP-1 feed valve fails closed (real PITEX scenario 16)
}


def generate_random_mission(mission_id: str, duration_s: float = 9776, dt_seconds: float = 5.0,
                             fault_probability: float = 0.5, rng: random.Random = None) -> dict:
    """One mission: nominal with probability (1 - fault_probability), else
    one randomly-chosen fault template fired at a randomized onset time."""
    rng = rng or random.Random()
    rocket = RocketA()
    timeline = MissionTimeline()

    fault_label, fault_component, fault_state, fault_onset = None, None, None, None
    fault_fired = False

    if rng.random() < fault_probability:
        fault_label = rng.choice(list(FAULT_TEMPLATES.keys()))
        fault_component, fault_state = FAULT_TEMPLATES[fault_label]
        # Onset randomized across most of the mission window, leaving margin
        # at both ends so there's always some pre-fault AND post-fault
        # telemetry to actually learn a before/after distinction from.
        fault_onset = rng.uniform(300, duration_s - 400)

    telemetry_rows, state_rows = [], []
    t = 0.0
    while t < duration_s:
        rocket.tick(dt_seconds)
        timeline.advance(rocket)

        if fault_label and not fault_fired and rocket.mission_time_s >= fault_onset:
            rocket.inject_valve_fault(fault_component, fault_state)
            rocket.active_faults.append({
                "scenario_id": None,        # not a fixed PITEX scenario — randomized onset
                "component_id": fault_component,
                "description": f"{fault_label} (randomized onset)",
                "onset_time": round(fault_onset, 1),
            })
            fault_fired = True

        telemetry_rows.append(rocket._read_telemetry_row())
        state_rows.append(rocket.true_state_row())
        t = rocket.mission_time_s

    return {
        "mission_id": mission_id,
        "telemetry": telemetry_rows,
        "state": state_rows,
        "events": rocket.active_faults,
        "label": fault_label or "nominal",
    }


def write_mission_csv(mission_data: dict, out_dir: str):
    out = Path(out_dir)
    (out / "telemetry").mkdir(parents=True, exist_ok=True)
    (out / "state").mkdir(parents=True, exist_ok=True)
    (out / "events").mkdir(parents=True, exist_ok=True)
    mission_id = mission_data["mission_id"]

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


def generate_dataset(n_missions: int, out_dir: str = "dataset", dt_seconds: float = 5.0,
                      fault_probability: float = 0.5, seed: int = 42):
    """Generates N missions and a manifest.csv summarizing each one — the
    manifest is what a future training script would actually load first,
    rather than scanning every telemetry file to figure out which missions
    have which labels."""
    rng = random.Random(seed)
    manifest_rows = []

    for i in range(1, n_missions + 1):
        mission_id = f"mission_{i:04d}"
        data = generate_random_mission(mission_id, dt_seconds=dt_seconds,
                                        fault_probability=fault_probability, rng=rng)
        write_mission_csv(data, out_dir=out_dir)

        onset = data["events"][0]["onset_time"] if data["events"] else None
        manifest_rows.append({
            "mission_id": mission_id,
            "label": data["label"],
            "fault_onset_time_s": onset,
            "n_telemetry_rows": len(data["telemetry"]),
        })
        print(f"[{mission_id}] label={data['label']:<20} onset={onset}")

    manifest_path = Path(out_dir) / "manifest.csv"
    with open(manifest_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=manifest_rows[0].keys())
        writer.writeheader()
        writer.writerows(manifest_rows)

    print(f"\nWrote {n_missions} missions + manifest.csv to {out_dir}/")
    return manifest_rows


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    generate_dataset(n_missions=n, dt_seconds=10.0)