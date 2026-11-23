"""Quick wins uit Ahrefs en ProRankTracker per klant (features/customers/quick_wins).

Draait tegen een in-memory SQLite-database; Ahrefs wordt nooit echt aangeroepen
(`ahrefs.organic_keywords` en `ahrefs.is_configured` zijn in elke test vervangen), en
ProRankTracker ook niet (`prt.rank_overview` is vervangen waar de PRT-kant meedoet).
"""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import require_user_id
from app.db.models import Base, CustomerQuickWins, CustomerWebsite
from app.db.session import get_db
from app.features.customers import quick_wins, rankings
from app.features.customers.quick_wins import convert, kans, to_row
from app.features.customers.router import router
from app.services.ahrefs.client import AhrefsResult, AhrefsServiceError
from app.services.proranktracker.client import ProRankTrackerServiceError

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def _settings(**overrides):
    values = {"ahrefs_quick_wins_limit": 50, "ahrefs_quick_wins_ttl_days": 30, "ahrefs_country": "nl"}
    values.update(overrides)
    return SimpleNamespace(**values)


def _raw(keyword="seo bureau", position=7, diff=-2, volume=900, kd=25, url="https://klant.nl/seo/"):
    return {
        "keyword": keyword, "best_position": position, "best_position_diff": diff,
        "best_position_url": url, "volume": volume, "keyword_difficulty": kd,
    }


# --- omzetten en kans-regel ------------------------------------------------------------

class KansTest(unittest.TestCase):
    def test_boundaries(self):
        cases = [
            # positie 10/11 bij lage KD
            ((10, 30), "hoog"), ((11, 30), "middel"),
            # positie 15/16
            ((15, 30), "middel"), ((16, 30), "laag"), ((16, 0), "laag"),
            # KD 30/31 binnen de top 10
            ((4, 30), "hoog"), ((4, 31), "middel"),
            # KD 60/61
            ((8, 60), "middel"), ((8, 61), "laag"), ((12, 61), "laag"),
            # zonder KD telt alleen de positie
            ((4, None), "middel"), ((10, None), "middel"), ((15, None), "middel"),
            ((16, None), "laag"), ((20, None), "laag"),
        ]
        for (position, kd), expected in cases:
            with self.subTest(position=position, kd=kd):
                self.assertEqual(kans(position, kd, 100), expected)

    def test_without_volume_never_high(self):
        # Zonder zoekvolume (0 of onbekend) valt "hoog" terug op de rest van de regel.
        for volume in (0, None):
            with self.subTest(volume=volume):
                self.assertEqual(kans(6, 0, volume), "middel")
                self.assertEqual(kans(16, 0, volume), "laag")
                self.assertEqual(kans(8, 61, volume), "laag")
        self.assertEqual(kans(6, 0, 1), "hoog")


class ConvertTest(unittest.TestCase):
    def test_row_shape_and_delta_sign(self):
        self.assertEqual(to_row(_raw()), {
            "keyword": "seo bureau", "position": 7, "delta": 2, "volume": 900, "kd": 25,
            "url": "https://klant.nl/seo/", "kans": "hoog",
        })
        # Gezakt (diff positief) wordt een negatieve delta.
        self.assertEqual(to_row(_raw(position=12, diff=3))["delta"], -3)
        # Toen niet gerankt: delta blijft leeg; geen verandering blijft 0.
        self.assertIsNone(to_row(_raw(diff=None))["delta"])
        self.assertEqual(to_row(_raw(diff=0))["delta"], 0)

    def test_missing_values(self):
        row = to_row(_raw(volume=None, kd=None, url=None, position="16"))
        self.assertEqual((row["position"], row["volume"], row["kd"], row["url"], row["kans"]),
                         (16, None, None, None, "laag"))

    def test_invalid_rows_are_dropped_and_order_kept(self):
        rows = [
            _raw("b", volume=900), _raw("", position=5), _raw(None), _raw("buiten", position=3),
            _raw("ver", position=21), _raw("geen positie", position=None), _raw("tekst", position="abc"),
            _raw("bool", position=True), _raw("a", position=20, volume=10), _raw("c", position=4, volume=5),
        ]
        self.assertEqual([r["keyword"] for r in convert(rows)], ["b", "a", "c"])


