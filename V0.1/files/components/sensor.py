"""
sensor.py — Sensor wrapper for the Virtual Rocket A simulator.

This is the ONLY file that is allowed to add noise. tank.py and valve.py
hold ground truth; a Sensor object wraps a piece of that ground truth and
produces the noisy, resolution-limited, occasionally-biased "reading" that
is what telemetry.csv actually contains — this is the hard line between
the "true state" and "telemetry" tiers described in the project brief
(section 20).

Sources:
  [RW]  Addressing the Real-World Challenges in PITEX (Maul et al., 2005)
        -> sensor noise handling, A/D resolution, and the specific
           "Biased" fault mode for controller pressure sensors
  [LV]  The Livingstone Model of a Main Propulsion System (Bajwa & Sweet, 2002)
        -> "Faulty" / "Biased" fault modes and ranks per sensor type (Table 1)
  [CM]  Damage Propagation Modeling (Saxena et al., 2008) — C-MAPSS paper
        -> used ONLY as a style reference for noise magnitude, NOT as a
           data source. See noise_std_pct below.
"""

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class SensorFault(str, Enum):
    NONE = "none"
    FAULTY = "faulty"    # [LV] — reading becomes unreliable/frozen/garbage
    BIASED = "biased"    # [LV]/[RW] — reading offset by a constant, but still tracks trend


@dataclass
class SensorConfig:
    tag: str                      # e.g. "mpre104p" — matches data_dictionary.csv sensor_tags
    component_id: str              # which Tank/Valve this observes, e.g. "forwardLO2"
    unit: str

    # --- noise model ---
    # [RW] describes noise as a real, unavoidable property that must be
    # distinguished from true signal, but does NOT give a universal magnitude
    # (it's sensor-specific and was tuned empirically per-sensor on real
    # hardware). No public number exists for X-34 sensors specifically.
    # C-MAPSS [CM] is used here ONLY as a rough proportionality reference:
    # published C-MAPSS sensor noise is small relative to full-scale range
    # (single-digit percent). We reuse that PROPORTION, not any actual value.
    noise_std_pct_of_range: float = 0.01   # ASSUMPTION (proportion borrowed from [CM] style, not a cited number)

    # --- resolution ---
    # [RW] explicitly identifies A/D resolution as a real effect: the smallest
    # change in true value that will show up at all in the reading. No
    # specific bit-depth is published for X-34 sensors, so this is left
    # coarse and flagged as an assumption.
    resolution_step: float = 0.0   # 0 = unlimited resolution (assumption; see above)

    # --- reading range, used only to scale noise_std_pct_of_range ---
    value_range_min: float = 0.0
    value_range_max: float = 100.0


@dataclass
class Sensor:
    """Wraps a `getter` callable that returns the current TRUE value from
    a Tank/Valve object, and produces a noisy reading on demand.

    Kept deliberately decoupled from Tank/Valve (no inheritance, no direct
    reference stored) — a Sensor just needs *a function that returns a number
    right now*. This means the same Sensor class works whether it's watching
    tank.pressure_psia, a Valve's flow_allowed() cast to 0/1, etc.
    """

    config: SensorConfig
    getter: Callable[[], float]
    fault: SensorFault = SensorFault.NONE
    _bias_offset: float = field(default=0.0, repr=False)
    _frozen_value: float = field(default=None, repr=False)

    # ---- fault injection ----
    def inject_bias(self, offset: float):
        """[LV]/[RW]: reading is offset by a constant but the sensor is 'not
        biased' check fails — still moves with true value, just shifted."""
        self.fault = SensorFault.BIASED
        self._bias_offset = offset

    def inject_fault(self):
        """[LV] generic 'Faulty' mode — modeled here as the reading freezing
        at its last value, one of the simplest realistic failure shapes and
        the one Livingstone's own 'Unknown'/'Faulty' catch-all covers without
        specifying an exact mechanism."""
        self.fault = SensorFault.FAULTY

    def clear_fault(self):
        self.fault = SensorFault.NONE
        self._bias_offset = 0.0
        self._frozen_value = None

    # ---- reading ----
    def read(self) -> float:
        true_value = self.getter()

        if self.fault == SensorFault.FAULTY:
            if self._frozen_value is None:
                self._frozen_value = true_value
            return self._frozen_value  # frozen, still noisy at freeze time — see below

        noisy = self._apply_noise(true_value)

        if self.fault == SensorFault.BIASED:
            noisy += self._bias_offset

        return self._apply_resolution(noisy)

    def _apply_noise(self, value: float) -> float:
        span = self.config.value_range_max - self.config.value_range_min
        std = span * self.config.noise_std_pct_of_range
        return value + random.gauss(0, std)

    def _apply_resolution(self, value: float) -> float:
        step = self.config.resolution_step
        if step <= 0:
            return value
        return round(value / step) * step


# ---------------------------------------------------------------------------
# Convenience builders for the sensor types that actually appear repeatedly
# in data_dictionary.csv (pressure / temperature sensors), so callers don't
# have to hand-build SensorConfig every time.
# ---------------------------------------------------------------------------

def pressure_sensor(tag: str, component_id: str, getter: Callable[[], float],
                     range_min_psia: float, range_max_psia: float) -> Sensor:
    cfg = SensorConfig(
        tag=tag, component_id=component_id, unit="psia",
        value_range_min=range_min_psia, value_range_max=range_max_psia,
    )
    return Sensor(config=cfg, getter=getter)


def temperature_sensor(tag: str, component_id: str, getter: Callable[[], float],
                        range_min_r: float, range_max_r: float) -> Sensor:
    cfg = SensorConfig(
        tag=tag, component_id=component_id, unit="R",
        value_range_min=range_min_r, value_range_max=range_max_r,
    )
    return Sensor(config=cfg, getter=getter)


def discrete_position_sensor(tag: str, component_id: str, getter: Callable[[], bool]) -> Sensor:
    """For microswitch-style position readings (open=1/closed=0). Noise/resolution
    are irrelevant here, so this bypasses the numeric noise model — matches
    [LV]'s treatment of microswitches as a separate, discrete sensor category."""
    cfg = SensorConfig(tag=tag, component_id=component_id, unit="bool",
                        noise_std_pct_of_range=0.0, value_range_min=0, value_range_max=1)
    return Sensor(config=cfg, getter=lambda: float(getter()))
