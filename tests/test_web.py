import io
import json
import unittest

from order_matcher.data import load
from order_matcher.deciders import LocalDecider
from order_matcher.web import MAX_LINES, App

CATALOG, HISTORY, CUSTOMERS = load()


def call(app, method, path, body=None, raw=None, ip="203.0.113.7", headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_LENGTH": str(len(data)),
               "wsgi.input": io.BytesIO(data), "REMOTE_ADDR": ip, **(headers or {})}
    seen = {}

    def start_response(status, response_headers):
        seen["status"], seen["headers"] = status, dict(response_headers)

    payload = b"".join(app(environ, start_response))
    return int(seen["status"][:3]), seen["headers"], payload


def make_app(**limits):
    return App(CATALOG, HISTORY, CUSTOMERS, LocalDecider(), **limits)


class PagesTest(unittest.TestCase):
    def test_page_and_assets_are_served_with_security_headers(self):
        app = make_app()
        for path, kind in [("/", "text/html"), ("/app.js", "text/javascript"),
                           ("/styles.css", "text/css"), ("/favicon.svg", "image/svg+xml")]:
            status, headers, body = call(app, "GET", path)
            self.assertEqual(status, 200, path)
            self.assertTrue(headers["Content-Type"].startswith(kind), path)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertGreater(len(body), 0)

    def test_health_check(self):
        self.assertEqual(call(make_app(), "GET", "/healthz")[2], b"ok")

    def test_unknown_address_is_404(self):
        status, _, body = call(make_app(), "GET", "/admin")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(body))

    def test_bootstrap_lists_restaurants_catalog_and_examples(self):
        status, _, body = call(make_app(), "GET", "/api/bootstrap")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertFalse(data["live"])
        self.assertEqual(len(data["customers"]), len(CUSTOMERS))
        self.assertEqual(len(data["catalog"]), len(CATALOG))
        self.assertTrue(data["examples"])


class MatchTest(unittest.TestCase):
    def match(self, app, body, **kwargs):
        status, _, payload = call(app, "POST", "/api/match", body, **kwargs)
        return status, json.loads(payload)

    def test_matches_an_order(self):
        status, data = self.match(make_app(), {"customer_id": "C003",
                                               "order": "2 cs portobellos, 5# limes, cs grass"})
        self.assertEqual(status, 200)
        self.assertEqual([line["text"] for line in data["lines"]],
                         ["2 cs portobellos", "5# limes", "cs grass"])
        first = data["lines"][0]
        self.assertEqual(first["item"]["sku"], "MPO-CS")
        self.assertEqual(first["item"]["unit"], "case")
        self.assertEqual(first["status"], "ok")
        self.assertTrue(first["usual"])
        self.assertFalse(data["cached"])

    def test_the_same_order_again_comes_from_the_cache(self):
        app = make_app()
        order = {"customer_id": "C003", "order": "2 cs portobellos"}
        self.match(app, order)
        status, data = self.match(app, order)
        self.assertEqual(status, 200)
        self.assertTrue(data["cached"])

    def test_rejects_bad_requests(self):
        app = make_app()
        cases = [
            ({"customer_id": "C999", "order": "2 cs kale"}, 400),
            ({"customer_id": "C003", "order": "   "}, 400),
            ({"customer_id": "C003", "order": "x" * 2001}, 413),
            ({"customer_id": "C003", "order": ", ".join(["1 cs kale"] * (MAX_LINES + 1))}, 413),
            (["not", "an", "object"], 400),
        ]
        for body, expected in cases:
            status, data = self.match(app, body)
            self.assertEqual(status, expected, body)
            self.assertIn("error", data)
        status, _, _ = call(app, "POST", "/api/match", raw=b"{not json")
        self.assertEqual(status, 400)
        status, _, _ = call(app, "GET", "/api/match")
        self.assertEqual(status, 405)

    def test_limits_orders_per_visitor(self):
        app = make_app(per_visitor=2)
        for n in range(2):
            self.assertEqual(self.match(app, {"customer_id": "C003", "order": f"{n + 1} cs kale"})[0], 200)
        status, data = self.match(app, {"customer_id": "C003", "order": "9 cs kale"})
        self.assertEqual(status, 429)
        # Another visitor still gets through.
        status, _ = self.match(app, {"customer_id": "C003", "order": "9 cs kale"}, ip="198.51.100.4")
        self.assertEqual(status, 200)

    def test_limits_orders_per_day_across_visitors(self):
        app = make_app(per_day=1)
        self.assertEqual(self.match(app, {"customer_id": "C003", "order": "1 cs kale"})[0], 200)
        status, _ = self.match(app, {"customer_id": "C003", "order": "2 cs kale"}, ip="198.51.100.4")
        self.assertEqual(status, 429)

    def test_visitor_address_comes_from_the_proxy_only_when_trusted(self):
        forwarded = {"HTTP_X_FORWARDED_FOR": "192.0.2.1, 10.0.0.1"}
        self.assertEqual(make_app(trust_proxy=True)._visitor({"REMOTE_ADDR": "10.0.0.2", **forwarded}), "192.0.2.1")
        self.assertEqual(make_app(trust_proxy=False)._visitor({"REMOTE_ADDR": "10.0.0.2", **forwarded}), "10.0.0.2")


class SecretTest(unittest.TestCase):
    def test_no_response_contains_the_api_key(self):
        class FakeJev(LocalDecider):
            name = "jev"
            api_key = "sk-test-SECRET-123"

        app = App(CATALOG, HISTORY, CUSTOMERS, FakeJev())
        responses = [call(app, "GET", path)[2] for path in ("/", "/app.js", "/api/bootstrap")]
        responses.append(call(app, "POST", "/api/match", {"customer_id": "C003", "order": "2 cs kale"})[2])
        for body in responses:
            self.assertNotIn(b"SECRET", body)


if __name__ == "__main__":
    unittest.main()
