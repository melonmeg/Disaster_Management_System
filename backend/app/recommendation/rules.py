"""Configurable knowledge used by the deterministic recommender.

The database stores only a free-text `units.unit_type` and `incidents.incident_type`;
it does not record which unit types suit which incident. The mapping below is therefore
an explicit, editable HEURISTIC (not learned from data and not validated statistically).
An incident whose type matches no rule gets capability = unknown, and is never treated
as a capability match.
"""
from ..config import settings

ALGORITHM_VERSION = "rules-v1"

# keyword in incident_type (lower-case) -> unit types that fit best / can support.
CAPABILITY_RULES = [
    {"keywords": ("fire", "explosion", "gas leak"),
     "primary": ("Fire Truck",), "supporting": ("Rescue Vehicle", "Ambulance", "Police Car"),
     "resource_types": ("Firefighting Equipment", "Power Equipment")},
    {"keywords": ("medical", "cardiac", "injur", "overdose"),
     "primary": ("Ambulance",), "supporting": ("Rescue Vehicle",),
     "resource_types": ("Medical Supply",)},
    {"keywords": ("accident", "collision", "crash"),
     "primary": ("Ambulance", "Police Car"), "supporting": ("Rescue Vehicle", "Fire Truck"),
     "resource_types": ("Medical Supply",)},
    {"keywords": ("rescue", "flood", "collapse", "trapped"),
     "primary": ("Rescue Vehicle",), "supporting": ("Fire Truck", "Ambulance"),
     "resource_types": ("Power Equipment", "Medical Supply")},
    {"keywords": ("robbery", "theft", "assault", "disturbance", "crime"),
     "primary": ("Police Car",), "supporting": (),
     "resource_types": ()},
]

DEFAULT_WEIGHTS = {"capability": 0.5, "availability": 0.2, "distance": 0.2, "resources": 0.1}


def weights() -> dict[str, float]:
    """RECO_WEIGHTS="capability=0.5,distance=0.3,..." overrides the defaults."""
    result = dict(DEFAULT_WEIGHTS)
    for part in filter(None, (p.strip() for p in settings.reco_weights.split(","))):
        key, _, value = part.partition("=")
        if key.strip() in result:
            result[key.strip()] = float(value)
    if any(v < 0 for v in result.values()) or sum(result.values()) <= 0:
        raise ValueError("RECO_WEIGHTS must be non-negative with a positive sum")
    return result


def rule_for(incident_type: str) -> dict | None:
    text = incident_type.lower()
    return next((r for r in CAPABILITY_RULES if any(k in text for k in r["keywords"])), None)
