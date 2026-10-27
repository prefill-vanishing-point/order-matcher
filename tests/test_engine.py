import unittest
from datetime import date, timedelta

from order_matcher.data import Catalog, History, Purchase, Sku
from order_matcher.deciders import (NONE_DESCRIPTION, NONE_OF_THESE, Choice, LocalDecider,
                                    Option, jev_confidence, jev_request)
from order_matcher.engine import Matcher
from order_matcher.parse import parse_line

DAY = date(2026, 10, 26)


def sku(code, name, unit):
    label = {"CS": "case", "LB": "per lb", "EA": "each"}[unit]
    return Sku(f"{code}-{unit}", code, name, unit, f"{name}, {label}")


def bought(customer, sku_id, *days_ago):
    return [Purchase(customer, DAY - timedelta(days=d), sku_id) for d in days_ago]


CATALOG = Catalog([
    sku("BAN", "Bananas", "CS"), sku("BAN", "Bananas", "LB"),
    sku("KAL", "Kale, green", "CS"), sku("KAL", "Kale, green", "EA"),
    sku("ASP", "Asparagus", "CS"),
    sku("MCR", "Mushrooms, crimini (baby bella)", "CS"),
])
HISTORY = History(
    bought("C1", "BAN-CS", 3, 10, 17) + bought("C1", "KAL-CS", 5, 12) + bought("C1", "MCR-CS", 4)
    + bought("C1", "ASP-CS", 120)  # outside the 90-day window
    + bought("C2", "ASP-CS", 2, 9)
    + bought("C3", "BAN-CS", 2, 8, 15) + bought("C3", "BAN-LB", 6)
)


class ScriptedDecider:
    """Gives the answers it was handed, in order, and records the options it was offered."""

    name = "scripted"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.offered = []

    def choose(self, line, options):
        self.offered.append([o.sku.sku for o in options])
        choice, confidence = self.answers.pop(0)
        return Choice(choice, confidence, {choice: confidence})


class MatcherTest(unittest.TestCase):
    def setUp(self):
        self.matcher = Matcher(CATALOG, HISTORY, LocalDecider())

    def match(self, text, customer="C1"):
        return self.matcher.match_order(text, customer, DAY)

    def test_matches_from_customer_history(self):
        [m] = self.match("2 cases crimini")
        self.assertEqual(m.sku.sku, "MCR-CS")
        self.assertFalse(m.second_pass)
        self.assertFalse(m.needs_review)

    def test_unit_rule_switches_to_the_unit_the_chef_named(self):
        [m] = self.match("5 lb bananas")
        self.assertEqual(m.sku.sku, "BAN-LB")
        self.assertTrue(m.unit_fixed)

    def test_second_pass_finds_products_the_customer_has_not_ordered_recently(self):
        [m] = self.match("a case of asparagus")
        self.assertEqual(m.sku.sku, "ASP-CS")
        self.assertTrue(m.second_pass)

    def test_every_line_of_an_order_is_matched(self):
        matches = self.match("5 pounds bananas, a case of kale\n2 cases of crimini")
        self.assertEqual([m.sku.sku for m in matches], ["BAN-LB", "KAL-CS", "MCR-CS"])

    def test_line_with_nothing_to_match_goes_to_review(self):
        [m] = self.match("a case of durian", customer="C9")
        self.assertIsNone(m.sku)
        self.assertTrue(m.needs_review)


class DecisionFlowTest(unittest.TestCase):
    def match(self, decider, text, customer):
        return Matcher(CATALOG, HISTORY, decider).match_order(text, customer, DAY)

    def test_none_of_these_triggers_the_wider_search(self):
        decider = ScriptedDecider((NONE_OF_THESE, 0.95), ("ASP-CS", 0.97))
        [m] = self.match(decider, "a case of asparagus", "C1")
        self.assertEqual(m.sku.sku, "ASP-CS")
        self.assertTrue(m.second_pass)
        self.assertIn("ASP-CS", decider.offered[1])

    def test_none_of_these_twice_means_no_match(self):
        decider = ScriptedDecider((NONE_OF_THESE, 0.95), (NONE_OF_THESE, 0.95))
        [m] = self.match(decider, "a case of asparagus", "C1")
        self.assertIsNone(m.sku)
        self.assertTrue(m.needs_review)

    def test_named_unit_offers_each_product_once_in_that_unit(self):
        decider = ScriptedDecider(("BAN-LB", 0.99))
        self.match(decider, "5 lb bananas", "C3")
        self.assertEqual(decider.offered[0], ["BAN-LB"])

    def test_no_unit_offers_every_unit(self):
        decider = ScriptedDecider(("BAN-CS", 0.99))
        self.match(decider, "bananas x2", "C3")
        self.assertEqual(decider.offered[0], ["BAN-CS", "BAN-LB"])


class JevFormatTest(unittest.TestCase):
    def test_confidence_matches_the_example_in_jev_docs(self):
        self.assertAlmostEqual(jev_confidence({"angry": 0.15, "calm": 0.8, "excited": 0.05}), 0.7)

    def test_request_offers_skus_and_none_of_these_as_choices(self):
        options = [Option(CATALOG["MCR-CS"], 4, "This customer ordered it 4 times in the last 90 days")]
        body = jev_request(parse_line("2 cs crimini"), options)
        question = body["questions"]["item"]
        self.assertEqual(body["state"], "2 cs crimini")
        self.assertEqual(question["type"], "choice")
        self.assertEqual(question["criteria"], {
            "MCR-CS": "Mushrooms, crimini (baby bella), case. "
                      "This customer ordered it 4 times in the last 90 days.",
            NONE_OF_THESE: NONE_DESCRIPTION})


if __name__ == "__main__":
    unittest.main()
