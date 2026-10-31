"""Check your Mappls key and see exactly what the geocode API returns for an address.

    python scripts/mappls_probe.py "Connaught Place, New Delhi"

Prints the HTTP status and the JSON body (the key is never printed), then how the app interprets it.
If it says "no coordinates", paste the printed JSON (it contains no secrets) so the parser can be adjusted.
"""
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings  # noqa: E402
from app.geocoding import GeocoderError, parse_mappls  # noqa: E402

address = " ".join(sys.argv[1:]) or "Connaught Place, New Delhi"
if not settings.mappls_api_key:
    sys.exit("MAPPLS_API_KEY is not set in backend/.env")
params = {"address": address, "itemCount": 3, "access_token": settings.mappls_api_key}
if settings.mappls_region:
    params["region"] = settings.mappls_region
res = httpx.get(settings.mappls_geocode_url, params=params, timeout=15)
print("HTTP", res.status_code)
try:
    body = res.json()
    print(json.dumps(body, indent=2)[:4000])
except ValueError:
    print(res.text[:500])
    sys.exit(1)
try:
    print("Interpreted as:", parse_mappls(body))
except GeocoderError as exc:
    print("Interpreted as error:", exc)
