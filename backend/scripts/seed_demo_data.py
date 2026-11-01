"""Replace the operational data of the REAL database with a realistic Bengaluru scenario that shows up on the map.

    python scripts/seed_demo_data.py --yes

What it does
  1. Looks up every incident location and unit base on OpenStreetMap (Nominatim), BEFORE touching anything.
     A location that cannot be found, is only a district/city centre, or lies outside Bengaluru stops the run.
     Coordinates are never invented: they come from that lookup and are stored in geocode_cache as RESOLVED.
  2. Backs up the current rows (JSON, in backend/backups/; app_users and password hashes are NOT included) and the two
     MongoDB collections that point at MySQL ids (recommendation_history, call_transcripts), then empties those
     collections because the old ids no longer exist.
  3. Empties incidents, calls, dispatches, resources, patients, activity_logs and geocode_cache, replaces organizations,
     units and responders, and re-creates the scenario THROUGH THE REAL TRIGGERS (so stock, unit status and the activity
     log are consistent). Session TIMESTAMP is set before each event so the triggers stamp the right times.
  4. Keeps app_users and responders 1 (dispatcher Aarav Sharma) and 2 (Diya Nair): the three logins still work.

Dates are relative to the moment you run it (open incidents are minutes to hours old, resolved ones up to a week old).
Names, phone numbers and e-mail addresses are fictitious. Place names and coordinates are real (OpenStreetMap data,
(c) OpenStreetMap contributors, ODbL). The original sample-data SQL files are not changed and the test database is
not touched.
"""
import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_db import admin_connection  # noqa: E402  (also loads backend/.env)

BBOX = (12.80, 13.20, 77.40, 77.85)            # Bengaluru: lat_min, lat_max, lon_min, lon_max
COARSE_TYPES = {"city", "town", "village", "suburb", "state", "district", "county", "administrative", "neighbourhood"}
UA = "ERMS-college-dbms-demo/1.0 (student project)"

# DB location text -> (OpenStreetMap search text, substring the result's name must contain)
PLACES = {
    # unit bases
    "Cubbon Park Police Station, Kasturba Road, Bengaluru": ("Cubbon Park Police Station, Bengaluru", "Cubbon Park Police"),
    "Jayanagar 4th Block Police Station, Bengaluru": ("Jayanagar Police Station, Bengaluru", "Jayanagar"),
    "Hebbal Police Station, 3rd Main Road, Bengaluru": ("Hebbal Police Station, Bengaluru", "Hebbal Police"),
    "Whitefield Police Station, Whitefield Main Road, Bengaluru": ("Whitefield Police Station, Bengaluru", "Whitefield Police"),
    "Hebbal Fire Station, Bengaluru": ("Hebbal Fire Station, Bengaluru", "Hebbal Fire"),
    "Whitefield Fire Station, Hoodi, Bengaluru": ("Whitefield Fire Station, Bengaluru", "Whitefield Fire"),
    "Fire Station, Nelamangala - Majestic Service Road, Bengaluru": ("Fire Station, Bengaluru", "Fire Station"),
    "St. John's Medical College Hospital, Sarjapur Road, Bengaluru": ("St. John's Medical College Hospital, Bengaluru", "John"),
    "Manipal Hospital, Old Airport Road, Bengaluru": ("Manipal Hospital, Old Airport Road, Bengaluru", "Manipal"),
    "Sparsh Hospital, Tumkur Road, Bengaluru": ("Sparsh Hospital, Bengaluru", "Sparsh"),
    # incident locations
    "KR Market, Kalasipalya, Bengaluru": ("KR Market, Bengaluru", "KR Market"),
    "Silk Board Junction, Hosur Road, Bengaluru": ("Silk Board Junction, Bengaluru", "Silk Board"),
    "100 Feet Road, Indiranagar, Bengaluru": ("100 Feet Road, Indiranagar, Bengaluru", "100 Feet Road"),
    "Commercial Street, Shivajinagar, Bengaluru": ("Commercial Street, Bengaluru", "Commercial Street"),
    "Marathahalli Bridge, Varthur Road, Bengaluru": ("Marathahalli Bridge, Bengaluru", "Marathahalli"),
    "Hebbal Flyover, Bengaluru": ("Hebbal Flyover, Bengaluru", "Hebbal"),
    "Lalbagh Botanical Garden, Bengaluru": ("Lalbagh Botanical Gardens, Bengaluru", "Lalbagh"),
    "Electronic City Flyover, Phase 1, Bengaluru": ("Electronic City Phase 1, Bengaluru", "Electronic"),
    "Kempegowda Bus Station, Bengaluru": ("Kempegowda Bus Station, Bengaluru", "Kempegowda"),
    "Yeshwanthpur Railway Station, Bengaluru": ("Yeshwanthpur Railway Station, Bengaluru", "Yeshwanthpur"),
    "Mekhri Circle, Bellary Road, Bengaluru": ("Mekhri Circle, Bengaluru", "Mekhri"),
    "Cubbon Park, Bengaluru": ("Cubbon Park, Bengaluru", "Cubbon Park"),
    "MG Road Metro Station, Bengaluru": ("MG Road Metro Station, Bengaluru", "MG Road"),
    "Majestic Metro Station, Bengaluru": ("Majestic Metro Station, Bengaluru", "Kempegowda"),
}
CP, JP, HP, WP = ("Cubbon Park Police Station, Kasturba Road, Bengaluru", "Jayanagar 4th Block Police Station, Bengaluru",
                  "Hebbal Police Station, 3rd Main Road, Bengaluru", "Whitefield Police Station, Whitefield Main Road, Bengaluru")
