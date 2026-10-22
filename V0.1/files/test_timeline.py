
from dataclasses import dataclass

from timeline import MissionTimeline, PhaseEvent


@dataclass
class FakeRocket:
    mission_time_s: float = 0.0
    flight_phase: str = "LOCKUP"
    commands: list[str] = None

    def __post_init__(self):
        if self.commands is None:
            self.commands = []

    def command_lox_vent_open(self):
        self.commands.append("lox_vent_open")

    def command_pressurization_enable(self):
        self.commands.append("pressurization_enable")

    def command_rp1_feed_open(self):
        self.commands.append("rp1_feed_open")

    def command_lox_feed_open(self):
        self.commands.append("lox_feed_open")


def event(order, phase, time_s):
    return PhaseEvent(order, phase, phase, time_s, "test")


def test_time_zero_events_are_processed_in_phase_order():
    rocket = FakeRocket()
    timeline = MissionTimeline([
        event(2, "ASCENT", 0),
        event(1, "LOCKUP", 0),
    ])

    last = timeline.advance(rocket)

    assert rocket.flight_phase == "ASCENT"
    assert last.phase_name == "ASCENT"


def test_all_due_events_are_processed_in_one_advance():
    rocket = FakeRocket(mission_time_s=10)
    timeline = MissionTimeline([
        event(1, "LOX_CONDITIONING", 2),
        event(2, "PRESSURIZATION", 5),
        event(3, "RP1_BLEED", 10),
    ])

    last = timeline.advance(rocket)

    assert rocket.commands == [
        "lox_vent_open",
        "pressurization_enable",
        "rp1_feed_open",
    ]
    assert rocket.flight_phase == "RP1_BLEED"
    assert last.phase_name == "RP1_BLEED"


def test_future_event_is_not_processed_early():
    rocket = FakeRocket(mission_time_s=4)
    timeline = MissionTimeline([
        event(1, "LOX_CONDITIONING", 5),
    ])

    assert timeline.advance(rocket) is None
    assert rocket.commands == []

    rocket.mission_time_s = 5
    timeline.advance(rocket)

    assert rocket.commands == ["lox_vent_open"]


def test_mission_completes_after_free_flight():
    rocket = FakeRocket(mission_time_s=10)
    timeline = MissionTimeline([
        event(1, "FREE_FLIGHT", 10),
    ])

    assert not timeline.is_mission_complete()
    timeline.advance(rocket)
    assert timeline.is_mission_complete()