# --- laden, verversen en bewaren -------------------------------------------------------

class _DbBase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.customer_id = self.add_customer("https://www.klant.nl/")

        self.settings = _settings()
        self._patch(quick_wins, "settings", self.settings)
        self.configured = self._patch(quick_wins.ahrefs, "is_configured", Mock(return_value=True))
        self.fetch = self._patch(
            quick_wins.ahrefs, "organic_keywords",
            Mock(return_value=AhrefsResult(rows=[_raw("a"), _raw("b", position=18)], units=48)),
        )

    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def add_customer(self, base_url):
        customer_id = str(uuid.uuid4())
        with self.Session() as db:
            db.add(CustomerWebsite(
                id=customer_id, name="Klant", base_url=base_url, domain="klant.nl", created_by="user-1",
                created_at=NOW, updated_at=NOW,
            ))
            db.commit()
        return customer_id

    def store(self, *, fetched_at, target="klant.nl", country="nl", rows=None, units=48, last_error=None):
        with self.Session() as db:
            db.add(CustomerQuickWins(
                customer_website_id=self.customer_id, target=target, country=country,
                rows=rows if rows is not None else [to_row(_raw("oud"))], units=units,
                fetched_at=fetched_at, last_error=last_error, created_at=NOW, updated_at=NOW,
            ))
            db.commit()

    def call(self, fn, **kwargs):
        with self.Session() as db:
            customer = db.get(CustomerWebsite, self.customer_id)
            result = fn(db, customer, **kwargs)
            db.commit()
        return result

    def record(self):
        with self.Session() as db:
            return db.get(CustomerQuickWins, self.customer_id)


