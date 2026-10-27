"""Deterministic POD rule engine.

Takes the per-image observations returned by the LLM (see OBSERVATION_SCHEMA in
pod_check.py) plus the expected address, and judges Part A of POD_standard.md:

R1 label, R2 placement, R3 address marker, R4 special scenario, R5 prohibited.
"""
import re

PASS, FAIL, REVIEW, NA = "PASS", "FAIL", "REVIEW", "N/A"

PROHIBITED = {"mailbox", "usps", "public_area", "open_ground"}
UNIT_RE = re.compile(r"(?:\b(?:apt|apartment|unit|suite|ste|shop|bldg|building|lot|rm|room)\b\.?|#)\s*#?\s*([a-z0-9-]+)", re.I)


def norm_tracking(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def tracking_matches(read, tracking_id):
    r, t = norm_tracking(read), norm_tracking(tracking_id)
    if not r:
        return False
    if levenshtein(r, t) <= 2:
        return True
    # OCR often drops the SPX prefix or reads only the tail digits
    return len(r) >= 8 and r[-8:] == t[-8:]


def parse_address(address):
    """Return (house_number, unit) from e.g. '91 Market St Apt 218, BETHLEHEM, GA 30620'."""
    street = address.split(",")[0]
    # '71B E Candler St' -> 71b, but '1910winnst ead place' -> 1910
    m = re.match(r"\s*(\d+(?:[a-z](?![a-z]))?)", street, re.I)
    if not m:
        # number not leading: 'Westshore Drive, 2047, ...' or 'Eagle Creek Apts, 4280 S Lee St ...'
        m = re.search(r"\b(\d+[a-z]?)\b", ",".join(address.split(",")[:2]), re.I)
    house = m.group(1).lower() if m else None
    unit = None
    # a unit can sit in the street part or in its own comma field ("71 Main St, Apt. B, ...")
    for part in address.split(",")[:2]:
        u = UNIT_RE.search(part)
        if u and u.group(1).lower() != house:
            unit = u.group(1).lower()
            break
    return house, unit


def marker_tokens(texts):
    """Split visible marker strings ('2458', 'Bldg 3 Apt 3B') into lowercase alnum tokens."""
    tokens = set()
    for t in texts:
        for tok in re.findall(r"[a-z0-9]+", (t or "").lower()):
            tokens.add(tok)
            # '3b' -> also allow '3' to be compared as a number
            digits = re.match(r"\d+", tok)
            if digits:
                tokens.add(digits.group(0))
    return tokens


def check_label(images, tracking_id):
    reads = [n for im in images for n in im.get("tracking_numbers_read") or []]
    if any(tracking_matches(n, tracking_id) for n in reads):
        return PASS, "tracking number on label matches"
    wrong = [n for n in reads if len(norm_tracking(n)) >= 12]
    if wrong:
        return FAIL, f"wrong_package: label shows {', '.join(wrong)}"
    if any("label" in im.get("types", []) for im in images):
        return FAIL, "label photographed but tracking number unreadable"
    return FAIL, "no label photo"


def placement_shots(images):
    """Photos that show the package where it was left. Label close-ups are excluded: models often tag a
    package held up for the label shot as 'handoff' or 'other', which is not a delivery placement."""
    return [im for im in images if im.get("package_visible")
            and not ("label" in im.get("types", []) and "placement" not in im.get("types", []))]


def check_placement(images):
    shots = placement_shots(images)
    for im in shots:
        if im.get("location_type") not in (None, "none", "other"):
            return PASS, f"image_{im['index']}: {im.get('location_type')} - {im.get('placement_description', '')}".strip(" -")
    for im in shots:
        if "placement" in im.get("types", []):
            return PASS, f"image_{im['index']}: {im.get('placement_description', '')}"
    if shots:
        return FAIL, "package visible but placement surroundings not identifiable"
    if any(im.get("package_visible") for im in images):
        return FAIL, "package only shown in label close-ups; placement not photographed"
    return FAIL, "no photo of the placed package"


def check_address(images, expected):
    house, unit = parse_address(expected)
    markers = [t for im in images for t in im.get("address_marker_text") or []]
    tokens = marker_tokens(markers)
    locations = {im.get("location_type") for im in images}
    locker_ok = any(im.get("locker_screen_shows_name_address") for im in images)

    if not house:
        return REVIEW, f"expected address has no house number: {expected}"
    if house in tokens:
        if not unit or unit in tokens or locker_ok or locations & {"mailroom", "locker"}:
            return PASS, f"marker shows {house}" + (f" / unit {unit}" if unit and unit in tokens else "")
        return FAIL, f"house number {house} shown but unit {unit} not visible"
    if locker_ok:
        return PASS, "locker screen shows recipient name and address"

    types = {t for im in images for t in im.get("types", [])}
    if "exterior" in types and "gps_screenshot" in types:
        return PASS, "fallback: building exterior + GPS screenshot"
    numeric = sorted(t for t in tokens if t.isdigit())
    if numeric:
        return FAIL, f"address_mismatch: expected {house}, marker shows {', '.join(numeric)}"
    if "exterior" in types:
        return FAIL, "no address marker; exterior shown but no GPS screenshot"
    return FAIL, "no address marker and no exterior + GPS fallback"


def check_scenario(images):
    locs = {im.get("location_type") for im in placement_shots(images)}
    results = []
    if "mailroom" in locs:
        ok = any(im.get("other_carrier_parcels_visible") for im in images)
        results.append((PASS, "mailroom shows other carriers' parcels") if ok
                       else (FAIL, "mailroom photo does not show other carriers' parcels"))
    if "locker" in locs:
        ok = any(im.get("locker_screen_shows_name_address") for im in images)
        results.append((PASS, "locker screen shows name and address") if ok
                       else (FAIL, "locker delivery without screen showing name and address"))
    if locs & {"handoff", "front_desk"}:
        faces = [im["index"] for im in images if im.get("face_visible")]
        results.append((FAIL, f"face visible in image_{faces[0]}") if faces
                       else (PASS, "hand-off photo without faces"))
    if "farm" in locs:
        ok = any(im.get("inside_fenced_or_secure_area") for im in images
                 if im.get("location_type") == "farm")
        results.append((PASS, "farm delivery inside fenced/secure area") if ok
                       else (FAIL, "farm delivery not inside a fenced/secure area"))
    if not results:
        return NA, "no special scenario"
    status = FAIL if any(s == FAIL for s, _ in results) else PASS
    return status, "; ".join(r for _, r in results)


def check_prohibited(images):
    bad = [(im["index"], im["location_type"]) for im in placement_shots(images)
           if im.get("location_type") in PROHIBITED]
    if bad:
        return FAIL, "; ".join(f"image_{i}: package in {loc}" for i, loc in bad)
    return PASS, "no prohibited placement"


def evaluate(observations, tracking_id, expected_address):
    images = (observations or {}).get("images") or []
    if not images:
        return {"verdict": REVIEW, "checks": {}, "reasons": ["no usable observations from LLM"]}
    checks = {
        "r1_label": check_label(images, tracking_id),
        "r2_placement": check_placement(images),
        "r3_address": check_address(images, expected_address),
        "r4_scenario": check_scenario(images),
        "r5_prohibited": check_prohibited(images),
    }
    statuses = [s for s, _ in checks.values()]
    verdict = FAIL if FAIL in statuses else REVIEW if REVIEW in statuses else PASS
    reasons = [f"{k}: {r}" for k, (s, r) in checks.items() if s in (FAIL, REVIEW)]
    return {
        "verdict": verdict,
        "checks": {k: {"status": s, "reason": r} for k, (s, r) in checks.items()},
        "reasons": reasons,
    }
