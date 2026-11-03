"""
Stream Processor  (consumer group `wastex-stream-processor`)

  bin-telemetry ─┐                         ┌─> bin-analytics   (per-bin enriched state)
                 ├─> stateful operators ───┼─> bin-alerts      (overflow / anomaly alerts)
collection-events┘                         └─> zone-aggregates (5-min tumbling windows)

Operators implemented (event-time, keyed by bin_id):
  1. Sliding count window  - last N validated readings -> least-squares fill rate (%/min)
  2. Overflow forecasting  - ETA = (100 - fill) / rate
  3. Anomaly detection     - physically implausible jumps (sensor spike), unexplained
                             drops (tamper / theft), temperature (fire), battery
  4. Stream-stream join    - telemetry joined with collection-events so that a drop
                             after a truck visit is treated as "emptied", not tamper
  5. Tumbling window       - per-zone aggregates every 5 simulated minutes
  6. Alert de-duplication  - one alert per bin+type until the condition clears
"""
import logging
import threading
import time
from collections import defaultdict, deque

from .. import config

log = logging.getLogger("wastex.stream")

SPIKE_JUMP = 15.0       # %/reading - bins physically cannot fill this fast
DROP_JUMP = -15.0
FIRE_TEMP = 60.0
LOW_BATTERY = 15.0


class BinState:
    __slots__ = ("window", "validated", "last_collection", "active", "last", "rate")

    def __init__(self):
        self.window = deque(maxlen=config.FILL_RATE_WINDOW)
        self.validated = None
        self.last_collection = -1e9
        self.active = {}          # alert type -> sim_min raised
        self.last = None
        self.rate = 0.0


def slope(points):
    n = len(points)
    if n < 3:
        return 0.0
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    den = sum((p[0] - mx) ** 2 for p in points)
    if den == 0:
        return 0.0
    return sum((p[0] - mx) * (p[1] - my) for p in points) / den


