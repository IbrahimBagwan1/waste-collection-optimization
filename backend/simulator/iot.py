"""
IoT Smart-Bin Simulator  (producer -> topic `bin-telemetry`)

Simulates every smart bin's ultrasonic fill sensor, load cell, temperature
probe and battery. Each tick publishes one telemetry record per bin, keyed by
bin_id so all readings of a bin land in the same partition (ordering guarantee).

Scenarios (slide 11 - "how do we simulate thousands of them?"):
  normal   - daily demand curve with per-zone base fill rates
  demand   - city-wide demand spike (festival / weekend)  x1.8
  surge    - event surge in one zone (match / concert)    x4 for 60 sim-min
  anomaly  - injected sensor faults: fire, spike, tamper, battery

It also consumes `collection-events` so that when a truck empties a bin the
physical bin resets - closing the loop between decisions and the world.
"""
import logging
import random
import threading

from .. import config
from ..core import demand_multiplier
from ..data.bengaluru import BIN_TYPES, ZONES

log = logging.getLogger("wastex.iot")


class SmartBin:
    def __init__(self, rng: random.Random, zone: dict, idx: int):
        self.zone = zone
        self.id = f"BIN-{zone['id'][1:]}{idx:02d}"
        self.lat = zone["lat"] + rng.gauss(0, 0.0065)
        self.lon = zone["lon"] + rng.gauss(0, 0.0065)
        r = rng.random()
        self.type = "SMART-1100" if r < 0.5 else ("SMART-240" if r < 0.75 else "COMMUNITY-3200")
        self.max_kg = BIN_TYPES[self.type]["max_kg"]
        self.litres = BIN_TYPES[self.type]["litres"]
        self.fill = rng.uniform(15, 82) if rng.random() < 0.85 else rng.uniform(82, 93)
        self.factor = rng.lognormvariate(0, 0.35)
        self.density = rng.uniform(0.85, 1.1)
        self.battery = rng.uniform(55, 100) if rng.random() > 0.05 else rng.uniform(12, 20)
        self.temp_offset = rng.uniform(-1.5, 1.5)
        self.anomaly = None          # (kind, remaining_minutes)
        self.overflow_minutes = 0.0
        self.collections = 0
        self.seq = 0


