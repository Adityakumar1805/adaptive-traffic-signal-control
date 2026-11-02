"""Emergency preemption modes: the RL system's green corridor and the baselines' stop-line
preemption, the simulators' view of where each emergency vehicle still has to go, and the
config switch between them."""
import copy
import re
import types

import pytest

from atsc.config import Config, validate_config
from atsc.control import EmergencyController
from atsc.control.emergency import corridor_controllers
from atsc.envs.traffic_env import MultiAgentTrafficEnv
from atsc.sim.backend import build_topology

NS, EW = 0, 1                       # phase indices of the shipped ns_ew scheme
ROUTE = {"ew": ["J1_0", "J1_1"], "ns": ["J0_1", "J1_1"]}


def _env(cfg, controller, scenario="medium", seed=4):
    env = MultiAgentTrafficEnv(cfg, backend_name="mini")
    emc = EmergencyController(cfg, env.topo, controller=controller)
    env.set_emergency_controller(emc)
    env.reset(scenario=scenario, seed=seed)
    return env, emc


def test_the_rl_system_clears_a_corridor_and_the_baselines_preempt_at_the_stop_line(cfg):
    topo = build_topology(cfg)
    assert corridor_controllers(cfg) == ("rl",)
    assert EmergencyController(cfg, topo, controller="rl").mode == "corridor"
    for name in ("fixed_time", "max_pressure", None):
        assert EmergencyController(cfg, topo, controller=name).mode == "stop_line"
    assert EmergencyController(cfg, topo, controller="rl", mode="stop_line").mode == "stop_line"
    with pytest.raises(ValueError):
        EmergencyController(cfg, topo, mode="sometimes")
    off = copy.deepcopy(dict(cfg))
    off["emergency"] = dict(cfg.emergency, corridor=[])
    assert EmergencyController(Config(off), topo, controller="rl").mode == "stop_line"


@pytest.mark.parametrize("corridor, kind", [("ew", "ambulance"), ("ns", "police"), ("ew", "fire")])
def test_a_corridor_requests_every_junction_still_ahead_until_the_vehicle_has_crossed(
        cfg, corridor, kind):
    env, emc = _env(cfg, "rl")
    env.inject_emergency(corridor, kind=kind)
    phase = EW if corridor == "ew" else NS
    other = {a: 1 - phase for a in env.agents}         # the base controller wants the other phase
    ahead_counts = []
    while env.backend.active_emergencies():
        (_vid, legs, _eta), = env.backend.emergency_routes()
        ahead = [tls for tls, _a in legs]
        env.step(other)                                # apply() runs first, on this state
        assert emc.preempted_intersections() == sorted(ahead)
        if not ahead_counts:                           # from dispatch: the whole route
            assert ahead == ROUTE[corridor]
            assert all(env.fsms[j].target == phase for j in ahead)
        ahead_counts.append(len(ahead))
    assert 1 in ahead_counts                           # seen with one junction still to go
    env.step(other)
    assert emc.preempted_intersections() == []


def test_stop_line_preemption_only_holds_the_junction_the_vehicle_waits_at(cfg):
    env, emc = _env(cfg, "fixed_time")
    env.inject_emergency("ns", kind="police")
    seen_on_link = False
    while env.backend.active_emergencies():
        (veh, where, tls, *_rest), = env.backend.emergency_snapshot()
        env.step({a: EW for a in env.agents})
        assert emc.preempted_intersections() == ([tls] if where == "q" else [])
        seen_on_link |= where == "l"
    assert seen_on_link


def _fake_env(topo, routes):
    fsms = {iid: types.SimpleNamespace(target=None) for iid in topo.order}
    for f in fsms.values():
        f.request = (lambda fsm: lambda p: setattr(fsm, "target", p))(f)
    return types.SimpleNamespace(backend=types.SimpleNamespace(emergency_routes=lambda: routes),
                                 fsms=fsms)


def test_where_two_vehicles_want_one_junction_the_closer_one_goes_first(cfg):
    topo = build_topology(cfg)
    emc = EmergencyController(cfg, topo, mode="corridor")
    # J1_1 is on both corridors. A police car waiting at J0_1 has it one junction ahead; an
    # ambulance on the link towards it is about to arrive: the ambulance gets it.
    env = _fake_env(topo, [("EMG1", [("J0_1", "N"), ("J1_1", "N")], 0.0),
                           ("EMG2", [("J1_1", "W")], 4.0)])
    emc.apply(env)
    assert (env.fsms["J0_1"].target, env.fsms["J1_1"].target) == (NS, EW)
    # both one junction away: the one already waiting at its junction comes first
    env = _fake_env(topo, [("EMG1", [("J1_0", "W"), ("J1_1", "W")], 3.0),
                           ("EMG2", [("J0_1", "N"), ("J1_1", "N")], 0.0)])
    emc.apply(env)
    assert env.fsms["J1_1"].target == NS
    # otherwise level: the one sent first
    env = _fake_env(topo, [("EMG1", [("J1_0", "W"), ("J1_1", "W")], 0.0),
                           ("EMG2", [("J0_1", "N"), ("J1_1", "N")], 0.0)])
    emc.apply(env)
    assert env.fsms["J1_1"].target == EW
    assert emc.preempted_intersections() == ["J0_1", "J1_0", "J1_1"]


def test_no_preemption_at_all_when_it_is_switched_off(cfg):
    raw = copy.deepcopy(dict(cfg))
    raw["emergency"] = dict(cfg.emergency, preemption=False)
    off = Config(raw)
    env, emc = _env(off, "rl")
    env.inject_emergency("ew")
    env.step({a: NS for a in env.agents})
    assert emc.preempted_intersections() == []