class LoadTest(_DbBase):
    def test_first_visit_fetches_and_stores(self):
        result = self.call(quick_wins.load)
        self.fetch.assert_called_once()
        args, kwargs = self.fetch.call_args
        self.assertEqual(args, ("klant.nl",))
        self.assertEqual(kwargs["country"], "nl")
        self.assertEqual((kwargs["position_min"], kwargs["position_max"]), (4, 20))
        self.assertEqual((kwargs["limit"], kwargs["compare_days"]), (50, 30))

        self.assertEqual(result["state"], "ok")
        self.assertIsNone(result["message"])
        self.assertIsNotNone(result["fetched_at"])
        self.assertEqual((result["limit"], result["capped"]), (50, False))
        self.assertEqual([(r["keyword"], r["kans"]) for r in result["rows"]], [("a", "hoog"), ("b", "laag")])

        record = self.record()
        self.assertEqual((record.target, record.country, record.units), ("klant.nl", "nl", 48))
        self.assertEqual(record.rows, result["rows"])
        self.assertIsNotNone(record.fetched_at)
        self.assertIsNone(record.last_error)

    def test_fresh_state_is_not_refetched(self):
        self.store(fetched_at=NOW - timedelta(days=29, hours=23))
        result = self.call(quick_wins.load, now=NOW)
        self.fetch.assert_not_called()
        self.assertEqual([r["keyword"] for r in result["rows"]], ["oud"])
        self.assertEqual(result["fetched_at"], (NOW - timedelta(days=29, hours=23)).isoformat())

    def test_expired_state_is_refetched(self):
        self.store(fetched_at=NOW - timedelta(days=30))
        result = self.call(quick_wins.load, now=NOW)
        self.fetch.assert_called_once()
        self.assertEqual([r["keyword"] for r in result["rows"]], ["a", "b"])

    def test_changed_target_or_country_is_refetched(self):
        self.store(fetched_at=NOW - timedelta(days=1), target="oud-domein.nl")
        self.call(quick_wins.load, now=NOW)
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.record().target, "klant.nl")

        self.settings.ahrefs_country = "be"
        self.call(quick_wins.load, now=datetime.now(timezone.utc))
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual(self.record().country, "be")

    def test_missing_fetched_at_is_refetched(self):
        self.store(fetched_at=None, rows=[], last_error="eerder mislukt")
        self.call(quick_wins.load, now=NOW)
        self.fetch.assert_called_once()
        self.assertIsNone(self.record().last_error)

    def test_ttl_zero_never_fetches_automatically(self):
        self.settings.ahrefs_quick_wins_ttl_days = 0
        result = self.call(quick_wins.load, now=NOW)
        self.fetch.assert_not_called()
        self.assertEqual((result["state"], result["rows"], result["fetched_at"]), ("ok", [], None))
        self.assertIn("Vernieuwen", result["message"])
        self.assertIsNone(self.record())

        # Een oude stand blijft dan gewoon staan.
        self.store(fetched_at=NOW - timedelta(days=400))
        result = self.call(quick_wins.load, now=NOW)
        self.fetch.assert_not_called()
        self.assertEqual([r["keyword"] for r in result["rows"]], ["oud"])

        # De knop haalt wel op.
        self.call(quick_wins.refresh)
        self.fetch.assert_called_once()

    def test_empty_result_is_stored(self):
        self.fetch.return_value = AhrefsResult(rows=[], units=0)
        result = self.call(quick_wins.load)
        self.assertEqual((result["state"], result["rows"], result["capped"]), ("ok", [], False))
        record = self.record()
        self.assertEqual(record.rows, [])
        self.assertIsNotNone(record.fetched_at)

        self.call(quick_wins.load)
        self.fetch.assert_called_once()

    def test_capped_when_limit_reached(self):
        self.settings.ahrefs_quick_wins_limit = 2
        result = self.call(quick_wins.load)
        self.assertEqual(self.fetch.call_args.kwargs["limit"], 2)
        self.assertEqual((result["limit"], result["capped"]), (2, True))

    def test_error_without_previous_state(self):
        self.fetch.side_effect = AhrefsServiceError("Ahrefs weigert de API-key.", code="unauthorized")
        result = self.call(quick_wins.load)
        self.assertEqual(result["state"], "error")
        self.assertIn("Ahrefs weigert de API-key.", result["message"])
        self.assertEqual((result["rows"], result["fetched_at"]), ([], None))
        record = self.record()
        self.assertIsNone(record.fetched_at)
        self.assertEqual(record.last_error, "Ahrefs weigert de API-key.")

        # Een volgend bezoek probeert het opnieuw.
        self.fetch.side_effect = None
        self.assertEqual(self.call(quick_wins.load)["state"], "ok")
        self.assertEqual(self.fetch.call_count, 2)

    def test_error_with_previous_state_keeps_it(self):
        fetched = NOW - timedelta(days=31)
        self.store(fetched_at=fetched)
        self.fetch.side_effect = AhrefsServiceError("Timeout bij verbinden met Ahrefs.", code="timeout")
        result = self.call(quick_wins.load, now=NOW)
        self.assertEqual(result["state"], "ok")
        self.assertIn("Timeout bij verbinden met Ahrefs.", result["message"])
        self.assertEqual([r["keyword"] for r in result["rows"]], ["oud"])
        self.assertEqual(result["fetched_at"], fetched.isoformat())
        record = self.record()
        self.assertEqual((record.units, record.last_error), (48, "Timeout bij verbinden met Ahrefs."))
        self.assertEqual(record.rows[0]["keyword"], "oud")

    def test_error_after_domain_change_does_not_show_old_domain(self):
        self.store(fetched_at=NOW - timedelta(days=1), target="oud-domein.nl")
        self.fetch.side_effect = AhrefsServiceError("Kapot", code="ahrefs_error")
        result = self.call(quick_wins.load, now=NOW)
        self.assertEqual((result["state"], result["rows"]), ("error", []))
        self.assertIsNone(self.record().fetched_at)

    def test_not_configured_makes_no_call(self):
        self.configured.return_value = False
        result = self.call(quick_wins.load)
        self.assertEqual(result["state"], "not_configured")
        self.assertIn("AHREFS_API_KEY", result["message"])
        self.assertEqual(self.call(quick_wins.refresh)["state"], "not_configured")
        self.fetch.assert_not_called()
        self.assertIsNone(self.record())

    def test_empty_base_url_is_error(self):
        with self.Session() as db:
            db.get(CustomerWebsite, self.customer_id).base_url = ""
            db.commit()
        result = self.call(quick_wins.load)
        self.assertEqual(result["state"], "error")
        self.assertIn("website-adres", result["message"])
        self.fetch.assert_not_called()


