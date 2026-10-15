import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from delivery_photo_detector import analyze_delivery_photo


class DeliveryPhotoDetectorTests(unittest.TestCase):
    def test_clear_and_well_lit_photo_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "good.png"
            image = Image.new("RGB", (800, 600), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((150, 120, 650, 520), fill=(120, 120, 120))
            for x in range(150, 650, 20):
                draw.line((x, 120, x, 520), fill=(20, 20, 20), width=2)
            image.save(image_path)

            result = analyze_delivery_photo(image_path)

            self.assertTrue(result["passed"])
            self.assertEqual(result["flaws"], [])

    def test_dark_low_resolution_photo_fails_with_expected_flaws(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "bad.png"
            image = Image.new("RGB", (320, 240), "black")
            image.save(image_path)

            result = analyze_delivery_photo(image_path)

            self.assertFalse(result["passed"])
            flaw_codes = {flaw["code"] for flaw in result["flaws"]}
            self.assertIn("LOW_RESOLUTION", flaw_codes)
            self.assertIn("TOO_DARK", flaw_codes)
            self.assertIn("BLURRY", flaw_codes)
            self.assertIn("INSUFFICIENT_SUBJECT", flaw_codes)


if __name__ == "__main__":
    unittest.main()
