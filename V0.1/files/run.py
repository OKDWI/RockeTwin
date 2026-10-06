"""
run.py — Entry point to actually exercise the full Rocket A simulator.

Usage:
    python3 run.py batch        # generate a small batch of missions to disk
    python3 run.py stream       # print a live stream of telemetry to the terminal
"""

import sys
from rocket import generate_mission, write_mission_csv, stream_mission


def run_batch():
    print("Generating 4 missions (1 nominal, 3 faulted)...\n")

    missions = [
        ("mission_0001_nominal", None),
        ("mission_0002_vr01_stuck_open", [5]),
        ("mission_0003_vr01_stuck_closed", [9]),
        ("mission_0004_pv02_fails_closed", [16]),
    ]

    for mission_id, fault_ids in missions:
        data = generate_mission(duration_s=9776, dt_seconds=5.0,
                                 mission_id=mission_id, fault_scenario_ids=fault_ids)
        write_mission_csv(data, out_dir="dataset", mission_id=mission_id)

        final_state = data["state"][-1]
        print(f"[{mission_id}]")
        print(f"  telemetry rows: {len(data['telemetry'])}")
        print(f"  final LOX mass: {final_state['lox_mass_lbm']:.1f} lbm")
        print(f"  final RP-1 mass: {final_state['rp1_mass_lbm']:.1f} lbm")
        print(f"  faults fired: {[e['description'] for e in data['events']]}")
        print(f"  -> written to dataset/telemetry|state|events/{mission_id}.csv\n")

    print("Done. Check the dataset/ folder.")


def run_stream():
    print("Streaming live telemetry (Ctrl+C to stop)...\n")
    gen = stream_mission(dt_seconds=50.0, realtime=False, fault_scenario_ids=[5])
    for i, row in enumerate(gen):
        print(f"t={row['mission_time_s']:>6.0f}s  phase={row['flight_phase']:<20} "
              f"lox_p={row['mpre104p']:>6.2f}psia  rp1_p={row['mpre105p']:>6.2f}psia  "
              f"vr01={row['vr01_state']:<12} pv03={row['pv03_state']}")
        if i >= 60:
            break


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "batch"
    if mode == "batch":
        run_batch()
    elif mode == "stream":
        run_stream()
    else:
        print("Usage: python3 run.py [batch|stream]")