HF, WF, NF = ("Hebbal Fire Station, Bengaluru", "Whitefield Fire Station, Hoodi, Bengaluru",
              "Fire Station, Nelamangala - Majestic Service Road, Bengaluru")
SJ, MH, SP = ("St. John's Medical College Hospital, Sarjapur Road, Bengaluru", "Manipal Hospital, Old Airport Road, Bengaluru",
              "Sparsh Hospital, Tumkur Road, Bengaluru")

ORGS = [(1, "Bengaluru City Police", "Bengaluru"), (2, "Karnataka Fire and Emergency Services", "Bengaluru"),
        (3, "Bengaluru Emergency Medical Services", "Bengaluru")]
UNITS = [  # id, name, type, status, base, org
    (1, "Police Unit 12", "Police Car", "AVAILABLE", CP, 1), (2, "Fire Engine 04", "Fire Truck", "AVAILABLE", HF, 2),
    (3, "Ambulance 07", "Ambulance", "AVAILABLE", SJ, 3), (4, "Rescue Unit 02", "Rescue Vehicle", "AVAILABLE", NF, 2),
    (5, "Police Unit 15", "Police Car", "AVAILABLE", JP, 1), (6, "Police Unit 21", "Police Car", "AVAILABLE", HP, 1),
    (7, "Police Unit 33", "Police Car", "AVAILABLE", WP, 1), (8, "Fire Engine 11", "Fire Truck", "AVAILABLE", WF, 2),
    (9, "Fire Engine 02", "Fire Truck", "AVAILABLE", NF, 2), (10, "Ambulance 12", "Ambulance", "AVAILABLE", MH, 3),
    (11, "Ambulance 19", "Ambulance", "AVAILABLE", SP, 3), (12, "Ambulance 03", "Ambulance", "OUT_OF_SERVICE", SJ, 3),
]
# responders 1 and 2 already exist (linked to logins) and are updated in place; the rest are inserted
RESPONDERS = [  # id, first, middle, last, phone, email, type, availability, org, unit
    (3, "Meera", None, "Krishnan", "9845012303", "meera.krishnan@example.com", "Dispatcher", "AVAILABLE", 1, None),
    (4, "Rahul", None, "Verma", "9845012304", "rahul.verma@example.com", "Police Officer", "AVAILABLE", 1, 1),
    (5, "Suresh", None, "Gowda", "9845012305", "suresh.gowda@example.com", "Police Officer", "ON_DUTY", 1, 5),
    (6, "Pooja", None, "Hegde", "9845012306", "pooja.hegde@example.com", "Police Officer", "ON_DUTY", 1, 5),
    (7, "Imran", None, "Pasha", "9845012307", "imran.pasha@example.com", "Police Officer", "AVAILABLE", 1, 6),
    (8, "Kavita", None, "Reddy", "9845012308", "kavita.reddy@example.com", "Police Officer", "AVAILABLE", 1, 7),
    (9, "Kabir", None, "Rao", "9845012309", "kabir.rao@example.com", "Firefighter", "AVAILABLE", 2, 2),
    (10, "Ishaan", None, "Patel", "9845012310", "ishaan.patel@example.com", "Firefighter", "AVAILABLE", 2, 2),
    (11, "Manjunath", None, "Shetty", "9845012311", "manjunath.shetty@example.com", "Firefighter", "ON_DUTY", 2, 9),
    (12, "Lakshmi", None, "Narayan", "9845012312", "lakshmi.narayan@example.com", "Firefighter", "ON_DUTY", 2, 9),
    (13, "Arjun", None, "Das", "9845012313", "arjun.das@example.com", "Firefighter", "ON_DUTY", 2, 8),
    (14, "Faisal", None, "Khan", "9845012314", "faisal.khan@example.com", "Firefighter", "ON_DUTY", 2, 8),
    (15, "Deepak", "K", "Murthy", "9845012315", "deepak.murthy@example.com", "Rescue Technician", "ON_DUTY", 2, 4),
    (16, "Nandini", None, "Rao", "9845012316", "nandini.rao@example.com", "Rescue Technician", "ON_DUTY", 2, 4),
    (17, "Ananya", "S", "Iyer", "9845012317", "ananya.iyer@example.com", "Paramedic", "ON_DUTY", 3, 3),
    (18, "Rohit", None, "Menon", "9845012318", "rohit.menon@example.com", "Paramedic", "ON_DUTY", 3, 3),
    (19, "Sneha", None, "Pillai", "9845012319", "sneha.pillai@example.com", "Paramedic", "ON_DUTY", 3, 10),
    (20, "Vijay", None, "Anand", "9845012320", "vijay.anand@example.com", "Paramedic", "ON_DUTY", 3, 10),
    (21, "Farah", None, "Siddiqui", "9845012321", "farah.siddiqui@example.com", "Paramedic", "AVAILABLE", 3, 11),
    (22, "Prakash", None, "Naik", "9845012322", "prakash.naik@example.com", "Paramedic", "AVAILABLE", 3, 11),
    (23, "Tanvi", None, "Joshi", "9845012323", "tanvi.joshi@example.com", "Paramedic", "OFF_DUTY", 3, 12),
]
RESOURCES = [  # id, name, type, total, location, org
    (1, "Oxygen Cylinder", "Medical Supply", 24, SJ, 3), (2, "First Aid Kit", "Medical Supply", 30, SJ, 3),
    (3, "Defibrillator (AED)", "Medical Supply", 8, MH, 3), (4, "Stretcher", "Medical Supply", 10, SJ, 3),
    (5, "Trauma Kit", "Medical Supply", 12, SP, 3), (6, "Fire Extinguisher (9 kg ABC)", "Firefighting Equipment", 40, HF, 2),
    (7, "Thermal Imaging Camera", "Firefighting Equipment", 4, NF, 2), (8, "Portable Generator", "Power Equipment", 6, NF, 2),
    (9, "Portable Water Pump", "Power Equipment", 8, HF, 2), (10, "Hydraulic Rescue Tool Set", "Power Equipment", 3, NF, 2),
    (11, "Traffic Barricade Set", "Traffic Control", 20, CP, 1), (12, "First Aid Kit (Patrol)", "Medical Supply", 15, CP, 1),
]
OXY, FAK, AED, STR, TRA, EXT, THC, GEN, PMP, HYD, BAR, FKP = range(1, 13)


