#!/usr/bin/env python3
"""Emergency-vehicle evaluation: the MARL controller against the fixed-time baseline, for
every emergency vehicle type.

    python tools/emergency_eval.py                      # 4 scenarios x 10 seeds x 25 dispatches
    python tools/emergency_eval.py --scenarios rush --seeds 0 1 2 3 4
    python tools/emergency_eval.py --quick              # 1 scenario x 2 seeds, a smoke test

How it works
------------
For every scenario and seed, each controller drives one episode on the built-in simulator
(the backend of the published benchmark and of the dashboard) with the preemption the
benchmark and the dashboard give it: a green corridor for the MARL controller, stop-line
preemption for fixed-time (``emergency.corridor`` in config.yaml). At every dispatch time
(60 s, then every 65 s) the running simulation is copied once per emergency type, and that
type is sent along its configured corridor in its own copy. Each vehicle therefore meets exactly the
traffic its controller has built up by then, and never another emergency vehicle; the main
run carries on without emergencies, so dispatches cannot influence one another. Both
controllers get the same scenarios, seeds and dispatch times, so every dispatch is a matched
pair. The 65 s step against the fixed-time plan's 60 s cycle walks the dispatches through
every point of the cycle.

Per dispatch it records

  travel_s  dispatch to leaving the grid: the project's emergency clearance KPI
            (``emergency_clearance_time``), read back from the simulator
  wait_s    seconds held at stop lines (the simulator's own waiting-time count)
  stops     junctions at which the vehicle was held longer than the 1 s the point-queue
            model needs to cross an empty approach on green
  clear_s   time to clear an intersection: from reaching a junction's stop line to crossing
            it, averaged over the junctions on the route

and, per junction on the route, whether its approach had green on arrival, how many
vehicles were queued ahead of it, how long it waited for green, and how often a green it was
waiting in ended before it got through.

Outputs (``outputs/emergency/`` by default): ``emergency_dispatches.csv`` (one row per
dispatch and controller), ``emergency_summary.csv`` (type x scenario x controller means),
``emergency_results.md`` (the results table with the improvement and the pass/fail check)
and ``emergency_<type>.png`` (one comparison chart per type). The pass condition is the
one stated in ``emergency_results.md``: for every emergency type the MARL controller's mean
travel time is lower than fixed-time's.
"""
from __future__ import annotations

import argparse
import copy
import math
import os
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

CONTROLLERS = ("rl", "fixed_time")
LABEL = {"rl": "MARL", "fixed_time": "Fixed-time"}
METRICS = (  # column, label, unit, decimals
    ("travel_s", "Average travel time", "s", 1),
    ("wait_s", "Waiting time", "s", 1),
    ("stops", "Number of stops", "", 2),
    ("clear_s", "Time to clear an intersection", "s", 1),
)
DEFAULT_DISPATCH = tuple(60 + 65 * i for i in range(25))      # 60 s ... 1620 s
QUICK_DISPATCH = (60, 125, 190, 255)


