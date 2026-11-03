"""
Offline evaluation: fixed BBMP schedule (slide 2) vs WASTEX multi-agent policy.

Both strategies run on the *identical* synthetic city (same seed, same bins,
same fill dynamics) for 24 simulated hours. The WASTEX run reuses the real
Waste / Route / Fleet agent classes, so the numbers reflect the same logic
that runs live on Kafka.

    python -m backend.benchmark
"""
import random
from collections import deque

from . import config
from .agents.fleet_agent import FleetManagerAgent
from .agents.route_agent import RoutePlannerAgent
from .agents.waste_agent import WasteIntelligenceAgent
from .core import demand_multiplier, haversine_km, road_km, traffic_speed_kmh
from .data.bengaluru import DEPOTS, FLEET, ZONES
from .simulator.iot import SmartBin
from .streaming.processor import slope

FIXED_TIMES = {"fixed": [(7, 30), (18, 0)],                       # BBMP schedule (slide 2)
               "fixed4": [(7, 30), (12, 30), (18, 0), (23, 0)]}  # same idea, twice as often
COST_PER_KM_INR = 42.0  # diesel + maintenance for a municipal truck


def _make_city(seed):
    rng = random.Random(seed)
    bins = [SmartBin(rng, z, i + 1) for z in ZONES for i in range(config.BINS_PER_ZONE)]
    return bins


def _route_times(start, stops, hour):
    """Arrival minute offsets for each stop along a route."""
    speed = traffic_speed_kmh(hour) / 60
    t, cur, out = 0.0, start, []
    for s in stops:
        t += road_km(cur, s) / speed
        out.append(t)
        t += config.SERVICE_MIN_PER_BIN
        cur = s
    return out, t


