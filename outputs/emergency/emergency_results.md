# Emergency vehicles: MARL vs fixed-time

Built-in simulator, 4 scenario(s) (low, medium, high, rush) x 10 seeds (0, 1, 2, 3, 4, 5, 6, 7, 8, 9) x 25 dispatch times (60 s to 1620 s, every 65 s) = 1000 matched dispatches per vehicle type. Each dispatch sends one vehicle of each type into its own copy of the running simulation, under each controller, so every vehicle meets the traffic its controller has built up and no other emergency vehicle. `emergency_dispatches.csv` next to this file has every dispatch.

Preemption, as in the benchmark and the dashboard (`emergency.corridor` in `config.yaml`): MARL - green corridor along the route; Fixed-time - stop-line preemption.

Improvement = (fixed-time − MARL) / fixed-time: positive means MARL is lower, which is better for every metric here.

## Results (all scenarios pooled)

| Vehicle type | Metric | Fixed-time | MARL | Improvement |
|:--|:--|--:|--:|--:|
| **Ambulance** | Average travel time | 61.7 s | 24.5 s | +60.4 % |
|  | Waiting time | 49.7 s | 12.5 s | +74.9 % |
|  | Number of stops | 1.78 | 1.54 | +13.7 % |
|  | Time to clear an intersection | 24.8 s | 6.2 s | +74.9 % |
| **Police car** | Average travel time | 22.9 s | 20.9 s | +8.9 % |
|  | Waiting time | 11.9 s | 9.9 s | +17.1 % |
|  | Number of stops | 1.40 | 1.29 | +7.6 % |
|  | Time to clear an intersection | 5.9 s | 4.9 s | +17.1 % |
| **Fire engine** | Average travel time | 64.0 s | 26.3 s | +58.9 % |
|  | Waiting time | 51.0 s | 13.3 s | +73.9 % |
|  | Number of stops | 1.80 | 1.66 | +7.9 % |
|  | Time to clear an intersection | 25.5 s | 6.7 s | +73.9 % |

## Pass / fail

Pass condition: every emergency vehicle type has a lower average travel time under MARL than under fixed-time.

| Vehicle type | Corridor | Travel time, fixed-time | Travel time, MARL | Improvement | Lower under MARL in | MARL faster / tie / slower | Result |
|:--|:--|--:|--:|--:|--:|--:|:--|
| Ambulance | EW | 61.7 s | 24.5 s | +60.4 % | 4 of 4 scenarios | 85 / 3 / 11 % | **PASS** |
| Police car | NS | 22.9 s | 20.9 s | +8.9 % | 4 of 4 scenarios | 58 / 9 / 32 % | **PASS** |
| Fire engine | EW | 64.0 s | 26.3 s | +58.9 % | 4 of 4 scenarios | 85 / 3 / 11 % | **PASS** |

Overall: **PASS**

*MARL faster / tie / slower* is the share of matched dispatches in which the vehicle got through the MARL grid sooner, at the same second, or later.

## Charts

![Ambulance: MARL against fixed-time on the four metrics, by scenario and pooled](emergency_ambulance.png)

![Police car: MARL against fixed-time on the four metrics, by scenario and pooled](emergency_police.png)

![Fire engine: MARL against fixed-time on the four metrics, by scenario and pooled](emergency_fire.png)

## By scenario

### Ambulance (EW corridor, speed factor 1.30)

| Scenario | Metric | Fixed-time | MARL | Improvement |
|:--|:--|--:|--:|--:|
| low | Average travel time | 23.9 s | 19.9 s | +16.7 % |
|  | Waiting time | 11.9 s | 7.9 s | +33.5 % |
|  | Number of stops | 1.45 | 1.11 | +23.7 % |
|  | Time to clear an intersection | 6.0 s | 4.0 s | +33.5 % |
| medium | Average travel time | 29.6 s | 21.5 s | +27.3 % |
|  | Waiting time | 17.6 s | 9.5 s | +45.9 % |
|  | Number of stops | 1.71 | 1.40 | +18.0 % |
|  | Time to clear an intersection | 8.8 s | 4.8 s | +45.9 % |
| high | Average travel time | 73.7 s | 27.2 s | +63.1 % |
|  | Waiting time | 61.7 s | 15.2 s | +75.3 % |
|  | Number of stops | 1.98 | 1.83 | +7.7 % |
|  | Time to clear an intersection | 30.8 s | 7.6 s | +75.3 % |
| rush | Average travel time | 119.6 s | 29.1 s | +75.6 % |
|  | Waiting time | 107.6 s | 17.1 s | +84.1 % |
|  | Number of stops | 2.00 | 1.82 | +8.6 % |
|  | Time to clear an intersection | 53.8 s | 8.6 s | +84.1 % |

| Scenario | Matched dispatches | MARL faster | Tie | Fixed-time faster | Seeds where MARL's mean is lower | 95 % CI of the gain over seeds |
|:--|--:|--:|--:|--:|--:|--:|
| **all** | 1000 | 85 % | 3 % | 11 % | 40 / 40 | +37.2 ± 12.6 s |
| low | 250 | 66 % | 9 % | 25 % | 10 / 10 | +4.0 ± 1.0 s |
| medium | 250 | 76 % | 4 % | 20 % | 10 / 10 | +8.1 ± 1.3 s |
| high | 250 | 100 % | 0 % | 0 % | 10 / 10 | +46.5 ± 11.8 s |
| rush | 250 | 100 % | 0 % | 0 % | 10 / 10 | +90.5 ± 27.6 s |