class RefreshTest(_DbBase):
    def test_refresh_always_fetches(self):
        self.store(fetched_at=datetime.now(timezone.utc))
        result = self.call(quick_wins.refresh)
        self.fetch.assert_called_once()
        self.assertEqual([r["keyword"] for r in result["rows"]], ["a", "b"])
        self.assertEqual(self.record().rows, result["rows"])

    def test_refresh_error_keeps_previous_state(self):
        self.store(fetched_at=datetime.now(timezone.utc))
        self.fetch.side_effect = AhrefsServiceError("Kapot", code="ahrefs_error")
        result = self.call(quick_wins.refresh)
        self.assertEqual(result["state"], "ok")
        self.assertIn("Kapot", result["message"])
        # De waarschuwing blijft zichtbaar zolang de bewaarde stand wordt getoond.
        again = self.call(quick_wins.load)
        self.assertIn("Kapot", again["message"])
        self.assertEqual(self.fetch.call_count, 1)


# --- samenvoegen met ProRankTracker ----------------------------------------------------

def _prt(name="webdesign ermelo", rank="13", month="15", *, volume="70", url="https://klant.nl/webdesign/",
         engine="Google.nl"):
    return {
        "name": name, "rank": rank, "monthagorank": month, "localmonthlysearches": volume,
        "matchedurl": url, "engine": engine, "term_type": "organic", "is_ai_term": 0,
    }


def _ahrefs(keyword="seo bureau", position=7, **kwargs):
    return to_row(_raw(keyword, position, **kwargs))


def _ahrefs_result(rows=None, *, state="ok", message=None, capped=False):
    return {
        "state": state, "message": message, "fetched_at": "2026-11-23T12:00:00+00:00" if state == "ok" else None,
        "limit": 50, "capped": capped, "rows": rows if rows is not None else [],
    }