# ------------------------------------------------------------------ the scenario
def build_events(now: datetime):
    ev: list = []

    def at(t, fn):
        assert t <= now, f"event in the future: {t}"
        ev.append((t, len(ev), fn))

    m = lambda n: timedelta(minutes=n)          # noqa: E731

    def incident(key, itype, sev, loc, created, calls, dispatches=(), patients=(), resolve=None, close=None, notes=()):
        def create(cur, ctx):
            cur.execute("INSERT INTO incidents (incident_type, severity, location, status, created_at) VALUES (%s,%s,%s,'OPEN',%s)",
                        (itype, sev, loc, created))
            ctx[key] = cur.lastrowid
        at(created, create)

        for n, (off, recv, name, phone, prio, status, text) in enumerate(calls):
            def add_call(cur, ctx, off=off, recv=recv, name=name, phone=phone, prio=prio, status=status, text=text):
                cur.execute("INSERT INTO calls (received_by, status, transcript, received_at, caller_name, priority, caller_phone, "
                            "location, incident_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (recv, status, text, created + m(off), name, prio, phone, loc, ctx[key]))
            at(created + m(off), add_call)

        for d in dispatches:
            unit, off, route, scene, done, res = d["unit"], d["at"], d["route"], d.get("scene"), d.get("done"), d.get("res", ())
            t0 = created + m(off)
            holder = {}

            def dispatch(cur, ctx, unit=unit, t0=t0, holder=holder):
                cur.execute("INSERT INTO dispatches (incident_id, unit_id, dispatched_at, status) VALUES (%s,%s,%s,'DISPATCHED')",
                            (ctx[key], unit, t0))
                holder["id"] = cur.lastrowid
            at(t0, dispatch)
            for rid, qty in res:
                def alloc(cur, ctx, rid=rid, qty=qty, holder=holder):
                    cur.execute("INSERT INTO dispatch_resources (dispatch_id, resource_id, quantity_assigned) VALUES (%s,%s,%s)",
                                (holder["id"], rid, qty))
                at(t0 + m(1), alloc)

            def step(status, holder=holder):
                def go(cur, ctx):
                    cur.execute("UPDATE dispatches SET status=%s WHERE dispatch_id=%s", (status, holder["id"]))
                return go
            t = t0 + m(route)
            at(t, step("EN_ROUTE"))
            if scene is not None:
                t += m(scene)
                at(t, step("ON_SCENE"))
            if done is not None:
                t += m(done)

                def finish(cur, ctx, holder=holder):
                    cur.execute("UPDATE dispatch_resources SET quantity_returned = quantity_assigned WHERE dispatch_id=%s", (holder["id"],))
                    cur.execute("UPDATE dispatches SET status='COMPLETED' WHERE dispatch_id=%s", (holder["id"],))
                at(t, finish)

        for n, (off, name, age, gender, cond) in enumerate(patients, 1):
            def add_patient(cur, ctx, n=n, off=off, name=name, age=age, gender=gender, cond=cond):
                cur.execute("INSERT INTO incident_patients (incident_id, patient_no, patient_name, age, gender, patient_condition, created_at) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s)", (ctx[key], n, name, age, gender, cond, created + m(off)))
            at(created + m(off), add_patient)

        for off, text in notes:
            def add_note(cur, ctx, text=text, off=off):
                cur.execute("INSERT INTO activity_logs (incident_id, action, action_time) VALUES (%s,%s,%s)", (ctx[key], text, created + m(off)))
            at(created + m(off), add_note)

        if resolve is not None:
            def do_resolve(cur, ctx, t=created + m(resolve)):
                cur.execute("UPDATE incidents SET status='RESOLVED', resolved_at=%s WHERE incident_id=%s", (t, ctx[key]))
            at(created + m(resolve), do_resolve)
        if close is not None:
            def do_close(cur, ctx):
                cur.execute("UPDATE incidents SET status='CLOSED' WHERE incident_id=%s", (ctx[key],))
            at(created + m(close), do_close)

    D1, D3 = 1, 3                                   # dispatchers who took the calls
    ago = lambda **kw: now - timedelta(**kw)        # noqa: E731

    # ---- resolved earlier in the week -------------------------------------------------------------
    incident("i14", "Medical Emergency", "LOW", "MG Road Metro Station, Bengaluru", ago(days=6, hours=1),
             [(0, D3, "Karthik Subramanian", "9886100114", "LOW", "CLOSED", "Commuter felt faint on the platform concourse; conscious and talking, no chest pain.")],
             [dict(unit=10, at=6, route=2, scene=9, done=35, res=[(FAK, 1)])],
             [(12, "Karthik Subramanian", 31, "Male", "Dehydration; recovered on scene")], resolve=60, close=300)
    incident("i13", "Grass Fire", "LOW", "Cubbon Park, Bengaluru", ago(days=5, hours=4),
             [(0, D1, "Padma Raghavan", "9886100113", "LOW", "CLOSED", "Dry grass burning near the walking track, spreading slowly towards the bamboo grove.")],
             [dict(unit=2, at=10, route=3, scene=14, done=40, res=[(EXT, 2)])], resolve=70, close=1500)
    incident("i12", "Wall Collapse - Rescue", "MEDIUM", "Mekhri Circle, Bellary Road, Bengaluru", ago(days=4, hours=2),
             [(0, D1, "Gurpreet Singh", "9886100112", "HIGH", "CLOSED", "Compound wall of an under-construction site has fallen onto the service road; a worker may be trapped.")],
             [dict(unit=4, at=8, route=2, scene=18, done=110, res=[(HYD, 1), (PMP, 1)]),
              dict(unit=3, at=9, route=2, scene=12, done=60, res=[(STR, 1), (FAK, 1)])],
             [(25, "Mahesh Y", 36, "Male", "Leg injury; freed after 40 minutes"), (30, "Santosh B", 29, "Male", "Minor cuts")],
             resolve=140, close=420)
    incident("i11", "Medical Emergency", "HIGH", "Yeshwanthpur Railway Station, Bengaluru", ago(days=3, hours=5),
             [(0, D3, "Anitha Raman", "9886100111", "HIGH", "CLOSED", "Elderly passenger collapsed on platform 2 complaining of chest pain and sweating.")],
             [dict(unit=11, at=4, route=1, scene=11, done=45, res=[(OXY, 1), (AED, 1)])],
             [(16, "Mohan Lal", 67, "Male", "Chest pain; stabilised, referred to hospital")], resolve=65)
    incident("i10", "Assault", "MEDIUM", "Kempegowda Bus Station, Bengaluru", ago(days=2, hours=3),
             [(0, D1, "Bus conductor (anonymous)", None, "MEDIUM", "CLOSED", "Fight between two groups near the platform entrance; one man has a bleeding lip.")],
             [dict(unit=1, at=5, route=1, scene=10, done=32)], resolve=52)
    incident("i9", "Road Accident", "HIGH", "Hebbal Flyover, Bengaluru", ago(hours=28),
             [(0, D3, "Rakesh Gowda", "9886100109", "HIGH", "CLOSED", "Car hit the divider on the Hebbal flyover; driver not responding, second passenger trapped in the back seat.")],
             [dict(unit=11, at=4, route=1, scene=10, done=55, res=[(TRA, 2), (STR, 1)]),
              dict(unit=6, at=5, route=2, scene=9, done=50, res=[(BAR, 6)])],
             [(18, "Ajay Nair", 41, "Male", "Head injury; shifted to Sparsh Hospital"), (19, "Deepa S", 27, "Female", "Minor injuries")],
             resolve=72)
    incident("i8", "Vehicle Fire", "MEDIUM", "Electronic City Flyover, Phase 1, Bengaluru", ago(hours=13, minutes=13),
             [(0, D1, "Sunil Kamath", "9886100108", "MEDIUM", "CLOSED", "A parked SUV is on fire at the foot of the flyover; no one inside, traffic slowing down.")],
             [dict(unit=8, at=6, route=2, scene=16, done=46, res=[(EXT, 2)])], resolve=75)
    # ---- earlier today ------------------------------------------------------------------------------
    incident("i7", "Medical Emergency", "MEDIUM", "Lalbagh Botanical Garden, Bengaluru", ago(hours=3),
             [(0, D1, "Garden security guard", "9886100107", "MEDIUM", "PROCESSED", "Morning walker has chest discomfort and dizziness near the glass house; sitting down, conscious.")],
             [dict(unit=3, at=5, route=1, scene=9, done=40, res=[(OXY, 1)])],
             [(14, "Venkatesh P", 58, "Male", "Chest pain; taken for an ECG")], resolve=58)
    incident("i1", "Building Fire", "HIGH", "KR Market, Kalasipalya, Bengaluru", ago(hours=2, minutes=10),
             [(0, D1, "Rohan Mehta", "9886100101", "HIGH", "PROCESSED", "Smoke and flames from the upper floor of a three-storey commercial building next to the market. Shops are being evacuated."),
              (3, D3, "Meera Das", "9886100102", "HIGH", "PROCESSED", "Fire is spreading to the next shop; several people are standing on the first-floor balcony.")],
             [dict(unit=9, at=5, route=2, scene=12, res=[(EXT, 4), (THC, 1), (PMP, 2), (GEN, 1)]),
              dict(unit=3, at=8, route=1, scene=13, res=[(OXY, 2), (STR, 2), (FAK, 2)])],
             [(25, "Ramesh Babu", 45, "Male", "Smoke inhalation; on oxygen"), (27, "Savitha K", 38, "Female", "Minor burns on forearm")],
             notes=[(6, "Caller advised to keep clear of the building"), (40, "Adjoining shops evacuated; traffic diverted")])
    incident("i6", "Flooded Underpass - Rescue", "MEDIUM", "Hebbal Flyover, Bengaluru", ago(hours=1, minutes=30),
             [(0, D3, "Mohammed Irfan", "9886100106", "MEDIUM", "PROCESSED", "Underpass is waterlogged after the rain and a car has stalled with two people inside; water is above the wheels.")],
             [dict(unit=4, at=7, route=2, scene=15, res=[(PMP, 2)])])
    incident("i2", "Road Accident", "MEDIUM", "Silk Board Junction, Hosur Road, Bengaluru", ago(minutes=55),
             [(0, D1, "Vikram Joshi", "9886100103", "MEDIUM", "PROCESSED", "A two-wheeler and a car collided at the junction. The rider is on the road, conscious, with a bleeding leg."),
              (2, D1, "Sara Khan", "9886100104", "MEDIUM", "PROCESSED", "I saw the collision from the bus: traffic is blocked on one lane and a second person is sitting on the divider.")],
             [dict(unit=10, at=4, route=1, scene=12, res=[(TRA, 1), (STR, 1)]),
              dict(unit=5, at=6, route=2, scene=9, res=[(BAR, 4)])],
             [(15, "Arun Prasad", 29, "Male", "Suspected leg fracture; conscious"), (16, "Neha Kulkarni", 34, "Female", "Minor abrasions")])
    incident("i5", "Gas Leak", "HIGH", "Marathahalli Bridge, Varthur Road, Bengaluru", ago(minutes=40),
             [(0, D3, "Lokesh Hegde", "9886100105", "HIGH", "PROCESSED", "Strong smell of cooking gas outside a roadside eatery near the bridge; the shop has been emptied and customers moved back.")],
             [dict(unit=8, at=6, route=2, res=[(EXT, 2)])])
    # ---- just received: no unit sent yet (good candidates for a recommendation) ----------------------
    incident("i4", "Robbery", "HIGH", "Commercial Street, Shivajinagar, Bengaluru", ago(minutes=25),
             [(0, D1, "Shop owner", "9886100115", "HIGH", "RECEIVED", "Two men on a motorcycle took cash from a jewellery counter and rode off towards Shivajinagar; nobody is hurt.")])
    incident("i15", "Public Disturbance", "HIGH", "Majestic Metro Station, Bengaluru", ago(minutes=18),
             [(0, D3, "Station guard", "9886100116", "HIGH", "RECEIVED", "A large crowd is arguing and pushing outside the concourse exit; we are asking for police support.")])
    incident("i3", "Medical Emergency", "CRITICAL", "100 Feet Road, Indiranagar, Bengaluru", ago(minutes=12),
             [(0, D3, "Priya Natarajan", "9886100117", "CRITICAL", "RECEIVED", "My father (62) collapsed at home and is not responding; his breathing is irregular. Please send an ambulance now.")])
    return sorted(ev, key=lambda e: (e[0], e[1]))


# ------------------------------------------------------------------ geocoding (before anything is changed)
def lookup_all() -> dict:
    found = {}
    with httpx.Client(headers={"User-Agent": UA}, timeout=20) as http:
        for text, (query, must) in PLACES.items():
            res = http.get("https://nominatim.openstreetmap.org/search",
                           params={"q": query, "format": "jsonv2", "limit": 5, "countrycodes": "in"}).json()
            time.sleep(1.2)                                   # Nominatim usage policy: at most one request per second
            if not res:
                raise SystemExit(f"STOP: no OpenStreetMap match for {text!r} (searched {query!r}). Nothing was changed.")
            ok = [r for r in res
                  if r.get("category") != "boundary" and r.get("type") not in COARSE_TYPES
                  and BBOX[0] <= float(r["lat"]) <= BBOX[1] and BBOX[2] <= float(r["lon"]) <= BBOX[3]
                  and must.lower() in r["display_name"].lower()]
            if not ok:
                raise SystemExit(f"STOP: no precise Bengaluru match for {text!r}; best was {res[0]['display_name']!r}. Nothing was changed.")
            r = ok[0]
            lat, lon = float(r["lat"]), float(r["lon"])
            found[text] = (round(lat, 6), round(lon, 6), r["display_name"][:500])
            print(f"  {lat:.5f} {lon:.5f}  {text}")
    return found


# ------------------------------------------------------------------ backup
def backup(conn, stamp: str) -> Path:
    tables = ["organizations", "responders", "units", "incidents", "calls", "dispatches", "resources",
              "dispatch_resources", "incident_patients", "activity_logs", "geocode_cache"]
    dump = {}
    with conn.cursor() as cur:
        for t in tables:
            if t == "calls":     # audio bytes go to separate files, not into the JSON
                cur.execute("SELECT call_id, received_by, status, transcript, received_at, caller_name, priority, caller_phone, "
                            "location, incident_id, audio_filename, audio_mime_type, audio_size_bytes, audio_sha256 FROM calls")
            else:
                cur.execute(f"SELECT * FROM {t}")
            cols = [c[0] for c in cur.description]
            dump[t] = [dict(zip(cols, row)) for row in cur.fetchall()]
    out = BACKEND / "backups"
    out.mkdir(exist_ok=True)
    with conn.cursor() as cur:
        cur.execute("SELECT call_id, audio_filename, audio_recording FROM calls WHERE audio_recording IS NOT NULL")
        recordings = cur.fetchall()
    if recordings:
        folder = out / f"before-demo-seed-{stamp}-audio"
        folder.mkdir(exist_ok=True)
        for call_id, filename, data in recordings:
            (folder / f"call-{call_id}-{filename or 'recording'}").write_bytes(data)
        print(f"  {len(recordings)} call recording(s) saved as files in {folder}")
    path = out / f"before-demo-seed-{stamp}.json"
    path.write_text(json.dumps(dump, default=lambda o: base64.b64encode(o).decode() if isinstance(o, bytes) else str(o), indent=1), encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="confirm that the current data may be replaced (a backup is written first)")
    ap.add_argument("--skip-mongo", action="store_true", help="leave MongoDB alone (for trial runs against the test database)")
    ap.add_argument("--database", default=os.environ.get("DB_NAME", "emergency_response_management"))
    args = ap.parse_args()
    if not args.yes:
        raise SystemExit("This replaces the data in %r (backup written first). Re-run with --yes to continue." % args.database)

    now = datetime.now().replace(second=0, microsecond=0)
    stamp = now.strftime("%Y%m%d-%H%M")
    events = build_events(now)
    print("1/5 Looking up real coordinates on OpenStreetMap (about 30 s) ...")
    coords = lookup_all()

    print("2/5 Backing up current data ...")
    conn = admin_connection(args.database)
    conn.autocommit(True)
    path = backup(conn, stamp)
    print("  MySQL rows ->", path)
    mongo = None
    if not args.skip_mongo:
        from pymongo import MongoClient
        mongo = MongoClient(os.environ.get("MONGODB_URI", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=3000)[os.environ.get("MONGODB_DB", "erms")]
        mongo.list_collection_names()                                 # raises now, before anything is deleted, if MongoDB is down
        mdump = {c: list(mongo[c].find({}, {"_id": 0})) for c in ("recommendation_history", "call_transcripts")}
        mpath = path.with_name(f"before-demo-seed-{stamp}-mongodb.json")
        mpath.write_text(json.dumps(mdump, default=str, indent=1), encoding="utf-8")
        print("  MongoDB documents ->", mpath, {k: len(v) for k, v in mdump.items()})

    print("3/5 Replacing data ...")
    cur = conn.cursor()
    cur.execute("SELECT responder_id FROM app_users WHERE responder_id IS NOT NULL")
    clash = sorted({r[0] for r in cur.fetchall()} & {r[0] for r in RESPONDERS})
    if clash:
        raise SystemExit(f"STOP: logins point at responders {clash}, whose ids this script wants to reuse. Nothing was changed.")
    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
    for t in ("activity_logs", "dispatch_resources", "dispatches", "incident_patients", "calls", "incidents", "resources", "geocode_cache"):
        cur.execute(f"TRUNCATE TABLE {t}")
    cur.execute("SELECT responder_id, unit_id FROM responders WHERE unit_id IS NOT NULL AND responder_id IN "
                "(SELECT responder_id FROM app_users WHERE responder_id IS NOT NULL)")
    kept_units = cur.fetchall()                          # people with a login keep their unit (units are re-created with the same ids)
    cur.execute("UPDATE responders SET unit_id = NULL")
    cur.execute("DELETE FROM responders WHERE responder_id > 2 AND responder_id NOT IN "
                "(SELECT responder_id FROM app_users WHERE responder_id IS NOT NULL)")
    cur.execute("DELETE FROM units")
    cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    for oid, name, loc in ORGS:
        cur.execute("INSERT INTO organizations (organization_id, organization_name, location, status) VALUES (%s,%s,%s,'ACTIVE') "
                    "ON DUPLICATE KEY UPDATE organization_name=VALUES(organization_name), location=VALUES(location), status='ACTIVE'", (oid, name, loc))
    cur.executemany("INSERT INTO units (unit_id, unit_name, unit_type, status, base_location, organization_id) VALUES (%s,%s,%s,%s,%s,%s)", UNITS)
    cur.execute("UPDATE responders SET unit_id = NULL, availability = 'AVAILABLE', organization_id = 1 WHERE responder_id = 1")
    cur.execute("UPDATE responders SET unit_id = 1, availability = 'AVAILABLE', organization_id = 1, responder_type = 'Police Officer' WHERE responder_id = 2")
    cur.executemany("INSERT INTO responders (responder_id, first_name, middle_name, last_name, phone, email, responder_type, availability, "
                    "organization_id, unit_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", RESPONDERS)
    for rid, uid in kept_units:
        if rid > 2:
            cur.execute("UPDATE responders SET unit_id = %s WHERE responder_id = %s AND organization_id = (SELECT organization_id FROM units WHERE unit_id = %s)", (uid, rid, uid))
    cur.executemany("INSERT INTO resources (resource_id, resource_name, resource_type, quantity_total, quantity_available, location, organization_id, status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,'AVAILABLE')", [(i, n, t, q, q, loc, o) for i, n, t, q, loc, o in RESOURCES])
    for text, (lat, lon, display) in coords.items():
        cur.execute("INSERT INTO geocode_cache (location_key, status, latitude, longitude, display_name, provider) VALUES (%s,'RESOLVED',%s,%s,%s,'nominatim')",
                    (text, lat, lon, display))
    for c in ("recommendation_history", "call_transcripts") if mongo is not None else ():   # they point at the old MySQL ids
        mongo[c].delete_many({})

    print("4/5 Re-creating incidents, calls, dispatches ... through the triggers")
    ctx: dict = {}
    for t, _, fn in events:
        cur.execute("SET TIMESTAMP = %s", (time.mktime(t.timetuple()),))
        fn(cur, ctx)
    cur.execute("SET TIMESTAMP = DEFAULT")
    # crew of units that are out on a dispatch are on duty, others available (unit 12 is out of service: its crew is off duty)
    cur.execute("UPDATE responders r JOIN units u ON u.unit_id = r.unit_id SET r.availability = "
                "CASE WHEN u.status = 'DISPATCHED' THEN 'ON_DUTY' WHEN u.status = 'OUT_OF_SERVICE' THEN 'OFF_DUTY' ELSE 'AVAILABLE' END "
                "WHERE r.responder_id > 2 OR r.responder_id = 2")

    print("5/5 Checking ...")
    checks = {
        "unmapped incidents": "SELECT COUNT(*) FROM v_incident_map WHERE geocode_status IS NULL OR geocode_status <> 'RESOLVED'",
        "unmapped unit bases": "SELECT COUNT(*) FROM v_unit_locations WHERE geocode_status IS NULL OR geocode_status <> 'RESOLVED'",
        "units whose status disagrees with their active dispatches": (
            "SELECT COUNT(*) FROM units u WHERE u.status <> 'OUT_OF_SERVICE' AND "
            "(u.status = 'DISPATCHED') <> EXISTS (SELECT 1 FROM dispatches d WHERE d.unit_id = u.unit_id AND d.status IN ('DISPATCHED','EN_ROUTE','ON_SCENE'))"),
        "resources where available <> total - outstanding": (
            "SELECT COUNT(*) FROM resources r WHERE r.quantity_available <> r.quantity_total - COALESCE((SELECT SUM(dr.quantity_assigned - dr.quantity_returned) "
            "FROM dispatch_resources dr WHERE dr.resource_id = r.resource_id), 0)"),
    }
    bad = 0
    for label, sql in checks.items():
        cur.execute(sql)
        n = cur.fetchone()[0]
        bad += n
        print(f"  {label}: {n}")
    for t in ("organizations", "responders", "units", "incidents", "calls", "dispatches", "resources", "dispatch_resources", "incident_patients", "activity_logs", "geocode_cache"):
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]}")
    conn.close()
    if bad:
        raise SystemExit("Some checks failed; see above. The backup is in " + str(path))
    print("Done. Backup:", path)


if __name__ == "__main__":
    main()
