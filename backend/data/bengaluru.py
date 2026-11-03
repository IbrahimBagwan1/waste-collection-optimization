"""
Real Bengaluru reference data used by WASTEX.

Sources (as listed in the SPA Lab presentation):
  * Dry Waste Collection Centres (DWCC)        -> BBMP / OpenCity
  * Waste processing plants + capacity (TPD)   -> BBMP SWM statistics via OpenCity
  * Landfill coordinates                        -> BBMP landfill registry
  * Ward-level garbage complaints               -> BBMP official stats via OpenCity

Live bin telemetry is synthetic (see simulator/iot.py) but every bin is
anchored to a real Bengaluru ward centroid so the geography is realistic.
"""

# --------------------------------------------------------------------------
# Dry Waste Collection Centres (slide 4) - also used as truck depots
# --------------------------------------------------------------------------
DRY_WASTE_CENTRES = [
    {"id": "DWCC01", "name": "Kempegowda", "lat": 13.10928, "lon": 77.576778},
    {"id": "DWCC02", "name": "Doddabommasandra", "lat": 13.06894, "lon": 77.563879},
    {"id": "DWCC03", "name": "Jakkur", "lat": 13.072449, "lon": 77.630249},
    {"id": "DWCC04", "name": "Hebbal", "lat": 13.036574, "lon": 77.597274},
    {"id": "DWCC05", "name": "Koramangala", "lat": 12.934294, "lon": 77.61465},
    {"id": "DWCC06", "name": "HSR Layout", "lat": 12.91263, "lon": 77.649028},
    {"id": "DWCC07", "name": "JP Nagar", "lat": 12.91651, "lon": 77.599874},
    {"id": "DWCC08", "name": "Kengeri", "lat": 12.91477, "lon": 77.481763},
    {"id": "DWCC09", "name": "Bellandur", "lat": 12.912793, "lon": 77.676734},
    {"id": "DWCC10", "name": "Kadugodi", "lat": 12.99371, "lon": 77.759137},
    {"id": "DWCC11", "name": "K R Puram", "lat": 13.018675, "lon": 77.70366},
    {"id": "DWCC12", "name": "Yelahanka Satellite Town", "lat": 13.094001, "lon": 77.578976},
]

# Truck depots = a subset of DWCCs spread across the city
DEPOTS = [
    {"id": "DEPOT-N", "name": "Hebbal Depot", "dwcc": "DWCC04", "lat": 13.036574, "lon": 77.597274},
    {"id": "DEPOT-S", "name": "Koramangala Depot", "dwcc": "DWCC05", "lat": 12.934294, "lon": 77.61465},
    {"id": "DEPOT-E", "name": "K R Puram Depot", "dwcc": "DWCC11", "lat": 13.018675, "lon": 77.70366},
    {"id": "DEPOT-W", "name": "JP Nagar Depot", "dwcc": "DWCC07", "lat": 12.91651, "lon": 77.599874},
]

# --------------------------------------------------------------------------
# Waste processing plants (slides 5 + 8). Capacity / intake in tonnes per day.
# --------------------------------------------------------------------------
PROCESSING_PLANTS = [
    {"id": "PLT1", "name": "Seegehalli SWM Facility", "area": "Seegehalli", "lat": 12.97386, "lon": 77.441004,
     "mixed_tpd": 200, "wet_tpd": 120, "intake_tpd": 70},
    {"id": "PLT2", "name": "Kannahalli Waste Processing Unit", "area": "Kannahalli", "lat": 12.968195, "lon": 77.444193,
     "mixed_tpd": 500, "wet_tpd": 350, "intake_tpd": 40},
    {"id": "PLT3", "name": "Doddabidarakallu Waste Processing Plant", "area": "Dodda Bidarakallu", "lat": 13.031319,
     "lon": 77.479684, "mixed_tpd": 200, "wet_tpd": 150, "intake_tpd": 150},
    {"id": "PLT4", "name": "Subbarayanapalya Waste Processing Plant", "area": "Subbarayanapalya", "lat": 12.882866,
     "lon": 77.430853, "mixed_tpd": 200, "wet_tpd": 150, "intake_tpd": 50},
    {"id": "PLT5", "name": "Lingadeeranahalli Waste Processing Unit", "area": "Hemmigepura", "lat": 12.875929,
     "lon": 77.506767, "mixed_tpd": 200, "wet_tpd": 150, "intake_tpd": 90},
    {"id": "PLT6", "name": "KCDC (Karnataka Compost Development Corp.)", "area": "Mangammanapalya", "lat": 12.896044,
     "lon": 77.649861, "mixed_tpd": 500, "wet_tpd": 350, "intake_tpd": 80},
    {"id": "PLT7", "name": "Chikkanagamangala Waste Processing Plant", "area": "Chikkanagamangala", "lat": 12.857962,
     "lon": 77.686032, "mixed_tpd": 500, "wet_tpd": 300, "intake_tpd": 170},
    {"id": "PLT8", "name": "Mavallipura Waste Processing Plant", "area": "Mavallipura", "lat": 13.122286,
     "lon": 77.540021, "mixed_tpd": 0, "wet_tpd": 0, "intake_tpd": 0},  # closed - 0 capacity
]

# MSGP has capacity data (slide 8) but no coordinates in the dataset -> EDA only
MSGP_PLANT = {"name": "MSGP", "mixed_tpd": 600, "wet_tpd": None, "intake_tpd": 500}