class MergeTest(unittest.TestCase):
    def test_only_prt(self):
        rows = quick_wins.merge([_prt()], [])
        self.assertEqual(rows, [{
            "keyword": "webdesign ermelo", "position": 13, "delta": 2, "volume": 70, "kd": None,
            "url": "https://klant.nl/webdesign/", "kans": "middel", "source": "prt",
        }])

    def test_prt_values(self):
        cases = [
            # (monthagorank, volume, matchedurl) -> (delta, volume, url)
            (("NTH", "70", None), (None, 70, None)),
            (("9", None, ""), (-4, None, None)),
            (("", "abc", "None"), (None, None, None)),
            (("13", "0", " https://klant.nl/ "), (0, 0, "https://klant.nl/")),
        ]
        for (month, volume, url), expected in cases:
            with self.subTest(month=month, volume=volume, url=url):
                row = quick_wins.merge([_prt(month=month, volume=volume, url=url)], [])[0]
                self.assertEqual((row["delta"], row["volume"], row["url"]), expected)

    def test_prt_outside_range_is_dropped(self):
        rows = [_prt("twee", "2"), _prt("drie", "3"), _prt("vier", "4"), _prt("twintig", "20"),
                _prt("eenentwintig", "21"), _prt("ver", "35"), _prt("weg", "NTH"), _prt("", "8")]
        self.assertEqual([r["keyword"] for r in quick_wins.merge(rows, [])], ["vier", "twintig"])

    def test_only_ahrefs(self):
        row = _ahrefs()
        self.assertEqual(quick_wins.merge([], [row]), [{**row, "source": "ahrefs"}])

    def test_in_both_prt_leads(self):
        ahrefs_row = _ahrefs("Webdesign Ermelo", position=9, diff=-1, volume=40, kd=12,
                             url="https://klant.nl/oud/")
        rows = quick_wins.merge([_prt(rank="8", month="12", volume="70")], [ahrefs_row])
        self.assertEqual(rows, [{
            "keyword": "webdesign ermelo", "position": 8, "delta": 4, "volume": 70, "kd": 12,
            "url": "https://klant.nl/webdesign/", "kans": "hoog", "source": "both",
        }])
        # Zonder PRT-volume komt het volume uit Ahrefs.
        row = quick_wins.merge([_prt(volume=None)], [ahrefs_row])[0]
        self.assertEqual((row["volume"], row["source"]), (40, "both"))

    def test_key_ignores_case_and_whitespace(self):
        self.assertEqual(quick_wins.keyword_key("  Website  laten\tmaken ERMELO "), "website laten maken ermelo")
        rows = quick_wins.merge([_prt("Website  laten maken Ermelo ", "15")],
                                [_ahrefs("website laten maken ermelo", position=11, kd=20)])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["source"], rows[0]["position"], rows[0]["kd"]), ("both", 15, 20))

    def test_duplicate_prt_rows_take_best_position(self):
        rows = quick_wins.merge([
            _prt("seo", "NTH", engine="Bing"), _prt("SEO", "14", url="https://klant.nl/a/"),
            _prt("seo ", "9", url="https://klant.nl/b/", engine="Google.be"), _prt("seo", "11"),
        ], [])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["position"], rows[0]["url"], rows[0]["keyword"]), (9, "https://klant.nl/b/", "seo"))

        # De beste positie telt ook als die buiten 4–20 valt: dan geen quick win.
        self.assertEqual(quick_wins.merge([_prt("seo", "12"), _prt("seo", "2")], []), [])

    def test_prt_outside_range_drops_ahrefs_row(self):
        for rank in ("2", "35", "NTH", "21"):
            with self.subTest(rank=rank):
                rows = quick_wins.merge([_prt("seo bureau", rank)], [_ahrefs("seo bureau"), _ahrefs("ander")])
                self.assertEqual([r["keyword"] for r in rows], ["ander"])

    def test_sorting(self):
        rows = quick_wins.merge(
            [_prt("p geen volume", "5", volume=None), _prt("p groot", "12", volume="500"),
             _prt("b gelijk", "6", volume="100"), _prt("a gelijk", "6", volume="100")],
            [_ahrefs("ahrefs midden", position=4, volume=100), _ahrefs("ahrefs zonder", position=4, volume=None)],
        )
        self.assertEqual([r["keyword"] for r in rows], [
            "p groot", "ahrefs midden", "a gelijk", "b gelijk", "ahrefs zonder", "p geen volume",
        ])

    def test_kans_is_recalculated(self):
        rows = {r["keyword"]: r for r in quick_wins.merge(
            [_prt("acht", "8"), _prt("zestien", "16"), _prt("beide", "6")],
            [_ahrefs("beide", position=18, kd=10)],
        )}
        # Zonder KD telt alleen de positie.
        self.assertEqual((rows["acht"]["kans"], rows["zestien"]["kans"]), ("middel", "laag"))
        # In beide: positie uit PRT (6) met KD uit Ahrefs (10).
        self.assertEqual(rows["beide"]["kans"], "hoog")

    def test_iexist_example(self):
        rows = quick_wins.merge(
            [_prt("Webdesign Ermelo", "13", volume="30"), _prt("Website laten maken Ermelo", "15", volume="20"),
             _prt("webdesign amersfoort", "2")],
            [_ahrefs("bureau amersfoort", position=6, volume=50)],
        )
        self.assertEqual([(r["keyword"], r["position"], r["source"]) for r in rows], [
            ("bureau amersfoort", 6, "ahrefs"), ("Webdesign Ermelo", 13, "prt"),
            ("Website laten maken Ermelo", 15, "prt"),
        ])


