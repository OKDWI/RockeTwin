from pathlib import Path
import ast
import pandas as pd

DISCRETE_STATE_COLUMNS = [
    "vr01_state", "sv31_state", "sv03_state", "pv03_state",
    "vr06_state", "sv02_state", "pv02_state",
]
NUMERIC_TELEMETRY = [
    "mission_time_s", "mpre104p", "mrtd104t", "mpre105p", "mrtd105t",
    "mmsw203x", "mmsw205x", "mmsw301x",
]

FAULT_MAP = {
    "vr01_stuck_open": "vr01_stuck_open",
    "vr01_stuck_closed": "vr01_stuck_closed",
    "vr06_stuck_open": "vr06_stuck_open",
    "vr06_stuck_closed": "vr06_stuck_closed",
    "pv03_stuck_closed": "pv03_stuck_closed",
    "pv02_stuck_closed": "pv02_stuck_closed",
}

# Some valve faults can be injected before the affected valve is
# commanded open. Before that point, telemetry cannot distinguish the
# stuck-closed fault from nominal behavior.
OBSERVABLE_ONSET = {
    "pv03_stuck_closed": 9410.0,
    "pv02_stuck_closed": 9359.0,
}


def event_for_mission(events_dir: Path, mission_id: str):
    path = events_dir / f"{mission_id}.csv"
    if not path.exists():
        return None
    events = pd.read_csv(path)
    if events.empty:
        return None
    row = events.iloc[0]
    description = str(row.get("description", ""))
    label = description.split(" (randomized onset)")[0].strip()
    onset = float(row["onset_time"])
    if label not in FAULT_MAP:
        raise ValueError(f"Unknown fault label {label!r} in {path}")
    return {"label": FAULT_MAP[label], "onset": onset, "component": row.get("component_id")}


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["mission_id", "mission_time_s"]).copy()
    for col in NUMERIC_TELEMETRY[1:]:
        grouped = df.groupby("mission_id")[col]

        # Immediate change
        df[f"{col}_diff"] = grouped.diff().fillna(0.0)

        # Multi-timescale temporal context
        for window in [3, 10, 30]:
            df[f"{col}_roll_mean_{window}"] = grouped.transform(
                lambda s, w=window: s.rolling(w, min_periods=1).mean()
            )
            df[f"{col}_roll_std_{window}"] = grouped.transform(
                lambda s, w=window: s.rolling(w, min_periods=1).std().fillna(0.0)
            )
    phase = pd.get_dummies(df["flight_phase"], prefix="phase", dtype=float)
    df = pd.concat([df.drop(columns=["flight_phase"]), phase], axis=1)
    return df


def build_dataset(dataset_dir: Path, output: Path) -> pd.DataFrame:
    rows = []
    telemetry_dir = dataset_dir / "telemetry"
    events_dir = dataset_dir / "events"
    for path in sorted(telemetry_dir.glob("mission_*.csv")):
        mission_id = path.stem
        event = event_for_mission(events_dir, mission_id)
        df = pd.read_csv(path)
        df["mission_id"] = mission_id
        if event is None:
            df["target"] = "nominal"
            df["fault_present"] = 0
            df["fault_component"] = "none"
        else:
            effective_onset = max(
                event["onset"],
                OBSERVABLE_ONSET.get(event["label"], event["onset"]),
            )

            df["target"] = (
                df["mission_time_s"]
                .ge(effective_onset)
                .map({True: event["label"], False: "nominal"})
            )

            df["fault_present"] = (df["target"] != "nominal").astype(int)
            df["fault_component"] = event["component"]
        rows.append(df)
    data = pd.concat(rows, ignore_index=True)
    data = add_features(data)
    # Prevent simulator's commanded/actual valve-state columns from leaking the answer.
    drop = [
        "rocket_id",
        "mission_id",
        "mission_time_s",
        "fault_component",
        "target",
        "fault_present",
        *DISCRETE_STATE_COLUMNS,
    ]
    feature_cols = [c for c in data.columns if c not in drop]
    result = data[["mission_id", "mission_time_s", "target", "fault_present", *feature_cols]]
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset")
    parser.add_argument("--output", default="mlops/data/processed/training.csv")
    args = parser.parse_args()
    result = build_dataset(Path(args.dataset), Path(args.output))
    print(f"Wrote {len(result):,} rows to {args.output}")
    print(result["target"].value_counts().to_string())
