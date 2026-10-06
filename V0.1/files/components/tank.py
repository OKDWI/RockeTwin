"""
tank.py — Propellant tank component for the Virtual Rocket A simulator.

Every numeric constant in this file is traceable to a specific NASA source
(see the `source=` note on each constant). Where a paper did not provide a
number, that is stated explicitly rather than silently guessed.

Sources:
  [SA]  Subsystem Analysis/Optimization for the X-34 MPS (McDonald et al., AIAA-98-4827)
  [PM]  Propellant Management and Conditioning Within the X-34 MPS (Brown et al., AIAA-98-3518)
  [LV]  The Livingstone Model of a Main Propulsion System (Bajwa & Sweet, 2002)
"""

from dataclasses import dataclass, field
from enum import Enum


class Propellant(str, Enum):
    LOX = "LOX"
    RP1 = "RP1"


@dataclass
class TankConfig:
    """Static, per-propellant parameters — pulled from component_parameters.csv
    and propellant_flow_parameters.csv, not invented."""

    propellant: Propellant

    # --- capacity / loading [PM] ---
    initial_propellant_mass_lbm: float
    proof_pressure_psig: float          # [SA]
    ullage_pressure_min_psia: float      # [SA]
    ullage_pressure_max_psia: float      # [SA]

    # --- dump flow equation coefficients [PM] ---
    # LOX:  Mdot(LOX) = 1.358*DP + 74.53                              (valid DP 42-59 psi)
    # RP-1: Mdot(RP)  = 16.254 + 3.0888*dP - 0.04887*dP^2 + 0.00040263*dP^3
    dump_flow_coeffs: tuple

    # --- boil-off (LOX only; RP-1 has none reported) [PM] ---
    boiloff_total_lbm: float = 0.0        # total lbm lost over full captive carry window
    boiloff_window_seconds: float = 9000  # ~2.5 hr captive carry, [PM]/[Overview]

    # --- nominal engine feed rate ---
    # NOTE: the papers give dump-phase flow equations, NOT a steady engine-feed
    # flow rate (engine feed depends on the Fastrac engine's own throttle curve,
    # which was never published / the engine was never completed). This value
    # is therefore an ASSUMPTION, not a NASA-sourced number: it's back-calculated
    # so that the tank drains over a plausible captive-carry-scale mission window.
    # Flag this explicitly in any report — do not present it as cited.
    assumed_feed_rate_lbm_per_sec: float = 0.0

    # --- vent bleed rate, for STUCK-OPEN vent fault behavior ---
    # [PM] states the controlled vent/relief valve "cycles the vent/relief
    # valve seven times during the 2.5 hour captive carry" within a
    # controlled band of 13-20 psia. That fact is used here to DERIVE
    # (not cite verbatim) a bleed rate: 7 psi swing over roughly half of
    # each ~1286s cycle -> ~0.0109 psi/sec. This is an estimate built from
    # a real stated fact, not an invented number, but it is NOT a value
    # printed anywhere in the paper itself — treat it as derived, and say
    # so if presenting it.
    vent_bleed_rate_psi_per_sec: float = 0.0
    vent_controlled_floor_psia: float = 13.0   # [PM] lower bound of controlled vent band

    # --- pressure RISE rate, for STUCK-CLOSED vent fault behavior ---
    # [PM]'s lockup model (Figure 9/10) states tank pressure "will rise to
    # 43 psia... during the 1800 second lock-up portion of captive carry"
    # starting near the controlled floor (~15 psia). That gives a DERIVED
    # rise rate of ~0.0156 psi/sec when heat load isn't relieved by venting
    # — i.e. exactly what happens if the vent is stuck closed. Same caveat
    # as vent_bleed_rate_psi_per_sec: derived from a stated fact, not a
    # number printed directly in the paper.
    vent_stuck_closed_rise_rate_psi_per_sec: float = 0.0


