
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.model_selection import train_test_split

DATA_PATH = Path("mlops/data/processed/training.csv")
MODEL_PATH = Path("mlops/models/rockettwin_xgb.joblib")
OUTPUT_PATH = Path("mlops/reports/detection_latency_v2.json")

RANDOM_STATE = 42
TEST_SIZE = 0.2
CONSECUTIVE_HITS = 2


def count_false_alarm_bursts(predictions):
    """Count contiguous runs of fault predictions in nominal segments."""
    active = [prediction != "nominal" for prediction in predictions]
    return sum(
        current and (i == 0 or not active[i - 1])
        for i, current in enumerate(active)
    )


def main():
    df = pd.read_csv(DATA_PATH)
    bundle = joblib.load(MODEL_PATH)

    model = bundle["model"]
    inv_mapping = bundle["inv_mapping"]
    features = bundle["features"]

    # Timestamp is evaluation metadata, never a model input.
    if any("mission_time_s" in feature for feature in features):
        raise ValueError("Timestamp leakage: remove time from model features.")

    missing = set(features) - set(df.columns)
    if missing:
        raise ValueError(f"Missing model features: {sorted(missing)}")

    # Reproduce the training script's mission-level split.
    mission_labels = df.groupby("mission_id")["target"].agg(
        lambda s: "nominal" if (s == "nominal").all()
        else s[s != "nominal"].iloc[0]
    )

    _, test_missions = train_test_split(
        mission_labels.index,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=mission_labels.values,
    )

    test = df[df["mission_id"].isin(test_missions)].copy()
    test = test.sort_values(["mission_id", "mission_time_s"])

    # Each row's features are built from current/past telemetry.
    test["prediction"] = [
        inv_mapping[int(value)]
        for value in model.predict(test[features]).astype(int)
    ]

    results = []
    nominal_segment_rows = 0
    false_alarm_rows = 0
    false_alarm_bursts = 0
    missions_with_false_alarms = 0

    for mission_id, mission in test.groupby("mission_id", sort=False):
        mission = mission.sort_values("mission_time_s").reset_index(drop=True)
        fault_rows = mission[mission["target"] != "nominal"]

        if fault_rows.empty:
            nominal_segment = mission
            fault_label = "nominal"
            onset_time = None
        else:
            fault_label = str(fault_rows["target"].iloc[0])
            onset_time = float(fault_rows["mission_time_s"].iloc[0])
            nominal_segment = mission[
                mission["mission_time_s"] < onset_time
            ]

        # False alarms before any labelled fault onset.
        nominal_segment_rows += len(nominal_segment)
        segment_predictions = nominal_segment["prediction"].tolist()
        segment_false_rows = sum(
            prediction != "nominal"
            for prediction in segment_predictions
        )
        segment_bursts = count_false_alarm_bursts(segment_predictions)

        false_alarm_rows += segment_false_rows
        false_alarm_bursts += segment_bursts

        if segment_false_rows:
            missions_with_false_alarms += 1

        if fault_label == "nominal":
            results.append({
                "mission_id": mission_id,
                "actual_fault": "nominal",
                "false_alarm_rows": segment_false_rows,
                "false_alarm_bursts": segment_bursts,
            })
            continue

        # Find the first sustained run of correct fault predictions.
        post_onset = mission[
            mission["mission_time_s"] >= onset_time
        ]

        streak = 0
        streak_start = None
        detected_at = None

        for row in post_onset.itertuples(index=False):
            timestamp = float(row.mission_time_s)

            if row.prediction == fault_label:
                if streak == 0:
                    streak_start = timestamp

                streak += 1

                if streak >= CONSECUTIVE_HITS:
                    detected_at = streak_start
                    break
            else:
                streak = 0
                streak_start = None

        detected = detected_at is not None

        results.append({
            "mission_id": mission_id,
            "actual_fault": fault_label,
            "observable_onset_s": onset_time,
            "detected": detected,
            "detection_time_s": detected_at,
            "detection_delay_s": (
                detected_at - onset_time if detected else None
            ),
            "false_alarm_rows_before_onset": segment_false_rows,
        })

    fault_results = [
        row for row in results if row["actual_fault"] != "nominal"
    ]
    detected_results = [
        row for row in fault_results if row["detected"]
    ]
    delays = [
        row["detection_delay_s"]
        for row in detected_results
        if row["detection_delay_s"] is not None
    ]

    summary = {
        "test_missions": len(results),
        "fault_missions": len(fault_results),
        "nominal_missions": len(results) - len(fault_results),
        "fault_missions_detected": len(detected_results),
        "fault_missions_missed": len(fault_results) - len(detected_results),
        "mission_detection_rate": (
            len(detected_results) / len(fault_results)
            if fault_results else None
        ),
        "consecutive_hits_required": CONSECUTIVE_HITS,
        "mean_detection_delay_s": (
            sum(delays) / len(delays) if delays else None
        ),
        "median_detection_delay_s": (
            float(pd.Series(delays).median()) if delays else None
        ),
        "p95_detection_delay_s": (
            float(pd.Series(delays).quantile(0.95))
            if delays else None
        ),
        "nominal_segment_rows": nominal_segment_rows,
        "false_alarm_rows": false_alarm_rows,
        "false_alarm_row_rate": (
            false_alarm_rows / nominal_segment_rows
            if nominal_segment_rows else None
        ),
        "false_alarm_bursts": false_alarm_bursts,
        "missions_with_pre_onset_false_alarms": missions_with_false_alarms,
        "per_mission": results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(summary, indent=2))

    # Log this evaluation as a separate MLflow run when available.
    try:
        import mlflow

        mlflow.set_experiment("RocketTwin-Fault-Detection")
        with mlflow.start_run(run_name="detection-latency-v2"):
            mlflow.log_params({
                "evaluation": "chronological_detection_latency",
                "consecutive_hits": CONSECUTIVE_HITS,
                "split_unit": "mission",
                "timestamp_feature": False,
            })

            numeric_metrics = {
                key: value
                for key, value in summary.items()
                if isinstance(value, (int, float))
                and value is not None
                and key != "test_missions"
            }
            mlflow.log_metrics(numeric_metrics)
            mlflow.log_artifact(str(OUTPUT_PATH))
    except ImportError:
        pass

    print(json.dumps({
        key: value
        for key, value in summary.items()
        if key != "per_mission"
    }, indent=2))
    print(f"\nDetailed results written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