# --------------------------------------------------------------------------- #
# one emergency vehicle, followed second by second
# --------------------------------------------------------------------------- #
class _Follow:
    """Follows one emergency vehicle through the copy of the simulation it was sent into.

    It wraps the copy's ``backend.step`` and looks at the vehicle after every simulated
    second; it only reads, so the simulation runs exactly as it would without it. Times are
    the backend clock of the second in which something happened.
    """

    def __init__(self, env, vid: str) -> None:
        b = env.backend
        self.b = b
        self.veh = next(v for q in b._queues.values() for v in q if v.id == vid)
        self.legs = list(self.veh.legs)
        n = len(self.legs)
        self.n = n
        self.t0 = b.time                          # dispatched before the second t0 runs
        self.arrive: List[Optional[float]] = [None] * n
        self.cross: List[Optional[float]] = [None] * n
        self.ahead: List[Optional[int]] = [None] * n
        self.green_on_arrival: List[Optional[bool]] = [None] * n
        self.first_green: List[Optional[float]] = [None] * n
        self.lost_green = [0] * n
        self._was_green = False
        self.k = 0                                # junction it is heading to / waiting at
        q = b._queues[self.legs[0]]
        self.arrive[0] = self.t0
        self.ahead[0] = len(q) - 1                # enters at the back of the entry queue
        self.done = False
        step = b.step

        def tracked_step():
            out = step()
            self._after(b.time - b._step_len)
            return out
        b.step = tracked_step

    def _after(self, t: float) -> None:
        b, veh = self.b, self.veh
        k = self.k
        if k < self.n and self.arrive[k] is not None:        # held at junction k during t
            tls, appr = self.legs[k]
            green = appr in b._green[tls]
            if self.green_on_arrival[k] is None:
                self.green_on_arrival[k] = green
            if green and self.first_green[k] is None:
                self.first_green[k] = t
            if self._was_green and not green:
                self.lost_green[k] += 1
            self._was_green = green
        while self.k < veh.leg_index:                          # crossed junction k during t
            k = self.k
            if self.arrive[k] is None:                         # arrived and crossed in one second
                self.arrive[k], self.ahead[k], self.green_on_arrival[k] = t, 0, True
            if self.first_green[k] is None:
                self.first_green[k] = t
            self.cross[k] = t
            self._was_green = False
            self.k += 1
        if self.k >= self.n:
            self.done = True
            return
        k = self.k
        if self.arrive[k] is None:                             # reached junction k's stop line?
            tls, appr = self.legs[k]
            for i, v in enumerate(b._queues[(tls, appr)]):
                if v is veh:
                    green = appr in b._green[tls]
                    self.arrive[k], self.ahead[k], self.green_on_arrival[k] = t, i, green
                    if green:
                        self.first_green[k] = t
                    self._was_green = green
                    break

    def record(self) -> Dict[str, object]:
        """Per-dispatch metrics (see the module docstring)."""
        n = self.n
        if not self.done:
            return {"censored": True}
        clear = [self.cross[k] - self.arrive[k] for k in range(n)]
        row: Dict[str, object] = {
            "censored": False,
            "travel_s": self.cross[-1] - self.t0,
            "wait_s": float(self.veh.wait_time),
            "stops": sum(1 for c in clear if c > 1.0),
            "clear_s": sum(clear) / n,
        }
        for k in range(n):
            j = k + 1
            row[f"j{j}"] = self.legs[k][0]
            row[f"j{j}_clear_s"] = clear[k]
            row[f"j{j}_signal_s"] = self.first_green[k] - self.arrive[k]
            row[f"j{j}_ahead"] = self.ahead[k]
            row[f"j{j}_green_on_arrival"] = bool(self.green_on_arrival[k])
            row[f"j{j}_lost_green"] = self.lost_green[k]
        return row


# --------------------------------------------------------------------------- #
# one (controller, scenario, seed) episode with its dispatches
# --------------------------------------------------------------------------- #
_STATE: Dict[str, object] = {}


def _init_worker(config_path: Optional[str], checkpoint: Optional[str], nn_backend: Optional[str],
                 episode_s: int, max_trip_s: int, worker: bool = True) -> None:
    """Load the config once per process. A pool worker also goes quiet and single-threaded
    (the workers already use every core); the calling process is left as it is."""
    if worker:
        import logging
        logging.disable(logging.WARNING)
        try:
            import torch
            torch.set_num_threads(1)
        except Exception:
            pass
    from atsc.config import load_config
    from atsc.sim.backend import build_topology
    cfg = load_config(config_path)
    if nn_backend:
        cfg["rl"]["nn_backend"] = nn_backend
    _STATE.update(cfg=cfg, topo=build_topology(cfg), checkpoint=checkpoint,
                  episode_s=episode_s, max_trip_s=max_trip_s, controllers={})


