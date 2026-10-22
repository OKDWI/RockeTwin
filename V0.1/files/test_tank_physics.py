
import pytest

from components.tank import (
    LOX_TANK_CONFIG,
    RP1_TANK_CONFIG,
    Propellant,
    Tank,
)


def test_tank_starts_at_configured_mass_and_minimum_pressure():
    tank = Tank(LOX_TANK_CONFIG)

    assert tank.propellant_mass_lbm == LOX_TANK_CONFIG.initial_propellant_mass_lbm
    assert tank.pressure_psia == LOX_TANK_CONFIG.ullage_pressure_min_psia


def test_closed_feed_valve_prevents_engine_feed_loss():
    tank = Tank(RP1_TANK_CONFIG)
    initial_mass = tank.propellant_mass_lbm

    tank.update(dt_seconds=10, feed_valve_open=False)

    # RP-1 has no configured boil-off and no leak in this test.
    assert tank.propellant_mass_lbm == initial_mass


def test_open_feed_valve_reduces_mass_by_configured_feed_rate():
    tank = Tank(RP1_TANK_CONFIG)
    initial_mass = tank.propellant_mass_lbm
    dt = 10

    tank.update(dt_seconds=dt, feed_valve_open=True)

    expected = initial_mass - RP1_TANK_CONFIG.assumed_feed_rate_lbm_per_sec * dt
    assert tank.propellant_mass_lbm == pytest.approx(expected)


def test_mass_never_becomes_negative():
    tank = Tank(RP1_TANK_CONFIG)
    tank.propellant_mass_lbm = 1

    tank.update(dt_seconds=100, feed_valve_open=True)

    assert tank.propellant_mass_lbm == 0


def test_lox_boiloff_reduces_mass_when_feed_is_closed():
    tank = Tank(LOX_TANK_CONFIG)
    initial_mass = tank.propellant_mass_lbm
    dt = 10

    tank.update(dt_seconds=dt, feed_valve_open=False)

    expected = initial_mass - (
        LOX_TANK_CONFIG.boiloff_total_lbm
        / LOX_TANK_CONFIG.boiloff_window_seconds
        * dt
    )
    assert tank.propellant_mass_lbm == pytest.approx(expected)


def test_pressure_tracks_mass_fraction_without_vent_faults():
    tank = Tank(RP1_TANK_CONFIG)
    tank.propellant_mass_lbm = (
        RP1_TANK_CONFIG.initial_propellant_mass_lbm * 0.5
    )

    tank.update(dt_seconds=0.1, feed_valve_open=False)

    expected = (
        RP1_TANK_CONFIG.ullage_pressure_min_psia
        + 0.5 * (
            RP1_TANK_CONFIG.ullage_pressure_max_psia
            - RP1_TANK_CONFIG.ullage_pressure_min_psia
        )
    )
    assert tank.pressure_psia == pytest.approx(expected)


def test_proof_pressure_configuration_is_in_psig():
    assert LOX_TANK_CONFIG.proof_pressure_psig > 0
    assert RP1_TANK_CONFIG.proof_pressure_psig > 0


def test_lox_pressure_reflects_boiloff_in_same_tick():
    tank = Tank(LOX_TANK_CONFIG)
    dt = 10.0

    tank.update(dt_seconds=dt, feed_valve_open=False)

    expected_mass = (
        LOX_TANK_CONFIG.initial_propellant_mass_lbm
        - LOX_TANK_CONFIG.boiloff_total_lbm
        / LOX_TANK_CONFIG.boiloff_window_seconds
        * dt
    )
    expected_pressure = (
        LOX_TANK_CONFIG.ullage_pressure_min_psia
        + (
            expected_mass
            / LOX_TANK_CONFIG.initial_propellant_mass_lbm
        )
        * (
            LOX_TANK_CONFIG.ullage_pressure_max_psia
            - LOX_TANK_CONFIG.ullage_pressure_min_psia
        )
    )

    assert tank.propellant_mass_lbm == pytest.approx(expected_mass)
    assert tank.pressure_psia == pytest.approx(expected_pressure)
