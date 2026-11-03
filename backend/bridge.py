"""
Dashboard bridge  (consumer group `wastex-dashboard-bridge`)

Subscribes to every topic and materialises the views the web dashboard needs
(latest bin table, fleet table, alert feed, decision log, zone windows, topic
tails and per-topic throughput). The FastAPI WebSocket pushes a snapshot of
these views once per second.
"""
import threading
import time
from collections import defaultdict, deque

from . import config


def _summary(topic, v):
    if topic == "bin-telemetry":
        return f"{v['bin_id']} fill={v['fill_level']}% {v['weight_kg']}kg {v['temperature_c']}°C bat={v['battery_pct']}% [{v['scenario']}]"
    if topic == "bin-analytics":
        eta = v.get("eta_min")
        return f"{v['bin_id']} fill={v['fill_level']}% rate={v['rate_per_hr']}%/h eta={eta if eta is not None else '∞'}m {v['status']}"
    if topic == "bin-alerts":
        return f"{v['type']} {v.get('bin_id')} · {v.get('message')}"
    if topic == "zone-aggregates":
        return f"{v['zone']} [{v['window_start']}-{v['window_end']}m] avg={v['avg_fill']}% max={v['max_fill']}% >90:{v['bins_over_90']}"
    if topic == "agent-decisions":
        return f"{v['decision_id']} {v['outcome']} · {v['trigger']['label']}"
    if topic == "collection-plans":
        return f"{v['plan_id']} {v['truck_id']} {len(v['stops'])} stops {v['load_kg']}kg {v['distance_km']}km"
    if topic == "fleet-status":
        return f"{v['truck_id']} {v['status']} load={v['load_kg']}kg next={v.get('next_stop')}"
    if topic == "collection-events":
        return f"{v['bin_id']} emptied by {v['truck_id']} ({v['kg']} kg)"
    return str(v)[:120]