def _controller(name: str):
    from atsc.control import build_controller
    cache = _STATE["controllers"]
    if name not in cache:
        kwargs = {}
        if name == "rl" and _STATE["checkpoint"]:
            kwargs["checkpoint"] = _STATE["checkpoint"]
        cache[name] = build_controller(name, _STATE["cfg"], _STATE["topo"], **kwargs)
    return cache[name]


def _dispatch(env, controller, etype: Dict[str, object]) -> Dict[str, object]:
    """Send one emergency vehicle into a copy of ``env`` and follow it until it is out."""
    memo = {id(env.cfg): env.cfg, id(env.topo): env.topo}
    branch = copy.deepcopy(env, memo)
    branch._episode_seconds = 10 ** 9            # the copy runs until the vehicle is out
    vid = branch.inject_emergency(str(etype["corridor"]), kind=str(etype["kind"]))
    follow = _Follow(branch, vid)
    limit = branch._elapsed + float(_STATE["max_trip_s"])
    while not follow.done and branch._elapsed < limit:
        branch.step(controller.act(branch))
    row = follow.record()
    if not row["censored"]:
        kpi = branch.backend.metrics().emergency_times
        assert kpi and abs(kpi[-1] - row["travel_s"]) < 1e-9, "travel time != simulator KPI"
    branch.close()
    return row


def run_task(task: Tuple[str, str, int, Tuple[int, ...]]) -> List[Dict[str, object]]:
    """One episode of one controller, with every emergency type dispatched at every time."""
    from atsc import vehicles as vehicle_catalogue
    from atsc.control import EmergencyController
    from atsc.envs.traffic_env import MultiAgentTrafficEnv

    name, scenario, seed, dispatch_times = task
    cfg, topo = _STATE["cfg"], _STATE["topo"]
    controller = _controller(name)
    controller.reset()
    env = MultiAgentTrafficEnv(cfg, backend_name="mini", topo=topo)
    env._episode_seconds = int(_STATE["episode_s"])
    env.set_emergency_controller(EmergencyController(cfg, topo, controller=controller.name))
    env.reset(scenario=scenario, seed=seed)
    types = vehicle_catalogue.emergency_types(cfg)
    pending = sorted(int(t) for t in dispatch_times)
    rows: List[Dict[str, object]] = []
    while env.agents:
        while pending and env._elapsed >= pending[0]:
            at = pending.pop(0)
            for etype in types:
                row = {"controller": name, "scenario": scenario, "seed": seed,
                       "kind": etype["kind"], "label": etype["label"],
                       "corridor": etype["corridor"], "speed_factor": etype["speed_factor"],
                       "dispatch_s": at}
                row.update(_dispatch(env, controller, etype))
                rows.append(row)
        env.step(controller.act(env))
    env.close()
    return rows


def evaluate(scenarios: Sequence[str], seeds: Sequence[int],
             dispatch_times: Sequence[int] = DEFAULT_DISPATCH,
             controllers: Sequence[str] = CONTROLLERS, config_path: Optional[str] = None,
             checkpoint: Optional[str] = None, nn_backend: Optional[str] = None,
             episode_s: Optional[int] = None, max_trip_s: int = 900,
             workers: int = 1, progress: bool = True):
    """Run every (controller, scenario, seed) episode and return the dispatches as a table."""
    import pandas as pd
    from atsc.config import load_config

    cfg = load_config(config_path)
    episode_s = int(episode_s or cfg.get_path("eval.episode_seconds") or cfg.sim.episode_seconds)
    latest = episode_s - int(cfg.signal.decision_interval_s)
    times = tuple(sorted({int(t) for t in dispatch_times if 0 <= int(t) <= latest}))
    step = int(cfg.signal.decision_interval_s)
    if any(t % step for t in times):
        raise ValueError(f"dispatch times must be multiples of the {step} s decision interval")
    tasks = [(c, s, int(seed), times) for s in scenarios for seed in seeds for c in controllers]
    init = (config_path, checkpoint, nn_backend, episode_s, max_trip_s)
    rows: List[Dict[str, object]] = []
    t_start = time.time()

    def note(done: int) -> None:
        if progress:
            print(f"  {done}/{len(tasks)} episodes  ({time.time() - t_start:.0f} s)",
                  file=sys.stderr, flush=True)

    if workers > 1:
        import multiprocessing as mp
        ctx = mp.get_context("fork" if "fork" in mp.get_all_start_methods() else "spawn")
        with ctx.Pool(workers, initializer=_init_worker, initargs=init) as pool:
            for i, part in enumerate(pool.imap(run_task, tasks), 1):
                rows.extend(part)
                note(i)
    else:
        _init_worker(*init, worker=False)
        for i, task in enumerate(tasks, 1):
            rows.extend(run_task(task))
            note(i)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# summary, table and charts
