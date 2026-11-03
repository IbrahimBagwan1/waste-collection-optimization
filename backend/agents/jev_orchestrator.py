"""
JEV Orchestrator - Multi-Agent Decision Layer (slides 12 & 13)

Consumes  : bin-analytics (materialised as a bin table), bin-alerts (triggers),
            fleet-status (materialised as a fleet table)
Produces  : agent-decisions (full reasoning trace), collection-plans

Adaptive workflow - not a fixed sequence:

  Streaming event ─> JEV ─> Waste Agent: "What needs attention?"
                             │ priority bins? ── NO ──> No Action Needed
                             ▼ YES
                           Route Agent: "How should we collect?"
                             ▼
                           Fleet Agent: "Which truck?"
                             │ feasible? ── NO ──> JEV re-plans (split route) / retry
                             ▼ YES
                           Collection Plan

Triggers: (a) a planning cycle every PLANNING_INTERVAL_MIN simulated minutes,
          (b) immediately on a critical alert (overflow, critical fill, fire,
              predicted overflow, truck breakdown).
"""
import itertools
import logging
import threading
import time
from collections import deque

from .. import config, routing
from .fleet_agent import FleetManagerAgent
from .route_agent import RoutePlannerAgent
from .waste_agent import WasteIntelligenceAgent

log = logging.getLogger("wastex.jev")

TRIGGER_ALERTS = {"OVERFLOW", "CRITICAL_FILL", "FIRE", "PREDICTED_OVERFLOW", "TRUCK_BREAKDOWN"}


