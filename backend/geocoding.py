"""Reference location for a case: geocode the assigned address (OpenStreetMap Nominatim) in the background.

* Only cases explicitly marked location_status="pending" are processed (new cases, or an address correction).
  Existing cases are never touched unless an admin/supervisor corrects their address.
* Only the address text (address, city, state, pincode) is sent — never names, phones or case ids.
* Nominatim usage policy: max 1 request/second and an identifying User-Agent. Set GEOCODING_PROVIDER=off to disable.
* A manually pinned location always wins: results are written only while the case is still "pending".
"""
import asyncio
import logging
import os
import re
import threading
import time

import requests

import core

logger = logging.getLogger(__name__)

PROVIDER = (os.environ.get("GEOCODING_PROVIDER") or "nominatim").strip().lower()
NOMINATIM_URL = os.environ.get("NOMINATIM_URL") or "https://nominatim.openstreetmap.org/search"
USER_AGENT = os.environ.get("GEOCODER_USER_AGENT") or "CheckSphere/1.0 (internal field verification system)"


# ---------------------------------------------------------------- forward geocoding (case reference location)
# A geocoder "hit" is not proof of the address. On 14-Nov-2026, for "2C NS Road ... Howrah 711204":
#   * the structured street search answered with Grand Trunk Road (a different street) at street rank;
#   * the PIN 711204 search answered with a centre in Barrackpur-II, North 24 Parganas (another district).
# So a result is used automatically only when it is VERIFIED against the case:
#   street   the returned road name matches the street in the address, and the district/city (and state) match
#   locality the returned place name matches a locality in the address, district/city match, and the PIN matches
#   pincode  the PIN centre lies in the case's district/city (and state)
# Anything else is kept only as an unverified candidate for a Supervisor / Super Admin to confirm or replace with a pin.
_STREET_WORDS = r"(?:road|rd|street|st|lane|ln|sarani|sarini|path|marg|avenue|ave|bypass|highway|hwy|row)"
_STREET_RX = re.compile(r"\b((?:[a-z][a-z.]*\s+){0,3}" + _STREET_WORDS + r")\b\.?(.*)$", re.I)
# building / flat / shop lines: a map cannot locate these ("5th Block Koramangala" is a locality, so no ordinals here)
_UNIT_RX = re.compile(r"\b(flat|floor|apartments?|apt|appt|tower|wing|room|house\s*no|h\.?\s*no|plot|door|unit|shop)\b", re.I)
_HOUSE_NO_RX = re.compile(r"^\s*(?:no\.?\s*)?(?![0-9]+(?:st|nd|rd|th)\b)[a-z]?[-/]?[0-9][0-9a-z/\-]*\s*,?(?:\s+|$)", re.I)
_AREA_KEYS = ("city", "town", "village", "municipality", "county", "state_district", "district", "suburb", "city_district")
_ALIASES = {"haora": "howrah", "calcutta": "kolkata", "bombay": "mumbai", "bangalore": "bengaluru", "madras": "chennai"}


def _norm(s) -> str:
    s = re.sub(r"\b(road)\b", "rd", str(s or "").lower())
    s = re.sub(r"\b(street)\b", "st", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return _ALIASES.get(s, s)


def _same_place(a, b) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a) and bool(b) and (a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)))


def parse_address(text: str) -> dict:
    """Split an Indian free-text address into {street, localities} (flat / floor / apartment lines dropped)."""
    street, localities = None, []
    for seg in re.split(r"[\n,;]+", text or ""):
        seg = " ".join(seg.split())
        if not seg:
            continue
        seg = _HOUSE_NO_RX.sub("", seg).strip()
        if not seg:
            continue
        m =_STREET_RX.search(seg)
        if m and not street:
            street = m.group(1).strip(" .")
            rest = _HOUSE_NO_RX.sub("", m.group(2).strip(" ,."))
            if rest and not _UNIT_RX.search(rest):
                localities.append(rest)
            continue
        if _UNIT_RX.search(seg):
            continue  # "GOKUL APARTMENT FLAT 7 SECOND FLOOR": a building / flat, not something a map can locate
        localities.append(seg)
    return {"street": street, "localities": localities}


