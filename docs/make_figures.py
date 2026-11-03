"""Generate the report's charts (docs/figures/*.png) from the real data and benchmark."""
import json
import math
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from backend import benchmark  # noqa: E402
from backend.core import demand_multiplier, traffic_speed_kmh  # noqa: E402
from backend.data import bengaluru as d  # noqa: E402

OUT = os.path.join(ROOT, "docs", "figures")
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.family": "Times New Roman", "font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
C_FIX, C_FIX4, C_WX = "#c0392b", "#e69a28", "#138d75"


def save(name):
    plt.tight_layout()
    plt.savefig(os.path.join(OUT, name), dpi=170)
    plt.close()


def main():
    r = benchmark.compare(24)
    f, f4, w = r["fixed"], r["fixed4"], r["wastex"]
    with open(os.path.join(OUT, "benchmark.json"), "w") as fh:
        json.dump(r, fh, indent=2)

    # 1. overflowing bins over the day
    hours = [s["hour"] for s in f["series"]]
    lab = [f"{int(h):02d}:{int(round((h % 1) * 60)) % 60:02d}" for h in hours]
    x = range(len(lab))
    plt.figure(figsize=(8, 3.6))
    plt.plot(x, [s["overflowing"] for s in f["series"]], color=C_FIX, lw=2, label="Fixed schedule (BBMP, 2x/day)")
    plt.plot(x, [s["overflowing"] for s in f4["series"]], color=C_FIX4, lw=2, label="Fixed schedule (4x/day)")
    plt.plot(x, [s["overflowing"] for s in w["series"]], color=C_WX, lw=2.6, label="WASTEX (multi-agent)")
    plt.xticks(list(x)[::4], lab[::4], rotation=45)
    plt.ylabel("Bins overflowing")
    plt.xlabel("Simulated time of day")
    plt.legend(frameon=False)
    plt.grid(axis="y", alpha=.3)
    save("fig_overflow_series.png")

    # 2. KPI comparison
    metrics = [("Overflow\nbin-min / 100", "overflow_bin_minutes", 100), ("Overflow\nevents", "overflow_events", 1),
               ("Bin lifts\n/ 10", "collections", 10), ("Avg fill at\npickup (%)", "avg_fill_at_collection", 1),
               ("Distance\nkm / 20", "km", 20)]
    plt.figure(figsize=(8, 3.8))
    bw = 0.26
    for i, (s, c, nm) in enumerate([(f, C_FIX, "Fixed 2x/day"), (f4, C_FIX4, "Fixed 4x/day"), (w, C_WX, "WASTEX")]):
        plt.bar([k + (i - 1) * bw for k in range(len(metrics))], [s[m[1]] / m[2] for m in metrics], bw, color=c, label=nm)
    plt.xticks(range(len(metrics)), [m[0] for m in metrics])
    plt.legend(frameon=False)
    plt.grid(axis="y", alpha=.3)
    save("fig_strategy_bars.png")

    # 3. plant capacity (EDA)
    plants = [(p["area"], p["mixed_tpd"], p["intake_tpd"]) for p in d.PROCESSING_PLANTS] + [("MSGP", 600, 500)]
    plt.figure(figsize=(8, 3.6))
    idx = range(len(plants))
    plt.bar([i - .2 for i in idx], [p[1] for p in plants], .4, color="#1e5a96", label="Mixed-waste capacity (TPD)")
    plt.bar([i + .2 for i in idx], [p[2] for p in plants], .4, color="#c0782c", label="Current intake (TPD)")
    plt.xticks(idx, [p[0] for p in plants], rotation=35, ha="right")
    plt.legend(frameon=False)
    plt.grid(axis="y", alpha=.3)
    save("fig_plant_capacity.png")

    # 4. ward complaints (EDA)
    z = sorted(d.ZONES, key=lambda x: -x["complaints"])
    plt.figure(figsize=(8, 3.4))
    plt.bar([q["name"] for q in z], [q["complaints"] for q in z], color="#2e6fb7")
    plt.xticks(rotation=40, ha="right")
    plt.ylabel("Complaint records")
    plt.grid(axis="y", alpha=.3)
    save("fig_ward_complaints.png")

    # 5. demand curve + traffic speed model
    hs = [h / 4 for h in range(0, 96)]
    fig, ax = plt.subplots(figsize=(8, 3.3))
    ax.plot(hs, [demand_multiplier(h) for h in hs], color=C_WX, lw=2.4, label="Waste-generation multiplier")
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Generation multiplier")
    ax2 = ax.twinx()
    ax2.step(hs, [traffic_speed_kmh(h) for h in hs], color="#7f8c8d", lw=1.6, ls="--", where="post", label="Truck speed (km/h)")
    ax2.set_ylabel("Truck speed (km/h)")
    ax.set_xticks(range(0, 25, 2))
    lines = ax.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
    ax.legend(lines, [ln.get_label() for ln in lines], frameon=False, loc="upper left")
    save("fig_demand_model.png")

    # 6. waste-agent urgency function
    etas = list(range(0, 300, 2))
    from backend.agents.waste_agent import HORIZON_ETA, URGENT_ETA
    u = [1.0 if e <= URGENT_ETA else max(0.0, 1 - (e - URGENT_ETA) / (HORIZON_ETA - URGENT_ETA)) for e in etas]
    plt.figure(figsize=(6.5, 2.8))
    plt.plot(etas, u, color="#c0392b", lw=2.4)
    plt.xlabel("Predicted time to overflow (min)")
    plt.ylabel("Urgency")
    plt.grid(alpha=.3)
    save("fig_urgency.png")
    routing_study()
    print("figures written to", OUT)
    return r


