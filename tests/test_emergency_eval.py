"""tools/emergency_eval.py: every dispatch is followed to the end, its numbers add up to what
the simulator counts, and the summary, table and charts come out of them."""
import importlib.util
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ev():
    spec = importlib.util.spec_from_file_location("emergency_eval",
                                                  ROOT / "tools" / "emergency_eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dispatches(ev):
    return ev.evaluate(["high"], [3], dispatch_times=(60, 125, 190), workers=1, progress=False)


def test_every_dispatch_is_matched_and_gets_through(dispatches):
    df = dispatches
    assert len(df) == 2 * 3 * 3                       # controllers x dispatch times x types
    assert not df["censored"].any()
    assert set(df["controller"]) == {"rl", "fixed_time"}
    assert set(df["kind"]) == {"ambulance", "police", "fire"}
    pairs = df.groupby(["kind", "dispatch_s"])["controller"].nunique()
    assert (pairs == 2).all()


def test_the_measurements_add_up_to_what_the_simulator_counts(cfg, dispatches):
    for _, r in dispatches.iterrows():
        # travel = time held at the two stop lines + the drive along the link between them,
        # in whole simulated seconds
        drive = math.ceil(cfg.network.link_length_m / (cfg.sim.free_speed_mps * r["speed_factor"]))
        assert r["travel_s"] == r["wait_s"] + drive
        assert r["j1_clear_s"] + r["j2_clear_s"] == r["wait_s"]
        assert r["clear_s"] == r["wait_s"] / 2
        assert r["j1_clear_s"] >= 1 and r["j2_clear_s"] >= 1       # 1 s to cross, at best
        assert r["stops"] == (r["j1_clear_s"] > 1) + (r["j2_clear_s"] > 1)
        for j in ("j1", "j2"):
            assert 0 <= r[f"{j}_signal_s"] < r[f"{j}_clear_s"]
            assert r[f"{j}_green_on_arrival"] == (r[f"{j}_signal_s"] == 0)


def test_the_summary_table_and_charts(ev, cfg, dispatches, tmp_path):
    from atsc import vehicles
    meta = {e["kind"]: e for e in vehicles.emergency_types(cfg)}
    summary, comp = ev.summarize(dispatches, ["high"])
    assert set(comp["scenario"]) == {"all", "high"}
    row = comp[(comp["kind"] == "police") & (comp["scenario"] == "high")].iloc[0]
    rl = dispatches[(dispatches["kind"] == "police") & (dispatches["controller"] == "rl")]
    assert row["travel_s_rl"] == pytest.approx(rl["travel_s"].mean())
    ft = row["travel_s_ft"]
    assert row["travel_s_impr_%"] == pytest.approx(100 * (ft - row["travel_s_rl"]) / ft)
    assert row["rl_wins"] + row["ties"] + row["rl_losses"] == pytest.approx(1.0)
    verdict = ev.write_markdown(comp, dispatches, tmp_path / "r.md", ["high"], [3],
                                (60, 125, 190), meta)
    text = (tmp_path / "r.md").read_text()
    assert set(verdict) == set(meta) and "Pass condition" in text
    assert ("Overall: **PASS**" in text) == all(verdict.values())
    charts = ev.plot_types(comp, tmp_path, ["high"], meta)
    assert [p.name for p in charts] == [f"emergency_{k}.png" for k in meta]
    assert all(p.stat().st_size > 10_000 for p in charts)