def test_the_simulator_reports_every_emergency_vehicle_with_the_junctions_ahead(cfg):
    env, _ = _env(cfg, "rl")
    first = env.inject_emergency("ew", kind="fire")
    second = env.inject_emergency("ns", kind="police")
    routes = env.backend.emergency_routes()
    assert routes == [(first, [("J1_0", "W"), ("J1_1", "W")], 0.0),
                      (second, [("J0_1", "N"), ("J1_1", "N")], 0.0)]
    where = set()
    while env.backend.active_emergencies():
        snap = {veh.id: (veh, w, tls, appr, rem)
                for veh, w, tls, appr, _p, _q, rem in env.backend.emergency_snapshot()}
        for vid, legs, eta in env.backend.emergency_routes():
            veh, w, tls, appr, rem = snap[vid]
            assert legs == veh.legs[veh.leg_index:] and legs[0] == (tls, appr)
            assert eta == (0.0 if w == "q" else rem) and (w == "q" or eta > 0)
            where.add((vid, w, tls))
        env.step({a: NS for a in env.agents})
    assert (first, "l", "J1_1") in where and (second, "l", "J1_1") in where
    assert env.backend.emergency_routes() == []


def test_a_backend_without_routes_falls_back_to_the_stop_line(cfg):
    from atsc.sim.backend import SimBackend
    env, _ = _env(cfg, "rl")
    env.inject_emergency("ns", kind="police")
    plain = SimBackend.emergency_routes(env.backend)         # the interface's default
    assert plain == [("J0_1:N", [("J0_1", "N")], 0.0)]


@pytest.mark.parametrize("value, ok", [([], True), (["rl", "max_pressure"], True),
                                       (["mp"], False), ("rl", False)])
def test_the_corridor_setting_is_validated(cfg, value, ok):
    raw = copy.deepcopy(dict(cfg))
    raw["emergency"] = dict(cfg.emergency, corridor=value)
    if ok:
        validate_config(Config(raw))
    else:
        with pytest.raises(ValueError, match=re.escape("emergency.corridor")):
            validate_config(Config(raw))


class _FakeTraci:
    """Just enough of a TraCI connection for ``SumoBackend.emergency_routes``."""

    def __init__(self, vehicles):
        self.v = vehicles                     # vid -> (route, route index, road, speed, pos)
        fake = self
        self.vehicle = types.SimpleNamespace(
            getIDList=lambda: list(fake.v),
            getRoute=lambda vid: fake.v[vid][0],
            getRouteIndex=lambda vid: fake.v[vid][1],
            getRoadID=lambda vid: fake.v[vid][2],
            getSpeed=lambda vid: fake.v[vid][3],
            getLaneID=lambda vid: fake.v[vid][2] + "_0",
            getLanePosition=lambda vid: fake.v[vid][4])
        self.lane = types.SimpleNamespace(getLength=lambda lane: 200.0)


def test_sumo_reads_the_junctions_ahead_off_each_vehicles_route(cfg):
    """The same view from SUMO, without starting SUMO: the junction at the end of every edge
    still to drive, minus the one a vehicle is crossing; a halted vehicle is waiting."""
    from atsc.sim import netgen
    from atsc.sim.sumo_backend import SumoBackend, _NOT_INSERTED_ETA
    topo = build_topology(cfg)
    ns = netgen.straight_corridor_edges(topo, "J0_1", "N")    # cap -> J0_1 -> J1_1 -> cap
    ew = netgen.straight_corridor_edges(topo, "J1_0", "W")
    assert ns == ["J0_1_Ncap__J0_1", "J0_1__J1_1", "J1_1__J1_1_Scap"]
    b = SumoBackend(cfg, topo)
    both, last = [("J0_1", "N"), ("J1_1", "N")], [("J1_1", "N")]
    cases = [  # (where the police car is, what it still needs, eta)
        ((ns, 0, ns[0], 10.0, 150.0), both, 5.0),              # driving in, 50 m to go
        ((ns, 0, ns[0], 0.0, 190.0), both, 0.0),               # halted in the queue
        ((ns, 0, ":J0_1_3", 8.0, 2.0), last, _NOT_INSERTED_ETA),   # crossing J0_1
        ((ns, 1, ns[1], 12.0, 80.0), last, 10.0),              # on the link to J1_1
        ((ns, 1, ":J1_1_1", 9.0, 1.0), None, None),            # crossing J1_1: nothing left
        ((ns, 2, ns[2], 13.0, 20.0), None, None),              # on its way out
    ]
    for state, legs, eta in cases:
        b._conn = _FakeTraci({"EMG3": state})
        b._known_emerg, b._arrived_emerg, b._emerg_routes = {"EMG3"}, set(), {"EMG3": ns}
        expected = [] if legs is None else [("EMG3", legs, pytest.approx(eta))]
        assert b.emergency_routes() == expected, state
    # one added but not inserted yet, one arrived, dispatch order EMG2 before EMG10
    b._conn = _FakeTraci({"EMG10": (ew, 0, ew[0], 0.0, 100.0)})
    b._known_emerg = {"EMG10", "EMG2", "EMG1"}
    b._arrived_emerg = {"EMG1"}
    b._emerg_routes = {"EMG2": ns, "EMG10": ew, "EMG1": ns}
    assert b.emergency_routes() == [("EMG2", both, _NOT_INSERTED_ETA),
                                    ("EMG10", [("J1_0", "W"), ("J1_1", "W")], 0.0)]
