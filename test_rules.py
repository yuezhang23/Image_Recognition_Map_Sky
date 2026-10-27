import unittest

import rules

TID = "SPXPDK005672610220031814"
ADDR = "384 Auburn Station Dr, Auburn, GA 30011"


def img(index, **kw):
    base = {"index": index, "types": [], "quality": "clear", "tracking_numbers_read": [], "label_address_read": None,
            "address_marker_text": [], "package_visible": False, "location_type": "none",
            "placement_description": "", "other_carrier_parcels_visible": False,
            "locker_screen_shows_name_address": False, "face_visible": False, "inside_fenced_or_secure_area": False}
    base.update(kw)
    return base


LABEL = img(1, types=["label"], tracking_numbers_read=[TID])
PLACED = img(2, types=["placement", "address_marker"], address_marker_text=["384"], package_visible=True,
             location_type="doorstep", placement_description="on the mat")


def run(*images, tid=TID, addr=ADDR):
    return rules.evaluate({"images": list(images), "notes": ""}, tid, addr)


class RulesTest(unittest.TestCase):
    def test_good_delivery_passes(self):
        self.assertEqual(run(LABEL, PLACED)["verdict"], "PASS")

    def test_ocr_error_in_tracking_still_matches(self):
        label = img(1, types=["label"], tracking_numbers_read=["SPXPDK0056726I0220031814"])
        self.assertEqual(run(label, PLACED)["checks"]["r1_label"]["status"], "PASS")
        tail = img(1, types=["label"], tracking_numbers_read=["20031814"])
        self.assertEqual(run(tail, PLACED)["checks"]["r1_label"]["status"], "PASS")

    def test_wrong_package(self):
        label = img(1, types=["label"], tracking_numbers_read=["SPXPDK013662610190054282"])
        r = run(label, PLACED)
        self.assertEqual(r["verdict"], "FAIL")
        self.assertIn("wrong_package", r["checks"]["r1_label"]["reason"])

    def test_unreadable_label(self):
        label = img(1, types=["label"], quality="blurry")
        self.assertEqual(run(label, PLACED)["checks"]["r1_label"]["status"], "FAIL")

    def test_address_mismatch(self):
        placed = dict(PLACED, address_marker_text=["386"])
        r = run(LABEL, placed)
        self.assertEqual(r["checks"]["r3_address"]["status"], "FAIL")
        self.assertIn("address_mismatch", r["checks"]["r3_address"]["reason"])

    def test_unit_required(self):
        addr = "91 Market St Apt 218, BETHLEHEM, GA 30620"
        self.assertEqual(rules.parse_address(addr), ("91", "218"))
        self.assertEqual(rules.parse_address("71 Main St, Apt. B, AUBURN, GA 30011"), ("71", "b"))
        self.assertEqual(rules.parse_address("103 Smithwood Dr # 103, Bethlehem, GA 30620"), ("103", None))
        self.assertEqual(rules.parse_address("1910winnst ead place, Loganville, GA 30052"), ("1910", None))
        self.assertEqual(rules.parse_address("71B E Candler St Casa 71 B, Winder, GA 30680"), ("71b", None))
        self.assertEqual(rules.parse_address("Westshore Drive, 2047, CUMMING, GA 30041"), ("2047", None))
        self.assertEqual(rules.parse_address("Eagle Creek Apts, 4280 S Lee St Apt B7 B7, Buford, GA 30518"),
                         ("4280", "b7"))
        self.assertEqual(run(LABEL, PLACED, addr="Main Street, Buford, GA")["checks"]["r3_address"]["status"],
                         "REVIEW")
        building_only = dict(PLACED, address_marker_text=["91"])
        self.assertEqual(run(LABEL, building_only, addr=addr)["checks"]["r3_address"]["status"], "FAIL")
        with_unit = dict(PLACED, address_marker_text=["91", "Apt 218"])
        self.assertEqual(run(LABEL, with_unit, addr=addr)["checks"]["r3_address"]["status"], "PASS")

    def test_gps_fallback(self):
        placed = dict(PLACED, types=["placement", "exterior"], address_marker_text=[])
        gps = img(3, types=["gps_screenshot"])
        self.assertEqual(run(LABEL, placed, gps)["checks"]["r3_address"]["status"], "PASS")
        self.assertEqual(run(LABEL, placed)["checks"]["r3_address"]["status"], "FAIL")

    def test_mailbox_prohibited(self):
        in_mailbox = dict(PLACED, location_type="mailbox")
        self.assertEqual(run(LABEL, in_mailbox)["checks"]["r5_prohibited"]["status"], "FAIL")

    def test_mailbox_as_marker_is_fine(self):
        marker = img(3, types=["address_marker"], address_marker_text=["384"], location_type="none")
        self.assertEqual(run(LABEL, PLACED, marker)["verdict"], "PASS")

    def test_handoff_face(self):
        hand = img(2, types=["handoff"], package_visible=True, location_type="handoff", face_visible=True,
                   address_marker_text=["384"])
        self.assertEqual(run(LABEL, hand)["checks"]["r4_scenario"]["status"], "FAIL")
        hand["face_visible"] = False
        self.assertEqual(run(LABEL, hand)["checks"]["r4_scenario"]["status"], "PASS")

    def test_mailroom_needs_other_parcels(self):
        room = img(2, types=["mailroom"], package_visible=True, location_type="mailroom")
        self.assertEqual(run(LABEL, room)["checks"]["r4_scenario"]["status"], "FAIL")
        room["other_carrier_parcels_visible"] = True
        self.assertEqual(run(LABEL, room)["checks"]["r4_scenario"]["status"], "PASS")

    def test_label_held_in_hand_is_not_a_handoff(self):
        held = img(1, types=["label", "handoff"], tracking_numbers_read=[TID], package_visible=True,
                   location_type="handoff", face_visible=False)
        marker = img(2, types=["address_marker"], address_marker_text=["384"])
        r = run(held, marker)
        self.assertEqual(r["checks"]["r4_scenario"]["status"], "N/A")
        self.assertEqual(r["checks"]["r2_placement"]["status"], "FAIL")
        self.assertIn("label close-ups", r["checks"]["r2_placement"]["reason"])

    def test_placement_typed_other_location_still_counts(self):
        walkway = dict(PLACED, location_type="other", placement_description="on the walkway by the steps")
        self.assertEqual(run(LABEL, walkway)["checks"]["r2_placement"]["status"], "PASS")

    def test_no_observations_is_review(self):
        self.assertEqual(rules.evaluate(None, TID, ADDR)["verdict"], "REVIEW")


if __name__ == "__main__":
    unittest.main()
