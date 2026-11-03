"""
Agent 2 - Route Planner  ("HOW should we collect?")

Inputs  : priority bins, depot locations, road network model, vehicle
          constraints, processing-plant capacity (EDA slide 8).
Steps   :
  1. Capacity-constrained clustering - seed with the most urgent bin and grow
     the cluster with the nearest bins while load <= capacity limit.
  2. Opportunistic pickup - MEDIUM bins (and LOW bins already >= 55 % full)
     within 3 km of a cluster are added if capacity allows (saves a future trip).
  3. Batching - a route is dispatched only if it has >= 4 stops or contains an
     imminent bin (ETA <= 30 min, >= 95 % full or fire); otherwise it waits so
     trucks are not sent across the city for a single bin.
  4. Sequencing - nearest-neighbour tour improved by 2-opt + Or-opt local search.
  5. Disposal - a truck unloads only once it is >= 75 % full (otherwise it
     parks on standby at its last stop, ready for the next dispatch). The plant is the nearest one
     weighted by utilisation; closed plants (Mavallipura) and plants above
     90 % utilisation are skipped.
  6. Road-aware cost - distance = great-circle x circuity, time-of-day traffic
     speed, service time per bin and unloading time.
"""
from .. import config, routing
from ..core import haversine_km, road_km, traffic_speed_kmh
from ..data.bengaluru import DEPOTS, PROCESSING_PLANTS

MAX_STOPS = 15
CLUSTER_RADIUS_KM = 4.5
PIGGYBACK_KM = 3.0
MIN_BATCH = 4          # stops needed before a non-urgent route is dispatched
IMMINENT_ETA = 30.0
LOAD_SAFETY = 1.10  # bins keep filling while the truck drives


def est_load(b):
    return b["weight_kg"] * LOAD_SAFETY


