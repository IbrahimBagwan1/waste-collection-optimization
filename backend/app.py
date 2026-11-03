"""
WASTEX application server.

Starts the whole event-driven pipeline in one process and serves the dashboard:

  IoT Simulator ─> [bin-telemetry] ─> Stream Processor ─> [bin-analytics] [bin-alerts] [zone-aggregates]
                                                               │
                         [fleet-status] ──────────────> JEV Orchestrator (Waste / Route / Fleet agents)
                              ▲                                │
                       Fleet Simulator <── [collection-plans] ─┘   + [agent-decisions]
                              │
                              └─> [collection-events] ─> IoT Simulator (bin emptied) + Stream Processor

Run:  python run.py      (or  uvicorn backend.app:app)
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import benchmark, config, routing
from .agents.jev_orchestrator import JEVOrchestrator
from .bridge import DashboardBridge
from .bus import create_bus
from .core import SimClock, road_km, traffic_speed_kmh
from .data import bengaluru as data
from .simulator.fleet import FleetSimulator
from .simulator.iot import IoTSimulator
from .streaming.processor import StreamProcessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logging.getLogger("kafka").setLevel(logging.ERROR)  # kafka-python is very chatty below ERROR
log = logging.getLogger("wastex")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


class System:
    def start(self):
        self.started_at = time.time()
        self.clock = SimClock()
        self.bus = create_bus(config.BUS_MODE, config.KAFKA_BOOTSTRAP)
        self.bus.create_topics(config.TOPICS)
        self.iot = IoTSimulator(self.bus, self.clock)
        self.stream = StreamProcessor(self.bus)
        self.jev = JEVOrchestrator(self.bus, self.clock)
        self.fleet = FleetSimulator(self.bus, self.clock)
        self.jev.route.plant_intake = self.fleet.plant_kg
        self.bridge = DashboardBridge(self.bus, self.clock)

        # 1. consumers join their groups first ...
        for c in (self.bridge, self.stream, self.jev, self.fleet, self.iot):
            c.start()
        for name, c in (("dashboard", self.bridge), ("stream", self.stream), ("jev", self.jev),
                        ("fleet", self.fleet), ("iot-gateway", self.iot)):
            if not c.ready.wait(45):
                log.warning("%s consumer not ready after 45 s - continuing", name)
        # 2. ... then the producers start, so no event is missed
        self.fleet.start_moving()
        self.iot.start_producing()
        log.info("WASTEX pipeline running on %s", self.bus.description)
        # the 24 h evaluation takes ~45 s; compute it in the background so the Results page opens instantly
        import threading
        threading.Thread(target=benchmark.compare, args=(24,), name="benchmark-warmup", daemon=True).start()

    def stop(self):
        for c in (self.iot, self.fleet, self.jev, self.stream, self.bridge):
            c.stop()
        time.sleep(0.6)
        self.bus.close()


system = System()


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(system.start)
    yield
    await asyncio.to_thread(system.stop)


app = FastAPI(title="WASTEX", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store"  # local dev tool: always serve fresh UI files
    return response


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/static")
def static_data():
    return {
        "zones": data.ZONES, "depots": data.DEPOTS, "plants": data.PROCESSING_PLANTS, "msgp": data.MSGP_PLANT,
        "landfills": data.LANDFILLS, "dwcc": data.DRY_WASTE_CENTRES, "fleet": data.FLEET,
        "complaint_themes": data.COMPLAINT_THEMES, "fixed_schedule": data.FIXED_SCHEDULE,
        "topics": config.TOPICS, "groups": config.GROUPS,
        "bus": {"kind": system.bus.kind, "description": system.bus.description},
        "config": {"planning_interval": config.PLANNING_INTERVAL_MIN, "zone_window": config.ZONE_WINDOW_MINUTES,
                   "fill_rate_window": config.FILL_RATE_WINDOW, "high": config.HIGH_THRESHOLD,
                   "medium": config.MEDIUM_THRESHOLD, "dispose_at": config.DISPOSE_AT},
    }


def snapshot():
    s = system.bridge.snapshot()
    s["clock"] = {"iso": system.clock.iso(), "time": system.clock.now().strftime("%H:%M"),
                  "day": system.clock.now().strftime("%a %d %b"), "sim_min": round(system.clock.minutes, 1),
                  "speed": system.clock.speed, "paused": system.clock.paused}
    s["bus"] = {"kind": system.bus.kind, "description": system.bus.description, "produced": system.bus.produced}
    s["kafka"] = system.bus.stats()
    s["stream"] = system.stream.metrics()
    s["jev"] = dict(system.jev.stats)
    s["jev"]["scheduled"] = len(system.jev.scheduled)
    s["scheduled_bins"] = list(system.jev.scheduled)
    s["fleet_metrics"] = system.fleet.metrics()
    s["truth"] = system.iot.ground_truth()
    s["uptime_s"] = round(time.time() - system.started_at)
    s["hotspots"] = system.bridge.hotspots()
    return s


@app.get("/api/snapshot")
def api_snapshot():
    return JSONResponse(snapshot())


@app.get("/api/topic/{name}")
def api_topic(name: str):
    return system.bridge.tail(name)


@app.get("/api/health")
def api_health():
    """Liveness of every pipeline thread plus their current stack (for troubleshooting)."""
    import sys
    import threading
    import traceback
    frames = sys._current_frames()
    names = {"iot-producer", "iot-gateway", "stream-processor", "jev-orchestrator", "fleet-plans", "fleet-sim", "dashboard-bridge"}
    out = {}
    for t in threading.enumerate():
        if t.name in names:
            st = traceback.extract_stack(frames.get(t.ident)) if t.ident in frames else []
            out[t.name] = {"alive": t.is_alive(), "at": [f"{f.filename.split('site-packages')[-1]}:{f.lineno} {f.name}" for f in st[-6:]]}
    missing = sorted(names - set(out))
    return {"ok": not missing, "missing_threads": missing, "threads": out,
            "bus": system.bus.kind, "sim_min": round(system.clock.minutes, 1), "jev_cycles": system.jev.stats["cycles"]}


@app.get("/api/benchmark")
async def api_benchmark(hours: int = 24):
    return await asyncio.to_thread(benchmark.compare, max(6, min(hours, 72)))


class RouteRequest(BaseModel):
    start: str                      # depot id (DEPOT-S ...) or truck id (TRUCK-03 ...)
    bin_ids: list[str]
    plant: str = "auto"             # "auto", a plant id, or "standby" (no unloading)
    algorithm: str | None = None    # dispatch only: which ordering to send
    order: list[str] | None = None  # dispatch only: bin ids in the chosen order
    truck_id: str | None = None     # dispatch only


def _route_context(req: RouteRequest):
    """Resolve the start point, the selected bins (live state) and the end point."""
    if req.start in {d["id"] for d in data.DEPOTS}:
        start = dict(next(d for d in data.DEPOTS if d["id"] == req.start))
    elif req.start in system.jev.trucks:
        t = system.jev.trucks[req.start]
        start = {"id": t["truck_id"], "name": f"{t['truck_id']} (current position)", "lat": t["lat"], "lon": t["lon"]}
    else:
        raise ValueError(f"unknown start {req.start}")
    bins = system.bridge.bins
    stops = []
    for bid in req.bin_ids:
        b = bins.get(bid)
        if b:
            stops.append({k: b[k] for k in ("bin_id", "zone", "zone_id", "lat", "lon", "fill_level", "weight_kg", "max_kg",
                                             "rate_per_min", "eta_min")})
    if not stops:
        raise ValueError("select at least one bin")
    if len(stops) > 25:
        raise ValueError("select at most 25 bins for one route")
    return start, stops


def _end_point(choice, last):
    if choice == "standby":
        return None, False
    if choice == "auto":
        return system.jev.route.choose_plant(last), True
    p = next((p for p in data.PROCESSING_PLANTS if p["id"] == choice), None)
    if p is None or p["mixed_tpd"] <= 0:
        raise ValueError("that plant is closed or unknown")
    return p, True


def _plant_table(last, chosen_id):
    rows = []
    for p in data.PROCESSING_PLANTS:
        intake = p["intake_tpd"] + system.fleet.plant_kg.get(p["id"], 0) / 1000
        util = intake / p["mixed_tpd"] if p["mixed_tpd"] else None
        km = road_km(last, p)
        if p["mixed_tpd"] <= 0:
            status = "closed (0 TPD)"
        elif util > 0.9:
            status = "skipped (> 90% utilised)"
        else:
            status = "chosen" if p["id"] == chosen_id else "candidate"
        rows.append({"id": p["id"], "name": p["name"], "km": round(km, 2), "util_pct": round(100 * util, 1) if util is not None else None,
                     "cost": round(km * (1 + 0.6 * util), 2) if util is not None else None, "status": status,
                     "lat": p["lat"], "lon": p["lon"]})
    rows.sort(key=lambda r: (r["cost"] is None, r["cost"] or 0))
    return rows


@app.post("/api/route/plan")
def api_route_plan(req: RouteRequest):
    try:
        start, stops = _route_context(req)
        hour = system.clock.hour()
        # fix the end point first (plant nearest the provisional tour end), then optimise towards it
        end, dispose = _end_point(req.plant, routing.nearest_neighbour(start, stops)[-1])
        results = routing.compare(start, stops, end, hour)
        if dispose:
            for r in results:
                r["minutes"] = round(r["minutes"] + config.UNLOAD_MIN, 1)
        best = min(results, key=lambda r: (r["km"], r["key"] != "nn2opt"))
        pts = lambda order: [start] + order + ([end] if end else [])  # noqa: E731
        load = round(sum(s["weight_kg"] * 1.1 for s in stops), 1)
        trucks = []
        for t in system.jev.trucks.values():
            free = t["capacity_kg"] - t.get("load_kg", 0) - t.get("planned_kg", 0)
            ok = t["status"] not in ("breakdown", "to_plant", "unloading") and free >= load
            trucks.append({"truck_id": t["truck_id"], "type": t["type"], "status": t["status"], "free_kg": round(free),
                           "deadhead_km": round(road_km(t, stops[0]), 2), "feasible": ok})
        trucks.sort(key=lambda x: (not x["feasible"], x["deadhead_km"]))
        return {
            "start": start, "end": end, "dispose": dispose, "load_kg": load, "hour": round(hour, 2),
            "speed_kmh": traffic_speed_kmh(hour), "best": best["key"],
            "results": [{**{k: v for k, v in r.items() if k != "order"}, "order": [s["bin_id"] for s in r["order"]]} for r in results],
            "stops": stops, "plants": _plant_table(best["order"][-1], end["id"] if end else None), "trucks": trucks,
            "scheduled": {s["bin_id"]: system.jev.scheduled[s["bin_id"]][0] for s in stops if s["bin_id"] in system.jev.scheduled},
            "road_best": routing.road_geometry(pts(best["order"])),
            "road_naive": routing.road_geometry(pts(results[0]["order"])),
        }
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/route/dispatch")
def api_route_dispatch(req: RouteRequest):
    try:
        if not req.truck_id:
            raise ValueError("choose a truck")
        # the route is driven from the truck's current position, in the order the operator chose
        start, stops = _route_context(RouteRequest(start=req.truck_id, bin_ids=req.order or req.bin_ids))
        end, dispose = _end_point(req.plant, stops[-1])
        hour = system.clock.hour()
        km = round(routing.tour_km(start, stops, end), 2)
        minutes = round(km / traffic_speed_kmh(hour) * 60 + config.SERVICE_MIN_PER_BIN * len(stops)
                        + (config.UNLOAD_MIN if dispose else 0), 1)
        naive_stops = [s for bid in req.bin_ids for s in stops if s["bin_id"] == bid]
        naive_km = round(routing.tour_km(start, naive_stops, end), 2)
        if end is None:
            end = {"id": "STANDBY", "name": f"standby near {stops[-1]['zone']}", "lat": stops[-1]["lat"], "lon": stops[-1]["lon"]}
        plan = system.jev.dispatch_manual(req.truck_id, stops, end, dispose, km, minutes, naive_km, req.algorithm or "NN + 2-opt")
        log.info("route dispatched: %s -> %s", plan["plan_id"], req.truck_id)
        return {"ok": True, "message": f"{plan['plan_id']} published to collection-plans for {req.truck_id} ({len(stops)} stops, {km} km from its current position)",
                "plan_id": plan["plan_id"]}
    except ValueError as e:
        return JSONResponse({"ok": False, "message": str(e)}, status_code=400)


class Control(BaseModel):
    action: str
    value: float | None = None
    zone_id: str | None = None
    kind: str | None = None
    target: str | None = None


@app.post("/api/control")
def control(c: Control):
    clk = system.clock
    msg = "ok"
    if c.action == "pause":
        clk.paused = True
    elif c.action == "resume":
        clk.paused = False
    elif c.action == "speed":
        clk.speed = max(0.5, min(float(c.value or 1), 10))
        msg = f"speed {clk.speed}x"
    elif c.action == "demand":
        system.iot.set_demand(bool(c.value))
        msg = "demand spike " + ("ON" if c.value else "OFF")
    elif c.action == "surge":
        zid = c.zone_id or "Z01"
        system.iot.trigger_surge(zid, int(c.value or 60))
        msg = f"event surge in {zid}"
    elif c.action == "anomaly":
        bid = system.iot.inject_anomaly(c.kind or "fire", c.target)
        msg = f"{c.kind} anomaly injected on {bid}"
    elif c.action == "breakdown":
        tid = system.fleet.breakdown(c.target)
        msg = f"{tid} broke down" if tid else "no truck available"
    elif c.action == "slide13":
        # Reproduce the 'Example Event' of slide 13: Bin A -> 96 %, fill rate HIGH,
        # Truck 1 at 20 % spare capacity -> JEV detects the constraint -> another truck assigned.
        zone = next(z for z in data.ZONES if z["id"] == "Z02")
        truck = system.fleet.nearest_truck(zone)
        if truck is None:
            return {"ok": False, "message": "no truck available for the demo"}
        spare = system.fleet.preload_spare(truck.id, 0.20)
        targets, load = [], 0.0
        pool = [b for b in system.iot.bins if b.zone["id"] == "Z02" and b.id not in system.jev.scheduled]
        for b in sorted(pool, key=lambda b: -b.max_kg):
            targets.append(b)
            load += b.max_kg * 0.96 * 1.1
            if load > spare * 1.3:  # clearly more than the nearest truck can still take
                break
        for b in targets:
            b.fill = 96.0
            b.factor = max(b.factor, 1.8)
            # operator override: the stream processor accepts the new level instead of
            # quarantining the jump as a sensor spike
            system.stream.reset_bin(b.id)
        msg = (f"Slide-13 scenario: {', '.join(b.id for b in targets)} → 96 %, "
               f"nearest truck {truck.id} at 20 % spare capacity ({spare:.0f} kg)")
    elif c.action == "plan_now":
        system.jev.last_cycle_min = -1e9
        msg = "planning cycle requested"
    else:
        return JSONResponse({"ok": False, "message": f"unknown action {c.action}"}, status_code=400)
    log.info("control: %s", msg)
    return {"ok": True, "message": msg}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(await asyncio.to_thread(snapshot))
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:  # client went away mid-send
        log.debug("websocket closed: %s", e)
