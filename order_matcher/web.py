"""The order matcher as a web app: a page for trying orders and a small JSON API behind it.

Jev is called from the server, so the API key never reaches the browser. Limits on
order size, orders per visitor and orders per day keep a public demo from spending
much of the key's credit, and repeated orders are answered from a cache.

    python -m order_matcher serve      # then open http://127.0.0.1:8000
"""
import json
import logging
import os
import threading
import time
import urllib.error
from collections import OrderedDict, defaultdict, deque

from .data import Catalog, History, Sku
from .deciders import Decider, JevDecider
from .engine import REVIEW_BELOW, WINDOW_DAYS, LineMatch, Matcher
from .parse import split_order

log = logging.getLogger("order_matcher.web")

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
SECURITY_HEADERS = [
    ("Content-Security-Policy",
     "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
     "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
     "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),
]
JSON_TYPE = "application/json; charset=utf-8"

MAX_BODY_BYTES = 16_000
MAX_ORDER_CHARS = 2_000
MAX_LINES = 25
CACHE_SIZE = 256

# From `python -m order_matcher evaluate` on the 100 held-out test orders (716 lines).
TEST_RESULTS = {
    "jev": {"lines": 716, "exact": "96.2%", "skip_review": "79.7%", "wrong_flagged": "100%"},
    "local stand-in": {"lines": 716, "exact": "92.6%", "skip_review": "74.7%", "wrong_flagged": "90.6%"},
}

EXAMPLES = [
    {"customer_id": "C003", "label": "weekly reorder",
     "text": "2 cs portobellos\n5# limes\nstrawbs x3\na case of kale\nyukon golds 2\n"
             "2 cases shiitake\nchives 1 cs\nmixed greens 1 cs\ncs grass"},
    {"customer_id": "C002", "label": "text message",
     "text": "dill x2, 6 ea pineapple, 2 cs asparagus, baby broccoli 3 cs, peeled garlic 1 cs, "
             "shanghai bok choy 2, 10# white onions, 1 cs rocket"},
    {"customer_id": "C014", "label": "voicemail in capitals",
     "text": "RAZZ 2 CS\nBASIL 3 LB\n1 CS CARROTS\nGREEN ONIONS 12 BUNCHES\n2 CS BUTTON MUSHROOMS\n"
             "HOTHOUSE CUKES 1 CS\n4 CS ROMAS\n5 LB THAI BASIL"},
    {"customer_id": "C005", "label": "typos",
     "text": "10 lb shitake, carots 5#, 1 cs pinapple, granny smith 2 cs, chives x1, "
             "1 case lemmons, 3# haricot vert, spinach 2 cs"},
]


class RateLimiter:
    """Allows `limit` events per `window` seconds for each key."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._events: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] > self.window:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            if len(self._events) > 10_000:  # forget visitors with nothing left in the window
                for k in [k for k, v in self._events.items() if not v]:
                    del self._events[k]
            return True


class App:
    """A WSGI application. Any WSGI server can run it; `serve` below uses waitress."""

    def __init__(self, catalog: Catalog, history: History, customers: dict[str, str],
                 decider: Decider, *, per_visitor: int | None = None, per_day: int | None = None,
                 trust_proxy: bool | None = None):
        self.catalog = catalog
        self.history = history
        self.customers = customers
        self.decider = decider
        self.matcher = Matcher(catalog, history, decider)
        self.order_date = history.next_day
        self.per_visitor = RateLimiter(_setting(per_visitor, "ORDERS_PER_VISITOR", 20), 600)
        self.per_day = RateLimiter(_setting(per_day, "ORDERS_PER_DAY", 300), 86_400)
        # Hosts like Render put the visitor's address in X-Forwarded-For. The first entry
        # can be forged, but the daily cap still bounds what a forger can spend.
        self.trust_proxy = (os.environ.get("TRUST_PROXY") == "1"
                            if trust_proxy is None else trust_proxy)
        self._cache: OrderedDict[tuple[str, str], dict] = OrderedDict()
        self._cache_lock = threading.Lock()
        web_dir = os.path.join(os.path.dirname(__file__), "web")
        self._static = {}
        for path, (name, content_type) in STATIC_FILES.items():
            with open(os.path.join(web_dir, name), "rb") as f:
                self._static[path] = (f.read(), content_type)
        self._bootstrap = _json_bytes(self._bootstrap_payload())

    def __call__(self, environ, start_response):
        started = time.perf_counter()
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/") or "/"
        try:
            status, headers, body = self._route(method, path, environ)
        except Exception:
            log.exception("Unexpected error on %s %s", method, path)
            status, headers, body = _error(500, "Something went wrong on the server. "
                                                "Try again in a moment.")
        start_response(status, headers + SECURITY_HEADERS)
        log.info("%s %s %s %.0fms", method, path, status[:3], (time.perf_counter() - started) * 1000)
        return [b"" if method == "HEAD" else body]

    def _route(self, method: str, path: str, environ) -> tuple[str, list, bytes]:
        if path in self._static:
            if method not in ("GET", "HEAD"):
                return _error(405, "Open this address in a browser.", allow="GET, HEAD")
            body, content_type = self._static[path]
            return _response(200, body, content_type)
        if path == "/healthz":
            return _response(200, b"ok", "text/plain; charset=utf-8")
        if path == "/api/bootstrap":
            if method not in ("GET", "HEAD"):
                return _error(405, "Use GET for this address.", allow="GET, HEAD")
            return _response(200, self._bootstrap, JSON_TYPE)
        if path == "/api/match":
            if method != "POST":
                return _error(405, "Use POST to match an order.", allow="POST")
            return self._match(environ)
        return _error(404, "There's nothing at this address.")

    def _match(self, environ) -> tuple[str, list, bytes]:
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            return _error(413, f"That order is too long. Keep it under {MAX_ORDER_CHARS:,} characters.")
        try:
            body = json.loads(environ["wsgi.input"].read(length) or b"null")
        except (ValueError, UnicodeDecodeError):
            return _error(400, "The request wasn't valid JSON.")
        if not isinstance(body, dict):
            return _error(400, "Send the restaurant and the order text.")

        customer_id, order = body.get("customer_id"), body.get("order")
        if not isinstance(customer_id, str) or customer_id not in self.customers:
            return _error(400, "Choose a restaurant from the list.")
        if not isinstance(order, str) or not order.strip():
            return _error(400, "Type or paste an order first.")
        order = order.strip()
        if len(order) > MAX_ORDER_CHARS:
            return _error(413, f"That order is too long. Keep it under {MAX_ORDER_CHARS:,} characters.")
        line_count = len(split_order(order))
        if line_count > MAX_LINES:
            return _error(413, f"That order has {line_count} lines. This demo matches up to "
                               f"{MAX_LINES} at a time.")

        key = (customer_id, order)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
        if cached is not None:
            return _response(200, _json_bytes({**cached, "cached": True}), JSON_TYPE)

        if not self.per_visitor.allow(self._visitor(environ)):
            return _error(429, "You've matched a lot of orders in the last few minutes. "
                               "Wait a little and try again.")
        if not self.per_day.allow("all"):
            return _error(429, "This demo has reached its limit for today. Try again tomorrow.")

        started = time.perf_counter()
        try:
            matches = self.matcher.match_order(order, customer_id, self.order_date)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                log.error("Jev refused the API key (HTTP %d). Check TYPESAFE_API_KEY.", e.code)
            else:
                log.warning("Jev answered HTTP %d", e.code)
            if e.code == 429:
                return _error(503, "The matching service is busy. Try again in a minute.")
            return _error(502, "The matching service didn't answer properly. Try again in a moment.")
        except (OSError, ValueError, KeyError) as e:  # timeouts, network errors, odd responses
            log.warning("Matching failed: %s: %s", type(e).__name__, e)
            return _error(502, "The matching service didn't answer. Try again in a moment.")

        usual = {self.catalog[s].product
                 for s in self.history.counts(customer_id, self.order_date, WINDOW_DAYS)}
        payload = {
            "decider": self.decider.name,
            "match_ms": round((time.perf_counter() - started) * 1000),
            "lines": [_line_payload(m, usual) for m in matches],
        }
        with self._cache_lock:
            self._cache[key] = payload
            if len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return _response(200, _json_bytes({**payload, "cached": False}), JSON_TYPE)

    def _visitor(self, environ) -> str:
        if self.trust_proxy:
            forwarded = environ.get("HTTP_X_FORWARDED_FOR", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return environ.get("REMOTE_ADDR", "unknown")

    def _bootstrap_payload(self) -> dict:
        customers = []
        for cid, name in sorted(self.customers.items(), key=lambda kv: kv[1]):
            counts = self.history.counts(cid, self.order_date, WINDOW_DAYS)
            customers.append({
                "id": cid,
                "name": name,
                "products": len({self.catalog[s].product for s in counts}),
                "usual": [{**_sku_payload(self.catalog[s]), "orders": n}
                          for s, n in counts.most_common(8)],
            })
        return {
            "live": isinstance(self.decider, JevDecider),
            "decider": self.decider.name,
            "review_below": REVIEW_BELOW,
            "limits": {"max_lines": MAX_LINES, "max_chars": MAX_ORDER_CHARS},
            "test_results": TEST_RESULTS.get(self.decider.name),
            "customers": customers,
            "catalog": sorted((_sku_payload(s) for s in self.catalog),
                              key=lambda s: s["description"]),
            "examples": [e for e in EXAMPLES if e["customer_id"] in self.customers],
        }


def serve(app: App, host: str, port: int) -> None:
    try:
        from waitress import serve as waitress_serve
    except ImportError:
        raise SystemExit("The web server isn't installed. Run: python -m pip install -r requirements.txt")
    log.info("Order Matcher at http://%s:%d, decisions by %s", host, port, app.decider.name)
    waitress_serve(app, host=host, port=port, threads=8, ident="order-matcher")


def unit_label(sku: Sku) -> str:
    """How the unit reads after a quantity: "case", "lb", or "bunch", "pint" or "each"."""
    if sku.unit == "CS":
        return "case"
    if sku.unit == "LB":
        return "lb"
    return sku.description.rsplit(", ", 1)[-1]


def _sku_payload(sku: Sku) -> dict:
    return {"sku": sku.sku, "description": sku.description, "unit": unit_label(sku)}


def _line_payload(m: LineMatch, usual_products: set[str]) -> dict:
    status = "no_match" if m.sku is None else "review" if m.needs_review else "ok"
    return {
        "text": m.line.text,
        "qty": m.line.qty,
        "unit_named": m.line.unit is not None,
        "status": status,
        "confidence": round(m.confidence, 3),
        "item": _sku_payload(m.sku) if m.sku else None,
        "usual": m.sku is not None and m.sku.product in usual_products,
        "second_pass": m.second_pass,
        "unit_fixed": m.unit_fixed,
        "alternatives": [_sku_payload(s) for s in m.alternatives],
    }


def _setting(value: int | None, env_name: str, default: int) -> int:
    if value is not None:
        return value
    try:
        return int(os.environ.get(env_name, default))
    except ValueError:
        return default


def _json_bytes(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _response(code: int, body: bytes, content_type: str, extra: list | None = None):
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
              413: "Payload Too Large", 429: "Too Many Requests", 500: "Internal Server Error",
              502: "Bad Gateway", 503: "Service Unavailable"}[code]
    headers = [("Content-Type", content_type), ("Content-Length", str(len(body))),
               ("Cache-Control", "no-cache")] + (extra or [])
    return f"{code} {reason}", headers, body


def _error(code: int, message: str, allow: str | None = None):
    return _response(code, _json_bytes({"error": message}), JSON_TYPE,
                     [("Allow", allow)] if allow else None)
