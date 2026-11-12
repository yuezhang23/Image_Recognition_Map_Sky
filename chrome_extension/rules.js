// Port of rules.py: turns the LLM's per-image observations into R1-R5 and a verdict.
// Keep in sync with rules.py; `node chrome_extension/test_rules_parity.mjs` compares the two on saved runs.

export const PASS = "PASS", FAIL = "FAIL", REVIEW = "REVIEW", NA = "N/A";

const PROHIBITED = new Set(["mailbox", "usps", "public_area", "open_ground"]);
const UNIT_RE = /(?:\b(?:apt|apartment|unit|suite|ste|shop|bldg|building|lot|rm|room)\b\.?|#)\s*#?\s*([a-z0-9-]+)/i;

export function normTracking(s) {
  return (s || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function levenshtein(a, b) {
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur.push(Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] !== b[j - 1] ? 1 : 0)));
    }
    prev = cur;
  }
  return prev[prev.length - 1];
}

export function trackingMatches(read, trackingId) {
  const r = normTracking(read), t = normTracking(trackingId);
  if (!r) return false;
  if (levenshtein(r, t) <= 2) return true;
  // OCR often drops the SPX prefix or reads only the tail digits
  return r.length >= 8 && r.slice(-8) === t.slice(-8);
}

export function parseAddress(address) {
  const parts = address.split(",");
  const street = parts[0];
  let m = street.match(/^\s*(\d+(?:[a-z](?![a-z]))?)/i);
  if (!m) m = parts.slice(0, 2).join(",").match(/\b(\d+[a-z]?)\b/i);
  const house = m ? m[1].toLowerCase() : null;
  let unit = null;
  for (const part of parts.slice(0, 2)) {
    const u = part.match(UNIT_RE);
    if (u && u[1].toLowerCase() !== house) {
      unit = u[1].toLowerCase();
      break;
    }
  }
  return [house, unit];
}

function markerTokens(texts) {
  const tokens = new Set();
  for (const t of texts) {
    for (const tok of (t || "").toLowerCase().match(/[a-z0-9]+/g) || []) {
      tokens.add(tok);
      const digits = tok.match(/^\d+/);
      if (digits) tokens.add(digits[0]);
    }
  }
  return tokens;
}

const types = (im) => im.types || [];

function checkLabel(images, trackingId) {
  const reads = images.flatMap((im) => im.tracking_numbers_read || []);
  if (reads.some((n) => trackingMatches(n, trackingId))) return [PASS, "tracking number on label matches"];
  const wrong = reads.filter((n) => normTracking(n).length >= 12);
  if (wrong.length) return [FAIL, `wrong_package: label shows ${wrong.join(", ")}`];
  if (images.some((im) => types(im).includes("label"))) return [FAIL, "label photographed but tracking number unreadable"];
  return [FAIL, "no label photo"];
}

function placementShots(images) {
  return images.filter((im) => im.package_visible
    && !(types(im).includes("label") && !types(im).includes("placement")));
}

function checkPlacement(images) {
  const shots = placementShots(images);
  for (const im of shots) {
    const loc = im.location_type;
    if (loc != null && loc !== "none" && loc !== "other") {
      const text = `image_${im.index}: ${loc} - ${im.placement_description ?? ""}`.replace(/^[ -]+|[ -]+$/g, "");
      return [PASS, text];
    }
  }
  for (const im of shots) {
    if (types(im).includes("placement")) return [PASS, `image_${im.index}: ${im.placement_description ?? ""}`];
  }
  if (shots.length) return [FAIL, "package visible but placement surroundings not identifiable"];
  if (images.some((im) => im.package_visible)) return [FAIL, "package only shown in label close-ups; placement not photographed"];
  return [FAIL, "no photo of the placed package"];
}

