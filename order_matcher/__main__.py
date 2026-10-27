"""Command line for the order matcher.

    python -m order_matcher customers
    python -m order_matcher match C007 "5 lb bananas, cs kale, 2 cases crimini"
    python -m order_matcher evaluate
    python -m order_matcher serve
"""
import argparse
import json
import logging
import os
import sys
from datetime import date

from .data import load, load_orders
from .deciders import JEV_KEY_ENV, Decider, JevDecider, LocalDecider, jev_request
from .engine import WINDOW_DAYS, Matcher
from .evaluate import report, run
from .parse import parse_line, split_order
from .web import App, serve


def make_decider(name: str) -> Decider:
    if name == "auto":
        name = "jev" if os.environ.get(JEV_KEY_ENV) else "local"
    if name == "local":
        return LocalDecider()
    try:
        return JevDecider()
    except RuntimeError as e:
        sys.exit(str(e))


def cmd_customers(args, catalog, history, customers):
    day = history.next_day
    for cid, name in customers.items():
        products = []
        for sku, _ in history.counts(cid, day, WINDOW_DAYS).most_common():
            if catalog[sku].name not in products:
                products.append(catalog[sku].name)
        print(f"{cid}  {name:20}  {len(products):2} products, e.g. {'; '.join(products[:3])}")


def cmd_match(args, catalog, history, customers):
    if args.customer not in customers:
        sys.exit(f"Unknown customer {args.customer}. See: python -m order_matcher customers")
    day = date.fromisoformat(args.date) if args.date else history.next_day

    if args.show_request:
        options = Matcher(catalog, history, LocalDecider()).customer_options(args.customer, day)
        line = parse_line(split_order(args.order)[0])
        print(json.dumps(jev_request(line, options), indent=2))
        return

    decider = make_decider(args.decider)
    matches = Matcher(catalog, history, decider).match_order(args.order, args.customer, day)
    print(f"{customers[args.customer]} ({args.customer}), {day}, decider: {decider.name}\n")
    print(f"{'Line':28} {'Qty':>4}  {'SKU':7} {'Item':46} {'Conf':>4}  Status")
    for m in matches:
        notes = [n for n, on in (("asked twice", m.second_pass), ("unit fixed", m.unit_fixed)) if on]
        status = ("review" if m.needs_review else "ok") + (f" ({', '.join(notes)})" if notes else "")
        sku = m.sku.sku if m.sku else "-"
        item = m.sku.description if m.sku else "no match"
        print(f"{m.line.text[:28]:28} {m.line.qty:>4g}  {sku:7} {item[:46]:46} "
              f"{m.confidence:4.2f}  {status}")


def cmd_evaluate(args, catalog, history, customers):
    decider = make_decider(args.decider)
    results, latencies = run(Matcher(catalog, history, decider), load_orders(args.set))
    print(report(results, latencies, decider.name, args.show_errors))


def cmd_serve(args, catalog, history, customers):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    serve(App(catalog, history, customers, make_decider(args.decider)), args.host, args.port)


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(errors="replace")  # some Windows consoles can't print every character
    parser = argparse.ArgumentParser(prog="python -m order_matcher",
                                     description="Match restaurant order lines to catalog SKUs.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("customers", help="list customers and what they order")

    match = sub.add_parser("match", help="match one order")
    match.add_argument("customer", help="customer ID, e.g. C007")
    match.add_argument("order", help='order text, e.g. "5 lb bananas, cs kale, 2 cases crimini"')
    match.add_argument("--date", help="order date, YYYY-MM-DD (default: the day after the history ends)")
    match.add_argument("--show-request", action="store_true",
                       help="print the Jev request for the first line instead of matching")

    evaluate = sub.add_parser("evaluate", help="accuracy check on the labelled orders")
    evaluate.add_argument("--set", choices=["dev", "test"], default="test")
    evaluate.add_argument("--show-errors", type=int, default=0, metavar="N",
                          help="list the first N wrong lines")

    serve_cmd = sub.add_parser("serve", help="run the web app")
    serve_cmd.add_argument("--host", default="127.0.0.1",
                           help="address to listen on (use 0.0.0.0 when hosting)")
    serve_cmd.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)),
                           help="port to listen on (default: $PORT, or 8000)")

    for p in (match, evaluate, serve_cmd):
        p.add_argument("--decider", choices=["auto", "jev", "local"], default="auto",
                       help=f"jev needs {JEV_KEY_ENV}; auto uses jev when it's set")

    args = parser.parse_args(argv)
    commands = {"customers": cmd_customers, "match": cmd_match, "evaluate": cmd_evaluate,
                "serve": cmd_serve}
    commands[args.command](args, *load())


if __name__ == "__main__":
    main()