# --------------------------------------------------------------------------
# Landfills (slide 6)
# --------------------------------------------------------------------------
LANDFILLS = [
    {"id": "LF1", "name": "Outside BBMP (Village 15317)", "ward": "-", "lat": 13.1539417, "lon": 77.6688778},
    {"id": "LF2", "name": "Jakkur Landfill A (Village 15422)", "ward": "5", "lat": 13.10395, "lon": 77.6464667},
    {"id": "LF3", "name": "Jakkur Landfill B (Village 15422)", "ward": "5", "lat": 13.1035833, "lon": 77.6459222},
]

# --------------------------------------------------------------------------
# Wards / collection zones. `complaints` = BBMP ward complaint records (slide 7)
# where available; `base_rate` = typical fill rate (%/min) calibrated so that,
# with the daily demand curve and per-bin variation, peak-hour rates fall in the
# 0.2 - 0.6 %/min range seen in the zone EDA (slide 9; Indiranagar is the hotspot).
# --------------------------------------------------------------------------
ZONES = [
    {"id": "Z01", "name": "Indiranagar", "ward": 80, "lat": 12.9719, "lon": 77.6412, "complaints": 96, "base_rate": 0.21, "type": "commercial"},
    {"id": "Z02", "name": "Koramangala", "ward": 151, "lat": 12.9352, "lon": 77.6245, "complaints": 74, "base_rate": 0.15, "type": "mixed"},
    {"id": "Z03", "name": "Whitefield", "ward": 84, "lat": 12.9698, "lon": 77.7500, "complaints": 81, "base_rate": 0.17, "type": "it-park"},
    {"id": "Z04", "name": "Bellandur", "ward": 150, "lat": 12.9260, "lon": 77.6762, "complaints": 152, "base_rate": 0.19, "type": "residential"},
    {"id": "Z05", "name": "Banaswadi", "ward": 27, "lat": 13.0104, "lon": 77.6482, "complaints": 128, "base_rate": 0.165, "type": "residential"},
    {"id": "Z06", "name": "Benniganahalli", "ward": 50, "lat": 12.9925, "lon": 77.6620, "complaints": 52, "base_rate": 0.13, "type": "residential"},
    {"id": "Z07", "name": "HSR Layout", "ward": 174, "lat": 12.9116, "lon": 77.6389, "complaints": 63, "base_rate": 0.145, "type": "residential"},
    {"id": "Z08", "name": "JP Nagar", "ward": 177, "lat": 12.9063, "lon": 77.5857, "complaints": 47, "base_rate": 0.12, "type": "residential"},
    {"id": "Z09", "name": "Jayanagar", "ward": 169, "lat": 12.9293, "lon": 77.5826, "complaints": 58, "base_rate": 0.155, "type": "market"},
    {"id": "Z10", "name": "Malleshwaram", "ward": 45, "lat": 13.0035, "lon": 77.5647, "complaints": 44, "base_rate": 0.135, "type": "market"},
    {"id": "Z11", "name": "Hebbal", "ward": 21, "lat": 13.0450, "lon": 77.5950, "complaints": 39, "base_rate": 0.11, "type": "mixed"},
    {"id": "Z12", "name": "Yelahanka", "ward": 4, "lat": 13.1007, "lon": 77.5963, "complaints": 33, "base_rate": 0.1, "type": "residential"},
    {"id": "Z13", "name": "K R Puram", "ward": 52, "lat": 13.0076, "lon": 77.6960, "complaints": 70, "base_rate": 0.16, "type": "mixed"},
    {"id": "Z14", "name": "Rajajinagar", "ward": 99, "lat": 12.9900, "lon": 77.5530, "complaints": 41, "base_rate": 0.125, "type": "residential"},
]

# What residents report (slide 7) - used in the Insights page
COMPLAINT_THEMES = [
    {"rank": 1, "title": "Waste gets cleared but comes back", "detail": "Most common issue in the dataset"},
    {"rank": 2, "title": "Waste is never cleared", "detail": "Reported across several areas"},
    {"rank": 3, "title": "BBMP sweepers dumping waste", "detail": "Also: garbage burning, BBMP autos/pushcarts parked at dump sites"},
]

# Fixed BBMP collection schedule (slide 2) - used as the baseline strategy
FIXED_SCHEDULE = [
    {"days": "Monday - Friday", "window": "07:30 - 09:00"},
    {"days": "Monday - Friday", "window": "18:00 - 19:30"},
    {"days": "Saturday - Sunday", "window": "07:30 - 09:00"},
    {"days": "Saturday - Sunday", "window": "18:00 - 19:30"},
]

# Bin types: capacity in litres and max weight (kg) at 100 % fill.
BIN_TYPES = {
    "SMART-240": {"litres": 240, "max_kg": 60},
    "SMART-1100": {"litres": 1100, "max_kg": 260},
    "COMMUNITY-3200": {"litres": 3200, "max_kg": 720},
}

# Fleet (slide 16: mix of 5T and 2T trucks)
FLEET = [
    {"id": "TRUCK-01", "type": "Compactor", "capacity_kg": 5000, "depot": "DEPOT-S"},
    {"id": "TRUCK-02", "type": "Tipper", "capacity_kg": 2000, "depot": "DEPOT-S"},
    {"id": "TRUCK-03", "type": "Compactor", "capacity_kg": 5000, "depot": "DEPOT-N"},
    {"id": "TRUCK-04", "type": "Tipper", "capacity_kg": 2000, "depot": "DEPOT-N"},
    {"id": "TRUCK-05", "type": "Compactor", "capacity_kg": 5000, "depot": "DEPOT-E"},
    {"id": "TRUCK-06", "type": "Tipper", "capacity_kg": 2000, "depot": "DEPOT-E"},
    {"id": "TRUCK-07", "type": "Compactor", "capacity_kg": 5000, "depot": "DEPOT-W"},
    {"id": "TRUCK-08", "type": "Mini Tipper", "capacity_kg": 1200, "depot": "DEPOT-W"},
]
