"""Shared helpers: simulated clock, geo maths and the traffic-aware travel model."""
import math
import threading
import time
from datetime import datetime, timedelta

from . import config


class SimClock:
    """Simulated wall clock shared by all components (event time of the system)."""

    def __init__(self):
        today = datetime.now().replace(hour=config.SIM_START_HOUR, minute=0, second=0, microsecond=0)
        self._start = today
        self._minutes = 0.0
        self.speed = 1.0
        self.paused = False
        self._lock = threading.Lock()

    def advance(self, minutes: float):
        with self._lock:
            self._minutes += minutes

    @property
    def minutes(self) -> float:
        return self._minutes

    def now(self) -> datetime:
        return self._start + timedelta(minutes=self._minutes)

    def iso(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def hour(self) -> float:
        n = self.now()
        return n.hour + n.minute / 60

    def tick_interval(self) -> float:
        return config.TICK_SECONDS / max(self.speed, 0.1)

    def sleep_tick(self):
        time.sleep(self.tick_interval())


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def road_km(a, b) -> float:
    """Road-aware distance estimate between two {lat, lon} points."""
    return haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) * config.ROAD_CIRCUITY


def traffic_speed_kmh(hour: float) -> float:
    """Average Bengaluru truck speed by time of day (peak hours are slow)."""
    if 8 <= hour < 11 or 17 <= hour < 21:
        return 14.0
    if 11 <= hour < 17:
        return 20.0
    return 28.0  # night / early morning


def demand_multiplier(hour: float) -> float:
    """Waste generation follows daily activity: morning and evening peaks."""
    morning = math.exp(-((hour - 9.0) ** 2) / 4.0)
    evening = math.exp(-((hour - 20.0) ** 2) / 5.0)
    night_floor = 0.35
    return night_floor + 0.9 * morning + 1.0 * evening


def lerp(a, b, t):
    return a + (b - a) * t