class JEVOrchestrator:
    def __init__(self, bus, clock):
        self.bus = bus
        self.clock = clock
        self.waste = WasteIntelligenceAgent()
        self.route = RoutePlannerAgent()
        self.fleet = FleetManagerAgent()
        self.bins = {}
        self.trucks = {}
        self.scheduled = {}           # bin_id -> (truck_id, sim_min)
        self.pending_triggers = deque()
        self.last_cycle_min = -1e9
        self.last_event_cycle_min = -1e9
        self.ids = itertools.count(1)
        self.plan_ids = itertools.count(1)
        self.ready = threading.Event()
        self._stop = threading.Event()
        self.stats = {"cycles": 0, "no_action": 0, "plans": 0, "replans": 0, "deferred": 0,
                      "event_triggered": 0, "scheduled_triggered": 0, "avg_decision_ms": 0.0,
                      "naive_km": 0.0, "optimised_km": 0.0, "manual_dispatches": 0}
        self.last_assessment = []

    def start(self):
        threading.Thread(target=self._run, name="jev-orchestrator", daemon=True).start()

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------ loop
    def _run(self):
        c = self.bus.consumer(config.GROUPS["jev"], ["bin-analytics", "bin-alerts", "fleet-status"], "jev-orchestrator")
        self.producer = self.bus.producer()
        c.wait_ready()
        self.ready.set()
        while not self._stop.is_set():
            for rec in c.poll(timeout_ms=300, max_records=2000):
                v = rec.value
                if rec.topic == "bin-analytics":
                    self.bins[v["bin_id"]] = v
                elif rec.topic == "fleet-status":
                    self.trucks[v["truck_id"]] = v
                elif rec.topic == "bin-alerts" and v.get("type") in TRIGGER_ALERTS:
                    self.pending_triggers.append(v)
                    # the alert may overtake its bin-analytics record (different topic):
                    # fold its facts into the bin table so the decision sees them
                    b = self.bins.get(v.get("bin_id"))
                    if b is not None and v.get("fill_level") is not None:
                        b["fill_level"] = max(b["fill_level"], v["fill_level"])
                        if v.get("eta_min") is not None:
                            b["eta_min"] = v["eta_min"]
                        if v["type"] == "FIRE" and "FIRE" not in b.get("anomalies", []):
                            b["anomalies"] = list(b.get("anomalies", [])) + ["FIRE"]
            self._sync_scheduled()
            now = self.clock.minutes
            if not self.bins or not self.trucks:
                continue
            try:
                if self.pending_triggers and now - self.last_event_cycle_min >= 1:
                    trig = list(self.pending_triggers)
                    self.pending_triggers.clear()
                    if any(t["bin_id"] not in self.scheduled or t.get("type") == "TRUCK_BREAKDOWN" for t in trig):
                        self.last_event_cycle_min = now
                        self.cycle(self._describe(trig), trig)
                    continue
                if now - self.last_cycle_min >= config.PLANNING_INTERVAL_MIN:
                    self.last_cycle_min = now
                    self.cycle({"kind": "scheduled", "label": f"Planning cycle (every {config.PLANNING_INTERVAL_MIN} min)"}, [])
            except Exception:
                log.exception("JEV cycle failed")
        c.close()

    @staticmethod
    def _describe(trig):
        first = trig[0]
        label = f"{first['type'].replace('_', ' ').title()} · {first.get('bin_id', '')} ({first.get('zone', '')})"
        if len(trig) > 1:
            label += f" +{len(trig) - 1} more"
        return {"kind": "event", "label": label, "alert": first}

    def _sync_scheduled(self):
        """A bin stays 'scheduled' only while some truck still has it on its route."""
        on_route = {}
        for t in self.trucks.values():
            for b in t.get("remaining_stops", []):
                on_route[b] = t["truck_id"]
        now = self.clock.minutes
        for bid, (tid, at) in list(self.scheduled.items()):
            if bid not in on_route and now - at > 3:  # grace period for the plan to reach the truck
                del self.scheduled[bid]

    # ------------------------------------------------------------------ one decision
    def cycle(self, trigger, alerts):
        t0 = time.perf_counter()
        did = f"JEV-{next(self.ids):05d}"
        steps = []
        self.stats["cycles"] += 1
        self.stats["event_triggered" if trigger["kind"] == "event" else "scheduled_triggered"] += 1
        hour = self.clock.hour()

        steps.append({"agent": "JEV", "node": "event", "title": "Streaming event received",
                      "text": trigger["label"]})

        # ---- 1. Waste Intelligence -------------------------------------------------
        assessed, summary = self.waste.assess(self.bins, exclude=set(self.scheduled))
        self.last_assessment = assessed[:40]
        high = [a for a in assessed if a["priority"] == "HIGH"]
        medium = self.waste.opportunistic(assessed)
        steps.append({"agent": "Waste Agent", "node": "waste", "title": "What needs attention?",
                      "text": f"Scored {len(assessed)} unscheduled bins → {summary['HIGH']} HIGH · "
                              f"{summary['MEDIUM']} MEDIUM · {summary['LOW']} LOW",
                      "data": {"summary": summary, "top": assessed[:8]}})

        if not high:
            steps.append({"agent": "JEV", "node": "noaction", "title": "Priority bins?  NO",
                          "text": f"No bin needs collection now ({len(self.scheduled)} already scheduled). Monitoring continues."})
            self.stats["no_action"] += 1
            return self._publish(did, trigger, steps, "NO_ACTION", [], t0)

        steps.append({"agent": "JEV", "node": "priority", "title": "Priority bins?  YES",
                      "text": f"{len(high)} HIGH-priority bins: " + ", ".join(f"{h['bin_id']} ({h['reason']})" for h in high[:4])
                              + (" …" if len(high) > 4 else "")})

        # ---- 2. Route Planner -------------------------------------------------------
        usable = [t for t in self.trucks.values() if t["status"] in ("idle", "returning", "en_route", "collecting")]
        if not usable:
            steps.append({"agent": "Fleet Agent", "node": "fleet", "title": "Which truck?",
                          "text": "Entire fleet is busy or unavailable - bins deferred to next cycle."})
            self.stats["deferred"] += len(high)
            return self._publish(did, trigger, steps, "DEFERRED", [], t0)
        cap_limit = max(t["capacity_kg"] - t.get("load_kg", 0) - t.get("planned_kg", 0) for t in usable)
        cap_limit = max(cap_limit, max(h["weight_kg"] * 1.1 for h in high))
        routes = self.route.plan(high, medium, cap_limit, hour)
        steps.append({"agent": "Route Agent", "node": "route", "title": "How should we collect?",
                      "text": f"{len(routes)} route(s) via capacity-constrained clustering + nearest-neighbour + 2-opt "
                              f"(limit {cap_limit:.0f} kg, traffic speed {self._speed(hour)} km/h)",
                      "data": {"routes": [self._route_brief(r) for r in routes]}})

        # ---- 3. Fleet Manager + feasibility / re-plan loop -----------------------------
        queue = deque((r, 1) for r in routes)
        plans = []
        trucks = {k: dict(v) for k, v in self.trucks.items()}  # local what-if copy
        while queue:
            r, attempt = queue.popleft()
            res = self.fleet.assign(r, trucks)
            brief = self._route_brief(r)
            if res["feasible"]:
                tid = res["truck_id"]
                t = trucks[tid]
                start = {"lat": t["lat"], "lon": t["lon"]}
                seq = self.route.optimise_order(start, r["stops"])
                dispose = self.route.should_dispose(t.get("load_kg", 0) + t.get("planned_kg", 0), r["load_kg"], t["capacity_kg"])
                end, km, minutes = self.route.cost(start, seq, hour, dispose)
                plan = self._make_plan(t, res["mode"], seq, end, dispose, km, minutes, r, did)
                # what a non-optimising dispatcher would drive: most urgent bin first
                by_urgency = sorted(seq, key=lambda s: -s.get("score", 0))
                plan["naive_km"] = round(routing.tour_km(start, by_urgency, end if dispose else None), 2)
                plan["nn_km"] = round(routing.tour_km(start, routing.nearest_neighbour(start, seq), end if dispose else None), 2)
                self.stats["naive_km"] = round(self.stats["naive_km"] + plan["naive_km"], 2)
                self.stats["optimised_km"] = round(self.stats["optimised_km"] + km, 2)
                plans.append(plan)
                t["planned_kg"] = t.get("planned_kg", 0) + r["load_kg"]
                t["status"] = "en_route" if t["status"] in ("idle", "returning") else t["status"]
                t.setdefault("remaining_stops", [])
                t["remaining_stops"] = list(t["remaining_stops"]) + [s["bin_id"] for s in seq]
                txt = f"{tid} ({t['type']}, {res['candidates'][0]['remaining_pct']}% free) → {len(seq)} stops, " \
                      f"{r['load_kg']:.0f} kg, {km} km, ~{minutes:.0f} min [{res['mode']}] → "                       + (f"unload at {end['name']}" if dispose else f"back to {end['name']} (keeps collecting)")
                if res.get("constraint"):
                    steps.append({"agent": "JEV", "node": "constraint", "title": "Constraint detected",
                                  "text": res["constraint"] + f" → {tid} assigned instead"})
                steps.append({"agent": "Fleet Agent", "node": "fleet", "title": "Which truck?  Feasible ✓",
                              "text": txt, "data": {"route": brief, "candidates": res["candidates"][:6]}})
            else:
                steps.append({"agent": "Fleet Agent", "node": "fleet", "title": "Which truck?  Not feasible ✗",
                              "text": f"Route {brief['label']} needs {r['load_kg']:.0f} kg - "
                                      + ("no truck has enough spare capacity" if res["reason"] == "capacity" else "no truck available"),
                              "data": {"route": brief, "candidates": res["candidates"][:6]}})
                halves = self.route.split(r, hour) if res["reason"] == "capacity" else None
                if halves and attempt < config.MAX_REPLAN_ATTEMPTS:
                    self.stats["replans"] += 1
                    steps.append({"agent": "JEV", "node": "replan", "title": f"Re-plan / Retry (attempt {attempt + 1})",
                                  "text": f"Splitting route into {len(halves)} smaller routes: "
                                          + " | ".join(f"{len(h['stops'])} stops/{h['load_kg']:.0f} kg" for h in halves)})
                    for h in halves:
                        queue.append((h, attempt + 1))
                else:
                    self.stats["deferred"] += len(r["stops"])
                    steps.append({"agent": "JEV", "node": "replan", "title": "Deferred",
                                  "text": f"{len(r['stops'])} bins deferred to the next cycle (fleet saturated)"})

        for p in plans:
            self.producer.send("collection-plans", p["truck_id"], p)
            for s in p["stops"]:
                self.scheduled[s["bin_id"]] = (p["truck_id"], self.clock.minutes)
        self.stats["plans"] += len(plans)
        if plans:
            steps.append({"agent": "JEV", "node": "plan", "title": "Collection plan issued",
                          "text": f"{len(plans)} plan(s): " + "; ".join(
                              f"{p['truck_id']} → {' → '.join(s['bin_id'] for s in p['stops'][:5])}"
                              f"{' …' if len(p['stops']) > 5 else ''} → {p['end']['name'].split(' ')[0]}" for p in plans)})
            naive = sum(p["naive_km"] for p in plans)
            opt = sum(p["distance_km"] for p in plans)
            if naive > opt + 0.01:
                steps.append({"agent": "Route Agent", "node": "plan", "title": "Route optimisation gain",
                              "text": f"NN + 2-opt sequencing: {opt:.1f} km instead of {naive:.1f} km when visiting "
                                      f"bins in urgency order (−{100 * (naive - opt) / naive:.0f}%)"})
        return self._publish(did, trigger, steps, "PLAN" if plans else "DEFERRED", plans, t0)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _speed(hour):
        from ..core import traffic_speed_kmh
        return traffic_speed_kmh(hour)

    @staticmethod
    def _route_brief(r):
        return {"label": "/".join(r["zones"][:2]) + (f" +{len(r['zones']) - 2}" if len(r["zones"]) > 2 else ""),
                "stops": [s["bin_id"] for s in r["stops"]], "load_kg": r["load_kg"],
                "distance_km": r["distance_km"], "duration_min": r["duration_min"],
                "plant": r["plant"]["name"] if r.get("plant") else None, "piggyback": r.get("piggyback", [])}

    def dispatch_manual(self, truck_id, stops, end, dispose, km, minutes, naive_km, algorithm):
        """Operator dispatch from the Route Optimizer page: publish the chosen route to Kafka."""
        t = self.trucks.get(truck_id)
        if t is None:
            raise ValueError(f"unknown truck {truck_id}")
        if t["status"] in ("breakdown", "to_plant", "unloading"):
            raise ValueError(f"{truck_id} is {t['status'].replace('_', ' ')} - choose another truck")
        taken = [f"{s['bin_id']} ({self.scheduled[s['bin_id']][0]})" for s in stops if s["bin_id"] in self.scheduled]
        if taken:
            raise ValueError("already scheduled: " + ", ".join(taken[:4]) + (" …" if len(taken) > 4 else ""))
        load = round(sum(s["weight_kg"] * 1.1 for s in stops), 1)
        free = t["capacity_kg"] - t.get("load_kg", 0) - t.get("planned_kg", 0)
        if load > free:
            raise ValueError(f"{truck_id} can take only {free:.0f} kg but the route needs {load:.0f} kg")
        did = f"JEV-{next(self.ids):05d}"
        mode = "append" if t["status"] in ("en_route", "collecting") else "new"
        seq = [dict(s, priority=s.get("priority", "MANUAL")) for s in stops]
        plan = self._make_plan(t, mode, seq, end, dispose, km, minutes, {"piggyback": [], "load_kg": load}, did)
        plan["naive_km"] = naive_km
        plan["algorithm"] = algorithm
        plan["manual"] = True
        self.producer.send("collection-plans", truck_id, plan)
        for s in stops:
            self.scheduled[s["bin_id"]] = (truck_id, self.clock.minutes)
        self.stats["manual_dispatches"] += 1
        self.stats["plans"] += 1
        steps = [
            {"agent": "JEV", "node": "event", "title": "Operator request",
             "text": f"Route Optimizer: {len(stops)} selected bins → {truck_id}"},
            {"agent": "Route Agent", "node": "route", "title": "How should we collect?",
             "text": f"{algorithm}: {km} km (vs {naive_km} km in selection order), ~{minutes:.0f} min → {end['name']}"},
            {"agent": "Fleet Agent", "node": "fleet", "title": "Which truck?  Feasible ✓",
             "text": f"{truck_id} has {free:.0f} kg free for {load:.0f} kg [{mode}]"},
            {"agent": "JEV", "node": "plan", "title": "Collection plan issued",
             "text": f"{plan['plan_id']}: {truck_id} → " + " → ".join(s["bin_id"] for s in stops) + f" → {end['name']}"},
        ]
        self._publish(did, {"kind": "event", "label": f"Operator dispatch · {truck_id}"}, steps, "PLAN", [plan], time.perf_counter())
        return plan

    def _make_plan(self, t, mode, seq, end, dispose, km, minutes, r, did):
        return {
            "plan_id": f"PLAN-{next(self.plan_ids):05d}", "decision_id": did,
            "truck_id": t["truck_id"], "truck_type": t["type"], "capacity_kg": t["capacity_kg"], "mode": mode,
            "stops": [{"bin_id": s["bin_id"], "lat": s["lat"], "lon": s["lon"], "zone": s["zone"],
                       "priority": s["priority"], "fill_level": s["fill_level"],
                       "est_kg": round(s["weight_kg"] * 1.1, 1)} for s in seq],
            "piggyback": r.get("piggyback", []),
            "dispose": dispose,
            "plant": {k: end[k] for k in ("id", "name", "lat", "lon")} if dispose else None,
            "end": {k: end[k] for k in ("id", "name", "lat", "lon")},
            "distance_km": km, "duration_min": minutes, "load_kg": r["load_kg"],
            "ts": self.clock.iso(), "sim_min": round(self.clock.minutes, 1),
        }

    def _publish(self, did, trigger, steps, outcome, plans, t0):
        ms = (time.perf_counter() - t0) * 1000
        n = max(self.stats["cycles"], 1)
        self.stats["avg_decision_ms"] = round(self.stats["avg_decision_ms"] + (ms - self.stats["avg_decision_ms"]) / n, 2)
        self.producer.send("agent-decisions", "jev", {
            "decision_id": did, "trigger": trigger, "outcome": outcome, "steps": steps,
            "plans": [{"plan_id": p["plan_id"], "truck_id": p["truck_id"], "stops": len(p["stops"]),
                       "load_kg": p["load_kg"], "distance_km": p["distance_km"]} for p in plans],
            "duration_ms": round(ms, 2), "ts": self.clock.iso(), "sim_min": round(self.clock.minutes, 1),
        })
        self.producer.flush()
        return outcome
