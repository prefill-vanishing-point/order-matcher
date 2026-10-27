"""Accuracy check: run the engine on labelled orders and compare with the right answers."""
import statistics
import time
from dataclasses import dataclass
from datetime import date

from .data import Sku
from .engine import REVIEW_BELOW, LineMatch, Matcher


@dataclass(frozen=True)
class Result:
    order_id: str
    match: LineMatch
    expected: Sku

    @property
    def exact(self) -> bool:
        return self.match.sku is not None and self.match.sku.sku == self.expected.sku

    @property
    def right_product(self) -> bool:
        return self.match.sku is not None and self.match.sku.product == self.expected.product


def run(matcher: Matcher, orders: list[dict]) -> tuple[list[Result], list[float]]:
    """Match every order. Returns one result per line and the seconds each order took."""
    results, latencies = [], []
    for order in orders:
        start = time.perf_counter()
        matches = matcher.match_order(order["text"], order["customer_id"],
                                      date.fromisoformat(order["date"]))
        latencies.append(time.perf_counter() - start)
        expected = order["lines"]
        if len(matches) != len(expected):
            raise ValueError(f"{order['order_id']}: found {len(matches)} lines, "
                             f"expected {len(expected)}")
        results += [Result(order["order_id"], m, matcher.catalog[e["sku"]])
                    for m, e in zip(matches, expected)]
    return results, latencies


def report(results: list[Result], latencies: list[float], decider_name: str,
           show_errors: int = 0) -> str:
    def pct(part: int, whole: int) -> str:
        return f"{100 * part / whole:.1f}%" if whole else "n/a"

    n = len(results)
    passed = [r for r in results if not r.match.needs_review]
    wrong = [r for r in results if not r.exact]
    caught = [r for r in wrong if r.match.needs_review]
    p50 = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) > 1 else latencies[0]

    out = [
        f"Decider: {decider_name}    Orders: {len(latencies)}    Lines: {n}",
        "",
        f"Exact item + unit       {pct(sum(r.exact for r in results), n)}",
        f"Right product           {pct(sum(r.right_product for r in results), n)}",
        f"Asked twice             {pct(sum(r.match.second_pass for r in results), n)} of lines",
        f"Unit rule applied       {pct(sum(r.match.unit_fixed for r in results), n)} of lines",
        "",
        f"Confidence >= {REVIEW_BELOW:.2f}     {pct(len(passed), n)} of lines go straight through, "
        f"and {pct(sum(r.exact for r in passed), len(passed))} of those are right",
        f"Confidence < {REVIEW_BELOW:.2f}      {pct(n - len(passed), n)} of lines go to review",
        f"Wrong lines caught      {pct(len(caught), len(wrong))} of wrong lines were sent to review",
        "",
        f"Latency per order       p50 {p50 * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms",
    ]
    if show_errors and wrong:
        out += ["", f"First {min(show_errors, len(wrong))} of {len(wrong)} wrong lines:"]
        for r in wrong[:show_errors]:
            got = r.match.sku.sku if r.match.sku else "none"
            out.append(f"  {r.order_id}  {r.match.line.text!r:34} got {got:7} "
                       f"({r.match.confidence:.2f})  expected {r.expected.sku}")
    return "\n".join(out)
