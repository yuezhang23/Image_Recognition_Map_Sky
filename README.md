# Image Recognition Map Sky

Tools and reference material for reviewing SpeedX POD (Proof of Delivery) photos. The repo has a script that downloads delivery photos in bulk, the POD photo standard the photos are judged against, and tracking-number metadata for the photos.

## Contents

| File | Description |
|---|---|
| `download.py` | Downloads POD photos from an items JSON file into one folder per tracking number. |
| `POD_standard.md` | The SpeedX POD photo rules (Part A, transcribed from `image_instructions.png`) plus extra guidance for drivers (Part B). |
| `image_instructions.png` | The original SpeedX POD standard sheet in English, Spanish and Chinese. |
| `tracking_address.json` | Maps each tracking number to its delivery address. |

`.gitignore` keeps these out of git: the downloaded images (`valid_images/`), credentials (`.env`, `auth.json`), and the items JSON files (`images*.json`), which contain signed photo URLs.

## Items JSON format

`download.py` reads a JSON list in which each entry looks like this:

```json
{"url": "https://.../photo.jpg?<signature>", "key": "SPXPDK011972610140004853", "i": 1}
```

`key` is the tracking number and `i` is the photo's index for that package.

## Setup

Requires Python 3 and `requests`:

```bash
pip install requests
```

## Usage

```bash
python download.py --items_json images.json [--out path/to/output]
```

The script:

1. Moves any loose images already in the output folder into subfolders named after their tracking number (the part of the filename before the last `_`).
2. Downloads each photo with 4 parallel workers to `<output>/<key>/<key>_<i>.jpg`, where `<i>` is zero-padded to 4 digits. Photos that already exist are skipped, so you can safely re-run it.

If `--out` is omitted, images go to `~/Downloads/delivery task/valid_images`.

> **Note:** The photo URLs are signed links that expire. Regenerate the items JSON if downloads start failing with `403`.

## Output layout

```
valid_images/
├── SPXPDK011972610140004853/
│   ├── SPXPDK011972610140004853_0001.jpg
│   └── SPXPDK011972610140004853_0002.jpg
└── ...
```
