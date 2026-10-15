# Image_Recognition_Map_Sky

Lightweight image-recognition utility for checking delivery photos against quality standards.

## What it detects

The tool evaluates a delivery image and reports flaws such as:
- low resolution
- underexposure (too dark)
- overexposure (too bright)
- blur / low detail
- insufficient visible subject area

## Setup

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python delivery_photo_detector.py /path/to/photo.jpg --standards delivery_photo_standards.json
```

The command outputs a JSON report with:
- `passed` boolean
- `quality_score`
- measurements (brightness, sharpness, subject coverage)
- detected `flaws`

## Test

```bash
python -m unittest tests/test_delivery_photo_detector.py
```