class CombineTest(unittest.TestCase):
    AHREFS_ROWS = [_ahrefs("ahrefs", position=6)]
    PRT_ROWS = [_prt("prt", "13")]

    def combine(self, ahrefs_result, prt_state, prt_rows=()):
        return quick_wins.combine(ahrefs_result, prt_state, list(prt_rows))

    def sources(self, result):
        return sorted(r["source"] for r in result["rows"])

    def test_both_ok(self):
        result = self.combine(_ahrefs_result(self.AHREFS_ROWS), "ok", self.PRT_ROWS)
        self.assertEqual((result["state"], result["message"]), ("ok", None))
        self.assertEqual(self.sources(result), ["ahrefs", "prt"])
        self.assertEqual((result["fetched_at"], result["limit"]), ("2026-11-23T12:00:00+00:00", 50))

    def test_ahrefs_ok_prt_not_configured_or_not_tracked(self):
        for prt_state in ("not_configured", "not_tracked"):
            with self.subTest(prt_state=prt_state):
                result = self.combine(_ahrefs_result(self.AHREFS_ROWS), prt_state)
                self.assertEqual((result["state"], result["message"]), ("ok", None))
                self.assertEqual(self.sources(result), ["ahrefs"])

    def test_ahrefs_ok_prt_error(self):
        result = self.combine(_ahrefs_result(self.AHREFS_ROWS), "error")
        self.assertEqual(result["state"], "ok")
        self.assertEqual(result["message"], quick_wins.PRT_ERROR_MESSAGE)
        self.assertIn("ProRankTracker", result["message"])
        self.assertEqual(self.sources(result), ["ahrefs"])

    def test_ahrefs_stale_warning_and_prt_error_are_joined(self):
        result = self.combine(_ahrefs_result(self.AHREFS_ROWS, message="Vernieuwen mislukt."), "error")
        self.assertEqual(result["message"], f"Vernieuwen mislukt. {quick_wins.PRT_ERROR_MESSAGE}")

    def test_ahrefs_error_prt_ok(self):
        result = self.combine(_ahrefs_result(state="error", message="Quick wins niet opgehaald uit Ahrefs: X"),
                              "ok", self.PRT_ROWS)
        self.assertEqual((result["state"], result["message"]), ("ok", "Quick wins niet opgehaald uit Ahrefs: X"))
        self.assertEqual(self.sources(result), ["prt"])
        self.assertIsNone(result["fetched_at"])

    def test_ahrefs_not_fetched_prt_ok(self):
        result = self.combine(_ahrefs_result(message=quick_wins.MESSAGES["not_fetched"]), "ok", self.PRT_ROWS)
        self.assertEqual((result["state"], result["message"]), ("ok", quick_wins.MESSAGES["not_fetched"]))
        self.assertEqual(self.sources(result), ["prt"])

    def test_ahrefs_not_configured_prt_ok_or_not_tracked(self):
        ahrefs_result = _ahrefs_result(state="not_configured", message=quick_wins.MESSAGES["not_configured"])
        result = self.combine(ahrefs_result, "ok", self.PRT_ROWS)
        self.assertEqual((result["state"], result["message"]), ("ok", quick_wins.MESSAGES["not_configured"]))
        self.assertEqual(self.sources(result), ["prt"])
        # Niet gevolgd telt als bruikbaar met 0 rijen.
        result = self.combine(ahrefs_result, "not_tracked")
        self.assertEqual((result["state"], result["rows"]), ("ok", []))

    def test_neither_configured(self):
        result = self.combine(
            _ahrefs_result(state="not_configured", message=quick_wins.MESSAGES["not_configured"]), "not_configured"
        )
        self.assertEqual((result["state"], result["rows"]), ("not_configured", []))
        self.assertIn("AHREFS_API_KEY", result["message"])
        self.assertIn("PRORANKTRACKER_API_X_TOKEN", result["message"])

    def test_both_fail_or_one_fails_and_other_not_configured(self):
        ahrefs_error = _ahrefs_result(state="error", message="Ahrefs kapot.")
        ahrefs_off = _ahrefs_result(state="not_configured", message=quick_wins.MESSAGES["not_configured"])
        cases = [
            (ahrefs_error, "error", f"Ahrefs kapot. {quick_wins.PRT_ERROR_MESSAGE}"),
            (ahrefs_error, "not_configured", "Ahrefs kapot."),
            (ahrefs_off, "error", f"{quick_wins.MESSAGES['not_configured']} {quick_wins.PRT_ERROR_MESSAGE}"),
        ]
        for ahrefs_result, prt_state, message in cases:
            with self.subTest(ahrefs=ahrefs_result["state"], prt=prt_state):
                result = self.combine(ahrefs_result, prt_state)
                self.assertEqual((result["state"], result["message"], result["rows"]), ("error", message, []))

    def test_capped_follows_ahrefs(self):
        result = self.combine(_ahrefs_result(self.AHREFS_ROWS, capped=True), "ok", self.PRT_ROWS)
        self.assertTrue(result["capped"])
        self.assertEqual(len(result["rows"]), 2)
        result = self.combine(_ahrefs_result(self.AHREFS_ROWS, capped=False), "ok", [_prt(str(i), "10") for i in range(80)])
        self.assertFalse(result["capped"])


