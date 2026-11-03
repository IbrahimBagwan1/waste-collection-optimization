"""
Agent 3 - Fleet Manager  ("WHO collects it?")

Inputs  : route requirements (load, first stop), vehicle constraints,
          capacity, current load, location and availability of every truck.
Logic   : every truck is evaluated:
            unavailable  - breakdown / unloading / heading to plant
            insufficient - remaining capacity < route load
            feasible     - scored on dead-head distance + best-fit capacity
          Busy trucks still on their outbound leg may take extra stops
          ("append") if they have spare capacity - dynamic insertion.
Output  : best-fit truck, or an infeasibility reason the JEV orchestrator
          uses to trigger re-planning.
"""
from ..core import road_km

AVAILABLE = {"idle", "returning"}
APPENDABLE = {"en_route", "collecting"}


class FleetManagerAgent:
    name = "Fleet Manager Agent"

    def evaluate(self, route, trucks: dict):
        first = route["stops"][0]
        rows = []
        for t in trucks.values():
            cap = t["capacity_kg"]
            committed = t.get("load_kg", 0) + t.get("planned_kg", 0)
            remaining = cap - committed
            dead = road_km(t, first)
            row = {"truck_id": t["truck_id"], "type": t["type"], "capacity_kg": cap,
                   "load_kg": round(t.get("load_kg", 0)), "remaining_kg": round(remaining),
                   "remaining_pct": round(100 * remaining / cap), "status": t["status"],
                   "deadhead_km": round(dead, 2), "mode": None, "verdict": None, "score": None}
            if t["status"] in AVAILABLE:
                row["mode"] = "new"
            elif t["status"] in APPENDABLE and len(t.get("remaining_stops", [])) + len(route["stops"]) <= 14:
                row["mode"] = "append"
            if row["mode"] is None:
                row["verdict"] = "unavailable"
            elif remaining < route["load_kg"]:
                row["verdict"] = "insufficient"
            else:
                row["verdict"] = "feasible"
                slack = (remaining - route["load_kg"]) / cap
                row["score"] = round(dead + 6 * slack + (4 if row["mode"] == "append" else 0), 3)
            rows.append(row)
        rows.sort(key=lambda r: (r["verdict"] != "feasible", r["score"] if r["score"] is not None else r["deadhead_km"]))
        return rows

    def assign(self, route, trucks: dict):
        rows = self.evaluate(route, trucks)
        feasible = [r for r in rows if r["verdict"] == "feasible"]
        nearest_avail = min((r for r in rows if r["verdict"] != "unavailable"), key=lambda r: r["deadhead_km"], default=None)
        constraint = None
        if nearest_avail and nearest_avail["verdict"] == "insufficient":
            constraint = (f"Nearest truck {nearest_avail['truck_id']} can take only {nearest_avail['remaining_kg']} kg "
                          f"({nearest_avail['remaining_pct']}% free) but the route needs {route['load_kg']:.0f} kg")
        if feasible:
            return {"feasible": True, "truck_id": feasible[0]["truck_id"], "mode": feasible[0]["mode"],
                    "candidates": rows, "constraint": constraint}
        if any(r["verdict"] == "insufficient" for r in rows):
            reason = "capacity"
        else:
            reason = "no_available_truck"
        return {"feasible": False, "reason": reason, "candidates": rows, "constraint": constraint}