function checkAddress(images, expected) {
  const [house, unit] = parseAddress(expected);
  const tokens = markerTokens(images.flatMap((im) => im.address_marker_text || []));
  const locations = new Set(images.map((im) => im.location_type));
  const lockerOk = images.some((im) => im.locker_screen_shows_name_address);

  if (!house) return [REVIEW, `expected address has no house number: ${expected}`];
  if (tokens.has(house)) {
    if (!unit || tokens.has(unit) || lockerOk || locations.has("mailroom") || locations.has("locker")) {
      return [PASS, `marker shows ${house}` + (unit && tokens.has(unit) ? ` / unit ${unit}` : "")];
    }
    return [FAIL, `house number ${house} shown but unit ${unit} not visible`];
  }
  if (lockerOk) return [PASS, "locker screen shows recipient name and address"];

  const allTypes = new Set(images.flatMap(types));
  if (allTypes.has("exterior") && allTypes.has("gps_screenshot")) return [PASS, "fallback: building exterior + GPS screenshot"];
  const numeric = [...tokens].filter((t) => /^\d+$/.test(t)).sort();
  if (numeric.length) return [FAIL, `address_mismatch: expected ${house}, marker shows ${numeric.join(", ")}`];
  if (allTypes.has("exterior")) return [FAIL, "no address marker; exterior shown but no GPS screenshot"];
  return [FAIL, "no address marker and no exterior + GPS fallback"];
}

function checkScenario(images) {
  const locs = new Set(placementShots(images).map((im) => im.location_type));
  const results = [];
  if (locs.has("mailroom")) {
    results.push(images.some((im) => im.other_carrier_parcels_visible)
      ? [PASS, "mailroom shows other carriers' parcels"]
      : [FAIL, "mailroom photo does not show other carriers' parcels"]);
  }
  if (locs.has("locker")) {
    results.push(images.some((im) => im.locker_screen_shows_name_address)
      ? [PASS, "locker screen shows name and address"]
      : [FAIL, "locker delivery without screen showing name and address"]);
  }
  if (locs.has("handoff") || locs.has("front_desk")) {
    const faces = images.filter((im) => im.face_visible).map((im) => im.index);
    results.push(faces.length ? [FAIL, `face visible in image_${faces[0]}`] : [PASS, "hand-off photo without faces"]);
  }
  if (locs.has("farm")) {
    const ok = images.some((im) => im.location_type === "farm" && im.inside_fenced_or_secure_area);
    results.push(ok ? [PASS, "farm delivery inside fenced/secure area"] : [FAIL, "farm delivery not inside a fenced/secure area"]);
  }
  if (!results.length) return [NA, "no special scenario"];
  return [results.some(([s]) => s === FAIL) ? FAIL : PASS, results.map(([, r]) => r).join("; ")];
}

function checkProhibited(images) {
  const bad = placementShots(images).filter((im) => PROHIBITED.has(im.location_type));
  if (bad.length) return [FAIL, bad.map((im) => `image_${im.index}: package in ${im.location_type}`).join("; ")];
  return [PASS, "no prohibited placement"];
}

export function evaluate(observations, trackingId, expectedAddress) {
  const images = (observations || {}).images || [];
  if (!images.length) return { verdict: REVIEW, checks: {}, reasons: ["no usable observations from LLM"] };
  const checks = {
    r1_label: checkLabel(images, trackingId),
    r2_placement: checkPlacement(images),
    r3_address: checkAddress(images, expectedAddress),
    r4_scenario: checkScenario(images),
    r5_prohibited: checkProhibited(images),
  };
  const statuses = Object.values(checks).map(([s]) => s);
  const verdict = statuses.includes(FAIL) ? FAIL : statuses.includes(REVIEW) ? REVIEW : PASS;
  const reasons = Object.entries(checks).filter(([, [s]]) => s === FAIL || s === REVIEW).map(([k, [, r]]) => `${k}: ${r}`);
  return {
    verdict,
    checks: Object.fromEntries(Object.entries(checks).map(([k, [s, r]]) => [k, { status: s, reason: r }])),
    reasons,
  };
}
