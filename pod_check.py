import argparse, csv, json, os, random, sys
import base64, io
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Literal, Optional

from dotenv import load_dotenv
from PIL import Image
from pydantic import BaseModel

import rules
from llm_vendors import DEFAULT_MODELS, VENDORS, check_vision, extract_with_retry, make_client

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_EDGE = 1024

IMAGE_TYPES = ["label", "placement", "address_marker", "exterior", "gps_screenshot",
               "locker_screen", "mailroom", "handoff", "other"]
LOCATION_TYPES = ["doorstep", "porch", "garage", "side_or_back_door", "mailroom", "locker", "front_desk",
                  "handoff", "farm", "mailbox", "usps", "public_area", "open_ground", "other", "none"]


class ImageObs(BaseModel):
    index: int
    types: List[Literal[tuple(IMAGE_TYPES)]]
    quality: Literal["clear", "blurry", "dark", "obstructed"]
    tracking_numbers_read: List[str]
    label_address_read: Optional[str]
    address_marker_text: List[str]
    package_visible: bool
    location_type: Literal[tuple(LOCATION_TYPES)]
    placement_description: str
    other_carrier_parcels_visible: bool
    locker_screen_shows_name_address: bool
    face_visible: bool
    inside_fenced_or_secure_area: bool


class Observations(BaseModel):
    images: List[ImageObs]
    notes: str


def _strict(schema):
    """Make a pydantic JSON schema acceptable to strict structured-output modes (no $refs, all required)."""
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(dict(defs[node["$ref"].split("/")[-1]]))
            node = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if node.get("type") == "object":
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [walk(n) for n in node]
        return node

    return walk(schema)


OBSERVATION_SCHEMA = _strict(Observations.model_json_schema())

FIELD_GUIDE = """Fields for each image:
- index: the N in image_N.
- types: every role the image plays. label = shipping label close-up; placement = shows where the package was left;
  address_marker = a house/building/unit number is visible; exterior = building exterior; gps_screenshot = a phone or
  car navigation screen; locker_screen = parcel locker monitor; mailroom = shared package room; handoff = package in a
  person's hand.
- quality: clear, blurry, dark or obstructed.
- tracking_numbers_read: every tracking number you can read (usually printed under the barcode, e.g. SPXPDK...).
  Labels may be rotated or upside down - read them in any orientation. Transcribe exactly; leave empty if none
  is legible. Do not guess digits.
- label_address_read: the SHIP TO street address on the label, or null.
- address_marker_text: every house, building, apartment or unit number visible on the property (door, wall, post,
  mailbox, curb). Transcribe exactly as shown. Do not include numbers that appear only on the shipping label.
- package_visible: the delivered package itself appears in the image (not just a label close-up).
- location_type: where the PACKAGE is placed in this image; "none" if no package is visible, and "none" for a
  label close-up where the driver holds the package up or it sits in the vehicle. "handoff" means the package is
  being given to the recipient, not the driver holding it for the label photo. A mailbox merely
  appearing in the photo is not "mailbox" - use "mailbox" only if the package is inside or on a mailbox.
  public_area = shared public entrances, lobbies, community centers, sidewalks; open_ground = bare dirt/gravel/grass
  in the open away from any door.
- placement_description: one short sentence on where the package sits.
- other_carrier_parcels_visible: parcels from other carriers (Amazon, UPS, FedEx, ...) are visible in the same area.
- locker_screen_shows_name_address: a locker screen showing the recipient's name and address is legible.
- face_visible: any person's face is visible.
- inside_fenced_or_secure_area: the package is inside a fence, gate or similarly secured area.
notes: anything relevant that the fields do not capture."""


def part_a(standard_path):
    text = open(standard_path, encoding="utf-8").read()
    start, end = text.index("## Part A"), text.index("## Part B")
    return text[start:end].strip().rstrip("-").strip()


def system_prompt(standard_path):
    return (
        "You review proof-of-delivery (POD) photos taken by a parcel delivery driver. All photos given together "
        "belong to one package. Your job is to report what is visibly in each photo, factually and precisely. "
        "Do not decide whether the delivery passes; that is done separately from your observations.\n\n"
        "The company standard the photos are checked against:\n\n"
        f"{part_a(standard_path)}\n\n{FIELD_GUIDE}"
    )


