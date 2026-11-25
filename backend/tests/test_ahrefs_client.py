import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.services.ahrefs import client as ahrefs
from app.services.ahrefs.client import AhrefsServiceError

SETTINGS = SimpleNamespace(
    ahrefs_api_key="test-key", ahrefs_request_timeout_seconds=5.0, ahrefs_country="nl"
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _serp_row(position, types, url=None, title=None, **metrics):
    row = {
        "position": position, "url": url, "title": title, "type": types, "page_type": None,
        "domain_rating": None, "url_rating": None, "refdomains": None, "backlinks": None,
        "keywords": None, "update_date": "2026-11-22T14:53:16Z",
    }
    row.update(metrics)
    return row


# Vorm van een echte serp-overview-respons (top_positions=10, "seo bureau", nl),
# geanonimiseerd: features tussen de organische resultaten en sitelinks op dezelfde positie.
SERP_PAYLOAD = {"positions": [
    _serp_row(1, ["organic"], "https://bureau-a.nl/", "Bureau A", page_type="/Core_Page,/Core_Page/Homepage",
              domain_rating=20.0, url_rating=9.0, refdomains=664),
    _serp_row(1, ["sitelink"], "https://bureau-a.nl/team", "Team"),
    _serp_row(2, ["ai_overview"]),
    _serp_row(2, ["ai_overview_sitelink"], "https://bureau-a.nl/", "Bureau A"),
    _serp_row(2, ["ai_overview_sitelink"], "https://bureau-b.nl/seo/", "SEO bij B"),
    _serp_row(2, ["ai_overview_sitelink"], "https://bureau-b.nl/seo/", "SEO bij B"),
    _serp_row(3, ["question"], title="Wat is een SEO bureau?"),
    _serp_row(3, ["question"], title="Hoeveel kost SEO per maand?"),
    _serp_row(5, ["organic"], "https://bureau-b.nl/seo/", "SEO bij B", page_type="/Landing_Page/Service_Page",
              domain_rating=54.0, refdomains=65),
    _serp_row(4, ["organic"], "https://vergelijker.nl/seo", "186 bureaus vergeleken", page_type="/Listing_Collection",
              domain_rating=67.0, refdomains=7),
    _serp_row(6, ["organic", "snippet"], "https://bureau-c.nl/", "Bureau C", domain_rating=35.0, refdomains=0),
    _serp_row(7, ["organic"], "https://bureau-a.nl/", "Bureau A (tweede keer)"),
    _serp_row(8, ["organic"], "https://bureau-d.nl/", "Bureau D", domain_rating=52.0, refdomains=79),
]}


class AhrefsClientTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(ahrefs, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(ahrefs.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_top_pages_sends_bearer_and_params_and_reads_units(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers["Authorization"]
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(
                200,
                json={"pages": [{"url": "https://klant.nl/a", "sum_traffic": 120}]},
                headers={"x-api-units-cost-total-actual": "4800", "x-api-cache": "miss"},
            )

        result = ahrefs.top_pages(
            "klant.nl", country="nl", limit=200, on_date=date(2026, 11, 11), client=_client(handler)
        )

        self.assertEqual(seen["auth"], "Bearer test-key")
        self.assertEqual(seen["path"], "/v3/site-explorer/top-pages")
        self.assertEqual(seen["params"]["target"], "klant.nl")
        self.assertEqual(seen["params"]["mode"], "subdomains")
        self.assertEqual(seen["params"]["date"], "2026-11-11")
        self.assertEqual(seen["params"]["country"], "nl")
        self.assertEqual(seen["params"]["limit"], "200")
        self.assertEqual(seen["params"]["order_by"], "sum_traffic:desc")
        self.assertIn("top_keyword_best_position", seen["params"]["select"])
        self.assertEqual(result.rows, [{"url": "https://klant.nl/a", "sum_traffic": 120}])
        self.assertEqual(result.units, 4800)
        self.assertFalse(result.cached)

    def test_domain_overview_posts_single_target(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"targets": [{"domain_rating": 34.0, "refdomains": 210, "org_traffic": 1800, "extra": 1}]},
                headers={"x-api-units-cost-total-actual": "50"},
            )

        result = ahrefs.domain_overview("klant.nl", country="nl", client=_client(handler))

        self.assertEqual((seen["method"], seen["path"]), ("POST", "/v3/batch-analysis/batch-analysis"))
        self.assertEqual(seen["body"]["targets"], [{"url": "klant.nl", "mode": "subdomains", "protocol": "both"}])
        self.assertEqual(seen["body"]["country"], "nl")
        self.assertEqual(result.data["domain_rating"], 34.0)
        self.assertEqual(result.data["refdomains"], 210)
        self.assertNotIn("extra", result.data)
        self.assertEqual(result.units, 50)

    def test_organic_keywords_filters_positions_and_compares_30_days(self):
        seen = {}
        row = {
            "keyword": "seo bureau", "best_position": 7, "best_position_diff": -2,
            "best_position_url": "https://klant.nl/seo/", "volume": 900, "keyword_difficulty": 25,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(
                200, json={"keywords": [row, "geen dict"]},
                headers={"x-api-units-cost-total-actual": "48"},
            )

        result = ahrefs.organic_keywords(
            "klant.nl", country="nl", limit=50, on_date=date(2026, 11, 23), client=_client(handler)
        )

        params = seen["params"]
        self.assertEqual((seen["method"], seen["path"]), ("GET", "/v3/site-explorer/organic-keywords"))
        self.assertEqual(params["target"], "klant.nl")
        self.assertEqual(params["mode"], "subdomains")
        self.assertEqual(params["protocol"], "both")
        self.assertEqual(params["country"], "nl")
        self.assertEqual(params["date"], "2026-11-23")
        self.assertEqual(params["date_compared"], "2026-10-24")
        self.assertEqual(params["order_by"], "volume:desc")
        self.assertEqual(params["limit"], "50")
        self.assertEqual(
            params["select"],
            "keyword,best_position,best_position_diff,best_position_url,volume,keyword_difficulty",
        )
        self.assertEqual(json.loads(params["where"]), {"and": [
            {"field": "best_position", "is": ["gte", 4]},
            {"field": "best_position", "is": ["lte", 20]},
        ]})
        self.assertEqual(result.rows, [row])
        self.assertEqual(result.units, 48)

    def test_organic_keywords_custom_range_without_country(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"keywords": []})

        result = ahrefs.organic_keywords(
            "klant.nl", position_min=1, position_max=3, compare_days=7,
            on_date=date(2026, 3, 2), client=_client(handler),
        )
        self.assertNotIn("country", seen["params"])
        self.assertEqual(seen["params"]["date_compared"], "2026-02-23")
        where = json.loads(seen["params"]["where"])
        self.assertEqual([c["is"] for c in where["and"]], [["gte", 1], ["lte", 3]])
        self.assertEqual((result.rows, result.units), ([], 0))

    def test_broken_backlinks_and_pages_by_backlinks_use_their_own_keys(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/broken-backlinks"):
                self.assertEqual(request.url.params["aggregation"], "1_per_domain")
                return httpx.Response(200, json={"backlinks": [{"url_to": "https://klant.nl/oud"}]})
            self.assertEqual(request.url.params["history"], "live")
            return httpx.Response(200, json={"pages": [{"url_to": "https://klant.nl/a"}]})

        client = _client(handler)
        self.assertEqual(ahrefs.broken_backlinks("klant.nl", client=client).rows, [{"url_to": "https://klant.nl/oud"}])
        self.assertEqual(ahrefs.pages_by_backlinks("klant.nl", client=client).rows, [{"url_to": "https://klant.nl/a"}])

    def test_rate_limit_retries_then_succeeds(self):
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "2"})
            return httpx.Response(200, json={"pages": []})

        result = ahrefs.pages_by_backlinks("klant.nl", client=_client(handler))

        self.assertEqual(result.rows, [])
        self.assertEqual(len(calls), 2)
        self.sleep.assert_called_once_with(2.0)

    def test_rate_limit_gives_up_after_max_attempts(self):
        with self.assertRaises(AhrefsServiceError) as ctx:
            ahrefs.pages_by_backlinks("klant.nl", client=_client(lambda r: httpx.Response(429)))
        self.assertEqual(ctx.exception.code, "rate_limited")
        self.assertEqual(self.sleep.call_count, ahrefs.MAX_ATTEMPTS - 1)

    def test_error_statuses_map_to_codes(self):
        cases = {401: "unauthorized", 403: "forbidden", 400: "ahrefs_error"}
        for status, code in cases.items():
            with self.assertRaises(AhrefsServiceError) as ctx:
                ahrefs.limits_and_usage(
                    client=_client(lambda r, s=status: httpx.Response(s, json={"error": "nope"}))
                )
            self.assertEqual(ctx.exception.code, code)
        self.assertIn("nope", str(ctx.exception))

    def test_missing_key_is_not_configured(self):
        with patch.object(ahrefs, "settings", SimpleNamespace(ahrefs_api_key=" ", ahrefs_request_timeout_seconds=5.0)):
            self.assertFalse(ahrefs.is_configured())
            with self.assertRaises(AhrefsServiceError) as ctx:
                ahrefs.limits_and_usage(client=_client(lambda r: httpx.Response(200, json={})))
        self.assertEqual(ctx.exception.code, "not_configured")

    def test_limits_and_usage_unwraps_payload(self):
        payload = {"limits_and_usage": {"subscription": "Standard", "units_usage_workspace": 1200}}
        data = ahrefs.limits_and_usage(client=_client(lambda r: httpx.Response(200, json=payload)))
        self.assertEqual(data["subscription"], "Standard")

    def test_serp_overview_sends_keyword_country_and_reads_positions(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(
                200, json=SERP_PAYLOAD,
                headers={"x-api-units-cost-total-actual": "315", "x-api-cache": "hit"},
            )

        result = ahrefs.serp_overview(" seo bureau ", top_positions=15, client=_client(handler))

        params = seen["params"]
        self.assertEqual((seen["method"], seen["path"]), ("GET", "/v3/serp-overview/serp-overview"))
        self.assertEqual(params["keyword"], "seo bureau")
        self.assertEqual(params["country"], "nl")  # standaard settings.ahrefs_country
        self.assertEqual(params["top_positions"], "15")
        self.assertNotIn("date", params)
        self.assertEqual(params["select"].split(","), list(ahrefs.SERP_FIELDS))
        self.assertNotIn("traffic", params["select"].split(","))
        self.assertEqual(len(result.rows), len(SERP_PAYLOAD["positions"]))
        self.assertEqual(result.rows[0]["type"], ["organic"])
        self.assertEqual(result.units, 315)
        self.assertTrue(result.cached)

    def test_serp_overview_explicit_country(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"positions": []})

        result = ahrefs.serp_overview("seo agency", country="be", client=_client(handler))
        self.assertEqual(seen["params"]["country"], "be")
        self.assertEqual(seen["params"]["top_positions"], "10")
        self.assertEqual((result.rows, result.units), ([], 0))

    def test_keywords_overview_joins_keywords_and_reads_intents(self):
        seen = {}
        row = {
            "keyword": "seo bureau", "volume": 3900, "difficulty": 30,
            "intents": {"informational": True, "navigational": False, "commercial": True,
                        "transactional": False, "branded": False, "local": True},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"keywords": [row]}, headers={"x-api-units-cost-total-actual": "62"})

        result = ahrefs.keywords_overview(
            ["seo bureau", " zoekmachine optimalisatie ", "seo bureau", "", "a, b"],
            country="nl", client=_client(handler),
        )

        params = seen["params"]
        self.assertEqual((seen["method"], seen["path"]), ("GET", "/v3/keywords-explorer/overview"))
        self.assertEqual(params["keywords"], "seo bureau,zoekmachine optimalisatie")
        self.assertEqual(params["country"], "nl")
        self.assertEqual(params["select"], "keyword,volume,difficulty,intents")
        self.assertEqual(result.rows, [row])
        self.assertTrue(result.rows[0]["intents"]["commercial"])
        self.assertEqual(result.units, 62)

    def test_keywords_overview_without_keywords_skips_request(self):
        def handler(request):
            raise AssertionError("geen request verwacht")

        result = ahrefs.keywords_overview(["", "  "], client=_client(handler))
        self.assertEqual((result.rows, result.units), ([], 0))

    def test_url_metrics_uses_exact_mode_and_maps_targets_by_index(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            # Echte vorm: url zonder protocol, `index` volgt de invoer.
            return httpx.Response(
                200,
                json={"targets": [
                    {"index": 1, "url": "klant.nl/", "domain_rating": 34.0, "url_rating": 20.0, "refdomains": 210},
                    {"index": 0, "url": "klant.nl/diensten/seo/", "domain_rating": 34.0, "url_rating": 8.0,
                     "refdomains": 3},
                ]},
                headers={"x-api-units-cost-total": "50", "x-api-units-cost-total-actual": "50"},
            )

        result = ahrefs.url_metrics(
            ["https://klant.nl/diensten/seo/", " https://klant.nl/ ", ""], client=_client(handler)
        )

        self.assertEqual((seen["method"], seen["path"]), ("POST", "/v3/batch-analysis/batch-analysis"))
        self.assertEqual(seen["body"]["select"], ["index", "url", "domain_rating", "url_rating", "refdomains"])
        self.assertEqual(seen["body"]["targets"], [
            {"url": "https://klant.nl/diensten/seo/", "mode": "exact", "protocol": "both"},
            {"url": "https://klant.nl/", "mode": "exact", "protocol": "both"},
        ])
        self.assertNotIn("country", seen["body"])
        by_target = {row["target"]: row for row in result.rows}
        self.assertEqual(by_target["https://klant.nl/diensten/seo/"]["refdomains"], 3)
        self.assertEqual(by_target["https://klant.nl/"]["url_rating"], 20.0)
        self.assertEqual(result.units, 50)
        self.assertFalse(result.cached)

    def test_url_metrics_splits_over_100_targets_and_sums_units(self):
        bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            bodies.append(body)
            rows = [{"index": i, "url": t["url"], "refdomains": i} for i, t in enumerate(body["targets"])]
            return httpx.Response(200, json={"targets": rows}, headers={"x-api-units-cost-total-actual": "50"})

        urls = [f"https://klant.nl/p{i}" for i in range(150)]
        result = ahrefs.url_metrics(urls, client=_client(handler))

        self.assertEqual([len(b["targets"]) for b in bodies], [100, 50])
        self.assertEqual(len(result.rows), 150)
        self.assertEqual(result.rows[120]["target"], "https://klant.nl/p120")
        self.assertEqual(result.units, 100)

    def test_url_metrics_without_urls_skips_request(self):
        def handler(request):
            raise AssertionError("geen request verwacht")

        result = ahrefs.url_metrics([], client=_client(handler))
        self.assertEqual((result.rows, result.units, result.cached), ([], 0, False))

    def test_url_metrics_forbidden_raises(self):
        with self.assertRaises(AhrefsServiceError) as ctx:
            ahrefs.url_metrics(
                ["https://klant.nl/"],
                client=_client(lambda r: httpx.Response(403, json={"error": "insufficient units"})),
            )
        self.assertEqual(ctx.exception.code, "forbidden")
        self.assertIn("insufficient units", str(ctx.exception))

    def test_serp_overview_custom_fields(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"positions": []})

        ahrefs.serp_overview("seo", fields=("position", "url", "type", "title"), client=_client(handler))
        self.assertEqual(seen["params"]["select"], "position,url,type,title")

    def test_organic_competitors_orders_by_common_keywords(self):
        seen = {}
        row = {"competitor_domain": "moz.com", "domain_rating": 91.0, "keywords_common": 3000,
               "keywords_competitor": 90000, "keywords_target": 40000, "share": 8.4}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"competitors": [row]},
                                  headers={"x-api-units-cost-total-actual": "120"})

        result = ahrefs.organic_competitors(
            "klant.nl", country="nl", on_date=date(2026, 11, 25), client=_client(handler)
        )

        params = seen["params"]
        self.assertEqual((seen["method"], seen["path"]), ("GET", "/v3/site-explorer/organic-competitors"))
        self.assertEqual(params["target"], "klant.nl")
        self.assertEqual(params["mode"], "subdomains")
        self.assertEqual(params["date"], "2026-11-25")
        self.assertEqual(params["country"], "nl")
        self.assertEqual(params["order_by"], "keywords_common:desc")
        self.assertEqual(params["limit"], "20")
        self.assertEqual(
            params["select"],
            "competitor_domain,domain_rating,keywords_common,keywords_competitor,keywords_target,share",
        )
        self.assertNotIn("where", params)
        self.assertEqual(result.rows, [row])
        self.assertEqual(result.units, 120)

    def test_organic_competitors_with_domains_filters_without_order(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"competitors": []}, headers={"x-api-units-cost-total-actual": "50"})

        result = ahrefs.organic_competitors(
            "klant.nl", domains=["moz.com", " semrush.com ", ""], client=_client(handler)
        )
        params = seen["params"]
        self.assertNotIn("order_by", params)
        self.assertNotIn("country", params)
        self.assertEqual(params["limit"], "2")
        self.assertEqual(json.loads(params["where"]), {"or": [
            {"field": "competitor_domain", "is": ["eq", "moz.com"]},
            {"field": "competitor_domain", "is": ["eq", "semrush.com"]},
        ]})
        self.assertEqual(result.units, 50)

    def test_domains_metrics_posts_subdomains_and_maps_targets(self):
        bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            bodies.append(body)
            rows = [
                {"index": i, "url": f"{t['url']}/", "domain_rating": 50.0, "org_keywords": 100 + i,
                 "org_keywords_1_3": 10, "org_keywords_4_10": 20, "org_traffic": 1000}
                for i, t in reversed(list(enumerate(body["targets"])))
            ]
            return httpx.Response(200, json={"targets": rows}, headers={"x-api-units-cost-total-actual": "84"})

        domains = ["klant.nl", "a.nl"] + [f"d{i}.nl" for i in range(100)]
        result = ahrefs.domains_metrics(domains, country="nl", client=_client(handler))

        self.assertEqual([len(b["targets"]) for b in bodies], [100, 2])
        self.assertEqual(bodies[0]["select"], list(ahrefs.DOMAIN_METRICS_FIELDS))
        self.assertEqual(bodies[0]["country"], "nl")
        self.assertEqual(bodies[0]["targets"][0], {"url": "klant.nl", "mode": "subdomains", "protocol": "both"})
        by_target = {row["target"]: row for row in result.rows}
        self.assertEqual(by_target["klant.nl"]["org_keywords"], 100)
        self.assertEqual(by_target["a.nl"]["org_keywords"], 101)
        self.assertEqual(by_target["d99.nl"]["url"], "d99.nl/")
        self.assertEqual(len(result.rows), 102)
        self.assertEqual(result.units, 168)

    def test_domains_metrics_without_domains_skips_request(self):
        def handler(request):
            raise AssertionError("geen request verwacht")

        result = ahrefs.domains_metrics([" "], client=_client(handler))
        self.assertEqual((result.rows, result.units), ([], 0))

    def test_metrics_history_monthly(self):
        seen = {}
        rows = [{"date": "2026-09-01T00:00:00Z", "org_traffic": 18000},
                {"date": "2026-10-01T00:00:00Z", "org_traffic": 20481}]

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"metrics": rows}, headers={"x-api-units-cost-total-actual": "50"})

        result = ahrefs.metrics_history(
            "klant.nl", country="nl", date_from=date(2026, 9, 1), client=_client(handler)
        )
        params = seen["params"]
        self.assertEqual(seen["path"], "/v3/site-explorer/metrics-history")
        self.assertEqual(params["target"], "klant.nl")
        self.assertEqual(params["mode"], "subdomains")
        self.assertEqual(params["protocol"], "both")
        self.assertEqual(params["country"], "nl")
        self.assertEqual(params["date_from"], "2026-09-01")
        self.assertEqual(params["history_grouping"], "monthly")
        self.assertEqual(params["select"], "date,org_traffic")
        self.assertEqual(result.rows, rows)
        self.assertEqual(result.units, 50)

    def test_top10_keywords_without_order_by(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(
                200, json={"keywords": [{"keyword": "seo", "best_position": 3}]},
                headers={"x-api-units-cost-total-actual": "300"},
            )

        result = ahrefs.top10_keywords("klant.nl", country="nl", limit=150, client=_client(handler))

        params = seen["params"]
        self.assertEqual(seen["path"], "/v3/site-explorer/organic-keywords")
        self.assertNotIn("order_by", params)
        self.assertEqual(params["select"], "keyword,best_position")
        self.assertEqual(params["limit"], "150")
        self.assertEqual(params["country"], "nl")
        self.assertEqual(params["mode"], "subdomains")
        self.assertIn("date", params)
        self.assertEqual(json.loads(params["where"]), {"and": [{"field": "best_position", "is": ["lte", 10]}]})
        self.assertEqual(result.rows, [{"keyword": "seo", "best_position": 3}])
        self.assertEqual(result.units, 300)

    def test_top10_keywords_with_keyword_list(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"keywords": []})

        ahrefs.top10_keywords(
            "klant.nl", limit=3, keywords=["seo bureau", 'zoek "snel", nu', " "], client=_client(handler)
        )
        params = seen["params"]
        self.assertNotIn("order_by", params)
        self.assertEqual(json.loads(params["where"]), {"and": [
            {"field": "best_position", "is": ["lte", 10]},
            {"or": [
                {"field": "keyword", "is": ["eq", "seo bureau"]},
                {"field": "keyword", "is": ["eq", 'zoek "snel", nu']},
            ]},
        ]})

    def test_top10_keywords_without_position_limit(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(dict(request.url.params))
            return httpx.Response(200, json={"keywords": [{"keyword": "seo", "best_position": 14}]})

        result = ahrefs.top10_keywords(
            "klant.nl", limit=2, keywords=["seo", "sea"], max_position=None, client=_client(handler)
        )
        self.assertEqual(json.loads(seen[0]["where"]), {"and": [
            {"or": [
                {"field": "keyword", "is": ["eq", "seo"]},
                {"field": "keyword", "is": ["eq", "sea"]},
            ]},
        ]})
        self.assertEqual(result.rows, [{"keyword": "seo", "best_position": 14}])

        # Zonder zoekwoorden en zonder grens: geen `where`. Een andere grens komt in de `where`.
        ahrefs.top10_keywords("klant.nl", limit=5, max_position=None, client=_client(handler))
        self.assertNotIn("where", seen[1])
        ahrefs.top10_keywords("klant.nl", limit=5, max_position=20, client=_client(handler))
        self.assertEqual(json.loads(seen[2]["where"]), {"and": [{"field": "best_position", "is": ["lte", 20]}]})

    def test_organic_rows_skips_features_and_duplicates(self):
        result = ahrefs.AhrefsResult(rows=SERP_PAYLOAD["positions"])

        rows = ahrefs.organic_rows(result, 10)

        self.assertEqual(
            [row["url"] for row in rows],
            ["https://bureau-a.nl/", "https://vergelijker.nl/seo", "https://bureau-b.nl/seo/",
             "https://bureau-c.nl/", "https://bureau-d.nl/"],
        )
        self.assertEqual([row["organic_position"] for row in rows], [1, 2, 3, 4, 5])
        self.assertEqual([row["position"] for row in rows], [1, 4, 5, 6, 8])
        self.assertEqual(rows[1]["domain_rating"], 67.0)
        self.assertEqual([row["url"] for row in ahrefs.organic_rows(result, 2)],
                         ["https://bureau-a.nl/", "https://vergelijker.nl/seo"])
        self.assertNotIn("organic_position", SERP_PAYLOAD["positions"][0])

    def test_serp_features_lists_non_organic_types(self):
        result = ahrefs.AhrefsResult(rows=SERP_PAYLOAD["positions"])
        self.assertEqual(
            ahrefs.serp_features(result),
            ["ai_overview", "ai_overview_sitelink", "question", "sitelink", "snippet"],
        )
        self.assertEqual(ahrefs.serp_features(ahrefs.AhrefsResult(rows=[_serp_row(1, ["organic"], "https://a.nl/")])), [])

    def test_ai_overview_sources_and_people_also_ask(self):
        result = ahrefs.AhrefsResult(rows=SERP_PAYLOAD["positions"])
        self.assertEqual(ahrefs.ai_overview_sources(result), [
            {"url": "https://bureau-a.nl/", "title": "Bureau A"},
            {"url": "https://bureau-b.nl/seo/", "title": "SEO bij B"},
        ])
        self.assertEqual(
            ahrefs.people_also_ask(result), ["Wat is een SEO bureau?", "Hoeveel kost SEO per maand?"]
        )
        empty = ahrefs.AhrefsResult()
        self.assertEqual((ahrefs.ai_overview_sources(empty), ahrefs.people_also_ask(empty)), ([], []))


if __name__ == "__main__":
    unittest.main()
