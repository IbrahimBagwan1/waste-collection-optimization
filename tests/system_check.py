"""
End-to-end system check against a running WASTEX server.

    python tests/system_check.py                # server on http://127.0.0.1:8000
    python tests/system_check.py --port 8010

Exercises every API, every scenario control, the route optimizer and dispatch,
and verifies that Kafka consumer groups keep up. Exit code 0 = all checks passed.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8000)
B = f"http://127.0.0.1:{ap.parse_args().port}"
results = []


def get(p):
    return json.load(urllib.request.urlopen(B + p, timeout=240))


def post(p, d):
    r = urllib.request.Request(B + p, json.dumps(d).encode(), {"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(r, timeout=60))
    except urllib.error.HTTPError as e:
        return json.load(e)


def check(name, cond, info=""):
    results.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  ({info})" if info else ""))


def wait_until(fn, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


print(f"WASTEX system check -> {B}\n")
h = get("/api/health")
check("all pipeline threads alive", h["ok"], ", ".join(h["missing_threads"]) or h["bus"])
post("/api/control", {"action": "speed", "value": 4})
check("JEV orchestrator is deciding", wait_until(lambda: get("/api/health")["jev_cycles"] >= 2))
st = get("/api/static")
check("reference data loaded", len(st["zones"]) == 14 and len(st["plants"]) == 8 and len(st["fleet"]) == 8)
for t in st["topics"]:
    check(f"topic {t} readable", isinstance(get("/api/topic/" + t), list))

print("\nScenario controls")
for a in [{"action": "pause"}, {"action": "resume"}, {"action": "demand", "value": 1}, {"action": "demand", "value": 0},
          {"action": "surge", "zone_id": "Z05", "value": 30}, {"action": "anomaly", "kind": "fire"},
          {"action": "anomaly", "kind": "spike"}, {"action": "anomaly", "kind": "tamper"}, {"action": "anomaly", "kind": "battery"},
          {"action": "breakdown"}, {"action": "plan_now"}, {"action": "slide13"}]:
    r = post("/api/control", a)
    check(f"control {a['action']} {a.get('kind', '')}".strip(), r.get("ok"), r.get("message"))

print("\nStream processing and agents")
check("anomalies detected (fire, spike, tamper, breakdown)", wait_until(
    lambda: all(get("/api/snapshot")["alert_counts"].get(k, 0) > 0 for k in ("FIRE", "SENSOR_SPIKE", "TAMPER", "TRUCK_BREAKDOWN")), 60))
s = get("/api/snapshot")
check("140 bins and 8 trucks live", len(s["bins"]) == 140 and len(s["trucks"]) == 8)
check("hotspot ranking for 14 wards", len(s["hotspots"]) == 14)
check("JEV produced plans", wait_until(lambda: get("/api/snapshot")["jev"]["plans"] > 0, 60))
s = get("/api/snapshot")
check("route optimisation never longer than urgency order", s["jev"]["optimised_km"] <= s["jev"]["naive_km"] + 1e-6,
      f"{s['jev']['naive_km']} -> {s['jev']['optimised_km']} km")
lag = {g: sum(x["lag"] for t in v["topics"].values() for x in t) for g, v in s["kafka"]["groups"].items()}
check("consumer groups keep up (lag < 500)", lag and all(v < 500 for v in lag.values()), lag)

print("\nRoute optimizer")
free = [b["bin_id"] for b in sorted(s["bins"], key=lambda b: b["fill_level"]) if b["bin_id"] not in set(s["scheduled_bins"])]
for start in ("DEPOT-E", "TRUCK-04"):
    for plant in ("auto", "standby", "PLT2"):
        j = post("/api/route/plan", {"start": start, "bin_ids": free[:8], "plant": plant})
        ok = "results" in j and abs(min(r["km"] for r in j["results"]) - [r for r in j["results"] if r["key"] == j["best"]][0]["km"]) < 1e-6
        check(f"plan from {start} to {plant}", ok, j.get("error", ""))
j = post("/api/route/plan", {"start": "DEPOT-E", "bin_ids": free[:9], "plant": "auto"})
ex = {r["key"]: r["km"] for r in j["results"]}
check("live heuristic (2-opt + Or-opt) within 5% of the exact optimum", ex["ls"] <= ex["exact"] * 1.05, f"{ex['ls']} vs {ex['exact']} km (plain 2-opt {ex['nn2opt']})")
check("empty selection rejected", "error" in post("/api/route/plan", {"start": "DEPOT-E", "bin_ids": [], "plant": "auto"}))
check("closed plant rejected", "error" in post("/api/route/plan", {"start": "DEPOT-E", "bin_ids": free[:3], "plant": "PLT8"}))
bins = free[:4]
j = post("/api/route/plan", {"start": "DEPOT-W", "bin_ids": bins, "plant": "standby"})
best = [r for r in j["results"] if r["key"] == j["best"]][0]
truck = next(t["truck_id"] for t in j["trucks"] if t["feasible"])
r = post("/api/route/dispatch", {"start": "DEPOT-W", "bin_ids": bins, "order": best["order"], "plant": "standby", "truck_id": truck})
check("dispatch to truck via collection-plans", r.get("ok"), r.get("message"))
check("truck received the route", wait_until(lambda: set(bins) <= set(next(t for t in get("/api/snapshot")["trucks"]
                                                                            if t["truck_id"] == truck)["remaining_stops"]), 30))
r = post("/api/route/dispatch", {"start": "DEPOT-W", "bin_ids": bins, "order": best["order"], "plant": "standby", "truck_id": truck})
check("double dispatch refused", not r.get("ok"), r.get("message"))

print("\nEvaluation")
bm = get("/api/benchmark")
check("benchmark: WASTEX overflows less than the fixed schedule", bm["wastex"]["overflow_events"] < bm["fixed"]["overflow_events"])

failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed" + (f"  -  FAILED: {failed}" if failed else ""))
sys.exit(1 if failed else 0)