class IoTSimulator:
    def __init__(self, bus, clock, seed=config.SEED):
        self.bus = bus
        self.clock = clock
        self.rng = random.Random(seed)
        self.bins = [SmartBin(self.rng, z, i + 1) for z in ZONES for i in range(config.BINS_PER_ZONE)]
        self.by_id = {b.id: b for b in self.bins}
        self.demand_mode = False
        self.surge = {}               # zone_id -> remaining minutes
        self.counts = {"normal": 0, "demand": 0, "surge": 0, "anomaly": 0}
        self.overflow_events = 0
        self.ready = threading.Event()
        self._stop = threading.Event()
        self.producer = None

    # ------------------------------------------------------------------ controls
    def set_demand(self, on: bool):
        self.demand_mode = on

    def trigger_surge(self, zone_id: str, minutes: int = 60):
        self.surge[zone_id] = minutes

    def inject_anomaly(self, kind: str, bin_id: str = None):
        if bin_id:
            b = self.by_id[bin_id]
        else:
            # pick a bin where the fault is observable: tamper needs waste to remove,
            # a spike needs head-room above the current level
            pool = {"tamper": [x for x in self.bins if x.fill >= 60],
                    "spike": [x for x in self.bins if x.fill <= 50]}.get(kind) or self.bins
            b = self.rng.choice(pool)
        if kind == "fire":
            b.anomaly = ("fire", 25)
        elif kind == "spike":
            b.anomaly = ("spike", 3)
        elif kind == "tamper":
            b.anomaly = ("tamper", 1)
        elif kind == "battery":
            b.battery = self.rng.uniform(4, 9)
            b.anomaly = ("battery", 1)
        return b.id

    # ------------------------------------------------------------------ main loops
    def start(self):
        threading.Thread(target=self._consume_collections, name="iot-gateway", daemon=True).start()

    def start_producing(self):
        self.producer = self.bus.producer()
        threading.Thread(target=self._run, name="iot-producer", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _consume_collections(self):
        c = self.bus.consumer(config.GROUPS["iot"], ["collection-events"], "iot-gateway")
        c.wait_ready()
        self.ready.set()
        while not self._stop.is_set():
            for rec in c.poll(timeout_ms=500):
                ev = rec.value
                b = self.by_id.get(ev.get("bin_id"))
                if b:
                    b.fill = self.rng.uniform(0.5, 4.0)
                    b.collections += 1
                    if b.anomaly and b.anomaly[0] == "fire":
                        b.anomaly = None
        c.close()

    def _run(self):
        while not self._stop.is_set():
            if not self.clock.paused:
                self.clock.advance(config.SIM_MINUTES_PER_TICK)
                self._tick(config.SIM_MINUTES_PER_TICK)
            self.clock.sleep_tick()

    def _tick(self, dt):
        hour = self.clock.hour()
        dm = demand_multiplier(hour)
        ts = self.clock.iso()
        sim_min = round(self.clock.minutes, 2)
        ambient = 24 + 7 * max(0.0, 1 - abs(hour - 14) / 8)
        for zid in list(self.surge):
            self.surge[zid] -= dt
            if self.surge[zid] <= 0:
                del self.surge[zid]

        for b in self.bins:
            scenario = "normal"
            mult = dm
            if self.demand_mode:
                mult *= 1.8
                scenario = "demand"
            if b.zone["id"] in self.surge:
                mult *= 4.0
                scenario = "surge"
            rate = b.zone["base_rate"] * b.factor * mult
            b.fill = min(100.0, b.fill + max(0.0, self.rng.gauss(rate, rate * 0.25)) * dt)
            b.battery = max(0.0, b.battery - 0.004 * dt)
            temp = ambient + b.temp_offset + 0.04 * b.fill + self.rng.gauss(0, 0.4)
            reported_fill = b.fill

            if b.anomaly:
                kind, left = b.anomaly
                scenario = "anomaly"
                if kind == "fire":
                    temp = self.rng.uniform(62, 85)
                elif kind == "spike":
                    reported_fill = min(100.0, b.fill + self.rng.uniform(35, 55))
                elif kind == "tamper":
                    b.fill = max(12.0, b.fill - self.rng.uniform(35, 50))
                    reported_fill = b.fill
                left -= dt
                b.anomaly = (kind, left) if left > 0 else None

            if b.fill >= 100.0:
                if b.overflow_minutes == 0:
                    self.overflow_events += 1
                b.overflow_minutes += dt
            elif b.overflow_minutes and b.fill < 100:
                b.overflow_minutes = 0.0

            self.counts[scenario] += 1
            b.seq += 1
            self.producer.send("bin-telemetry", b.id, {
                "bin_id": b.id,
                "zone_id": b.zone["id"],
                "zone": b.zone["name"],
                "lat": round(b.lat, 6),
                "lon": round(b.lon, 6),
                "bin_type": b.type,
                "capacity_l": b.litres,
                "max_kg": b.max_kg,
                "fill_level": round(reported_fill, 2),
                "weight_kg": round(reported_fill / 100 * b.max_kg * b.density, 1),
                "temperature_c": round(temp, 1),
                "battery_pct": round(b.battery, 1),
                "ts": ts,
                "sim_min": sim_min,
                "scenario": scenario,
                "seq": b.seq,
            })
        self.producer.flush()

    # ------------------------------------------------------------------ metrics
    def ground_truth(self):
        overflowing = sum(1 for b in self.bins if b.fill >= 100)
        return {
            "bins": len(self.bins),
            "overflowing_now": overflowing,
            "overflow_events": self.overflow_events,
            "scenario_counts": dict(self.counts),
            "demand_mode": self.demand_mode,
            "surge_zones": {k: round(v) for k, v in self.surge.items()},
        }
