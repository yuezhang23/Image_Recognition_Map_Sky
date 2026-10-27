import json, os, shutil, sys, requests
from concurrent.futures import ThreadPoolExecutor

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}

import argparse
# parse items json directory from command line argument 
parser = argparse.ArgumentParser()
parser.add_argument("--items_json", help="Path to the items JSON file")
args = parser.parse_args()

OUT = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/Downloads/delivery task/valid_images")
os.makedirs(OUT, exist_ok=True)
items = json.load(open(os.path.expanduser(args.items_json), "r", encoding="utf-8"))

def group_existing():
    # Move any loose images in OUT into folders named by the prefix before the last "_"
    moved = 0
    for name in sorted(os.listdir(OUT)):
        src = os.path.join(OUT, name)
        stem, ext = os.path.splitext(name)
        if not os.path.isfile(src) or ext.lower() not in IMAGE_EXTS or "_" not in stem:
            continue
        dest_dir = os.path.join(OUT, stem.rsplit("_", 1)[0])
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name)
        if os.path.exists(dest):
            print("skip (exists):", dest)
            continue
        shutil.move(src, dest)
        moved += 1
    if moved:
        print(f"grouped {moved} existing files")

def grab(it):
    folder = os.path.join(OUT, it["key"])
    path = os.path.join(folder, f"{it['key']}_{it['i']:04d}.jpg")
    # Skip if the prefix folder already exists and already holds this image
    if os.path.isdir(folder) and os.path.isfile(path):
        return
    os.makedirs(folder, exist_ok=True)
    try:
        r = requests.get(it["url"], timeout=30)
        if r.ok:
            open(path, "wb").write(r.content)
        else:
            print("failed", r.status_code, path)
    except Exception as e:
        print("error", path, e)

group_existing()
with ThreadPoolExecutor(4) as ex:
    list(ex.map(grab, items))
print("done")
