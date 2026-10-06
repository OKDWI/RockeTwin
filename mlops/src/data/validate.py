from pathlib import Path
import pandas as pd
import pandera.pandas as pa

TELEMETRY_SCHEMA = pa.DataFrameSchema({
    "rocket_id": pa.Column(str),
    "mission_time_s": pa.Column(float, checks=pa.Check.ge(0)),
    "flight_phase": pa.Column(str),
    "mpre104p": pa.Column(float),
    "mrtd104t": pa.Column(float),
    "mpre105p": pa.Column(float),
    "mrtd105t": pa.Column(float),
    "mmsw203x": pa.Column(float),
    "mmsw205x": pa.Column(float),
    "mmsw301x": pa.Column(float),
    "vr01_state": pa.Column(str),
    "sv31_state": pa.Column(str),
    "sv03_state": pa.Column(str),
    "pv03_state": pa.Column(str),
    "vr06_state": pa.Column(str),
    "sv02_state": pa.Column(str),
    "pv02_state": pa.Column(str),
}, strict=False, coerce=True)


def validate_telemetry_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    validated = TELEMETRY_SCHEMA.validate(df, lazy=True)
    if not validated["mission_time_s"].is_monotonic_increasing:
        raise ValueError(f"mission_time_s is not monotonic: {path}")
    return validated


def validate_dataset(dataset_dir: Path) -> dict:
    telemetry_dir = dataset_dir / "telemetry"
    files = sorted(telemetry_dir.glob("mission_*.csv"))
    if not files:
        raise FileNotFoundError(f"No telemetry files found under {telemetry_dir}")
    rows = 0
    failures = []
    for path in files:
        try:
            rows += len(validate_telemetry_file(path))
        except Exception as exc:
            failures.append({"file": str(path), "error": str(exc)})
    return {"missions": len(files), "telemetry_rows": rows, "failures": failures}


if __name__ == "__main__":
    import argparse, json
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset")
    args = parser.parse_args()
    result = validate_dataset(Path(args.dataset))
    print(json.dumps(result, indent=2))
    if result["failures"]:
        raise SystemExit(1)