# --------------------------------------------------------------------------- #
def _pct(ft: float, rl: float) -> float:
    """Improvement of MARL over fixed-time in % (positive = MARL lower = better)."""
    return float("nan") if not ft else 100.0 * (ft - rl) / ft


def summarize(df, scenarios: Sequence[str]):
    """``(summary, comparison)``: means per type x scenario x controller, and per type x
    scenario the two controllers side by side with the improvement, the share of matched
    dispatches MARL wins / ties / loses, and in how many seeds MARL's mean is lower."""
    import pandas as pd

    ok = df[~df["censored"]]
    cols = [m for m, *_ in METRICS]
    groups = [("all", ok)] + [(s, ok[ok["scenario"] == s]) for s in scenarios]
    rows, comp = [], []
    for kind in ok["kind"].unique():
        for scen, part in groups:
            part = part[part["kind"] == kind]
            if part.empty:
                continue
            means = part.groupby("controller")[cols].mean()
            for ctrl in CONTROLLERS:
                if ctrl in means.index:
                    rows.append({"kind": kind, "scenario": scen, "controller": ctrl,
                                 "n": int((part["controller"] == ctrl).sum()),
                                 **{c: float(means.loc[ctrl, c]) for c in cols}})
            if not {"rl", "fixed_time"} <= set(means.index):
                continue
            key = ["scenario", "seed", "dispatch_s"]
            pair = part[part["controller"] == "rl"].set_index(key)["travel_s"].to_frame("rl").join(
                part[part["controller"] == "fixed_time"].set_index(key)["travel_s"].rename("ft"),
                how="inner")
            seed_means = part.groupby(["controller", "scenario", "seed"])["travel_s"].mean()
            rl_s, ft_s = seed_means.loc["rl"], seed_means.loc["fixed_time"]
            common = rl_s.index.intersection(ft_s.index)
            diff = (ft_s.loc[common] - rl_s.loc[common])
            entry = {"kind": kind, "scenario": scen, "pairs": len(pair),
                     "rl_wins": float((pair["rl"] < pair["ft"]).mean()),
                     "ties": float((pair["rl"] == pair["ft"]).mean()),
                     "rl_losses": float((pair["rl"] > pair["ft"]).mean()),
                     "seed_groups": len(common),
                     "rl_better_seed_groups": int((diff > 0).sum()),
                     "travel_diff_ci95_s": _ci95(diff.values)}
            for c in cols:
                ft, rl = float(means.loc["fixed_time", c]), float(means.loc["rl", c])
                entry[f"{c}_ft"], entry[f"{c}_rl"], entry[f"{c}_impr_%"] = ft, rl, _pct(ft, rl)
            comp.append(entry)
    return pd.DataFrame(rows), pd.DataFrame(comp)


def _ci95(values) -> float:
    """Half-width of a 95 % t-interval of the mean of ``values`` (nan for fewer than 2)."""
    n = len(values)
    if n < 2:
        return float("nan")
    import statistics as st
    t = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57, 7: 2.45, 8: 2.36, 9: 2.31, 10: 2.26}
    return float(t.get(n, 2.0 if n < 40 else 1.96) * st.stdev(values) / math.sqrt(n))


def _fmt(v: float, d: int) -> str:
    return "n/a" if v != v else f"{v:.{d}f}"