def _area_ok(addr: dict, case: dict) -> tuple:
    city, state = (case.get("city") or "").strip(), (case.get("state") or "").strip()
    if state and addr.get("state") and not _same_place(addr.get("state"), state):
        return False, f"it is in {addr.get('state')}, not {state}"
    if not city:
        return False, "the case has no city to check it against"
    if any(_same_place(addr.get(k), city) for k in _AREA_KEYS if addr.get(k)):
        return True, ""
    where = addr.get("state_district") or addr.get("county") or addr.get("city") or addr.get("town") or "another area"
    return False, f"it is in {where}, not {city}"


def _fwd(params: dict) -> list:
    return _throttled_get(NOMINATIM_URL, {**params, "format": "jsonv2", "limit": 5, "countrycodes": "in",
                                          "addressdetails": 1}, timeout=20) or []


def _cand(hit: dict, precision: str, why: str) -> dict:
    return {"lat": round(float(hit["lat"]), 7), "lon": round(float(hit["lon"]), 7), "precision": precision,
            "label": (hit.get("display_name") or "")[:200], "verified": False, "note": why, "source": "nominatim"}


def geocode_case_address(case: dict) -> dict:
    """Look up the case's assigned address. Blocking (run in a thread). Sends only address text, city, state, PIN.

    Returns {"status": "located", "lat", "lon", "precision", "note", "candidates"} for a verified match, or
    {"status": "needs_pin", "note", "candidates"} when nothing could be verified (candidates are unverified)."""
    city, state, pin = (case.get("city") or "").strip(), (case.get("state") or "").strip(), _valid_pin(case.get("pincode"))
    parsed = parse_address(str(case.get("assigned_address") or ""))
    street = parsed["street"]
    localities = [x for x in parsed["localities"] if not (_same_place(x, city) or _same_place(x, state))][:3]
    candidates, findings = [], []

    def add(c):
        if not any(abs(c["lat"] - o["lat"]) < 1e-4 and abs(c["lon"] - o["lon"]) < 1e-4 for o in candidates):
            candidates.append(c)

    if street:
        tries = [{"street": street, **({"city": city} if city else {}), **({"state": state} if state else {}),
                  **({"postalcode": pin} if pin else {}), "country": "India"},
                 {"q": ", ".join(x for x in (street, *localities, city, state, pin) if x)}]
        for params in tries:
            for hit in _fwd(params):
                a = hit.get("address") or {}
                road = a.get("road") or (hit.get("name") if hit.get("category") == "highway" else None)
                ok_area, why_area = _area_ok(a, case)
                if road and _same_place(road, street) and ok_area:
                    return {"status": "located", "lat": float(hit["lat"]), "lon": float(hit["lon"]), "precision": "street",
                            "note": f"Street match: {hit.get('display_name', '')[:160]}", "candidates": []}
                if road and not _same_place(road, street):
                    findings.append(f"the street search returned {road}, a different street")
                elif road:
                    findings.append(f"{road} was found but {why_area}")
        if not findings:
            findings.append(f"'{street}' is not in the map data")
    for loc in localities:
        for hit in _fwd({"q": ", ".join(x for x in (loc, city, state) if x)}):
            a = hit.get("address") or {}
            name = hit.get("name") or ""
            if not (_same_place(name, loc) or any(_same_place(a.get(k), loc) for k in ("suburb", "neighbourhood", "quarter", "village"))):
                continue
            ok_area, why_area = _area_ok(a, case)
            hit_pin = _valid_pin(a.get("postcode"))
            if ok_area and pin and hit_pin == pin:
                return {"status": "located", "lat": float(hit["lat"]), "lon": float(hit["lon"]), "precision": "locality",
                        "note": f"Locality match ({loc}, PIN {pin}): {hit.get('display_name', '')[:140]}", "candidates": []}
            why = why_area if not ok_area else (f"its PIN is {hit_pin or 'unknown'}, the case PIN is {pin}" if pin else "no PIN to check")
            add(_cand(hit, "locality", f"Locality '{name}' found but not verified: {why}"))
        if not candidates:
            findings.append(f"locality '{loc}' was not found in {city or 'the case city'}")
    if pin:
        for hit in _fwd({"postalcode": pin, "country": "India"})[:1]:
            a = hit.get("address") or {}
            ok_area, why_area = _area_ok(a, case)
            if ok_area:
                return {"status": "located", "lat": float(hit["lat"]), "lon": float(hit["lon"]), "precision": "pincode",
                        "note": f"PIN {pin} area centre only (approximate, within about 3 km)", "candidates": candidates}
            findings.append(f"the map centre of PIN {pin} is not in the case's area ({why_area})")
            add(_cand(hit, "pincode", f"PIN {pin} centre not verified: {why_area}"))
    if not street and not localities:
        findings.insert(0, "the address has no street or locality that can be searched")
    note = ("Could not locate the assigned address automatically: " + ("; ".join(dict.fromkeys(findings)) or "no match")
            + ". A Supervisor or Super Admin must confirm a candidate or pin the exact location.")
    return {"status": "needs_pin", "note": note[:700], "candidates": candidates[:5]}