def routing_study(trials=20, seed=7):
    """Average saving / optimality gap / runtime of each routing algorithm on random bin sets."""
    import random
    import statistics as st

    from backend import routing
    from backend.simulator.iot import SmartBin
    rng = random.Random(seed)
    bins = [SmartBin(rng, z, i + 1) for z in d.ZONES for i in range(10)]
    rows, runtime = [], {"ls": [], "exact": []}
    sizes = [5, 6, 7, 8, 9, 10, 11, 12, 15, 20]
    for n in sizes:
        agg = {}
        for _ in range(trials if n <= 12 else trials // 2):
            sel = rng.sample(bins, n)
            stops = [{"lat": b.lat, "lon": b.lon, "bin_id": b.id} for b in sel]
            res = routing.compare(rng.choice(d.DEPOTS), stops, None)
            if n == 12:  # compare() stops at 11; time the exact solver once more for the growth curve
                import time as _t
                t0 = _t.perf_counter()
                routing.held_karp(d.DEPOTS[0], stops, None)
                agg.setdefault("exact_rt", []).append((_t.perf_counter() - t0) * 1000)
            for x in res:
                agg.setdefault(x["key"], []).append((x["saving_pct"], x["gap_pct"], x["runtime_ms"]))
        row = {"n": n}
        for k in ("nn", "nn2opt", "ls", "exact"):
            if k in agg:
                row[k] = {"saving": round(st.mean(a[0] for a in agg[k]), 1), "gap": round(st.mean(a[1] for a in agg[k]), 2),
                          "ms": round(st.mean(a[2] for a in agg[k]), 2)}
        rows.append(row)
        runtime["ls"].append(row["ls"]["ms"])
        runtime["exact"].append(row["exact"]["ms"] if "exact" in row else (round(st.mean(agg["exact_rt"]), 2) if "exact_rt" in agg else None))
    with open(os.path.join(OUT, "routing_study.json"), "w") as fh:
        json.dump(rows, fh, indent=1)
    plt.figure(figsize=(7.5, 3.3))
    plt.semilogy(sizes, runtime["ls"], "o-", color=C_WX, lw=2, label="Multi-start 2-opt + Or-opt (live)")
    xs = [s for s, v in zip(sizes, runtime["exact"]) if v]
    plt.semilogy(xs, [v for v in runtime["exact"] if v], "s-", color=C_FIX, lw=2, label="Held-Karp exact (O(n²·2ⁿ))")
    plt.xlabel("Number of bins in the route")
    plt.ylabel("Runtime (ms, log scale)")
    plt.legend(frameon=False)
    plt.grid(alpha=.3, which="both")
    save("fig_routing_runtime.png")
    return rows


if __name__ == "__main__":
    main()