class DashboardBridge:
    def __init__(self, bus, clock):
        self.bus = bus
        self.clock = clock
        self.bins = {}
        self.trucks = {}
        self.alerts = deque(maxlen=80)
        self.decisions = deque(maxlen=40)
        self.plans = deque(maxlen=40)
        self.collections = deque(maxlen=120)
        self.zone_latest = {}
        self.zone_history = defaultdict(lambda: deque(maxlen=48))
        self.tails = {t: deque(maxlen=25) for t in config.TOPICS}
        self.counts = defaultdict(int)
        self.rates = {t: 0.0 for t in config.TOPICS}
        self.partition_counts = defaultdict(lambda: defaultdict(int))
        self.fill_at_collection = deque(maxlen=300)
        self.kpi_series = deque(maxlen=240)
        self.alert_counts = defaultdict(int)
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, name="dashboard-bridge", daemon=True).start()
        threading.Thread(target=self._rates, name="bridge-rates", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        c = self.bus.consumer(config.GROUPS["ui"], list(config.TOPICS), "dashboard-bridge")
        c.wait_ready()
        self.ready.set()
        while not self._stop.is_set():
            recs = c.poll(timeout_ms=400, max_records=3000)
            if not recs:
                continue
            with self._lock:
                for r in recs:
                    self._apply(r)
        c.close()

    def _apply(self, r):
        t, v = r.topic, r.value
        self.counts[t] += 1
        self.partition_counts[t][r.partition] += 1
        self.tails[t].append({"p": r.partition, "o": r.offset, "k": r.key, "s": _summary(t, v)})
        if t == "bin-analytics":
            self.bins[v["bin_id"]] = v
        elif t == "fleet-status":
            self.trucks[v["truck_id"]] = v
        elif t == "bin-alerts":
            self.alerts.appendleft(v)
            self.alert_counts[v["type"]] += 1
        elif t == "agent-decisions":
            self.decisions.appendleft(v)
        elif t == "collection-plans":
            self.plans.appendleft(v)
        elif t == "collection-events":
            self.collections.appendleft(v)
            if v.get("fill_at_collection") is not None:
                self.fill_at_collection.append(v["fill_at_collection"])
        elif t == "zone-aggregates":
            self.zone_latest[v["zone_id"]] = v
            self.zone_history[v["zone_id"]].append(v)

    def _rates(self):
        prev = dict(self.counts)
        last_t = time.time()
        last_kpi = -1
        while not self._stop.is_set():
            time.sleep(1.0)
            now = time.time()
            cur = dict(self.counts)
            for t in config.TOPICS:
                self.rates[t] = round((cur.get(t, 0) - prev.get(t, 0)) / (now - last_t), 1)
            prev, last_t = cur, now
            m = int(self.clock.minutes)
            if m // 5 != last_kpi and self.bins:
                last_kpi = m // 5
                with self._lock:
                    fills = [b["fill_level"] for b in self.bins.values()]
                    self.kpi_series.append({
                        "sim_min": m, "t": self.clock.now().strftime("%H:%M"),
                        "avg_fill": round(sum(fills) / len(fills), 1),
                        "over_90": sum(1 for f in fills if f >= 90),
                        "overflow": sum(1 for f in fills if f >= 100),
                        "active_trucks": sum(1 for x in self.trucks.values() if x["status"] not in ("idle", "breakdown")),
                    })

    def snapshot(self):
        with self._lock:
            return {
                "bins": [{k: b[k] for k in ("bin_id", "zone", "zone_id", "lat", "lon", "fill_level", "rate_per_hr",
                                            "eta_min", "status", "anomalies", "temperature_c", "battery_pct",
                                            "weight_kg", "bin_type")} for b in self.bins.values()],
                "trucks": list(self.trucks.values()),
                "alerts": list(self.alerts)[:30],
                "decisions": list(self.decisions)[:12],
                "plans": list(self.plans)[:12],
                "collections": list(self.collections)[:25],
                "zones": list(self.zone_latest.values()),
                "zone_history": {z: list(h) for z, h in self.zone_history.items()},
                "rates": dict(self.rates),
                "counts": dict(self.counts),
                "partition_counts": {t: dict(p) for t, p in self.partition_counts.items()},
                "kpi_series": list(self.kpi_series),
                "alert_counts": dict(self.alert_counts),
                "avg_fill_at_collection": round(sum(self.fill_at_collection) / len(self.fill_at_collection), 1)
                if self.fill_at_collection else None,
            }

    def hotspots(self):
        """Where is trash increasing? Live generation rate per zone vs its recent windows."""
        from .data.bengaluru import ZONES
        with self._lock:
            per = defaultdict(list)
            for b in self.bins.values():
                per[b["zone_id"]].append(b)
            out = []
            for z in ZONES:
                bins = per.get(z["id"], [])
                if not bins:
                    continue
                gen = sum(b["rate_per_min"] * b["max_kg"] / 100 * 60 for b in bins)
                hist = [w.get("gen_kg_per_hr", 0) for w in self.zone_history.get(z["id"], [])][-12:]
                # baseline = the zone's previous ~45 min of windows (excluding the latest 15 min)
                base_win = hist[:-3] if len(hist) > 4 else hist[:-1] or hist
                base = sum(base_win) / len(base_win) if base_win else gen
                trend = 100 * (gen - base) / base if base > 1 else 0.0
                status = "SURGE" if trend > 40 else "RISING" if trend > 10 else "FALLING" if trend < -10 else "STABLE"
                out.append({
                    "zone_id": z["id"], "zone": z["name"], "lat": z["lat"], "lon": z["lon"],
                    "gen_kg_per_hr": round(gen, 1), "trend_pct": round(trend, 1), "status": status,
                    "avg_fill": round(sum(b["fill_level"] for b in bins) / len(bins), 1),
                    "bins_over_75": sum(1 for b in bins if b["fill_level"] >= 75),
                    "kg_waiting": round(sum(b["weight_kg"] for b in bins), 1),
                    "spark": [round(h, 1) for h in hist] + [round(gen, 1)],
                })
            out.sort(key=lambda h: -h["gen_kg_per_hr"])
            return out

    def tail(self, topic):
        with self._lock:
            return list(self.tails.get(topic, []))
