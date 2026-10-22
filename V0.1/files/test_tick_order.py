
from rocket import RocketA


def test_before_update_runs_before_physics_and_telemetry():
    rocket = RocketA()
    events = []

    original_update = rocket.lox_tank.update
    original_read = rocket._read_telemetry_row

    def before_update():
        events.append("control")

    def tracked_update(*args, **kwargs):
        events.append("physics")
        return original_update(*args, **kwargs)

    def tracked_read():
        events.append("telemetry")
        return original_read()

    rocket.lox_tank.update = tracked_update
    rocket._read_telemetry_row = tracked_read

    row = rocket.tick(1.0, before_update=before_update)

    assert events == ["control", "physics", "telemetry"]
    assert row["mission_time_s"] == 1.0


def test_tick_rejects_nonpositive_dt():
    rocket = RocketA()

    for dt in (0, -1):
        try:
            rocket.tick(dt)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected ValueError for dt={dt}")
