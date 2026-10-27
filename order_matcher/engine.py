"""The matching engine: one Choice per order line, with every line of an order in parallel.

For each line:
1. Ask the decider to choose from what this customer ordered in the last 90 days.
   If the chef named a unit, each product is offered once, in that unit when the
   customer buys it that way, so the decider picks the product and step 3 the unit.
2. If confidence is under 0.85, or Jev answers "none of these", search what every
   customer ordered in the last 90 days for products whose names match the line,
   and ask a second time.
3. If the chef named a unit (lb, case, each) and the choice is in a different
   one, switch to the same product in that unit.
4. Lines under 0.90 confidence go to a person for review.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

from .data import Catalog, History, Sku
from .deciders import NONE_OF_THESE, Choice, Decider, Option
from .parse import OrderLine, parse_line, shares_keyword, similarity, split_order

WINDOW_DAYS = 90
RETRY_BELOW = 0.85
REVIEW_BELOW = 0.90
MAX_OPTIONS = 255           # the most options one Jev Choice accepts
SEARCH_LIMIT = 50           # options from the wider search on the second pass
KEEP_FROM_FIRST_PASS = 5    # the first pass's best guesses stay in the second pass


@dataclass(frozen=True)
class LineMatch:
    line: OrderLine
    sku: Sku | None  # None when nothing in the search matched
    confidence: float
    second_pass: bool
    unit_fixed: bool

    @property
    def needs_review(self) -> bool:
        return self.sku is None or self.confidence < REVIEW_BELOW


class Matcher:
    def __init__(self, catalog: Catalog, history: History, decider: Decider, workers: int = 16):
        self.catalog = catalog
        self.history = history
        self.decider = decider
        self.workers = workers

    def match_order(self, text: str, customer_id: str, order_date: date) -> list[LineMatch]:
        lines = [parse_line(part) for part in split_order(text)]
        options = self.customer_options(customer_id, order_date)
        buyers = self.history.buyers(order_date, WINDOW_DAYS)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return list(pool.map(lambda line: self.match_line(line, options, buyers), lines))

    def customer_options(self, customer_id: str, order_date: date) -> list[Option]:
        counts = self.history.counts(customer_id, order_date, WINDOW_DAYS)
        return [Option(self.catalog[sku], n,
                       f"This customer ordered it {n} times in the last {WINDOW_DAYS} days")
                for sku, n in counts.most_common(MAX_OPTIONS)]

    def search_options(self, line: OrderLine, buyers: Counter[str]) -> list[Option]:
        """SKUs any customer ordered recently that share a word with the line, best first."""
        scored = []
        for sku_id, n in buyers.items():
            sku = self.catalog[sku_id]
            if shares_keyword(line.item, sku.name):
                note = f"{n} customers ordered it in the last {WINDOW_DAYS} days"
                scored.append((similarity(line.item, sku.name), Option(sku, n, note)))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [option for _, option in scored[:SEARCH_LIMIT]]

    def match_line(self, line: OrderLine, options: list[Option], buyers: Counter[str]) -> LineMatch:
        options = _one_per_product(options, line.unit)
        first = self._ask(line, options)
        best = first if first is not None and first.choice != NONE_OF_THESE else None
        second_pass = best is None or best.confidence < RETRY_BELOW
        if second_pass:
            kept = []
            if first is not None:
                top = sorted(first.probabilities, key=first.probabilities.get, reverse=True)
                kept = [o for o in options if o.sku.sku in top[:KEEP_FROM_FIRST_PASS]]
            wider = _dedupe(kept + self.search_options(line, buyers))
            retry = self._ask(line, _one_per_product(wider, line.unit))
            if (retry is not None and retry.choice != NONE_OF_THESE
                    and (best is None or retry.confidence > best.confidence)):
                best = retry
        if best is None:
            return LineMatch(line, None, 0.0, second_pass, unit_fixed=False)
        sku, unit_fixed = self.fix_unit(self.catalog[best.choice], line.unit)
        return LineMatch(line, sku, best.confidence, second_pass, unit_fixed)

    def fix_unit(self, sku: Sku, unit: str | None) -> tuple[Sku, bool]:
        """Switch to the unit the chef named, if the product is sold in it."""
        if unit and sku.unit != unit:
            other = self.catalog.variant(sku.product, unit)
            if other is not None:
                return other, True
        return sku, False

    def _ask(self, line: OrderLine, options: list[Option]) -> Choice | None:
        return self.decider.choose(line, options) if options else None


def _one_per_product(options: list[Option], unit: str | None) -> list[Option]:
    """When the chef named a unit, keep one option per product: the one in that unit
    if there is one, otherwise the first (most ordered) one. Otherwise keep them all."""
    if not unit:
        return options
    by_product: dict[str, Option] = {}
    for o in options:
        current = by_product.get(o.sku.product)
        if current is None or (o.sku.unit == unit and current.sku.unit != unit):
            by_product[o.sku.product] = o
    return list(by_product.values())


def _dedupe(options: list[Option]) -> list[Option]:
    seen, result = set(), []
    for o in options:
        if o.sku.sku not in seen:
            seen.add(o.sku.sku)
            result.append(o)
    return result
