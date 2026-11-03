"""
Fleet Simulator  (consumer `collection-plans` -> producer `fleet-status`, `collection-events`)

Each truck is a small state machine driven by the simulated clock:

  idle ──plan──> en_route ──arrive──> collecting ──> en_route ... ──> to_plant
       <──────── returning <──────── unloading <───────────────────────┘
  breakdown (manual scenario) releases all stops so JEV re-plans them.

Movement follows the road model (great-circle x circuity) at the time-of-day
traffic speed. On every bin visit a `collection-events` record is produced;
the IoT layer empties the bin and the stream processor resets its window.
"""
import logging
import threading

from .. import config
from ..core import haversine_km, road_km, traffic_speed_kmh
from ..data.bengaluru import DEPOTS, FLEET, PROCESSING_PLANTS

log = logging.getLogger("wastex.fleet")
DEPOT_BY_ID = {d["id"]: d for d in DEPOTS}


class Truck:
    def __init__(self, spec):
        self.id = spec["id"]
        self.type = spec["type"]
        self.capacity = spec["capacity_kg"]
        self.depot = DEPOT_BY_ID[spec["depot"]]
        self.lat, self.lon = self.depot["lat"], self.depot["lon"]
        self.status = "idle"
        self.load = 0.0
        self.stops = []           # pending stops (dicts from the plan)
        self.plant = None
        self.dispose = False
        self.target = None        # current waypoint {lat, lon}
        self.service_left = 0.0
        self.breakdown_left = 0.0
        self.km = 0.0
        self.trips = 0
        self.collected = 0
        self.kg_delivered = 0.0
        self.plan_id = None
        self.route_line = []      # remaining polyline for the map

    def planned_kg(self):
        return sum(s["est_kg"] for s in self.stops)

    def to_status(self, clock):
        return {
            "truck_id": self.id, "type": self.type, "capacity_kg": self.capacity,
            "load_kg": round(self.load, 1), "planned_kg": round(self.planned_kg(), 1),
            "status": self.status, "lat": round(self.lat, 6), "lon": round(self.lon, 6),
            "depot_id": self.depot["id"], "depot": self.depot["name"],
            "remaining_stops": [s["bin_id"] for s in self.stops],
            "next_stop": self.stops[0]["bin_id"] if self.stops else (self.plant["name"] if self.status == "to_plant" and self.plant else None),
            "plan_id": self.plan_id, "km_today": round(self.km, 2), "trips": self.trips,
            "collected_bins": self.collected, "kg_delivered": round(self.kg_delivered, 1),
            "co2_kg": round(self.km * config.DIESEL_KG_CO2_PER_KM, 2),
            "utilisation_pct": round(100 * (self.load + self.planned_kg()) / self.capacity, 1),
            "route_line": [[round(p["lat"], 5), round(p["lon"], 5)] for p in self._line()],
            "ts": clock.iso(), "sim_min": round(clock.minutes, 1),
        }

    def _line(self):
        pts = [{"lat": self.lat, "lon": self.lon}]
        if self.status in ("en_route", "collecting"):
            pts += self.stops
            pts.append(self.plant if self.dispose and self.plant else self.depot)
        elif self.status == "to_plant" and self.plant:
            pts.append(self.plant)
        elif self.status == "returning":
            pts.append(self.depot)
        return pts


