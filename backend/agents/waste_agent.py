"""
Agent 1 - Waste Intelligence  ("WHAT needs attention?")

Inputs  : fill level, fill rate (%/min from the stream processor), history
          (ward complaint records), live anomalies.
Output  : a priority score in [0, 1] and a class HIGH (collect) / MEDIUM
          (monitor) / LOW (ignore) with a human-readable justification.

Score = 0.35*fill + 0.35*urgency + 0.15*rate + 0.15*history (+ anomaly boost)
  urgency = 1 when the bin will overflow within 60 min (a truck needs time to
  reach it), falling linearly to 0 at 240 min.
Growth rate matters, not level alone (EDA slide 9): a 78 % bin filling fast is
HIGH while a 92 % bin filling slowly is only MEDIUM.
"""
from .. import config
from ..data.bengaluru import ZONES

MAX_COMPLAINTS = max(z["complaints"] for z in ZONES)
HISTORY = {z["id"]: z["complaints"] / MAX_COMPLAINTS for z in ZONES}
URGENT_ETA = 60.0
HORIZON_ETA = 240.0
OPPORTUNISTIC_FILL = 55.0


class WasteIntelligenceAgent:
    name = "Waste Intelligence Agent"

    def score(self, b: dict) -> dict:
        fill = b["fill_level"]
        rate = b.get("rate_per_min") or 0.0
        eta = b.get("eta_min")
        if fill >= 100:
            eta = 0.0
        if eta is None:
            urgency = 0.0
        elif eta <= URGENT_ETA:
            urgency = 1.0
        else:
            urgency = max(0.0, 1 - (eta - URGENT_ETA) / (HORIZON_ETA - URGENT_ETA))
        rate_n = min(rate / 0.5, 1.0)
        hist = HISTORY.get(b["zone_id"], 0.3)
        score = 0.35 * fill / 100 + 0.35 * urgency + 0.15 * rate_n + 0.15 * hist
        reasons = []
        anomalies = b.get("anomalies") or []
        if "FIRE" in anomalies:
            score = max(score + 0.35, 0.85)  # garbage burning: always dispatch
            reasons.append("fire risk")
        if fill >= config.CRITICAL_FILL:
            score = max(score, 0.9)
            reasons.append(f"critical fill {fill:.0f}%")
        score = min(score, 1.0)

        if score >= config.HIGH_THRESHOLD:
            pri = "HIGH"
        elif score >= config.MEDIUM_THRESHOLD:
            pri = "MEDIUM"
        else:
            pri = "LOW"
        speed = "FAST" if rate >= 0.4 else ("MODERATE" if rate >= 0.2 else "SLOW")
        if not reasons:
            reasons.append(f"{fill:.0f}% · {speed} {rate * 60:.0f}%/hr")
        if eta is not None and eta < 999:
            reasons.append(f"overflow in ~{eta:.0f} min")
        return {
            "bin_id": b["bin_id"], "zone": b["zone"], "zone_id": b["zone_id"],
            "lat": b["lat"], "lon": b["lon"], "fill_level": fill, "rate_per_min": rate,
            "eta_min": eta, "weight_kg": b.get("weight_kg", 0), "max_kg": b.get("max_kg", 0),
            "score": round(score, 3), "priority": pri, "speed": speed,
            "components": {"fill": round(fill / 100, 3), "urgency": round(urgency, 3),
                           "rate": round(rate_n, 3), "history": round(hist, 3)},
            "reason": ", ".join(reasons),
        }

    def assess(self, bins: dict, exclude=frozenset()):
        """Rank every bin not already scheduled for collection."""
        out = [self.score(b) for bid, b in bins.items() if bid not in exclude]
        out.sort(key=lambda x: -x["score"])
        summary = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for a in out:
            summary[a["priority"]] += 1
        return out, summary

    @staticmethod
    def opportunistic(assessed):
        """Bins worth emptying if a truck is already nearby: MEDIUM, or LOW but >= 55 % full."""
        return [a for a in assessed if a["priority"] == "MEDIUM"
                or (a["priority"] == "LOW" and a["fill_level"] >= OPPORTUNISTIC_FILL)]
