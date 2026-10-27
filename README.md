# Image Recognition Map Sky

Tools and reference material for reviewing SpeedX POD (Proof of Delivery) photos. The repo has a script that downloads delivery photos in bulk, the POD photo standard the photos are judged against, and tracking-number metadata for the photos.

## Contents

| File | Description |
|---|---|
| `download.py` | Downloads POD photos from an items JSON file into one folder per tracking number. |
| `POD_standard.md` | The SpeedX POD photo rules (Part A, transcribed from `image_instructions.png`) plus extra guidance for drivers (Part B). |
| `image_instructions.png` | The original SpeedX POD standard sheet in English, Spanish and Chinese. |
| `tracking_address.json` | Maps each tracking number to its delivery address. |
| `pod_check.py` | Checks each tracking number's photos against Part A of `POD_standard.md`. |
| `llm_vendors.py` | Vision LLM clients for Anthropic, OpenAI and DeepSeek. |
| `visualize.py` | Builds an HTML report from one or more `results_*.jsonl` files. |
| `rules.py` | The rules that turn the LLM's observations into a verdict. `test_rules.py` tests them. |

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

## POD compliance check

`pod_check.py` decides whether the photos in each `valid_images/<tracking_id>/` folder meet Part A of `POD_standard.md`.

The work is split in two:

1. **One vision LLM call per folder.** All of the folder's photos are sent in a single request, and the Part A text is taken from `POD_standard.md` at run time. The model only reports what it sees in each photo: image type, tracking numbers read, visible house or unit numbers, where the package sits, faces, and so on. It does not decide pass or fail.
2. **Python rules (`rules.py`) decide the verdict.** They compare those observations with the expected address in `tracking_address.json`:

| Check | Passes when |
|---|---|
| `r1_label` | A tracking number read from a label matches the folder ID. Up to 2 OCR character errors are allowed, as is a match on the last 8 digits. |
| `r2_placement` | The package is visible in an identifiable spot (door, porch, mailroom, and so on). |
| `r3_address` | A visible marker shows the expected house number, plus the unit number if the address has one. Without a marker, a building exterior plus a GPS screenshot is accepted. |
| `r4_scenario` | Mailroom: other carriers' parcels are visible. Locker: the screen shows the recipient's name and address. Hand-off: no faces. Farm: the package is inside a fence. |
| `r5_prohibited` | The package is not in a mailbox, at USPS, in a public area, or on open ground. |

The overall verdict is `FAIL` if any check fails. It is `REVIEW` if the LLM returned nothing usable. Otherwise it is `PASS`. Tracking IDs that are not in `tracking_address.json` are skipped and printed as `skipped_no_address`.

### Setup

```bash
pip install anthropic openai python-dotenv pillow pydantic
```

API keys are read from `.env`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `DEEPSEEK_API_KEY`.

### Usage

```bash
python pod_check.py --vendor anthropic                     # all folders that have an address
python pod_check.py --vendor openai --limit 20 --workers 8
python pod_check.py --vendor deepseek --ids SPXPDK005672610220031814
python pod_check.py --vendor openai --model gpt-6-luna --sample 50 --seed 42   # 50 random folders
python -m unittest test_rules                              # rule tests, no API calls
```

| Vendor | Default model | Override |
|---|---|---|
| `anthropic` | `claude-opus-5-5` | `--model` |
| `openai` | `gpt-5.5` | `--model` |
| `deepseek` | `deepseek-flash` | `--model` |

Avoid `deepseek-v4-pro`: it accepts images but ignores them. Before each run, the script checks that the model can read a number on a test image, and stops if it can't.

### Output (`results/`, git-ignored)

- `raw/<vendor>_<model>/<tracking_id>.json` stores the LLM's observations. Re-runs reuse these and make no new API calls; pass `--force` to call the API again.
- `results_<vendor>_<model>.jsonl` has one record per folder: the observations, each check's status and reason, and the verdict.
- `summary_<vendor>_<model>.csv` has the columns `tracking_id, n_images, address, r1..r5, verdict, reasons`.

Both files are rewritten on every run and contain only the folders checked in that run.

### Report

```bash
python visualize.py results/results_openai_gpt-6-luna.jsonl [other results_*.jsonl ...] [--out results/report.html]
```

The script writes one self-contained HTML page with light and dark themes. Click a panel's title to collapse or expand it. The first file is the main run, and every chart is drawn for it:

- headline tiles: the highest pass rate among the runs that checked at least half of the main run's folders, and the main run's verdict counts;
- the outcome of each check, R1–R5;
- failure reasons, grouped by type;
- verdict by number of photos;
- verdict by where the package was left;
- photo coverage by type, and photo quality;
- a table of every folder with its check badges, reasons and photo thumbnails, filterable by verdict.

Each additional file adds a model comparison section. It shows each run's verdict mix and how often runs agree on folders they share. The report re-scores every run from its saved observations with the current `rules.py`, so runs made under older rules stay comparable. The thumbnails link to the photos in `valid_images/`, so the report only works on this machine.