class FleetSimulator:
    def __init__(self, bus, clock):
        self.bus = bus
        self.clock = clock
        self.trucks = {s["id"]: Truck(s) for s in FLEET}
        self.plant_kg = {p["id"]: 0.0 for p in PROCESSING_PLANTS}
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.events = 0

    def start(self):
        threading.Thread(target=self._consume, name="fleet-plans", daemon=True).start()

    def start_moving(self):
        self.producer = self.bus.producer()
        threading.Thread(target=self._run, name="fleet-sim", daemon=True).start()

    def stop(self):
        self._stop.set()

    # ---------------------------------------------------------------- controls
    def breakdown(self, truck_id=None):
        with self._lock:
            cands = [t for t in self.trucks.values() if t.status != "breakdown"]
            busy = [t for t in cands if t.stops]
            t = self.trucks.get(truck_id) if truck_id else (busy[0] if busy else (cands[0] if cands else None))
            if not t:
                return None
            released = [s["bin_id"] for s in t.stops]
            t.stops = []
            t.status = "breakdown"
            t.breakdown_left = 60
            t.target = None
            self._producer_alert(t, released)
            return t.id

    def nearest_truck(self, pt):
        with self._lock:
            cands = [t for t in self.trucks.values() if t.status in ("idle", "returning", "en_route", "collecting")]
            return min(cands, key=lambda t: haversine_km(t.lat, t.lon, pt["lat"], pt["lon"]), default=None)

    def preload_spare(self, truck_id, frac_free):
        """Load a truck so only `frac_free` of its capacity is still uncommitted; returns spare kg."""
        with self._lock:
            t = self.trucks[truck_id]
            t.load = max(t.load, t.capacity * (1 - frac_free) - t.planned_kg())
            return t.capacity - t.load - t.planned_kg()

    def _producer_alert(self, t, released):
        p = getattr(self, "producer", None)
        if p is None:
            return
        p.send("bin-alerts", t.id, {
            "alert_id": f"{t.id}-BREAKDOWN-{int(self.clock.minutes)}", "type": "TRUCK_BREAKDOWN", "severity": "critical",
            "message": f"{t.id} broke down - {len(released)} stops released for re-planning",
            "bin_id": t.id, "zone": t.depot["name"], "zone_id": "-", "lat": t.lat, "lon": t.lon,
            "fill_level": None, "ts": self.clock.iso(), "sim_min": self.clock.minutes, "released": released,
        })

    # ---------------------------------------------------------------- plans in
    def _consume(self):
        c = self.bus.consumer(config.GROUPS["fleet"], ["collection-plans"], "fleet-simulator")
        c.wait_ready()
        self.ready.set()
        while not self._stop.is_set():
            for rec in c.poll(timeout_ms=500):
                with self._lock:
                    self._accept(rec.value)
        c.close()

    def _accept(self, plan):
        t = self.trucks.get(plan["truck_id"])
        if not t or t.status == "breakdown":
            return
        known = {s["bin_id"] for s in t.stops}
        new_stops = [s for s in plan["stops"] if s["bin_id"] not in known]
        if plan["mode"] == "append" and t.status in ("en_route", "collecting"):
            t.stops.extend(new_stops)
        else:
            t.stops = t.stops + new_stops
            if t.status in ("idle", "returning"):
                t.status = "en_route"
                t.trips += 1
        if plan.get("dispose") and plan.get("plant"):
            t.plant = plan["plant"]
            t.dispose = True
        t.plan_id = plan["plan_id"]

    # ---------------------------------------------------------------- movement
    def _run(self):
        last = self.clock.minutes
        while not self._stop.is_set():
            now = self.clock.minutes
            dt = now - last
            last = now
            if dt > 0:
                with self._lock:
                    for t in self.trucks.values():
                        self._step(t, dt)
                    for t in self.trucks.values():
                        self.producer.send("fleet-status", t.id, t.to_status(self.clock))
                self.producer.flush()
            self.clock.sleep_tick()

    def _move_towards(self, t, target, minutes):
        """Advance along the straight segment; returns leftover minutes if arrived."""
        speed = traffic_speed_kmh(self.clock.hour())
        can_km = speed / 60 * minutes
        dist = road_km(t.__dict__, target)
        if dist <= can_km or dist < 0.01:
            t.km += dist
            t.lat, t.lon = target["lat"], target["lon"]
            return minutes - (dist / (speed / 60) if speed else 0)
        frac = can_km / dist
        t.lat += (target["lat"] - t.lat) * frac
        t.lon += (target["lon"] - t.lon) * frac
        t.km += can_km
        return None

    def _step(self, t, dt):
        budget = dt
        guard = 0
        while budget > 1e-6 and guard < 20:
            guard += 1
            if t.status == "breakdown":
                t.breakdown_left -= budget
                if t.breakdown_left <= 0:
                    t.status = "to_plant" if t.load > 0 else "returning"
                return
            if t.status == "idle":
                return
            if t.status == "collecting":
                use = min(budget, t.service_left)
                t.service_left -= use
                budget -= use
                if t.service_left <= 1e-6:
                    t.status = "en_route"
                continue
            if t.status == "unloading":
                use = min(budget, t.service_left)
                t.service_left -= use
                budget -= use
                if t.service_left <= 1e-6:
                    if t.plant:
                        self.plant_kg[t.plant["id"]] = self.plant_kg.get(t.plant["id"], 0) + t.load
                    t.kg_delivered += t.load
                    t.load = 0.0
                    t.dispose = False
                    t.plant = None
                    t.status = "returning"
                continue
            if t.status == "en_route":
                if not t.stops:
                    t.status = "to_plant" if (t.dispose or t.load >= config.DISPOSE_AT * t.capacity) else "returning"
                    continue
                stop = t.stops[0]
                left = self._move_towards(t, stop, budget)
                if left is None:
                    return
                budget = left
                t.stops.pop(0)
                t.load = min(t.capacity, t.load + stop["est_kg"])
                t.collected += 1
                self.events += 1
                t.status = "collecting"
                t.service_left = config.SERVICE_MIN_PER_BIN
                self.producer.send("collection-events", stop["bin_id"], {
                    "bin_id": stop["bin_id"], "truck_id": t.id, "plan_id": t.plan_id, "kg": stop["est_kg"],
                    "zone": stop["zone"], "priority": stop.get("priority"), "fill_at_collection": stop.get("fill_level"),
                    "lat": stop["lat"], "lon": stop["lon"], "ts": self.clock.iso(), "sim_min": round(self.clock.minutes, 1),
                })
                continue
            if t.status == "to_plant":
                if not t.plant:
                    t.plant = min((p for p in PROCESSING_PLANTS if p["mixed_tpd"] > 0),
                                  key=lambda p: haversine_km(t.lat, t.lon, p["lat"], p["lon"]))
                left = self._move_towards(t, t.plant, budget)
                if left is None:
                    return
                budget = left
                t.status = "unloading"
                t.service_left = config.UNLOAD_MIN
                continue
            if t.status == "returning":
                if t.stops:
                    t.status = "en_route"
                    continue
                left = self._move_towards(t, t.depot, budget)
                if left is None:
                    return
                budget = left
                t.status = "idle"
                t.plan_id = None
                return

    def metrics(self):
        with self._lock:
            km = sum(t.km for t in self.trucks.values())
            return {
                "km": round(km, 2), "co2_kg": round(km * config.DIESEL_KG_CO2_PER_KM, 2),
                "collections": sum(t.collected for t in self.trucks.values()),
                "kg_delivered": round(sum(t.kg_delivered for t in self.trucks.values()), 1),
                "plant_kg": {k: round(v, 1) for k, v in self.plant_kg.items()},
                "active": sum(1 for t in self.trucks.values() if t.status not in ("idle", "breakdown")),
            }