# Pre-built configs using real extracted values.
LOX_TANK_CONFIG = TankConfig(
    propellant=Propellant.LOX,
    initial_propellant_mass_lbm=21050,      # [PM]
    proof_pressure_psig=113,                # [SA]
    ullage_pressure_min_psia=55,            # [SA]
    ullage_pressure_max_psia=61,            # [SA]
    dump_flow_coeffs=(1.358, 74.53),        # [PM] Mdot = 1.358*DP + 74.53
    boiloff_total_lbm=716,                  # [PM]
    boiloff_window_seconds=9000,
    assumed_feed_rate_lbm_per_sec=2.5,      # ASSUMPTION — not NASA-sourced
    vent_bleed_rate_psi_per_sec=0.0109,     # DERIVED from [PM] cycle count, see note above
    vent_controlled_floor_psia=13.0,        # [PM]
    vent_stuck_closed_rise_rate_psi_per_sec=0.0156,  # DERIVED from [PM] Fig 9/10, see note above
)

RP1_TANK_CONFIG = TankConfig(
    propellant=Propellant.RP1,
    initial_propellant_mass_lbm=9350,       # [PM]
    proof_pressure_psig=150,                # [SA]
    ullage_pressure_min_psia=47,            # [SA]
    ullage_pressure_max_psia=53,            # [SA]
    dump_flow_coeffs=(16.254, 3.0888, -0.04887, 0.00040263),  # [PM] cubic in dP
    boiloff_total_lbm=0.0,                  # not reported for RP-1
    assumed_feed_rate_lbm_per_sec=1.1,      # ASSUMPTION — not NASA-sourced
    # RP-1 vent cycle count not reported in [PM] — reusing LOX's derived rate
    # as a placeholder, flagged as a weaker assumption than the LOX value.
    vent_bleed_rate_psi_per_sec=0.0109,
    vent_controlled_floor_psia=11.0,        # loosely below RP-1's own ullage band [SA]; not cited
    # [PM]'s lockup rise data is LOX-specific (no RP-1 equivalent reported);
    # reusing the LOX-derived rate here is a weaker assumption, flagged as such.
    vent_stuck_closed_rise_rate_psi_per_sec=0.0156,
)


