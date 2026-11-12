"""Merge a delivery_data export ({tracking_id: {"address": ..., "images": [url, ...]}}) into
tracking_address.json and valid_images/, without duplicates.

python import_delivery_data.py "delivery_data (1).json"

- Addresses: new tracking IDs are added; existing ones are kept (a different address is reported, not overwritten).
- Photos: the same photo URL listed twice for one tracking ID is downloaded once, and a downloaded file whose
  bytes match a photo already in that folder is dropped. A photo shared by several tracking IDs (several
  packages left together) is kept in each folder, since each package needs its own proof.
"""
import argparse, hashlib, json, os
from concurrent.futures import ThreadPoolExecutor

import requests


def blob_id(url):
    # signed URLs differ per export only in the query string
    return url.split("?")[0]


def md5(data):
    return hashlib.md5(data).hexdigest()


def download(job):
    key, i, url, path = job
    try:
        r = requests.get(url, timeout=30)
    except Exception as e:
        return key, path, None, f"error {e}"
    if not r.ok:
        return key, path, None, f"failed {r.status_code}"
    return key, path, r.content, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data", help="delivery_data export JSON")
    parser.add_argument("--addresses", default="tracking_address.json")
    parser.add_argument("--images", default="valid_images")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    data = json.load(open(args.data, encoding="utf-8"))
    addresses = json.load(open(args.addresses, encoding="utf-8"))

    added, conflicts, no_address = 0, [], 0
    for key, item in data.items():
        addr = (item.get("address") or "").strip()
        if not addr:
            no_address += 1
        elif key not in addresses:
            addresses[key] = addr
            added += 1
        elif addresses[key].strip() != addr:
            conflicts.append((key, addresses[key], addr))
    with open(args.addresses, "w", encoding="utf-8") as f:
        json.dump(addresses, f, indent=2, ensure_ascii=False)
        f.write("\n")

    jobs, url_dups, no_images = [], 0, 0
    hashes = {}  # folder -> md5s of the photos it holds
    for key, item in data.items():
        urls = list(dict.fromkeys(item.get("images") or []))
        unique = list({blob_id(u): u for u in urls}.values())
        url_dups += len(item.get("images") or []) - len(unique)
        if not unique:
            no_images += 1
            continue
        folder = os.path.join(args.images, key)
        os.makedirs(folder, exist_ok=True)
        existing = sorted(os.listdir(folder))
        hashes[key] = {md5(open(os.path.join(folder, n), "rb").read()) for n in existing}
        for i, url in enumerate(unique, len(existing) + 1):
            jobs.append((key, i, url, os.path.join(folder, f"{key}_{i:04d}.jpg")))

    saved, byte_dups, errors = 0, 0, []
    with ThreadPoolExecutor(args.workers) as ex:
        for key, path, content, error in ex.map(download, jobs):
            if error:
                errors.append(f"{error} {path}")
                continue
            h = md5(content)
            if h in hashes[key]:
                byte_dups += 1
                continue
            hashes[key].add(h)
            open(path, "wb").write(content)
            saved += 1
    for key in hashes:
        folder = os.path.join(args.images, key)
        if not os.listdir(folder):
            os.rmdir(folder)

    for e in errors:
        print(e)
    for key, old, new in conflicts:
        print(f"address conflict, kept existing: {key}: {old!r} vs {new!r}")
    print(f"addresses: {added} added, {len(conflicts)} conflicts, {no_address} entries without address")
    print(f"photos: {saved} saved, {url_dups} duplicate URLs skipped, {byte_dups} identical files skipped, "
          f"{len(errors)} failed; {no_images} entries without photos")


if __name__ == "__main__":
    main()