### Police car (NS corridor, speed factor 1.40)

| Scenario | Metric | Fixed-time | MARL | Improvement |
|:--|:--|--:|--:|--:|
| low | Average travel time | 20.4 s | 17.6 s | +13.6 % |
|  | Waiting time | 9.4 s | 6.6 s | +29.6 % |
|  | Number of stops | 1.15 | 0.87 | +24.7 % |
|  | Time to clear an intersection | 4.7 s | 3.3 s | +29.6 % |
| medium | Average travel time | 21.8 s | 18.8 s | +13.7 % |
|  | Waiting time | 10.8 s | 7.8 s | +27.7 % |
|  | Number of stops | 1.32 | 1.13 | +14.8 % |
|  | Time to clear an intersection | 5.4 s | 3.9 s | +27.7 % |
| high | Average travel time | 24.5 s | 22.6 s | +7.5 % |
|  | Waiting time | 13.5 s | 11.6 s | +13.6 % |
|  | Number of stops | 1.55 | 1.53 | +1.3 % |
|  | Time to clear an intersection | 6.7 s | 5.8 s | +13.6 % |
| rush | Average travel time | 24.9 s | 24.4 s | +2.2 % |
|  | Waiting time | 13.9 s | 13.4 s | +3.9 % |
|  | Number of stops | 1.58 | 1.65 | −4.8 % |
|  | Time to clear an intersection | 7.0 s | 6.7 s | +3.9 % |

| Scenario | Matched dispatches | MARL faster | Tie | Fixed-time faster | Seeds where MARL's mean is lower | 95 % CI of the gain over seeds |
|:--|--:|--:|--:|--:|--:|--:|
| **all** | 1000 | 58 % | 9 % | 32 % | 37 / 40 | +2.0 ± 0.4 s |
| low | 250 | 61 % | 11 % | 28 % | 10 / 10 | +2.8 ± 0.6 s |
| medium | 250 | 59 % | 10 % | 31 % | 10 / 10 | +3.0 ± 0.6 s |
| high | 250 | 58 % | 8 % | 34 % | 10 / 10 | +1.8 ± 0.7 s |
| rush | 250 | 54 % | 9 % | 37 % | 7 / 10 | +0.5 ± 1.1 s |

### Fire engine (EW corridor, speed factor 1.15)

| Scenario | Metric | Fixed-time | MARL | Improvement |
|:--|:--|--:|--:|--:|
| low | Average travel time | 25.7 s | 21.8 s | +15.4 % |
|  | Waiting time | 12.7 s | 8.8 s | +31.1 % |
|  | Number of stops | 1.50 | 1.35 | +9.9 % |
|  | Time to clear an intersection | 6.4 s | 4.4 s | +31.1 % |
| medium | Average travel time | 31.8 s | 23.3 s | +26.7 % |
|  | Waiting time | 18.8 s | 10.3 s | +45.2 % |
|  | Number of stops | 1.72 | 1.55 | +10.0 % |
|  | Time to clear an intersection | 9.4 s | 5.1 s | +45.2 % |
| high | Average travel time | 76.3 s | 29.2 s | +61.8 % |
|  | Waiting time | 63.3 s | 16.2 s | +74.5 % |
|  | Number of stops | 1.98 | 1.86 | +5.9 % |
|  | Time to clear an intersection | 31.6 s | 8.1 s | +74.5 % |
| rush | Average travel time | 122.3 s | 31.1 s | +74.6 % |
|  | Waiting time | 109.3 s | 18.1 s | +83.5 % |
|  | Number of stops | 2.00 | 1.86 | +6.8 % |
|  | Time to clear an intersection | 54.6 s | 9.0 s | +83.5 % |

| Scenario | Matched dispatches | MARL faster | Tie | Fixed-time faster | Seeds where MARL's mean is lower | 95 % CI of the gain over seeds |
|:--|--:|--:|--:|--:|--:|--:|
| **all** | 1000 | 85 % | 3 % | 11 % | 40 / 40 | +37.7 ± 12.7 s |
| low | 250 | 65 % | 10 % | 25 % | 10 / 10 | +4.0 ± 0.9 s |
| medium | 250 | 77 % | 2 % | 20 % | 10 / 10 | +8.5 ± 1.6 s |
| high | 250 | 100 % | 0 % | 0 % | 10 / 10 | +47.1 ± 11.9 s |
| rush | 250 | 100 % | 0 % | 0 % | 10 / 10 | +91.2 ± 27.4 s |

## Metric definitions

- **Average travel time**: from dispatch (the vehicle enters the grid at the back of the entry queue) until it crosses the last junction on its route; this is the project's `emergency_clearance_time` and is read back from the simulator.
- **Waiting time**: seconds the vehicle spent held at stop lines (the simulator's own waiting-time count). Travel time = waiting time + the free-flow drive along the link between the junctions.
- **Number of stops**: junctions at which the vehicle was held longer than the 1 s the point-queue model needs to cross an empty approach on green.
- **Time to clear an intersection**: from reaching a junction's stop line to crossing it, averaged over the junctions on the route (2 on the 2 x 2 grid).
- **95 % CI of the gain over seeds**: fixed-time's minus MARL's mean travel time, with a 95 % t-interval over the per-seed means (per scenario and seed for **all**).
