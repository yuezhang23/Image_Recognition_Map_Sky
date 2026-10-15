from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat

DEFAULT_STANDARDS: dict[str, float] = {
    "min_width": 640,
    "min_height": 480,
    "min_brightness": 60,
    "max_brightness": 210,
    "min_sharpness": 120,
    "min_subject_coverage": 0.18,
}


def _variance(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _merge_standards(standards: dict[str, float] | None) -> dict[str, float]:
    merged = DEFAULT_STANDARDS.copy()
    if standards:
        merged.update(standards)
    return merged


def analyze_delivery_photo(image_path: str | Path, standards: dict[str, float] | None = None) -> dict[str, Any]:
    """Analyze a delivery photo and report flaws against quality standards."""
    thresholds = _merge_standards(standards)
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    grayscale = image.convert("L")

    brightness = ImageStat.Stat(grayscale).mean[0]

    edge_values = list(grayscale.filter(ImageFilter.FIND_EDGES).get_flattened_data())
    sharpness = _variance([float(v) for v in edge_values])

    gray_values = list(grayscale.get_flattened_data())
    subject_pixels = sum(1 for pixel in gray_values if abs(pixel - brightness) >= 25)
    subject_coverage = subject_pixels / max(len(gray_values), 1)

    flaws: list[dict[str, Any]] = []

    if width < thresholds["min_width"] or height < thresholds["min_height"]:
        flaws.append(
            {
                "code": "LOW_RESOLUTION",
                "message": "Image resolution is below required minimum.",
                "measured": {"width": width, "height": height},
                "expected": {
                    "min_width": thresholds["min_width"],
                    "min_height": thresholds["min_height"],
                },
            }
        )

    if brightness < thresholds["min_brightness"]:
        flaws.append(
            {
                "code": "TOO_DARK",
                "message": "Image is too dark for reliable package verification.",
                "measured": round(brightness, 2),
                "expected_min": thresholds["min_brightness"],
            }
        )
    elif brightness > thresholds["max_brightness"]:
        flaws.append(
            {
                "code": "TOO_BRIGHT",
                "message": "Image is overexposed for reliable package verification.",
                "measured": round(brightness, 2),
                "expected_max": thresholds["max_brightness"],
            }
        )

    if sharpness < thresholds["min_sharpness"]:
        flaws.append(
            {
                "code": "BLURRY",
                "message": "Image appears blurry and lacks detail.",
                "measured": round(sharpness, 2),
                "expected_min": thresholds["min_sharpness"],
            }
        )

    if subject_coverage < thresholds["min_subject_coverage"]:
        flaws.append(
            {
                "code": "INSUFFICIENT_SUBJECT",
                "message": "Delivery package area is too small or not clearly visible.",
                "measured": round(subject_coverage, 4),
                "expected_min": thresholds["min_subject_coverage"],
            }
        )

    checks_total = 5
    checks_failed = len(flaws)
    quality_score = max(0.0, round((checks_total - checks_failed) / checks_total, 3))

    return {
        "passed": checks_failed == 0,
        "quality_score": quality_score,
        "measurements": {
            "width": width,
            "height": height,
            "brightness": round(brightness, 2),
            "sharpness": round(sharpness, 2),
            "subject_coverage": round(subject_coverage, 4),
        },
        "flaws": flaws,
        "standards": thresholds,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect delivery photo flaws against configurable quality standards."
    )
    parser.add_argument("image_path", help="Path to the delivery photo")
    parser.add_argument(
        "--standards",
        help="Optional JSON file with standard threshold overrides",
    )
    args = parser.parse_args()

    standards = None
    if args.standards:
        standards = json.loads(Path(args.standards).read_text())

    result = analyze_delivery_photo(args.image_path, standards)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
