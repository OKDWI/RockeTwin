
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from mlops.api.main import (
    app,
    MISSION_STATES,
    STATE_LOCK,
    get_model_bundle,
    classify_features,
)
from mlops.src.features.build_dataset import add_features

DATASET_DIR = Path("dataset")
MISSION_ID = "parity-test-mission"


def clear_test_state():
    with STATE_LOCK:
        MISSION_STATES.pop(MISSION_ID, None)


def main():
    client = TestClient(app)

    telemetry_path = DATASET_DIR / "telemetry" / "mission_0002.csv"
    raw = pd.read_csv(telemetry_path).sort_values("mission_time_s")
    manifest = pd.read_csv(DATASET_DIR / "manifest.csv")
    mission_info = manifest.loc[
        manifest["mission_id"] == "mission_0002"
        ].iloc[0]

    ground_truth_fault = str(mission_info["label"])
    fault_onset_time = float(mission_info["fault_onset_time_s"])

    print(f"Ground-truth fault: {ground_truth_fault}")
    print(f"Fault onset: {fault_onset_time:.1f} s")

    # Use a short sequence first; extend to the full mission after passing.
    raw = raw.reset_index(drop=True)
    raw["mission_id"] = MISSION_ID

    # Generate expected features using the established batch pipeline.
    batch = add_features(raw.copy())

    # Match the batch feature matrix to the model's complete feature schema.
    # Missing phase columns mean those phases were absent from this sample.
    expected_features = get_model_bundle()["features"]
    batch = batch.reindex(columns=batch.columns.tolist() + [
        col for col in expected_features if col not in batch.columns
    ], fill_value=0.0)

    bundle_response = client.get("/health")
    assert bundle_response.status_code == 200
    assert bundle_response.json()["model_available"], "Model file is missing"

    bundle = get_model_bundle()

    # Confirm the batch pipeline and model agree on feature names.
    missing = sorted(set(expected_features) - set(batch.columns))
    assert not missing, f"Batch data is missing model features: {missing}"

    clear_test_state()

    pre_onset_false_alarms = 0
    consecutive_correct = 0
    detection_time = None
    post_onset_readings = 0

    for idx, row in raw.iterrows():
        payload = {
            key: row[key]
            for key in [
                "mission_time_s",
                "mpre104p",
                "mrtd104t",
                "mpre105p",
                "mrtd105t",
                "mmsw203x",
                "mmsw205x",
                "mmsw301x",
                "flight_phase",
            ]
        }

        response = client.post(
            f"/missions/{MISSION_ID}/predict",
            json=payload,
        )
        assert response.status_code == 200, (
            f"Request {idx} failed: {response.status_code} {response.text}"
        )

        actual = response.json()
        timestamp = float(row["mission_time_s"])

        if timestamp < fault_onset_time:
            if actual["fault"] != "nominal":
                pre_onset_false_alarms += 1
        else:
            post_onset_readings += 1

            if actual["fault"] == ground_truth_fault:
                consecutive_correct += 1
            else:
                consecutive_correct = 0

            if consecutive_correct >= 2 and detection_time is None:
                detection_time = timestamp
        expected_row = batch.iloc[idx][expected_features].to_dict()
        expected_prediction = classify_features(expected_row, bundle)

        assert actual["fault"] == expected_prediction["fault"], (
            f"Prediction mismatch at row {idx}: "
            f"API={actual['fault']}, "
            f"batch={expected_prediction['fault']}"
        )
        assert actual["readings_processed"] == idx + 1
        assert actual["mission_time_s"] == payload["mission_time_s"]

    print(f"\nFault evaluation: {ground_truth_fault}")
    print(f"Pre-onset false-alarm readings: {pre_onset_false_alarms}")

    if detection_time is not None:
        latency = detection_time - fault_onset_time
        print(f"Fault detected: YES")
        print(f"Detection time: {detection_time:.1f} s")
        print(f"Detection latency: {latency:.1f} s")
    else:
        print("Fault detected: NO")
        print(f"Post-onset readings evaluated: {post_onset_readings}")

    # Verify duplicate timestamps are rejected.
    duplicate_response = client.post(
        f"/missions/{MISSION_ID}/predict",
        json=payload,
    )
    assert duplicate_response.status_code == 409

    # Verify a second mission starts with independent state.
    second_response = client.post(
        "/missions/parity-test-mission-2/predict",
        json={**payload, "mission_time_s": 0},
    )
    assert second_response.status_code == 200
    assert second_response.json()["readings_processed"] == 1

    clear_test_state()
    with STATE_LOCK:
        MISSION_STATES.pop("parity-test-mission-2", None)

    print(
        f"PASS: {len(raw)} sequential API predictions match batch predictions."
    )
    print("PASS: Duplicate timestamps are rejected.")
    print("PASS: Mission state is isolated.")


if __name__ == "__main__":
    main()