def location_problem(case: dict):
    """Plain-language reason a case has no usable reference location (None when it has one)."""
    if case.get("assigned_lat") is not None and case.get("assigned_lon") is not None:
        return None
    st = case.get("location_status")
    if st == "awaiting_address" or not (case.get("assigned_address") or "").strip():
        return "No assigned address has been entered for this case yet."
    if st == "pending":
        return "The assigned address is being looked up; the distance will be checked once it is located."
    if st == "needs_pin":
        return case.get("location_note") or "The assigned address could not be located automatically. A supervisor must confirm or pin it."
    if st == "missing":
        return "Automatic address lookup is switched off. A supervisor must pin the case location."
    if st == "not_found":
        return "The assigned address was not found by the automatic lookup. A supervisor must confirm or pin it."
    return ("The assigned address has never been located (this case was created before automatic address lookup "
            "existed). A supervisor must look it up or pin it.")


# ---------------------------------------------------------------- reverse geocoding (photo location)
# The address printed on a photo comes ONLY from the GPS coordinates captured at the shutter.
# Only latitude/longitude are sent to the providers — never the case address, names or phone numbers.
#
# Why two sources: in many Indian localities OpenStreetMap roads carry no name, so Nominatim's best match is an
# unnamed road with only "city + postcode", and that postcode is inferred from nearby data (it changed from 711202 to
# 711107 between two points 60 m apart in Belur). Photon (same OSM data, different index) returns the nearest *named*
# place with its own postcode. A PIN code is printed only when it is consistent across sources or with the PIN's
# own centre; nothing is ever invented, and anything that is not a street-level match is labelled approximate.
REVERSE_URL = os.environ.get("NOMINATIM_REVERSE_URL") or "https://nominatim.openstreetmap.org/reverse"
PHOTON_URL = os.environ.get("PHOTON_REVERSE_URL") or "https://photon.komoot.io/reverse"
NEAR_PLACE_MAX_M = 120          # a named place further than this is not used as "Near ..."
PIN_CENTRE_MAX_M = 6000         # a PIN whose centre is further than this from the photo is not printed
_rev_lock = threading.Lock()
_rev_last = [0.0]
_rev_cache: dict = {}
_pin_centre_cache: dict = {}


def _throttled_get(url: str, params: dict, timeout: float = 8):
    with _rev_lock:  # Nominatim policy: at most 1 request per second (also applied to Photon, out of courtesy)
        wait = 1.1 - (time.monotonic() - _rev_last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
                                timeout=timeout)
        finally:
            _rev_last[0] = time.monotonic()
    resp.raise_for_status()
    return resp.json()


def _dist_m(lat1, lon1, lat2, lon2) -> float:
    return core.haversine_m(lat1, lon1, lat2, lon2)


def _valid_pin(pc) -> str | None:
    s = "".join(ch for ch in str(pc or "") if ch.isdigit())
    return s if len(s) == 6 and s[0] != "0" else None


def _pin_centre(pin: str):
    """Centre of a PIN code area (cached for the process lifetime; PIN areas don't move)."""
    if pin in _pin_centre_cache:
        return _pin_centre_cache[pin]
    centre = None
    try:
        items = _throttled_get(NOMINATIM_URL, {"postalcode": pin, "countrycodes": "in", "format": "jsonv2", "limit": 1})
        if items:
            centre = (float(items[0]["lat"]), float(items[0]["lon"]))
    except Exception as exc:
        logger.info("PIN centre lookup failed for %s: %s", pin, type(exc).__name__)
        return None  # not cached: try again next time
    _pin_centre_cache[pin] = centre
    return centre


def _nominatim(lat, lon) -> dict | None:
    item = _throttled_get(REVERSE_URL, {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2", "zoom": 18,
                                        "addressdetails": 1})
    return None if not item or item.get("error") else item