def simulate(strategy, hours=24, seed=config.SEED):
    bins = _make_city(seed)
    noise = random.Random(seed + 1)
    by_id = {b.id: b for b in bins}
    hist = {b.id: deque(maxlen=config.FILL_RATE_WINDOW) for b in bins}
    depot = {d["id"]: d for d in DEPOTS}
    trucks = {f["id"]: {"truck_id": f["id"], "type": f["type"], "capacity_kg": f["capacity_kg"], "load_kg": 0,
                        "planned_kg": 0, "status": "idle", "free_at": 0.0,
                        "lat": depot[f["depot"]]["lat"], "lon": depot[f["depot"]]["lon"], "remaining_stops": []}
              for f in FLEET}
    waste, route, fleet = WasteIntelligenceAgent(), RoutePlannerAgent(), FleetManagerAgent()
    due = []                     # (minute, bin_id)
    scheduled = set()
    km = 0.0
    trips = disposals = 0
    plant_km = 0.0
    overflow_min = 0
    overflow_events = 0
    fills_at_collection = []
    series = []
    done_fixed = set()

    for minute in range(hours * 60):
        hour = (config.SIM_START_HOUR + minute / 60) % 24
        dm = demand_multiplier(hour)
        # ---- physical world -------------------------------------------------
        for b in bins:
            rate = b.zone["base_rate"] * b.factor * dm
            was_full = b.fill >= 100
            b.fill = min(100.0, b.fill + max(0.0, noise.gauss(rate, rate * 0.25)))
            if b.fill >= 100:
                overflow_min += 1
                if not was_full:
                    overflow_events += 1
            hist[b.id].append((minute, b.fill))
        for item in [d for d in due if d[0] <= minute]:
            due.remove(item)
            b = by_id[item[1]]
            fills_at_collection.append(b.fill)
            b.fill = 2.0
            hist[b.id].clear()
            scheduled.discard(b.id)
        for t in trucks.values():
            t["status"] = "idle" if t["free_at"] <= minute else "en_route"
            if t["status"] == "idle":
                t["remaining_stops"] = []
                t["planned_kg"] = 0

        # ---- decision policy ------------------------------------------------
        hh, mm = int(hour), int(round((hour - int(hour)) * 60)) % 60
        if strategy in FIXED_TIMES:
            key = (minute // 1440, hh, mm)
            if (hh, mm) in FIXED_TIMES[strategy] and key not in done_fixed:
                done_fixed.add(key)
                # each depot's trucks sweep every bin closest to that depot
                for d in DEPOTS:
                    mine = [b for b in bins if min(DEPOTS, key=lambda x: haversine_km(b.lat, b.lon, x["lat"], x["lon"]))["id"] == d["id"]]
                    dtrucks = [t for t in trucks.values() if FLEET[[f["id"] for f in FLEET].index(t["truck_id"])]["depot"] == d["id"]]
                    stops = [{"bin_id": b.id, "lat": b.lat, "lon": b.lon, "kg": b.fill / 100 * b.max_kg} for b in mine]
                    ordered = route.optimise_order(d, stops)
                    ti = 0
                    while ordered:
                        t = dtrucks[ti % len(dtrucks)]
                        ti += 1
                        chunk, load = [], 0.0
                        while ordered and load + ordered[0]["kg"] <= t["capacity_kg"]:
                            s = ordered.pop(0)
                            chunk.append(s)
                            load += s["kg"]
                        if not chunk:
                            chunk.append(ordered.pop(0))
                        start_at = max(minute, t["free_at"])
                        start = {"lat": t["lat"], "lon": t["lon"]}
                        times, total = _route_times(start, chunk, hour)
                        plant, dist, dur = route.cost(start, chunk, hour)
                        km += dist
                        trips += 1
                        disposals += 1
                        plant_km += road_km(chunk[-1], plant)
                        for s, at in zip(chunk, times):
                            due.append((start_at + at, s["bin_id"]))
                        t["free_at"] = start_at + dur
                        t["lat"], t["lon"] = plant["lat"], plant["lon"]
        elif minute % config.PLANNING_INTERVAL_MIN == 0:
            table = {}
            for b in bins:
                r = max(0.0, slope(list(hist[b.id])))
                eta = (100 - b.fill) / r if r > 0.01 and b.fill < 100 else (0.0 if b.fill >= 100 else None)
                table[b.id] = {"bin_id": b.id, "zone": b.zone["name"], "zone_id": b.zone["id"], "lat": b.lat,
                               "lon": b.lon, "fill_level": b.fill, "rate_per_min": r, "eta_min": eta,
                               "weight_kg": b.fill / 100 * b.max_kg, "max_kg": b.max_kg, "anomalies": []}
            assessed, _ = waste.assess(table, exclude=scheduled)
            high = [a for a in assessed if a["priority"] == "HIGH"]
            medium = waste.opportunistic(assessed)
            idle = [t for t in trucks.values() if t["status"] == "idle"]
            if high and idle:
                cap = max(t["capacity_kg"] for t in idle)
                queue = deque((r, 1) for r in route.plan(high, medium, cap, hour) if route.dispatch_ready(r))
                while queue:
                    r, attempt = queue.popleft()
                    pool = {k: v for k, v in trucks.items() if v["status"] == "idle"}
                    if not pool:
                        break
                    res = fleet.assign(r, pool)
                    if res["feasible"]:
                        t = trucks[res["truck_id"]]
                        start = {"lat": t["lat"], "lon": t["lon"]}
                        seq = route.optimise_order(start, r["stops"])
                        times, _ = _route_times(start, seq, hour)
                        dispose = route.should_dispose(t["load_kg"], r["load_kg"], t["capacity_kg"])
                        end, dist, dur = route.cost(start, seq, hour, dispose)
                        km += dist
                        trips += 1
                        if dispose:
                            disposals += 1
                            plant_km += road_km(seq[-1], end)
                        for s, at in zip(seq, times):
                            due.append((minute + at, s["bin_id"]))
                            scheduled.add(s["bin_id"])
                        t["load_kg"] = 0 if dispose else t["load_kg"] + r["load_kg"]
                        t["free_at"] = minute + dur
                        t["status"] = "en_route"
                        t["lat"], t["lon"] = end["lat"], end["lon"]
                    elif res["reason"] == "capacity" and attempt < config.MAX_REPLAN_ATTEMPTS:
                        for h in route.split(r, hour) or []:
                            queue.append((h, attempt + 1))

        if minute % 30 == 0:
            series.append({"minute": minute, "hour": round(hour, 2),
                           "overflowing": sum(1 for b in bins if b.fill >= 100),
                           "avg_fill": round(sum(b.fill for b in bins) / len(bins), 1)})

    collections = len(fills_at_collection)
    return {
        "strategy": strategy,
        "km": round(km, 1),
        "co2_kg": round(km * config.DIESEL_KG_CO2_PER_KM, 1),
        "cost_inr": round(km * COST_PER_KM_INR),
        "collections": collections,
        "avg_fill_at_collection": round(sum(fills_at_collection) / collections, 1) if collections else 0,
        "overflow_bin_minutes": overflow_min,
        "overflow_events": overflow_events,
        "km_per_collection": round(km / collections, 2) if collections else 0,
        "trips": trips,
        "disposal_trips": disposals,
        "plant_km": round(plant_km, 1),
        "avg_stops_per_trip": round(collections / trips, 1) if trips else 0,
        "series": series,
    }


_cache = {}
_lock = __import__("threading").Lock()


def compare(hours=24, seed=config.SEED):
    """Cached; concurrent callers wait for the single in-progress computation."""
    key = (hours, seed)
    with _lock:
        return _compare(key, hours, seed)


def _compare(key, hours, seed):
    if key not in _cache:
        fixed = simulate("fixed", hours, seed)
        fixed4 = simulate("fixed4", hours, seed)
        wastex = simulate("wastex", hours, seed)

        def pct(a, b):
            return round(100 * (a - b) / a, 1) if a else 0.0

        _cache[key] = {
            "hours": hours, "bins": len(ZONES) * config.BINS_PER_ZONE, "trucks": len(FLEET),
            "fixed": fixed, "fixed4": fixed4, "wastex": wastex,
            "improvement": {
                "overflow_bin_minutes_pct": pct(fixed["overflow_bin_minutes"], wastex["overflow_bin_minutes"]),
                "overflow_events_pct": pct(fixed["overflow_events"], wastex["overflow_events"]),
                "km_per_collection_pct": pct(fixed["km_per_collection"], wastex["km_per_collection"]),
                "fill_at_collection_gain": round(wastex["avg_fill_at_collection"] - fixed["avg_fill_at_collection"], 1),
            },
            "improvement_vs_fixed4": {
                "overflow_bin_minutes_pct": pct(fixed4["overflow_bin_minutes"], wastex["overflow_bin_minutes"]),
                "overflow_events_pct": pct(fixed4["overflow_events"], wastex["overflow_events"]),
                "km_pct": pct(fixed4["km"], wastex["km"]),
                "collections_pct": pct(fixed4["collections"], wastex["collections"]),
                "fill_at_collection_gain": round(wastex["avg_fill_at_collection"] - fixed4["avg_fill_at_collection"], 1),
            },
        }
    return _cache[key]


if __name__ == "__main__":
    import json
    r = compare()
    for k in ("fixed", "fixed4", "wastex"):
        r[k].pop("series")
    print(json.dumps(r, indent=2))