class RoutePlannerAgent:
    name = "Route Planner Agent"

    def __init__(self, plant_intake=None):
        # live plant intake (t/day) so the agent avoids saturated plants
        self.plant_intake = plant_intake if plant_intake is not None else {}

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def tour_km(start, stops, end=None):
        pts = [start] + stops + ([end] if end else [])
        return sum(road_km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    def optimise_order(self, start, stops, end=None):
        """Nearest neighbour construction + 2-opt / Or-opt local search (see backend/routing.py)."""
        return routing.optimise(start, stops, end)

    def choose_plant(self, last):
        best, best_cost = None, 1e18
        for p in PROCESSING_PLANTS:
            if p["mixed_tpd"] <= 0:
                continue
            intake = p["intake_tpd"] + self.plant_intake.get(p["id"], 0) / 1000
            util = intake / p["mixed_tpd"]
            if util > 0.9:
                continue
            cost = road_km(last, p) * (1 + 0.6 * util)
            if cost < best_cost:
                best, best_cost = p, cost
        return best

    @staticmethod
    def nearest_depot(pt):
        return min(DEPOTS, key=lambda d: haversine_km(pt["lat"], pt["lon"], d["lat"], d["lon"]))

    def cost(self, start, stops, hour, dispose=True):
        """Route ends at a processing plant (dispose) or the truck parks on standby at its last stop."""
        if dispose:
            end = self.choose_plant(stops[-1])
        else:
            last = stops[-1]
            end = {"id": "STANDBY", "name": f"standby near {last.get('zone', 'last stop')}", "lat": last["lat"], "lon": last["lon"]}
        km = self.tour_km(start, stops, end if dispose else None)
        speed = traffic_speed_kmh(hour)
        minutes = km / speed * 60 + config.SERVICE_MIN_PER_BIN * len(stops) + (config.UNLOAD_MIN if dispose else 0)
        return end, round(km, 2), round(minutes, 1)

    @staticmethod
    def dispatch_ready(route):
        if len(route["stops"]) >= MIN_BATCH:
            return True
        for s in route["stops"]:
            eta = s.get("eta_min")
            if s["fill_level"] >= config.CRITICAL_FILL or (eta is not None and eta <= IMMINENT_ETA) or "fire" in s.get("reason", ""):
                return True
        return False

    @staticmethod
    def should_dispose(truck_load, route_load, capacity):
        """Trucks keep collecting until they are >= 75 % full, then unload."""
        return truck_load + route_load >= config.DISPOSE_AT * capacity

    # ---------------------------------------------------------------- planning
    def cluster(self, high, medium, cap_limit):
        unassigned = list(high)
        med_pool = list(medium)
        clusters = []
        while unassigned:
            seed = unassigned.pop(0)  # highest score first
            members, load = [seed], est_load(seed)
            while len(members) < MAX_STOPS:
                cands = [b for b in unassigned
                         if load + est_load(b) <= cap_limit
                         and min(haversine_km(m["lat"], m["lon"], b["lat"], b["lon"]) for m in members) <= CLUSTER_RADIUS_KM]
                if not cands:
                    break
                nxt = min(cands, key=lambda b: min(haversine_km(m["lat"], m["lon"], b["lat"], b["lon"]) for m in members))
                unassigned.remove(nxt)
                members.append(nxt)
                load += est_load(nxt)
            piggy = []
            for b in sorted(med_pool, key=lambda x: -x["score"]):
                if len(members) + len(piggy) >= MAX_STOPS:
                    break
                near = min(haversine_km(m["lat"], m["lon"], b["lat"], b["lon"]) for m in members)
                if near <= PIGGYBACK_KM and load + est_load(b) <= cap_limit:
                    piggy.append(b)
                    load += est_load(b)
            for b in piggy:
                med_pool.remove(b)
            clusters.append({"bins": members, "piggyback": [b["bin_id"] for b in piggy], "extra": piggy,
                             "load_kg": round(load, 1)})
        return clusters

    def plan(self, high, medium, cap_limit, hour):
        routes = []
        for c in self.cluster(high, medium, cap_limit):
            stops = c["bins"] + c["extra"]
            centroid = {"lat": sum(s["lat"] for s in stops) / len(stops), "lon": sum(s["lon"] for s in stops) / len(stops)}
            depot = self.nearest_depot(centroid)
            ordered = self.optimise_order(depot, stops)
            plant, km, minutes = self.cost(depot, ordered, hour)
            routes.append({
                "stops": ordered, "piggyback": c["piggyback"], "load_kg": c["load_kg"],
                "centroid": centroid, "depot": depot, "plant": plant,
                "distance_km": km, "duration_min": minutes,
                "zones": sorted({s["zone"] for s in ordered}),
            })
        return routes

    def split(self, route, hour):
        """Re-plan: divide an infeasible route into two geographically compact halves."""
        stops = route["stops"]
        if len(stops) < 2:
            return None
        axis = "lat" if (max(s["lat"] for s in stops) - min(s["lat"] for s in stops)) >= \
                        (max(s["lon"] for s in stops) - min(s["lon"] for s in stops)) else "lon"
        ordered = sorted(stops, key=lambda s: s[axis])
        total = sum(est_load(s) for s in ordered)
        acc, cut = 0.0, 1
        for i, s in enumerate(ordered):
            acc += est_load(s)
            if acc >= total / 2:
                cut = max(1, min(i + 1, len(ordered) - 1))
                break
        halves = []
        for part in (ordered[:cut], ordered[cut:]):
            centroid = {"lat": sum(s["lat"] for s in part) / len(part), "lon": sum(s["lon"] for s in part) / len(part)}
            depot = self.nearest_depot(centroid)
            seq = self.optimise_order(depot, part)
            plant, km, minutes = self.cost(depot, seq, hour)
            halves.append({"stops": seq, "piggyback": [b for b in route["piggyback"] if b in {s["bin_id"] for s in seq}],
                           "load_kg": round(sum(est_load(s) for s in seq), 1), "centroid": centroid, "depot": depot,
                           "plant": plant, "distance_km": km, "duration_min": minutes,
                           "zones": sorted({s["zone"] for s in seq})})
        return halves