def _photon(lat, lon) -> dict | None:
    """Nearest named OSM feature (shop, building, landmark, street) with its own postcode."""
    data = _throttled_get(PHOTON_URL, {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "limit": 1, "lang": "en"})
    for f in (data or {}).get("features") or []:
        p = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) == 2:
            return {**p, "distance_m": round(_dist_m(lat, lon, coords[1], coords[0]), 1)}
    return None


def _choose_pin(lat, lon, candidates: list[tuple[str, str]]) -> tuple[str | None, bool, list]:
    """candidates: [(source, pin)]. Returns (pin, verified, checks)."""
    pins = {}
    for src, pc in candidates:
        v = _valid_pin(pc)
        if v:
            pins.setdefault(v, []).append(src)
    checks = []
    for pin in pins:
        c = _pin_centre(pin)
        checks.append({"pin": pin, "sources": pins[pin],
                       "centre_distance_m": round(_dist_m(lat, lon, *c)) if c else None})
    plausible = [x for x in checks if x["centre_distance_m"] is None or x["centre_distance_m"] <= PIN_CENTRE_MAX_M]
    if not plausible:
        return None, False, checks
    agreed = [x for x in plausible if len(x["sources"]) >= 2]
    if agreed:
        return agreed[0]["pin"], True, checks
    # sources disagree (or only one): keep the PIN whose own centre is nearest; it is NOT marked verified
    best = min(plausible, key=lambda x: x["centre_distance_m"] if x["centre_distance_m"] is not None else 10 ** 9)
    verified = len(checks) == 1 and best["centre_distance_m"] is not None
    return best["pin"], verified, checks


def _compose(nom: dict | None, near: dict | None, pin: str | None) -> tuple[list[str], dict]:
    a = (nom or {}).get("address") or {}
    road = a.get("road") or a.get("pedestrian") or a.get("footway")
    comp = {
        "house_number": a.get("house_number"),
        "building": (nom or {}).get("name") or a.get("building") or a.get("amenity") or a.get("shop") or a.get("office"),
        "road": road,
        "locality": a.get("neighbourhood") or a.get("suburb") or a.get("quarter") or a.get("residential") or a.get("hamlet"),
        "post_office": None,  # no provider returns the post office reliably; never guessed
        "city": a.get("city") or a.get("town") or a.get("village") or a.get("city_district") or a.get("county"),
        "district": a.get("state_district"),
        "state": a.get("state"),
        "country": a.get("country"),
        "pincode": pin,
        "near": None,
    }
    if near:
        street = near.get("street") or ""
        comp["near"] = near.get("name")
        if not road and street and "," not in street and len(street) <= 60:
            comp["near_street"] = street
        for k, pk in (("city", "city"), ("state", "state"), ("country", "country"), ("locality", "district")):
            if not comp.get(k) and near.get(pk):
                comp[k] = near[pk]
    parts: list[str] = []

    def add(x):
        if x and x not in parts:
            parts.append(x)
    first = " ".join(x for x in (comp["house_number"], comp["road"]) if x)
    if comp["building"] and comp["building"] != first:
        add(comp["building"])
    add(first)
    if not first and comp.get("near"):
        add(f"Near {comp['near']}")
        add(comp.get("near_street"))
    add(comp["locality"])
    add(comp["city"])
    if comp["district"] and comp["district"] != comp["city"]:
        add(comp["district"])
    add(comp["state"])
    return parts, comp


