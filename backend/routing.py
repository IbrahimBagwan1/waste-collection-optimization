"""
Route optimisation toolkit (used by the Route Planner Agent and the Route Optimizer page).

Problem: given a start point (depot / truck), a set of bins and an end point
(processing plant or standby), find the visiting order with the shortest road
distance - a Travelling Salesman Path problem (NP-hard).

Algorithms compared:
  * As selected   - bins visited in the order they were picked (no optimisation)
  * Nearest neighbour (NN) - greedy construction, O(n^2)
  * NN + 2-opt    - local search that reverses segments while distance drops;
                    removes all crossing edges, O(n^2) per pass
  * 2-opt + Or-opt - adds Or-opt moves (relocate a chain of 1-3 stops to another
                    position) and alternates both until neither improves, started
                    from two construction tours (nearest neighbour and cheapest
                    insertion); this is what the live Route Planner Agent uses
  * Held-Karp     - exact dynamic programming over subsets, O(n^2 * 2^n);
                    used as the optimality reference for n <= 11 stops

Road geometry for display comes from the public OSRM router (real Bengaluru
roads) when internet is available; distances otherwise use the calibrated
road model (great-circle x 1.35 circuity).
"""
import json
import logging
import time
import urllib.request
from functools import lru_cache

from . import config
from .core import road_km, traffic_speed_kmh

log = logging.getLogger("wastex.routing")
EXACT_MAX = 11


@lru_cache(maxsize=200_000)
def _leg(a_lat, a_lon, b_lat, b_lon):
    return road_km({"lat": a_lat, "lon": a_lon}, {"lat": b_lat, "lon": b_lon})


def leg_km(a, b):
    """Cached road distance between two points (local search re-evaluates the same legs many times)."""
    return _leg(a["lat"], a["lon"], b["lat"], b["lon"])


def path_km(points):
    return sum(leg_km(points[i], points[i + 1]) for i in range(len(points) - 1))


def tour_km(start, stops, end=None):
    return path_km([start] + list(stops) + ([end] if end else []))


def nearest_neighbour(start, stops):
    remaining, tour, cur = list(stops), [], start
    while remaining:
        nxt = min(remaining, key=lambda s: road_km(cur, s))
        remaining.remove(nxt)
        tour.append(nxt)
        cur = nxt
    return tour


def two_opt(start, stops, end=None):
    tour = list(stops)
    best = tour_km(start, tour, end)
    improved = True
    while improved:
        improved = False
        for i in range(len(tour) - 1):
            for j in range(i + 1, len(tour)):
                cand = tour[:i] + tour[i:j + 1][::-1] + tour[j + 1:]
                d = tour_km(start, cand, end)
                if d + 1e-9 < best:
                    tour, best, improved = cand, d, True
    return tour


def or_opt(start, stops, end=None):
    """Relocate chains of 1-3 consecutive stops to a better position (Or, 1976)."""
    tour = list(stops)
    best = tour_km(start, tour, end)
    improved = True
    while improved:
        improved = False
        for seg in (1, 2, 3):
            for i in range(len(tour) - seg + 1):
                chain, rest = tour[i:i + seg], tour[:i] + tour[i + seg:]
                for j in range(len(rest) + 1):
                    if j == i:
                        continue
                    for piece in (chain, chain[::-1]):
                        cand = rest[:j] + piece + rest[j:]
                        d = tour_km(start, cand, end)
                        if d + 1e-9 < best:
                            tour, best, improved = cand, d, True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
    return tour


def local_search(start, stops, end=None):
    """Alternate 2-opt and Or-opt until no move shortens the route."""
    tour = list(stops)
    best = tour_km(start, tour, end)
    while True:
        tour = or_opt(start, two_opt(start, tour, end), end)
        d = tour_km(start, tour, end)
        if d + 1e-9 >= best:
            return tour
        best = d


def cheapest_insertion(start, stops, end=None):
    """Grow the route by inserting, each time, the stop that adds the least distance."""
    tour, remaining = [], list(stops)
    while remaining:
        best = None
        for s in remaining:
            for k in range(len(tour) + 1):
                d = tour_km(start, tour[:k] + [s] + tour[k:], end)
                if best is None or d < best[0]:
                    best = (d, s, k)
        _, s, k = best
        tour.insert(k, s)
        remaining.remove(s)
    return tour


