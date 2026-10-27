import unittest

from order_matcher.parse import parse_line, similarity, split_order


class ParseLineTest(unittest.TestCase):
    def check(self, text, qty, unit, item):
        line = parse_line(text)
        self.assertEqual((line.qty, line.unit, line.item), (qty, unit, item))

    def test_quantity_and_unit_first(self):
        self.check("5 pounds bananas", 5, "LB", "bananas")

    def test_a_case_of(self):
        self.check("a case of kale", 1, "CS", "kale")

    def test_pound_sign_after_item(self):
        self.check("bananas 5#", 5, "LB", "bananas")

    def test_unit_attached_to_number(self):
        self.check("2cs crimini", 2, "CS", "crimini")

    def test_no_unit(self):
        self.check("cilantro x3", 3, None, "cilantro")

    def test_bunches_count_as_each(self):
        self.check("2 bunches flat leaf parsley", 2, "EA", "flat leaf parsley")

    def test_accents_are_dropped(self):
        self.check("10 lb jalapeños", 10, "LB", "jalapenos")


class SplitOrderTest(unittest.TestCase):
    def test_commas_newlines_and_semicolons(self):
        self.assertEqual(split_order("5 lb bananas, cs kale\n2 cs crimini; 3 limes"),
                         ["5 lb bananas", "cs kale", "2 cs crimini", "3 limes"])


class SimilarityTest(unittest.TestCase):
    def test_close_spelling_beats_a_different_product(self):
        self.assertGreater(similarity("romas", "Tomatoes, roma"),
                           similarity("romas", "Lettuce, romaine"))


if __name__ == "__main__":
    unittest.main()
