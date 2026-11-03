"""Central configuration for WASTEX. Override any value with an environment variable."""
import os

# Message bus: "auto" tries a real Kafka broker first and falls back to the
# embedded broker; "kafka" forces Kafka; "embedded" forces the in-process broker.
BUS_MODE = os.getenv("WASTEX_BUS", "auto").lower()
KAFKA_BOOTSTRAP = os.getenv("WASTEX_KAFKA", "localhost:9092")

HOST = os.getenv("WASTEX_HOST", "127.0.0.1")
PORT = int(os.getenv("WASTEX_PORT", "8000"))

SEED = int(os.getenv("WASTEX_SEED", "42"))
BINS_PER_ZONE = int(os.getenv("WASTEX_BINS_PER_ZONE", "10"))

# Simulation clock: every tick advances simulated time by SIM_MINUTES_PER_TICK.
# At speed 1x one tick happens every TICK_SECONDS of real time.
SIM_MINUTES_PER_TICK = 1.0
TICK_SECONDS = 1.0
SIM_START_HOUR = 7  # simulated day starts at 07:00 IST (just before the morning peak)

# Kafka topics -> number of partitions
TOPICS = {
    "bin-telemetry": 6,      # raw IoT readings, keyed by bin_id
    "bin-analytics": 6,      # enriched per-bin state (fill rate, ETA, priority inputs)
    "bin-alerts": 3,         # overflow / anomaly / fire / battery alerts
    "zone-aggregates": 3,    # tumbling-window zone statistics
    "agent-decisions": 1,    # JEV reasoning trace (ordered)
    "collection-plans": 3,   # route + truck assignments, keyed by truck_id
    "fleet-status": 3,       # truck GPS / load heartbeat, keyed by truck_id
    "collection-events": 3,  # bin emptied events (closes the loop to the IoT layer)
}

# Consumer groups
GROUPS = {
    "stream": "wastex-stream-processor",
    "jev": "wastex-jev-orchestrator",
    "fleet": "wastex-fleet-simulator",
    "iot": "wastex-iot-gateway",
    "ui": "wastex-dashboard-bridge",
}

# Stream processing
FILL_RATE_WINDOW = 10          # readings used for the sliding-window fill-rate regression
ZONE_WINDOW_MINUTES = 5        # tumbling window size (simulated minutes)

# Agents
PLANNING_INTERVAL_MIN = 5      # JEV runs a full planning cycle every N simulated minutes
CRITICAL_FILL = 95.0
HIGH_THRESHOLD = 0.65
MEDIUM_THRESHOLD = 0.45
MAX_REPLAN_ATTEMPTS = 3

# Road model
ROAD_CIRCUITY = 1.35           # road distance ~= 1.35 x great-circle distance (urban grid)
SERVICE_MIN_PER_BIN = 3.0      # minutes to empty one bin
UNLOAD_MIN = 15.0              # minutes to unload at a processing plant
DISPOSE_AT = 0.75              # truck heads to a processing plant once this full
DIESEL_KG_CO2_PER_KM = 0.95    # heavy-duty municipal truck emission factor