def reverse_geocode(lat: float, lon: float) -> dict:
    """Best verified address for the captured coordinates. Blocking (run in a thread).
    Returns {"text", "status": resolved|approximate|unavailable, "precision", "components", "pin_verified", ...}."""
    if PROVIDER == "off" or lat is None or lon is None:
        return {"text": None, "status": "unavailable", "precision": None, "reason": "provider_off" if PROVIDER == "off" else "no_gps"}
    lat, lon = float(lat), float(lon)
    key = (round(lat, 5), round(lon, 5))  # ~1 m: a cached answer is never reused for a different spot
    if key in _rev_cache:
        return _rev_cache[key]
    nom, near, errors = None, None, []
    try:
        nom = _nominatim(lat, lon)
    except Exception as exc:
        errors.append(f"nominatim:{type(exc).__name__}")
    a = (nom or {}).get("address") or {}
    street_level = bool(a.get("road") or a.get("pedestrian") or a.get("house_number"))
    if not street_level:
        try:
            p = _photon(lat, lon)
            if p and p.get("name") and p["distance_m"] <= NEAR_PLACE_MAX_M:
                near = p
            elif p and p.get("postcode") and p["distance_m"] <= NEAR_PLACE_MAX_M * 3:
                near = {**p, "name": None}  # too far to say "near", but its postcode is still a PIN witness
        except Exception as exc:
            errors.append(f"photon:{type(exc).__name__}")
    if not nom and not near:
        logger.warning("reverse geocoding failed: %s", ",".join(errors) or "not_found")
        return {"text": None, "status": "unavailable", "precision": None, "reason": ",".join(errors) or "not_found"}
    cands = [("nominatim", a.get("postcode"))] + ([("photon", near.get("postcode"))] if near else [])
    pin, pin_verified, pin_checks = _choose_pin(lat, lon, cands)
    parts, comp = _compose(nom, near, pin)
    if not parts and not pin:
        return {"text": None, "status": "unavailable", "precision": None, "reason": "empty"}
    text = ", ".join(parts)
    if pin:
        text = f"{text} {pin}".strip() if pin_verified else f"{text} (PIN approx. {pin})".strip(" ,")
    precision = "street" if street_level else ("near_place" if near and near.get("name") else "locality")
    out = {"text": text[:300] or None, "status": "resolved" if street_level and pin_verified else "approximate",
           "precision": precision, "components": comp, "pin_verified": bool(pin and pin_verified),
           "pin_checks": pin_checks, "near_place_distance_m": (near or {}).get("distance_m"),
           "sources": [s for s, ok in (("nominatim", nom), ("photon", near)) if ok]}
    if len(_rev_cache) > 5000:
        _rev_cache.clear()
    _rev_cache[key] = out
    return out


def initial_location_fields(lat, lon) -> dict:
    """Location bookkeeping for a newly created case."""
    if lat is not None and lon is not None:
        return {"location_source": "manual", "location_status": "pinned", "location_precision": "exact"}
    return {"location_source": None, "location_status": "pending" if PROVIDER != "off" else "missing",
            "location_precision": None}


def location_update(res: dict) -> dict:
    """Case fields to store for a geocode_case_address() result."""
    now = core.now()
    if res["status"] == "located":
        return {"assigned_lat": res["lat"], "assigned_lon": res["lon"], "location_source": "geocoded",
                "location_status": "geocoded", "location_precision": res["precision"], "location_note": res["note"],
                "location_candidates": res.get("candidates") or [], "geocoded_at": now}
    return {"assigned_lat": None, "assigned_lon": None, "location_source": None, "location_precision": None,
            "location_status": "needs_pin", "location_note": res["note"],
            "location_candidates": res.get("candidates") or [], "geocoded_at": now}


async def geocode_pass(limit: int = 20) -> int:
    """Geocode up to `limit` cases whose reference location is pending. Returns how many were processed."""
    if PROVIDER == "off":
        return 0
    n = 0
    async for c in core.db.cases.find({"location_status": "pending", "deleted_at": None}).limit(limit):
        n += 1
        try:
            res = await asyncio.to_thread(geocode_case_address, c)
        except Exception as exc:
            logger.warning("geocoding failed for case %s: %s", c["_id"], type(exc).__name__)
            await asyncio.sleep(5)
            continue
        upd = location_update(res)
        r = await core.db.cases.update_one({"_id": c["_id"], "location_status": "pending"}, {"$set": upd})
        if r.modified_count:
            await core.audit({"name": "system", "role": "system"}, "case_location_geocoded", "case", str(c["_id"]),
                             {"result": upd["location_status"], "precision": upd.get("location_precision"),
                              "lat": upd.get("assigned_lat"), "lon": upd.get("assigned_lon"), "note": upd.get("location_note")})
            logger.info("case %s geocoded: %s (%s)", c["_id"], upd["location_status"], upd.get("location_precision"))
        await asyncio.sleep(1.1)  # Nominatim policy: max 1 request per second
    return n


async def geocode_loop():
    if PROVIDER == "off":
        logger.info("geocoding disabled (GEOCODING_PROVIDER=off)")
        return
    while True:
        try:
            await geocode_pass()
        except Exception as exc:
            logger.error("geocode loop error: %s", exc)
        await asyncio.sleep(20)