def load_images(folder):
    out = []
    names = sorted(n for n in os.listdir(folder) if os.path.splitext(n)[1].lower() in IMAGE_EXTS)
    for i, name in enumerate(names, 1):
        img = Image.open(os.path.join(folder, name)).convert("RGB")
        img.thumbnail((MAX_EDGE, MAX_EDGE))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        out.append((f"image_{i} ({name})", base64.standard_b64encode(buf.getvalue()).decode()))
    return names, out


def validate(data):
    return Observations.model_validate(data).model_dump()


def process(tracking_id, address, args, client, system):
    folder = os.path.join(args.images, tracking_id)
    cache = os.path.join(args.out, "raw", args.run_name, f"{tracking_id}.json")
    names, images = load_images(folder)
    obs, error = None, None
    if os.path.isfile(cache) and not args.force:
        obs = json.load(open(cache, encoding="utf-8"))
    elif images:
        try:
            obs = extract_with_retry(client, system, images, OBSERVATION_SCHEMA, validate)
            with open(cache, "w", encoding="utf-8") as f:
                json.dump(obs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            error = str(e)
    result = rules.evaluate(obs, tracking_id, address)
    if error:
        result["reasons"].append(f"error: {error}")
    return {"tracking_id": tracking_id, "address": address, "images": names, "vendor": args.vendor,
            "model": client.model, **result, "observations": obs}


def main():
    parser = argparse.ArgumentParser(description="Check POD photos against Part A of POD_standard.md")
    parser.add_argument("--vendor", required=True, choices=sorted(VENDORS))
    parser.add_argument("--model", help=f"Model ID (defaults: {DEFAULT_MODELS})")
    parser.add_argument("--images", default="valid_images", help="Folder with one subfolder per tracking ID")
    parser.add_argument("--addresses", default="tracking_address.json")
    parser.add_argument("--standard", default="POD_standard.md")
    parser.add_argument("--out", default="results")
    parser.add_argument("--ids", nargs="+", help="Only check these tracking IDs")
    parser.add_argument("--limit", type=int, help="Check at most N folders")
    parser.add_argument("--sample", type=int, help="Check N randomly chosen folders")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for --sample")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--force", action="store_true", help="Ignore cached LLM observations")
    args = parser.parse_args()

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

    addresses = json.load(open(args.addresses, encoding="utf-8"))
    folders = args.ids or sorted(n for n in os.listdir(args.images) if os.path.isdir(os.path.join(args.images, n)))
    todo = [t for t in folders if t in addresses]
    skipped = [t for t in folders if t not in addresses]
    for t in skipped:
        print("skipped_no_address:", t)
    if args.sample:
        todo = sorted(random.Random(args.seed).sample(todo, min(args.sample, len(todo))))
    if args.limit:
        todo = todo[:args.limit]

    client = make_client(args.vendor, args.model)
    # caches and outputs are keyed by vendor + model so runs of different models never mix
    args.run_name = f"{args.vendor}_{client.model}"
    os.makedirs(os.path.join(args.out, "raw", args.run_name), exist_ok=True)
    check_vision(client)
    system = system_prompt(args.standard)
    print(f"checking {len(todo)} folders with {args.vendor}/{client.model} ({len(skipped)} skipped, no address)")

    results = []
    with ThreadPoolExecutor(args.workers) as ex:
        futures = {ex.submit(process, t, addresses[t], args, client, system): t for t in todo}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            print(f"{r['verdict']:6} {r['tracking_id']}  {' | '.join(r['reasons'])}")
    results.sort(key=lambda r: r["tracking_id"])

    with open(os.path.join(args.out, f"results_{args.run_name}.jsonl"), "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    checks = ["r1_label", "r2_placement", "r3_address", "r4_scenario", "r5_prohibited"]
    with open(os.path.join(args.out, f"summary_{args.run_name}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tracking_id", "n_images", "address", *checks, "verdict", "reasons"])
        for r in results:
            w.writerow([r["tracking_id"], len(r["images"]), r["address"],
                        *[r["checks"].get(c, {}).get("status", "") for c in checks],
                        r["verdict"], " | ".join(r["reasons"])])

    counts = Counter(r["verdict"] for r in results)
    print("\nsummary:", dict(counts), f"skipped_no_address: {len(skipped)}")


if __name__ == "__main__":
    sys.exit(main())
