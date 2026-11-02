"""Emergency-vehicle preemption — deterministic overrides layered on the signal controller.

Real preemption systems (e.g. Opticom) are rule-based overrides on top of the normal
controller, and so is this. When it pre-empts a junction for an emergency vehicle (ambulance,
police car or fire engine — any vehicle with ``is_emergency``), that junction's FSM is asked
for the phase that serves the vehicle's approach, overriding the base controller's request for
that decision. The request still goes through the safety FSM, so min-green, amber and all-red
are never skipped. There are two ways of choosing which junctions to pre-empt:

``stop_line`` — local preemption, what a stand-alone signal can do
    A junction is pre-empted while an emergency vehicle is waiting on one of its approaches,
    so the next junction on the route only starts to change once the vehicle has reached it
    and stopped there.

``corridor`` — a green corridor along the vehicle's route
    From the moment an emergency vehicle is on the road, every junction still ahead of it
    requests the phase that serves its approach and keeps requesting it until the vehicle has
    crossed. The junctions ahead switch, and start to empty the queue in front of the vehicle,
    before it gets there. This needs a controller that knows the vehicle's route and
    coordinates the junctions along it, which the multi-agent RL system does. Where two
    vehicles want the same junction, the one closer to it goes first (fewer junctions away,
    then already waiting, then sooner there, then the one sent first).

``emergency.corridor`` in ``config.yaml`` lists the controllers that clear a corridor (by
default ``rl``); every other controller — fixed-time and max-pressure — pre-empts at the stop
line. The benchmark and the dashboard attach one override to each controller this way.

The RL reward has a bonus for clearing an emergency vehicle (``reward.w_emergency``) and the
observation has per-approach emergency flags, but training never sends an emergency vehicle,
so the learned policy itself does not react to either: what an emergency vehicle gets, on
any grid, comes from this override.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from atsc.sim.backend import APPROACHES

#: The two ways of choosing which junctions to pre-empt (see the module docstring).
MODES: Tuple[str, ...] = ("stop_line", "corridor")
#: Controllers that clear a green corridor when ``emergency.corridor`` is not set.
DEFAULT_CORRIDOR: Tuple[str, ...] = ("rl",)


def corridor_controllers(cfg) -> Tuple[str, ...]:
    """The controllers that clear a green corridor (``emergency.corridor``)."""
    getter = getattr(cfg, "get_path", None)
    raw = getter("emergency.corridor", None) if getter else None
    return DEFAULT_CORRIDOR if raw is None else tuple(str(c) for c in raw)


class EmergencyController:
    """Preemption override attached to the environment via ``set_emergency_controller``.

    ``controller`` is the name of the base controller it is attached to (``Controller.name``:
    ``rl``, ``fixed_time``, ``max_pressure``); the mode follows ``emergency.corridor``.
    ``mode`` sets it explicitly instead. With neither, it pre-empts at the stop line.
    """

    def __init__(self, cfg, topo, controller: Optional[str] = None,
                 mode: Optional[str] = None) -> None:
        self.cfg = cfg
        self.topo = topo
        self.enabled = bool(cfg.emergency.preemption)
        if mode is None:
            mode = ("corridor" if controller is not None
                    and controller in corridor_controllers(cfg) else "stop_line")
        if mode not in MODES:
            raise ValueError(f"preemption mode must be one of {list(MODES)}, got {mode!r}")
        self.mode = mode
        self.active: Set[str] = set()          # intersections currently preempted
        self._last_corridor: Optional[str] = None
        # (junction, approach) -> the first phase that gives that approach green
        self._phase_of: Dict[Tuple[str, str], int] = {}
        for iid in topo.order:
            for phase in topo.get(iid).phases:
                for a in phase.green_approaches:
                    self._phase_of.setdefault((iid, a), phase.index)

    def reset(self) -> None:
        self.active = set()
        self._last_corridor = None

    def notify_injection(self, corridor: str) -> None:
        self._last_corridor = corridor

    def apply(self, env) -> None:
        """Override FSM targets for the junctions an emergency vehicle needs (every decision)."""
        if not self.enabled:
            return
        if self.mode == "corridor":
            self._apply_corridor(env)
        else:
            self._apply_stop_line(env)

    def _apply_stop_line(self, env) -> None:
        """Pre-empt every junction with an emergency vehicle waiting on an approach."""
        backend = env.backend
        self.active = set()
        for iid in self.topo.order:
            it = self.topo.get(iid)
            emg_approach = None
            for a in APPROACHES:
                if backend.emergency_present(iid, a):
                    emg_approach = a
                    break
            if emg_approach is None:
                continue
            # find the phase serving that approach and force it
            for phase in it.phases:
                if emg_approach in phase.green_approaches:
                    env.fsms[iid].request(phase.index)
                    self.active.add(iid)
                    break

    def _apply_corridor(self, env) -> None:
        """Pre-empt every junction still ahead of an emergency vehicle on its route."""
        self.active = set()
        claims: Dict[str, Tuple[Tuple[int, float, int], str]] = {}
        for order, (_vid, legs, eta) in enumerate(env.backend.emergency_routes()):
            for hops, (iid, approach) in enumerate(legs):
                rank = (hops, eta, order)            # closer to the junction goes first
                if iid not in claims or rank < claims[iid][0]:
                    claims[iid] = (rank, approach)
        for iid in self.topo.order:
            if iid in claims:
                phase = self._phase_of.get((iid, claims[iid][1]))
                if phase is not None:
                    env.fsms[iid].request(phase)
                    self.active.add(iid)

    def preempted_intersections(self) -> List[str]:
        return sorted(self.active)