class StreamProcessor:
    def __init__(self, bus):
        self.bus = bus
        self.state = defaultdict(BinState)
        self.zone_win = {}       # zone_id -> current window accumulator
        self.ready = threading.Event()
        self._stop = threading.Event()
        self.processed = 0
        self.alerts_emitted = defaultdict(int)
        self.latency_ms = deque(maxlen=500)
        self.overrides = set()

    def start(self):
        threading.Thread(target=self._run, name="stream-processor", daemon=True).start()

    def stop(self):
        self._stop.set()

    def metrics(self):
        lat = sorted(self.latency_ms)
        return {
            "processed": self.processed,
            "alerts": dict(self.alerts_emitted),
            "latency_p50_ms": round(lat[len(lat) // 2], 1) if lat else 0,
            "latency_p95_ms": round(lat[int(len(lat) * 0.95)], 1) if lat else 0,
        }

    # ------------------------------------------------------------------
    def _run(self):
        c = self.bus.consumer(config.GROUPS["stream"], ["bin-telemetry", "collection-events"], "stream-processor")
        self.producer = self.bus.producer()
        c.wait_ready()
        self.ready.set()
        while not self._stop.is_set():
            recs = c.poll(timeout_ms=500, max_records=1000)
            # join side first: a collection must be known before the drop it explains
            recs.sort(key=lambda r: 0 if r.topic == "collection-events" else 1)
            for rec in recs:
                try:
                    if rec.topic == "collection-events":
                        self._on_collection(rec.value)
                    else:
                        self._on_telemetry(rec.value)
                        self.latency_ms.append(max(0.0, (time.time() - rec.timestamp) * 1000))
                except Exception:  # never let one bad record kill the stream
                    log.exception("failed to process record")
            if recs:
                self.producer.flush()
        c.close()

    def reset_bin(self, bin_id):
        """Operator override: accept the bin's next (jumped) level instead of quarantining it."""
        self.overrides.add(bin_id)

    def _on_collection(self, ev):
        st = self.state[ev["bin_id"]]
        st.last_collection = ev.get("sim_min", 0)
        st.window.clear()
        st.validated = None
        st.rate = 0.0
        for k in ("OVERFLOW", "CRITICAL_FILL", "PREDICTED_OVERFLOW", "FIRE"):
            st.active.pop(k, None)

    def _alert(self, st, t, kind, severity, msg, extra=None):
        if kind in st.active:
            return
        st.active[kind] = t["sim_min"]
        self.alerts_emitted[kind] += 1
        payload = {
            "alert_id": f"{t['bin_id']}-{kind}-{int(t['sim_min'])}",
            "type": kind, "severity": severity, "message": msg,
            "bin_id": t["bin_id"], "zone": t["zone"], "zone_id": t["zone_id"],
            "lat": t["lat"], "lon": t["lon"], "fill_level": t["fill_level"],
            "ts": t["ts"], "sim_min": t["sim_min"],
        }
        if extra:
            payload.update(extra)
        self.producer.send("bin-alerts", t["bin_id"], payload)

    def _clear(self, st, kind):
        st.active.pop(kind, None)

    def _on_telemetry(self, t):
        self.processed += 1
        if t["bin_id"] in self.overrides and t["fill_level"] >= 90:
            self.overrides.discard(t["bin_id"])
            self.state[t["bin_id"]] = BinState()
        st = self.state[t["bin_id"]]
        now = t["sim_min"]
        fill = t["fill_level"]
        anomalies = []

        # ---- anomaly detection on the raw delta --------------------------------
        if st.validated is not None:
            delta = fill - st.validated
            # a drop to near-empty is how an emptied bin looks even if the event is late
            recently_collected = now - st.last_collection <= 5 or fill < 5.0
            if delta > SPIKE_JUMP:
                anomalies.append("SENSOR_SPIKE")
                self._alert(st, t, "SENSOR_SPIKE", "warning",
                            f"Implausible jump +{delta:.0f}% in one reading - reading quarantined")
                fill = st.validated  # quarantine the bad reading
            elif delta < DROP_JUMP and not recently_collected:
                anomalies.append("TAMPER")
                self._alert(st, t, "TAMPER", "warning",
                            f"Fill dropped {delta:.0f}% without a collection event (tamper / scavenging)")
                st.window.clear()
            elif delta < DROP_JUMP:
                st.window.clear()  # emptied by a truck - restart the rate window
            else:
                self._clear(st, "SENSOR_SPIKE")
                self._clear(st, "TAMPER")
        st.validated = fill

        if t["temperature_c"] >= FIRE_TEMP:
            anomalies.append("FIRE")
            self._alert(st, t, "FIRE", "critical", f"Temperature {t['temperature_c']:.0f}°C - possible garbage burning")
        elif t["temperature_c"] < FIRE_TEMP - 10:
            self._clear(st, "FIRE")

        if t["battery_pct"] < LOW_BATTERY:
            anomalies.append("LOW_BATTERY")
            self._alert(st, t, "LOW_BATTERY", "info", f"Sensor battery {t['battery_pct']:.0f}% - schedule maintenance")

        # ---- sliding-window fill rate ------------------------------------------
        st.window.append((now, fill))
        rate = max(0.0, slope(list(st.window)))
        st.rate = 0.6 * rate + 0.4 * st.rate if st.rate else rate  # EWMA smoothing
        eta = (100 - fill) / st.rate if st.rate > 0.01 and fill < 100 else (0.0 if fill >= 100 else None)

        if fill >= 100:
            self._alert(st, t, "OVERFLOW", "critical", "Bin is overflowing")
        elif fill >= config.CRITICAL_FILL:
            self._alert(st, t, "CRITICAL_FILL", "critical", f"Fill level {fill:.0f}% - collect immediately")
        elif eta is not None and eta <= 30 and len(st.window) >= 4:
            self._alert(st, t, "PREDICTED_OVERFLOW", "warning",
                        f"Predicted to overflow in {eta:.0f} min (rate {st.rate:.2f}%/min)", {"eta_min": round(eta, 1)})
        # hysteresis: an alert re-arms only once the condition has clearly gone away
        if fill < 90:
            self._clear(st, "OVERFLOW")
            self._clear(st, "CRITICAL_FILL")
        if eta is None or eta > 60:
            self._clear(st, "PREDICTED_OVERFLOW")

        status = "ok"
        if anomalies:
            status = "fault"
        if fill >= 100:
            status = "overflow"
        elif fill >= 90:
            status = "critical"
        elif fill >= 75:
            status = "warning"

        enriched = {
            "bin_id": t["bin_id"], "zone_id": t["zone_id"], "zone": t["zone"],
            "lat": t["lat"], "lon": t["lon"], "bin_type": t["bin_type"], "max_kg": t["max_kg"],
            "fill_level": round(fill, 2), "raw_fill": t["fill_level"],
            "weight_kg": round(fill / 100 * t["max_kg"], 1),
            "temperature_c": t["temperature_c"], "battery_pct": t["battery_pct"],
            "rate_per_min": round(st.rate, 4), "rate_per_hr": round(st.rate * 60, 2),
            "eta_min": round(eta, 1) if eta is not None else None,
            "anomalies": anomalies, "status": status, "scenario": t["scenario"],
            "ts": t["ts"], "sim_min": now,
        }
        st.last = enriched
        self.producer.send("bin-analytics", t["bin_id"], enriched)
        self._window(enriched)

    # ---- tumbling window per zone -----------------------------------------------
    def _window(self, e):
        size = config.ZONE_WINDOW_MINUTES
        idx = int(e["sim_min"] // size)
        w = self.zone_win.get(e["zone_id"])
        if w is None or w["idx"] != idx:
            if w is not None and idx > w["idx"]:
                self._emit_window(w, size)
            w = {"idx": idx, "zone_id": e["zone_id"], "zone": e["zone"], "n": 0, "sum": 0.0, "max": 0.0,
                 "latest": {}, "rates": {}, "anomalies": 0}
            self.zone_win[e["zone_id"]] = w
        w["n"] += 1
        w["sum"] += e["fill_level"]
        w["max"] = max(w["max"], e["fill_level"])
        w["latest"][e["bin_id"]] = e
        w["rates"][e["bin_id"]] = e["rate_per_min"]
        if e["anomalies"]:
            w["anomalies"] += 1

    def _emit_window(self, w, size):
        latest = w["latest"].values()
        self.producer.send("zone-aggregates", w["zone_id"], {
            "zone_id": w["zone_id"], "zone": w["zone"],
            "window_start": w["idx"] * size, "window_end": (w["idx"] + 1) * size,
            "readings": w["n"],
            "avg_fill": round(w["sum"] / max(w["n"], 1), 2),
            "max_fill": round(w["max"], 2),
            "bins_over_90": sum(1 for b in latest if b["fill_level"] >= 90),
            "total_kg": round(sum(b["weight_kg"] for b in latest), 1),
            "avg_rate": round(sum(w["rates"].values()) / max(len(w["rates"]), 1), 3),
            # waste generation: how many kg/hour the zone's bins are currently accumulating
            "gen_kg_per_hr": round(sum(b["rate_per_min"] * b["max_kg"] / 100 * 60 for b in latest), 1),
            "anomalies": w["anomalies"],
        })
