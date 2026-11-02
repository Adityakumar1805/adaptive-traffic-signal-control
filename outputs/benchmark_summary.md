# Benchmark Summary

Grid: 2x2 | seeds: [0, 1, 2] | episode: 1800s | means over the seeds of outputs/benchmark_results.csv

## Average waiting time (s) by scenario and controller

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |       26.3 |         19.2 | 22.0 |
| medium   |       34.3 |         22.5 | 24.8 |
| high     |       68.7 |         35.6 | 35.6 |
| rush     |      113.0 |         50.5 | 43.9 |

## Average queue (veh/intersection)

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |        3.0 |          2.2 |  2.5 |
| medium   |        6.8 |          4.4 |  4.9 |
| high     |       20.1 |         10.4 | 10.4 |
| rush     |       36.5 |         16.3 | 14.2 |

## Throughput (vehicles completed)

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |        808 |          809 |  807 |
| medium   |       1399 |         1400 | 1398 |
| high     |       2002 |         2051 | 2057 |
| rush     |       2093 |         2246 | 2255 |

## Emergency clearance time (s)

| scenario | fixed_time | max_pressure |   rl |
|:---------|-----------:|-------------:|-----:|
| low      |       26.0 |         26.3 | 18.7 |
| medium   |       28.7 |         36.7 | 16.3 |
| high     |       80.0 |         42.0 | 31.7 |
| rush     |      113.7 |         39.3 | 25.3 |

## RL vs fixed-time: change (%)

Negative = RL is lower. For waiting time and queue length lower is better; for throughput higher is better. Same sign convention as README.md.

| scenario | waiting time |   queue | throughput |
|:---------|-------------:|--------:|-----------:|
| low      |      −16.2 % | −16.4 % |     −0.2 % |
| medium   |      −27.6 % | −27.8 % |      0.0 % |
| high     |      −48.2 % | −48.4 % |     +2.7 % |
| rush     |      −61.1 % | −61.3 % |     +7.7 % |
| **mean** |      −38.3 % | −38.5 % |     +2.5 % |
