
import random

from rocket import generate_mission, stream_mission


def test_batch_and_streaming_telemetry_match():
    dt = 1.0
    steps = 10

    random.seed(12345)
    batch = generate_mission(
        duration_s=steps * dt,
        dt_seconds=dt,
        mission_id="parity_test",
    )

    random.seed(12345)
    stream = stream_mission(dt_seconds=dt)
    try:
        streaming_rows = [next(stream) for _ in range(steps)]
    finally:
        stream.close()

    batch_rows = batch["telemetry"]

    assert len(batch_rows) == steps
    assert len(streaming_rows) == steps
    assert batch_rows == streaming_rows

    assert [
        row["mission_time_s"] for row in streaming_rows
    ] == [float(i) for i in range(1, steps + 1)]