class LoadMergedTest(_DbBase):
    def setUp(self):
        super().setUp()
        self.prt_configured = self._patch(rankings.prt, "is_configured", Mock(return_value=True))
        self.overview = self._patch(
            rankings.prt, "rank_overview",
            Mock(return_value=[_prt("a", "5", volume="2000"), _prt("prt", "13")]),
        )

    def test_load_merged_uses_stored_ahrefs_and_live_prt(self):
        self.store(fetched_at=NOW - timedelta(days=1), rows=[_ahrefs("oud"), _ahrefs("A", position=9, kd=5)])
        result = self.call(quick_wins.load_merged, now=NOW)
        self.fetch.assert_not_called()
        self.overview.assert_called_once()
        self.assertEqual(self.overview.call_args.args, ("klant.nl",))
        self.assertEqual([(r["keyword"], r["source"]) for r in result["rows"]],
                         [("a", "both"), ("oud", "ahrefs"), ("prt", "prt")])
        # PRT wordt niet bewaard.
        self.assertEqual([r["keyword"] for r in self.record().rows], ["oud", "A"])

    def test_refresh_merged_fetches_ahrefs(self):
        result = self.call(quick_wins.refresh_merged)
        self.fetch.assert_called_once()
        self.assertEqual([(r["keyword"], r["source"]) for r in result["rows"]],
                         [("a", "both"), ("b", "ahrefs"), ("prt", "prt")])

    def test_prt_error_keeps_ahrefs_rows(self):
        self.overview.side_effect = ProRankTrackerServiceError("Kapot", code="prt_error")
        result = self.call(quick_wins.load_merged)
        self.assertEqual((result["state"], result["message"]), ("ok", quick_wins.PRT_ERROR_MESSAGE))
        self.assertEqual([r["source"] for r in result["rows"]], ["ahrefs", "ahrefs"])


class QuickWinsEndpointTest(_DbBase):
    def setUp(self):
        super().setUp()
        self._patch(rankings.prt, "is_configured", Mock(return_value=True))
        self.overview = self._patch(rankings.prt, "rank_overview", Mock(return_value=[_prt("prt", "13")]))
        app = FastAPI()
        app.include_router(router)

        def override_db():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_user_id] = lambda: "user-1"
        self.client = TestClient(app)

    def test_get_and_refresh(self):
        response = self.client.get(f"/api/customers/{self.customer_id}/quick-wins")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"state", "message", "fetched_at", "limit", "capped", "rows"})
        self.assertEqual(set(body["rows"][0]),
                         {"keyword", "position", "delta", "volume", "kd", "url", "kans", "source"})
        self.assertEqual([(r["keyword"], r["source"]) for r in body["rows"]],
                         [("a", "ahrefs"), ("b", "ahrefs"), ("prt", "prt")])
        # Bewaard (gecommit): een tweede GET haalt niet opnieuw op uit Ahrefs; PRT wel (live).
        self.assertEqual(self.client.get(f"/api/customers/{self.customer_id}/quick-wins").json(), body)
        self.fetch.assert_called_once()
        self.assertEqual(self.overview.call_count, 2)

        response = self.client.post(f"/api/customers/{self.customer_id}/quick-wins/refresh")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.fetch.call_count, 2)
        self.assertEqual([r["source"] for r in response.json()["rows"]], ["ahrefs", "ahrefs", "prt"])

    def test_unknown_customer_is_404(self):
        for method in ("get", "post"):
            path = "/api/customers/onbekend/quick-wins" + ("/refresh" if method == "post" else "")
            response = getattr(self.client, method)(path)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"], "Klant niet gevonden.")


if __name__ == "__main__":
    unittest.main()