def _signed_pct(v: float) -> str:
    if v != v:
        return "n/a"
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.1f} %"


def write_markdown(comp, df, path: Path, scenarios: Sequence[str], seeds: Sequence[int],
                   times: Sequence[int], kinds_meta: Dict[str, Dict[str, object]],
                   preemption: Optional[Dict[str, str]] = None) -> Dict[str, bool]:
    """Write the results table and return ``{kind: passed}`` (pooled over every scenario).

    ``preemption`` names each controller's kind of preemption for the setup line
    (``{"rl": "green corridor", ...}``)."""
    per_type = len(scenarios) * len(seeds) * len(times)
    every = f", every {times[1] - times[0]} s" if len(times) > 1 else ""
    lines = ["# Emergency vehicles: MARL vs fixed-time", ""]
    lines.append(
        f"Built-in simulator, {len(scenarios)} scenario(s) ({', '.join(scenarios)}) x "
        f"{len(seeds)} seeds ({', '.join(map(str, seeds))}) x {len(times)} dispatch times "
        f"({times[0]} s to {times[-1]} s{every}) = {per_type} matched dispatches per vehicle "
        "type. Each dispatch sends one vehicle of each type into its own copy of the running "
        "simulation, under each controller, so every vehicle meets the traffic its controller "
        "has built up and no other emergency vehicle. `emergency_dispatches.csv` next to this "
        "file has every dispatch.")
    lines.append("")
    if preemption:
        lines.append("Preemption, as in the benchmark and the dashboard (`emergency.corridor` in "
                     "`config.yaml`): " + "; ".join(f"{LABEL.get(c, c)} - {preemption[c]}"
                                                    for c in CONTROLLERS if c in preemption)
                     + ".")
        lines.append("")
    lines.append("Improvement = (fixed-time \u2212 MARL) / fixed-time: positive means MARL is "
                 "lower, which is better for every metric here.")
    lines.append("")

    verdict: Dict[str, bool] = {}
    lower_in: Dict[str, int] = {}
    pooled = {}
    for kind in kinds_meta:
        part = comp[comp["kind"] == kind]
        if part.empty:
            continue
        allrow = part[part["scenario"] == "all"].iloc[0]
        per_scen = part[part["scenario"] != "all"]
        pooled[kind] = allrow
        verdict[kind] = bool(allrow["travel_s_rl"] < allrow["travel_s_ft"])
        lower_in[kind] = int((per_scen["travel_s_rl"] < per_scen["travel_s_ft"]).sum())

    lines += ["## Results (all scenarios pooled)", "",
              "| Vehicle type | Metric | Fixed-time | MARL | Improvement |",
              "|:--|:--|--:|--:|--:|"]
    for kind, r in pooled.items():
        name = f"**{kinds_meta[kind]['label']}**"
        for col, label, unit, d in METRICS:
            u = f" {unit}" if unit else ""
            lines.append(f"| {name} | {label} | {_fmt(r[f'{col}_ft'], d)}{u} | "
                         f"{_fmt(r[f'{col}_rl'], d)}{u} | {_signed_pct(r[f'{col}_impr_%'])} |")
            name = ""
    lines.append("")

    lines += ["## Pass / fail", "",
              "Pass condition: every emergency vehicle type has a lower average travel time "
              "under MARL than under fixed-time.", "",
              "| Vehicle type | Corridor | Travel time, fixed-time | Travel time, MARL | "
              "Improvement | Lower under MARL in | MARL faster / tie / slower | Result |",
              "|:--|:--|--:|--:|--:|--:|--:|:--|"]
    for kind, r in pooled.items():
        meta = kinds_meta[kind]
        lines.append(f"| {meta['label']} | {str(meta['corridor']).upper()} | "
                     f"{r['travel_s_ft']:.1f} s | {r['travel_s_rl']:.1f} s | "
                     f"{_signed_pct(r['travel_s_impr_%'])} | {lower_in[kind]} of "
                     f"{len(scenarios)} scenarios | {100 * r['rl_wins']:.0f} / "
                     f"{100 * r['ties']:.0f} / {100 * r['rl_losses']:.0f} % | "
                     f"**{'PASS' if verdict[kind] else 'FAIL'}** |")
    overall = bool(verdict) and all(verdict.values())
    lines += ["", f"Overall: **{'PASS' if overall else 'FAIL'}**", "",
              "*MARL faster / tie / slower* is the share of matched dispatches in which the "
              "vehicle got through the MARL grid sooner, at the same second, or later.", ""]
    lines += ["## Charts", ""]
    for kind in pooled:
        lines += [f"![{kinds_meta[kind]['label']}: MARL against fixed-time on the four metrics, "
                  f"by scenario and pooled](emergency_{kind}.png)", ""]

    lines += ["## By scenario", ""]
    for kind, meta in kinds_meta.items():
        part = comp[comp["kind"] == kind]
        if part.empty:
            continue
        lines.append(f"### {meta['label']} ({str(meta['corridor']).upper()} corridor, "
                     f"speed factor {float(meta['speed_factor']):.2f})")
        lines.append("")
        lines.append("| Scenario | Metric | Fixed-time | MARL | Improvement |")
        lines.append("|:--|:--|--:|--:|--:|")
        for _, r in part[part["scenario"] != "all"].iterrows():
            scen = r["scenario"]
            for col, label, unit, d in METRICS:
                u = f" {unit}" if unit else ""
                lines.append(f"| {scen} | {label} | {_fmt(r[f'{col}_ft'], d)}{u} | "
                             f"{_fmt(r[f'{col}_rl'], d)}{u} | {_signed_pct(r[f'{col}_impr_%'])} |")
                scen = ""
        lines.append("")
        lines.append("| Scenario | Matched dispatches | MARL faster | Tie | Fixed-time faster | "
                     "Seeds where MARL's mean is lower | 95 % CI of the gain over seeds |")
        lines.append("|:--|--:|--:|--:|--:|--:|--:|")
        for _, r in part.iterrows():
            scen = "**all**" if r["scenario"] == "all" else r["scenario"]
            gain = r["travel_s_ft"] - r["travel_s_rl"]
            ci = r["travel_diff_ci95_s"]
            lines.append(f"| {scen} | {int(r['pairs'])} | {100 * r['rl_wins']:.0f} % | "
                         f"{100 * r['ties']:.0f} % | {100 * r['rl_losses']:.0f} % | "
                         f"{int(r['rl_better_seed_groups'])} / {int(r['seed_groups'])} | "
                         f"{gain:+.1f} \u00b1 {_fmt(ci, 1)} s |")
        lines.append("")

    lines += ["## Metric definitions", "",
              "- **Average travel time**: from dispatch (the vehicle enters the grid at the back "
              "of the entry queue) until it crosses the last junction on its route; this is the "
              "project's `emergency_clearance_time` and is read back from the simulator.",
              "- **Waiting time**: seconds the vehicle spent held at stop lines (the simulator's "
              "own waiting-time count). Travel time = waiting time + the free-flow drive along "
              "the link between the junctions.",
              "- **Number of stops**: junctions at which the vehicle was held longer than the 1 s "
              "the point-queue model needs to cross an empty approach on green.",
              "- **Time to clear an intersection**: from reaching a junction's stop line to "
              "crossing it, averaged over the junctions on the route (2 on the 2 x 2 grid).",
              "- **95 % CI of the gain over seeds**: fixed-time's minus MARL's mean travel time, "
              "with a 95 % t-interval over the per-seed means (per scenario and seed for "
              "**all**).", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return verdict


def plot_types(comp, out_dir: Path, scenarios: Sequence[str],
               kinds_meta: Dict[str, Dict[str, object]]) -> List[Path]:
    """One comparison chart per emergency type: the four metrics, MARL against fixed-time,
    per scenario and pooled over every scenario. MARL is green and fixed-time grey, as in
    the benchmark plots; each pair is labelled with MARL's improvement."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"fixed_time": "#8c8c8c", "rl": "#2e7d32"}
    ink, secondary, muted = "#0b0b0b", "#52514e", "#898781"
    grid, axis_rule = "#e1e0d9", "#c3c2b7"
    order = [s for s in scenarios] + ["all"]
    names = {s: s.capitalize() for s in scenarios}
    names["all"] = "All"
    paths: List[Path] = []
    for kind, meta in kinds_meta.items():
        part = comp[comp["kind"] == kind].set_index("scenario")
        if part.empty or "all" not in part.index:
            continue
        xs = [s for s in order if s in part.index]
        # the pooled group stands a little apart from the scenarios it pools
        x = [i + (0.45 if s == "all" else 0.0) for i, s in enumerate(xs)]
        fig, axes = plt.subplots(1, len(METRICS), figsize=(14, 4.1))
        w = 0.34
        for ax, (col, label, unit, d) in zip(axes, METRICS):
            ft = [float(part.loc[s, f"{col}_ft"]) for s in xs]
            rl = [float(part.loc[s, f"{col}_rl"]) for s in xs]
            # white edges leave a surface gap between the two bars of a pair
            ax.bar([v - w / 2 for v in x], ft, w, color=colors["fixed_time"],
                   edgecolor="white", linewidth=1.1, label="Fixed-time")
            ax.bar([v + w / 2 for v in x], rl, w, color=colors["rl"],
                   edgecolor="white", linewidth=1.1, label="MARL")
            top = max(ft + rl) or 1.0
            for v, s, a, b in zip(x, xs, ft, rl):
                pct = float(part.loc[s, f"{col}_impr_%"])
                ax.text(v, max(a, b) + 0.025 * top, _signed_pct(pct).replace(" %", "%"),
                        ha="center", va="bottom", fontsize=8,
                        color=ink if s == "all" else secondary,
                        fontweight="bold" if s == "all" else "normal")
            ax.set_xticks(x)
            ax.set_xticklabels([names[s] for s in xs], fontsize=8.5, color=secondary)
            for tick, s in zip(ax.get_xticklabels(), xs):
                if s == "all":
                    tick.set_fontweight("bold")
                    tick.set_color(ink)
            ax.set_title(label + (f" ({unit})" if unit else ""), fontsize=10, color=ink,
                         loc="left", pad=8)
            ax.set_ylim(0, top * 1.16)
            ax.tick_params(axis="y", labelsize=8, colors=muted, length=0)
            ax.tick_params(axis="x", length=0)
            ax.grid(axis="y", color=grid, linewidth=0.7)
            ax.set_axisbelow(True)
            for side in ("top", "right", "left"):
                ax.spines[side].set_visible(False)
            ax.spines["bottom"].set_color(axis_rule)
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.995, 0.975), ncol=2,
                   frameon=False, fontsize=9, handlelength=1.0, columnspacing=1.4)
        allrow = part.loc["all"]
        passed = allrow["travel_s_rl"] < allrow["travel_s_ft"]
        fig.text(0.008, 0.955, f"{meta['label']}: MARL vs fixed-time", fontsize=12.5,
                 color=ink, fontweight="bold", va="top")
        fig.text(0.008, 0.895,
                 f"{'PASS' if passed else 'FAIL'}  \u00b7  mean travel time "
                 f"{allrow['travel_s_rl']:.1f} s under MARL against {allrow['travel_s_ft']:.1f} s "
                 f"under fixed-time ({_signed_pct(allrow['travel_s_impr_%'])}); "
                 f"{str(meta['corridor']).upper()} corridor, means over every seed and dispatch",
                 fontsize=9.5, color=secondary, va="top")
        fig.text(0.008, 0.012, "Labels: MARL's improvement over fixed-time (positive = MARL "
                 "lower = better). 'All' pools the scenarios.", fontsize=8, color=muted)
        fig.tight_layout(rect=(0, 0.04, 1, 0.86))
        path = out_dir / f"emergency_{kind}.png"
        fig.savefig(path, dpi=130, facecolor="white")
        plt.close(fig)
        paths.append(path)
    return paths


# --------------------------------------------------------------------------- #
def main(argv: Optional[Iterable[str]] = None) -> int:
    from atsc import vehicles as vehicle_catalogue
    from atsc.config import load_config, project_root
    from atsc.control.emergency import corridor_controllers

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None, help="config file (default config.yaml)")
    ap.add_argument("--scenarios", nargs="+", default=None, help="default: eval.scenarios")
    ap.add_argument("--seeds", nargs="+", type=int, default=list(range(10)),
                    help="default: 0..9")
    ap.add_argument("--dispatch", nargs="+", type=int, default=None,
                    help="dispatch times in s (multiples of the decision interval); "
                         "default: 60, 125, ... 1620")
    ap.add_argument("--checkpoint", default=None, help="RL checkpoint (default: the shipped one)")
    ap.add_argument("--nn-backend", default=None, choices=["torch", "numpy"],
                    help="network for the RL controller (default: rl.nn_backend)")
    ap.add_argument("--workers", type=int, default=max(1, min(4, os.cpu_count() or 1)))
    ap.add_argument("--out", default=None, help="output folder (default outputs/emergency)")
    ap.add_argument("--quick", action="store_true",
                    help="smoke test: first scenario, seeds 0-1, four dispatches")
    args = ap.parse_args(list(argv) if argv is not None else None)

    cfg = load_config(args.config)
    scenarios = args.scenarios or list(cfg.eval.scenarios)
    seeds = args.seeds
    times = tuple(args.dispatch) if args.dispatch else DEFAULT_DISPATCH
    if args.quick:
        scenarios, seeds, times = scenarios[-1:], seeds[:2], QUICK_DISPATCH
    out = Path(args.out) if args.out else project_root() / "outputs" / "emergency"
    out.mkdir(parents=True, exist_ok=True)

    kinds_meta = {e["kind"]: e for e in vehicle_catalogue.emergency_types(cfg)}
    print(f"Emergency evaluation: types {list(kinds_meta)}, scenarios {scenarios}, "
          f"seeds {seeds}, {len(times)} dispatches per episode", file=sys.stderr)
    t0 = time.time()
    df = evaluate(scenarios, seeds, times, config_path=args.config, checkpoint=args.checkpoint,
                  nn_backend=args.nn_backend, workers=args.workers)
    censored = int(df["censored"].sum())
    if censored:
        print(f"WARNING: {censored} dispatches did not get through within the time limit",
              file=sys.stderr)
    times = tuple(sorted(df["dispatch_s"].unique()))
    summary, comp = summarize(df, scenarios)
    df.to_csv(out / "emergency_dispatches.csv", index=False)
    summary.to_csv(out / "emergency_summary.csv", index=False)
    comp.to_csv(out / "emergency_comparison.csv", index=False)
    corridor = corridor_controllers(cfg)
    modes = {c: ("green corridor along the route" if c in corridor else "stop-line preemption")
             for c in CONTROLLERS}
    verdict = write_markdown(comp, df, out / "emergency_results.md", scenarios, seeds, times,
                             kinds_meta, preemption=modes)
    plot_types(comp, out, scenarios, kinds_meta)

    print(f"\nDone in {time.time() - t0:.0f} s -> {out}", file=sys.stderr)
    allc = comp[comp["scenario"] == "all"]
    for _, r in allc.iterrows():
        print(f"  {kinds_meta[r['kind']]['label']:12s} travel MARL {r['travel_s_rl']:6.1f} s  "
              f"fixed-time {r['travel_s_ft']:6.1f} s  ({_signed_pct(r['travel_s_impr_%'])})  "
              f"{'PASS' if verdict.get(r['kind']) else 'FAIL'}")
    ok = bool(verdict) and all(verdict.values())
    print(f"Overall: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
