# CHEATSHEET.md — say these cold

*One page, memorised cold. Numbers are from the real code
(`config.yaml`, `src/atsc/…`, `outputs/benchmark_summary.md`).*

---

**1. Elevator pitch (30 s).**
"Traffic lights usually run on fixed timers that ignore real traffic. We replace them with a
multi-agent Deep Reinforcement Learning controller — one Double + Dueling DQN per
intersection on a 2×2 grid — that watches the queues and decides which direction gets green,
second by second. Agents see their neighbours, so they coordinate into green waves. On
identical traffic it cuts average waiting time by up to ~61%, never allows an unsafe light
combination, and clears ambulances faster."

**2. State (one line).** 23 numbers per agent: per-approach queue (4) + waiting time (4) +
current-phase one-hot (2) + green-time-so-far (1) + emergency flags (4) + neighbour pressures
(4) + neighbour phases (4). *(`src/atsc/envs/spaces.py`)*

**3. Action (one line).** Choose the next green phase — NS or EW — a `Discrete(2)`; the agent
only *requests*, the safety FSM enforces legality. *(`envs/phases.py`)*

**4. Reward (one line).**
`r = −1.0·delay/40 − 0.30·pressure/40 − 0.20·switched + 5.0·emergency_cleared`
(minimise waiting & queues; penalise flicker; big bonus for clearing ambulances — though
training never sends one, so in practice the policy learns from the first three terms).
*(`traffic_env._rewards`, weights in `config.yaml → reward`)*

**5. Algorithm (one line).** Double DQN (kills Q over-estimation) + Dueling network (value vs
advantage) + Prioritized Experience Replay + target network; ε-greedy 1.0→0.05 over 22,000
steps; Adam lr 5e-4, γ 0.99, batch 64, hidden [128,128], Huber loss. *(`config.yaml → rl`,
`agents/double_dqn_agent.py`)*

**6. Headline results (memorise the table).** RL vs fixed-time, identical seeds:
Low **−16%**, Medium **−28%**, High **−48%**, Rush **−61%**, mean **≈38%**. Against the
strong **max-pressure** baseline: max-pressure wins at low and medium, RL draws level at high
(35.6 s each) and wins clearly at rush (43.9 vs 50.5 s). *(`outputs/benchmark_summary.md`)*

**7. Safety guarantee (say it with confidence).** The agent never drives the lights. A
finite-state machine (`phases.py`) enforces min-green 10 s, max-green 60 s, mandatory 3 s
yellow + 2 s all-red on every change — so conflicting greens are **impossible by
construction**. Verified over **18,000 random requests** (`test_phases_safety.py`).
*Know the caveat:* it accepts a new request during amber/all-red, so a policy can cancel a
change and keep a side street waiting past 60 s (up to ~113 s seen) — no conflict, but not
a starvation guarantee.

**8. Multi-agent / green wave.** One agent per intersection; they coordinate through neighbour
pressure + phase in the state (no central controller); by default they share network weights.
That coordination is what produces green waves.

**9. Emergency preemption (real number).** A rule-based override, never learned: on the RL
grid it clears a **green corridor** — the moment an emergency vehicle is sent, every junction
still ahead of it requests its phase until it has crossed; the fixed-time grid pre-empts a
junction only once the vehicle waits there. Both go through yellow/all-red. Measured
clearance **1.4× (low) → 4.5× (rush)** faster than fixed-time. *(Do NOT say 10×.)* Per type
(`tools/emergency_eval.py`, 1,000 matched dispatches each): ambulance **−60%**, police car
**−9%**, fire engine **−59%** travel time. *Know the caveat:* the police car is on the side
street, where the agents give less green — its lead comes from the corridor, is only 0.5 s at
rush, and with the same preemption on both grids it would be slower under RL.
*(`control/emergency.py`, `outputs/emergency/emergency_results.md`)*

**10. Baselines & fairness.** Compared against **fixed-time (30/30 s)** AND **max-pressure**
(near-optimal adaptive) on **byte-identical traffic** (same seed → same cars). *(`eval/benchmark.py`)*

**11. The one honest limitation (raise it first).** No time-of-day feature in the state → the
greedy policy can be whipsawed by sharp surges, so we model rush as *sustained* heavy demand.
Fix = add an arrival-rate / recurrent feature. *(`REPORT.md §8-9`)*

**12. Contribution / novelty (single best answer).** "Not a new RL algorithm — the novelty is
the **integration and rigor**: multi-agent neighbour-aware coordination (green waves) + a
provable safety layer + emergency preemption + honest multi-density benchmarking against TWO
baselines on identical seeds + a dependency-optional design that just runs anywhere, with a
live dashboard. Most prior student works do one junction, one scenario, no safety, no
emergencies."

**13. The live demo (what to show).** The page opens at rush hour, the RL Agent System on the
left and the Traditional Traffic System on the right, on identical traffic. Press **Send
emergency vehicle → Send ambulance**: the same ambulance enters both grids, the race drops to
slow motion, and the line above each map says where it is and why (*Waiting 0:12 · Red light
at J1_0 · 9 vehicles ahead · Junction 1 of 2*). The tracker under the maps says which system
has it further along, and once it is through both grids the race pauses on the result — for
an ambulance at rush hour about 4× faster on average (*RL Agent System got it through …×
faster*). Every word
comes from the simulator's own queues and links. *(`dashboard/session.py`, `static/js/tracker.js`)*

---

**Three things NOT to overstate:** emergency clearance is **~1.4–4.5×**, not 10×; the police
car's lead is small (−9% on average, 0.5 s at rush); and rush is **sustained heavy demand**,
not a time-varying spike (that's the limitation).

**If you forget everything else:** *state = 23 numbers (queues + waits + phase + neighbours +
emergency); action = pick NS or EW; reward = minimise delay, penalise flicker, reward
clearing ambulances; safety is a separate FSM; ~38% average waiting-time cut vs fixed-time.*