def optimise(start, stops, end=None):
    """Production heuristic: two construction tours (nearest neighbour, cheapest insertion),
    each improved by 2-opt/Or-opt local search; the shorter one wins (multi-start)."""
    if len(stops) <= 1:
        return list(stops)
    cands = [local_search(start, nearest_neighbour(start, stops), end),
             local_search(start, cheapest_insertion(start, stops, end), end)]
    return min(cands, key=lambda t: tour_km(start, t, end))


def held_karp(start, stops, end=None):
    """Exact shortest path start -> all stops -> end (end optional)."""
    n = len(stops)
    if n == 0:
        return []
    d0 = [road_km(start, s) for s in stops]
    d = [[road_km(a, b) for b in stops] for a in stops]
    de = [road_km(s, end) if end else 0.0 for s in stops]
    dp = {}
    for k in range(n):
        dp[(1 << k, k)] = (d0[k], -1)
    for mask in range(1, 1 << n):
        for last in range(n):
            if not mask & (1 << last) or (mask, last) not in dp:
                continue
            cost = dp[(mask, last)][0]
            for nxt in range(n):
                if mask & (1 << nxt):
                    continue
                key = (mask | (1 << nxt), nxt)
                c = cost + d[last][nxt]
                if key not in dp or c < dp[key][0]:
                    dp[key] = (c, last)
    full = (1 << n) - 1
    last = min(range(n), key=lambda k: dp[(full, k)][0] + de[k])
    order, mask = [], full
    while last != -1:
        order.append(stops[last])
        prev = dp[(mask, last)][1]
        mask ^= 1 << last
        last = prev
    return order[::-1]


def compare(start, stops, end=None, hour=10.0):
    """Run every algorithm and report distance, time, runtime and gap to the best."""
    speed = traffic_speed_kmh(hour)
    results = []

    def add(key, name, fn):
        t0 = time.perf_counter()
        order = fn()
        ms = (time.perf_counter() - t0) * 1000
        km = tour_km(start, order, end)
        results.append({"key": key, "name": name, "order": order, "km": round(km, 2),
                        "minutes": round(km / speed * 60 + config.SERVICE_MIN_PER_BIN * len(order), 1),
                        "runtime_ms": round(ms, 2)})

    add("naive", "As selected (no optimisation)", lambda: list(stops))
    add("nn", "Nearest neighbour", lambda: nearest_neighbour(start, stops))
    add("nn2opt", "Nearest neighbour + 2-opt", lambda: two_opt(start, nearest_neighbour(start, stops), end))
    add("ls", "Multi-start 2-opt + Or-opt (used live)", lambda: optimise(start, stops, end))
    if len(stops) <= EXACT_MAX:
        add("exact", "Held-Karp exact optimum", lambda: held_karp(start, stops, end))
    best = min(r["km"] for r in results)
    naive = results[0]["km"]
    for r in results:
        r["gap_pct"] = round(100 * (r["km"] - best) / best, 2) if best else 0.0
        r["saving_pct"] = round(100 * (naive - r["km"]) / naive, 1) if naive else 0.0
    return results


# ------------------------------------------------------------------ OSRM road geometry
@lru_cache(maxsize=512)
def _osrm(coord_key):
    url = f"https://router.project-osrm.org/route/v1/driving/{coord_key}?overview=full&geometries=geojson"
    req = urllib.request.Request(url, headers={"User-Agent": "WASTEX-student-project"})
    with urllib.request.urlopen(req, timeout=6) as r:
        data = json.loads(r.read().decode())
    if data.get("code") != "Ok":
        raise RuntimeError(data.get("code"))
    route = data["routes"][0]
    legs = [{"km": round(l["distance"] / 1000, 2), "min": round(l["duration"] / 60, 1)} for l in route["legs"]]
    return {"geometry": [[c[1], c[0]] for c in route["geometry"]["coordinates"]],
            "km": round(route["distance"] / 1000, 2), "minutes": round(route["duration"] / 60, 1), "legs": legs}


def road_geometry(points):
    """Real road polyline through the points, or None when OSRM is unreachable."""
    if len(points) < 2:
        return None
    key = ";".join(f"{p['lon']:.5f},{p['lat']:.5f}" for p in points)
    try:
        return _osrm(key)
    except Exception as e:  # offline or rate-limited -> straight segments on the client
        log.info("OSRM unavailable (%s) - using modelled road distances", e.__class__.__name__)
        return None