@dataclass
class Tank:
    """A single propellant tank with true (hidden) internal state.

    Public attributes here are the GROUND TRUTH the simulator tracks.
    The model/twin never sees this object directly — it only sees noisy
    Sensor wrappers built around tank.pressure_psia / tank.temperature_r
    (see sensor.py).
    """

    config: TankConfig
    propellant_mass_lbm: float = field(init=False)
    pressure_psia: float = field(init=False)
    temperature_r: float = field(init=False)
    mode: str = "NOMINAL"           # NOMINAL | DUMPING | LEAKING
    _leak_extra_rate_lbm_s: float = 0.0
    _vent_stuck_open_pressure_deficit: float = field(default=0.0, repr=False)
    _vent_stuck_closed_pressure_surplus: float = field(default=0.0, repr=False)

    def __post_init__(self):
        self.propellant_mass_lbm = self.config.initial_propellant_mass_lbm
        # LOX nominal temp 160 R [PM]; RP-1 uses a mid Start-Box estimate ~510 R (~51F) [PM]
        self.temperature_r = 160.0 if self.config.propellant == Propellant.LOX else 510.0
        self.pressure_psia = self.config.ullage_pressure_min_psia

    # ---- fault injection hooks ----
    def start_leak(self, extra_rate_lbm_s: float):
        """Simulates e.g. LOX_PRESSURE_LEAK from fault_catalog.csv."""
        self.mode = "LEAKING"
        self._leak_extra_rate_lbm_s = extra_rate_lbm_s

    def clear_fault(self):
        self.mode = "NOMINAL"
        self._leak_extra_rate_lbm_s = 0.0
        self._vent_stuck_open_pressure_deficit = 0.0
        self._vent_stuck_closed_pressure_surplus = 0.0

    def start_dump(self):
        self.mode = "DUMPING"

    # ---- per-tick physics update ----
    def update(self, dt_seconds: float, dump_pressure_differential_psi: float = None,
               feed_valve_open: bool = False, vent_stuck_open: bool = False,
               vent_stuck_closed: bool = False):
        """Advances tank state by dt_seconds.

        Three drain regimes, matching the paper's own three regimes:
          1. DUMPING -> use the real NASA dump-flow polynomial [PM]
          2. NOMINAL/LEAKING -> use the assumed steady feed rate, but ONLY
             if the feed valve is actually open (feed_valve_open=True).
             A closed feed valve means zero engine-feed flow — this mirrors
             [LV] Table 1's own valve constraint ("closed: flow=0"). A leak,
             if active, still applies regardless of valve state, since a
             leak is by definition an unintended flow path.
          3. Pressure is derived from remaining mass fraction, not modeled
             independently — this is the deliberate physical link that makes
             pressure and mass move together instead of as separate random walks.

        `vent_stuck_open`: an ADDITIONAL, uncontrolled pressure bleed is
        applied on top of the mass-fraction baseline, and never recovers.
        This is what makes a stuck-open vent fault (fault_catalog.csv
        scenario 5, 6, etc.) actually show up in telemetry.

        `vent_stuck_closed`: the opposite fault — heat load that would
        normally be relieved by venting instead accumulates as a rising
        pressure surplus, mirroring the overpressure risk described in
        [SA]/[PM]. This makes fault_catalog.csv scenario 9 (VR01 sticks
        closed) similarly detectable, instead of silently doing nothing.
        Both effects are mutually exclusive by construction (a valve can't
        be both stuck open and stuck closed at once).
        """
        if self.mode == "DUMPING" and dump_pressure_differential_psi is not None:
            mdot = self._dump_flow_rate(dump_pressure_differential_psi)
        else:
            feed_mdot = self.config.assumed_feed_rate_lbm_per_sec if feed_valve_open else 0.0
            mdot = feed_mdot + self._leak_extra_rate_lbm_s

        self.propellant_mass_lbm = max(0.0, self.propellant_mass_lbm - mdot * dt_seconds)

        # Pressure linked to remaining mass fraction (simple, physically-motivated
        # coupling — not independent noise). Full-tank -> upper bound pressure,
        # empty -> lower bound. This is the "physics-informed" link called for
        # in the project brief, kept intentionally simple (linear), not a full
        # ullage thermodynamics model like [PM]'s non-equilibrium lockup model.
        mass_fraction = self.propellant_mass_lbm / self.config.initial_propellant_mass_lbm
        p_min, p_max = self.config.ullage_pressure_min_psia, self.config.ullage_pressure_max_psia
        baseline_pressure = p_min + mass_fraction * (p_max - p_min)

        if vent_stuck_open:
            # Uncontrolled bleed accumulates and does not recover — this is
            # the distinguishing signature vs. a normal, controller-cycled
            # vent (which this simplified model does not separately simulate
            # as oscillation, per the scope note above).
            self._vent_stuck_open_pressure_deficit += self.config.vent_bleed_rate_psi_per_sec * dt_seconds
        elif vent_stuck_closed:
            # Unrelieved heat load accumulates as rising pressure — the
            # opposite failure mode. Not capped at proof pressure on purpose:
            # letting it exceed proof lets is_overpressure() correctly flag
            # the actual hazardous outcome this fault represents. Verified:
            # at this derived rate, LOX proof pressure (113 psig, [SA]) is
            # actually crossed after ~3300s of continuous stuck-closed
            # venting — this is a genuine, not just cosmetic, hazard signal.
            self._vent_stuck_closed_pressure_surplus += (
                self.config.vent_stuck_closed_rise_rate_psi_per_sec * dt_seconds
            )
        # NOTE: neither accumulator is reset here when its trigger goes False —
        # a stuck valve doesn't un-stick on its own. Use Tank.clear_fault().

        self.pressure_psia = max(
            self.config.vent_controlled_floor_psia * 0.5,  # hard floor, avoid non-physical negative/near-zero
            baseline_pressure - self._vent_stuck_open_pressure_deficit
                              + self._vent_stuck_closed_pressure_surplus
        )

        # Boil-off nudges LOX temperature/mass slightly during captive carry,
        # using the paper's reported total lbm lost over the reported window [PM].
        if self.config.propellant == Propellant.LOX and self.config.boiloff_total_lbm > 0:
            boiloff_rate = self.config.boiloff_total_lbm / self.config.boiloff_window_seconds
            self.propellant_mass_lbm = max(0.0, self.propellant_mass_lbm - boiloff_rate * dt_seconds)

    def _dump_flow_rate(self, dp_psi: float) -> float:
        c = self.config.dump_flow_coeffs
        if self.config.propellant == Propellant.LOX:
            a, b = c
            return a * dp_psi + b
        else:
            a, b, c2, c3 = c
            return a + b * dp_psi + c2 * dp_psi**2 + c3 * dp_psi**3

    def is_overpressure(self) -> bool:
        return self.pressure_psia >= self.config.proof_pressure_psig